"""Live immutable proposal gates using authored sources, never research gold data."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest

from backend.tests.evidence_fixtures import synthetic_artifact
from backend.tests.integration.test_evidence_storage import Context, context, parsed, persist
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.auth.types import User
from regintel.candidates.extraction import current_configuration, extract
from regintel.candidates.models import ExtractionInput, MetricDefinition
from regintel.candidates.records import CandidateRun, drafts, materialize, stable_id
from regintel.candidates.repository import (
    CandidateAuthorizationError,
    CandidateConflict,
    CandidateNotFound,
    CandidateRepository,
    CandidateSourceError,
)
from regintel.db.config import DatabaseSettings
from regintel.db.migrations import DatabaseConnection, connect_database
from regintel.entities.models import (
    ApprovedAlias,
    EntityRegistration,
    EntityReview,
    EntityRun,
    EvidenceAnchor,
)
from regintel.entities.repository import EntityRepository
from regintel.entities.resolution import EntityResolver
from regintel.entities.resolution import current_configuration as entity_configuration
from regintel.ingestion.models import CandidateRecord, QuantitativeContextRecord

pytestmark = pytest.mark.integration

SOURCE = (
    "Exact Lead 😀 e\u0301\n"
    "Alpha Solar Limited owns Beta Solar Limited.\n"
    "Alpha Solar Limited revenue was INR 1,234.50 crore on a consolidated basis "
    "for year ended 31 March 2024.\n"
    "Alpha Solar Limited business is manufacture of solar modules."
)


def raw_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class CandidateContext:
    fixture: Context
    repository: CandidateRepository
    user: User
    entity_run: EntityRun
    metrics: tuple[MetricDefinition, ...]
    source_text: str

    @property
    def metric_ids(self) -> tuple[str, ...]:
        return tuple(metric.id for metric in self.metrics)

    @property
    def database(self) -> DatabaseSettings:
        return self.repository.database


@pytest.fixture
def proposals(auth_database: DatabaseSettings, request: pytest.FixtureRequest) -> CandidateContext:
    options = getattr(request, "param", {})
    source_text = options.get("source", SOURCE)
    fixture = context(auth_database)
    artifact = synthetic_artifact(
        configuration=fixture.configuration,
        blob=fixture.blob,
        parse_id=fixture.artifact.id,
        filing_id=fixture.artifact.filing_id,
        filing_version_id=fixture.artifact.filing_version_id,
        original=source_text,
    )
    fixture = replace(fixture, artifact=artifact)
    with connect_database(auth_database) as connection, connection.transaction():
        persist(connection, fixture)
        parsed(connection, fixture)
    user = PostgreSQLAuthRepository(auth_database).get_by_username("admin")
    assert user is not None
    entities = EntityRepository(auth_database)
    evidence, artifact_sha = entities.evidence_for_parse(artifact.id)
    for name in ("Alpha Solar Limited", "Beta Solar Limited"):
        start = evidence[0].span.start + source_text.index(name)
        beta_start = evidence[0].span.start + source_text.index("Beta Solar Limited")
        aliases = ()
        if options.get("alias_collision") and name == "Alpha Solar Limited":
            aliases = (
                ApprovedAlias(
                    name="Beta Solar Limited",
                    support=EvidenceAnchor(
                        evidence_id=evidence[0].id,
                        start=beta_start,
                        end=beta_start + len("Beta Solar Limited"),
                        quote="Beta Solar Limited",
                    ),
                ),
            )
        entities.register(
            EntityRegistration(
                id=str(uuid4()),
                kind="COMPANY",
                legal_name=name,
                legal_name_support=EvidenceAnchor(
                    evidence_id=evidence[0].id,
                    start=start,
                    end=start + len(name),
                    quote=name,
                ),
                aliases=aliases,
                identifiers=(),
                review_note="Authored engineering fixture identity.",
            ),
            user,
        )
    entity_run = EntityResolver(entities.snapshot(), entity_configuration()).run(
        evidence,
        artifact_sha,
    )
    entities.save_run(entity_run, user)
    repository = CandidateRepository(auth_database)
    metrics = (
        MetricDefinition(
            id=str(uuid4()),
            key="revenue",
            label="Revenue raw disclosure",
            kind="numeric_fact",
            cue_phrases=("revenue",),
        ),
        MetricDefinition(
            id=str(uuid4()),
            key="business",
            label="Business description",
            kind="narrative_fact",
            cue_phrases=("business",),
        ),
    )
    for metric in metrics:
        repository.register_metric(metric, user)
    return CandidateContext(fixture, repository, user, entity_run, metrics, source_text)


def source_and_run(fixture: CandidateContext) -> tuple[ExtractionInput, CandidateRun]:
    source = fixture.repository.input_for_run(fixture.entity_run.id, fixture.metric_ids)
    return source, materialize(source, current_configuration(), extract(source))


def insert_run(
    connection: DatabaseConnection,
    fixture: CandidateContext,
    source: ExtractionInput,
    run: CandidateRun,
    *,
    input_value: object | None = None,
    bundle_value: object | None = None,
    configuration_value: object | None = None,
    count: int | None = None,
    run_id: str | None = None,
    actor: str | None = None,
    auth_version: int | None = None,
    hashes_valid: bool = True,
) -> None:
    input_bytes = raw_bytes(source.model_dump(mode="json") if input_value is None else input_value)
    bundle_bytes = raw_bytes(
        run.bundle.model_dump(mode="json") if bundle_value is None else bundle_value
    )
    configuration_bytes = raw_bytes(
        run.configuration.model_dump(mode="json")
        if configuration_value is None
        else configuration_value
    )
    # Mutations retain valid hashes/IDs so type/source gates, rather than hashing alone, are tested.
    identity = run_id or stable_id(
        "candidate-run:" + sha(input_bytes) + ":" + sha(configuration_bytes)
    )
    connection.execute(
        """INSERT INTO regintel.candidate_runs
        (id,entity_run_id,parse_version_id,input_bytes,input_sha256,configuration_bytes,
         configuration_sha256,bundle_bytes,bundle_sha256,candidate_count,submitted_by,auth_version)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            identity,
            run.entity_run_id,
            run.parse_version_id,
            input_bytes,
            sha(input_bytes) if hashes_valid else "0" * 64,
            configuration_bytes,
            sha(configuration_bytes),
            bundle_bytes,
            sha(bundle_bytes),
            len(run.candidates) if count is None else count,
            actor or fixture.user.id,
            fixture.user.auth_version if auth_version is None else auth_version,
        ),
    )


def insert_items(
    connection: DatabaseConnection,
    fixture: CandidateContext,
    run: CandidateRun,
    *,
    records: tuple[CandidateRecord, ...] | None = None,
    quantities: tuple[QuantitativeContextRecord, ...] | None = None,
) -> None:
    for quantity in run.quantities if quantities is None else quantities:
        fixture.repository._quantity(connection, quantity)
    for record, draft in zip(
        run.candidates if records is None else records, drafts(run.bundle), strict=True
    ):
        fixture.repository._candidate(connection, record)
        connection.execute(
            "INSERT INTO regintel.candidate_run_items"
            "(run_id,candidate_id,parse_version_id,draft_bytes) VALUES(%s,%s,%s,%s)",
            (run.id, record.id, run.parse_version_id, raw_bytes(draft.model_dump(mode="json"))),
        )


def assert_no_proposals(fixture: CandidateContext) -> None:
    with connect_database(fixture.database) as connection:
        for table in (
            "candidate_runs",
            "candidate_run_items",
            "candidates",
            "candidate_evidence",
            "quantitative_contexts",
            "quantitative_context_evidence",
        ):
            assert connection.execute(f"SELECT count(*) FROM regintel.{table}").fetchone() == (0,)


def test_three_proposal_kinds_replay_exact_unicode_and_raw_quantity(proposals):
    source, expected = source_and_run(proposals)
    assert len(expected.candidates) == 3
    assert {record.kind for record in expected.candidates} == {
        "numeric_fact",
        "narrative_fact",
        "relation",
    }
    assert SOURCE == source.evidence[0].span.quote
    run = proposals.repository.extract(
        proposals.entity_run.id, proposals.metric_ids, proposals.user
    )
    assert run == expected
    assert (
        proposals.repository.extract(
            proposals.entity_run.id, tuple(reversed(proposals.metric_ids)), proposals.user
        )
        == run
    )
    assert proposals.repository.get_run(run.id) == run
    assert proposals.repository.get_run(str(uuid4())) is None
    quantity = run.quantities[0].quantity
    assert quantity.raw_value == "1,234.50"
    assert quantity.normalized_value is None and quantity.normalized_unit is None
    assert quantity.raw_unit == "crore" and quantity.raw_currency == "INR"
    assert quantity.currency is None and quantity.basis == "UNKNOWN"
    assert quantity.raw_basis_label == "consolidated"
    assert (
        quantity.period.kind == "UNKNOWN"
        and quantity.period.raw_label == "year ended 31 March 2024"
    )
    relation = run.bundle.relations[0]
    assert relation.relation_type == "OWNS" and relation.raw_quantity is None
    with connect_database(proposals.database) as connection:
        assert connection.execute("SELECT count(*) FROM regintel.candidate_runs").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM regintel.candidates").fetchone() == (3,)
        for table in (
            "acceptance_audits",
            "fact_observations",
            "relation_observations",
            "corpus_versions",
        ):
            assert connection.execute(f"SELECT count(*) FROM regintel.{table}").fetchone() == (0,)


def test_concurrent_extraction_seals_one_complete_audited_run(proposals):
    with ThreadPoolExecutor(max_workers=2) as executor:
        runs = list(
            executor.map(
                lambda _: proposals.repository.extract(
                    proposals.entity_run.id, proposals.metric_ids, proposals.user
                ),
                range(2),
            )
        )
    assert runs[0] == runs[1]
    with connect_database(proposals.database) as connection:
        assert connection.execute("SELECT count(*) FROM regintel.candidate_runs").fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM regintel.candidate_run_items"
        ).fetchone() == (3,)


def test_metric_idempotency_conflicts_and_unknown_supplied_ids(proposals):
    metric = proposals.metrics[0]
    assert proposals.repository.register_metric(metric, proposals.user) is False
    altered = MetricDefinition.model_validate(
        metric.model_dump(mode="python") | {"label": "Changed"}
    )
    with pytest.raises(CandidateConflict):
        proposals.repository.register_metric(altered, proposals.user)
    duplicate_key = MetricDefinition.model_validate(
        metric.model_dump(mode="python") | {"id": str(uuid4())}
    )
    with pytest.raises(CandidateConflict):
        proposals.repository.register_metric(duplicate_key, proposals.user)
    with pytest.raises(CandidateNotFound):
        proposals.repository.extract(proposals.entity_run.id, (str(uuid4()),), proposals.user)
    with pytest.raises(CandidateNotFound):
        proposals.repository.extract(str(uuid4()), proposals.metric_ids, proposals.user)
    with pytest.raises(CandidateSourceError):
        proposals.repository.metrics((metric.id, metric.id))
    assert_no_proposals(proposals)


@pytest.mark.parametrize("change", ["role", "inactive", "auth_version"])
def test_writes_recheck_live_administrator_even_on_replay(proposals, change):
    run = proposals.repository.extract(
        proposals.entity_run.id, proposals.metric_ids, proposals.user
    )
    sql = {
        "role": "UPDATE regintel.users SET role='learner' WHERE id=%s",
        "inactive": "UPDATE regintel.users SET is_active=FALSE WHERE id=%s",
        "auth_version": "UPDATE regintel.users SET auth_version=auth_version+1 WHERE id=%s",
    }[change]
    with connect_database(proposals.database) as connection:
        connection.execute(sql, (proposals.user.id,))
    with pytest.raises(CandidateAuthorizationError):
        proposals.repository.extract(proposals.entity_run.id, proposals.metric_ids, proposals.user)
    with pytest.raises(CandidateAuthorizationError):
        proposals.repository.register_metric(proposals.metrics[0], proposals.user)
    assert proposals.repository.get_run(run.id) == run


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_key",
        "extra_key",
        "null_kind",
        "wrong_kind",
        "null_label",
        "oversized_label",
        "empty_cues",
        "cue_null",
        "cue_number",
        "cue_blank",
        "cue_space",
        "cue_tab",
        "cue_nbsp",
        "cue_duplicate",
        "cue_case_duplicate",
        "wrong_hash",
    ],
)
def test_sql_metric_poison_is_rejected_before_immutable_registration(proposals, mutation):
    metric = proposals.metrics[0]
    value = metric.model_dump(mode="json") | {"id": str(uuid4()), "key": "another_metric"}
    if mutation == "missing_key":
        value.pop("kind")
    elif mutation == "extra_key":
        value["unapproved"] = True
    elif mutation == "null_kind":
        value["kind"] = None
    elif mutation == "wrong_kind":
        value["kind"] = "relation"
    elif mutation == "null_label":
        value["label"] = None
    elif mutation == "oversized_label":
        value["label"] = "a" * 257
    elif mutation == "empty_cues":
        value["cue_phrases"] = []
    elif mutation.startswith("cue_"):
        value["cue_phrases"] = {
            "cue_null": [None],
            "cue_number": [1],
            "cue_blank": ["."],
            "cue_space": [" revenue"],
            "cue_tab": ["revenue\t"],
            "cue_nbsp": ["\u00a0revenue"],
            "cue_duplicate": ["revenue", "revenue"],
            "cue_case_duplicate": ["revenue", "Revenue"],
        }[mutation]
    payload = raw_bytes(value)
    with connect_database(proposals.database) as connection:
        with pytest.raises(psycopg.Error), connection.transaction():
            connection.execute(
                "INSERT INTO regintel.metric_definitions"
                "(id,metric_key,definition_bytes,definition_sha256,registered_by,auth_version) "
                "VALUES(%s,%s,%s,%s,%s,%s)",
                (
                    value["id"],
                    value["key"],
                    payload,
                    "0" * 64 if mutation == "wrong_hash" else sha(payload),
                    proposals.user.id,
                    proposals.user.auth_version,
                ),
            )
        assert connection.execute(
            "SELECT count(*) FROM regintel.metric_definitions"
        ).fetchone() == (2,)


@pytest.mark.parametrize(
    "mutation",
    [
        "input_missing",
        "input_extra",
        "input_reviews_null",
        "entity_run_altered",
        "missing_evidence",
        "foreign_evidence_id",
        "foreign_parse",
        "source_quote",
        "span_start_string",
        "span_null",
        "page_index_string",
        "geometry_missing",
        "geometry_extra",
        "geometry_width",
        "geometry_number_string",
        "boxes_null",
        "box_extra",
        "box_wrong",
        "metric_altered",
        "metric_missing",
        "metric_duplicate",
    ],
)
def test_sql_run_inputs_require_complete_exact_source_and_registered_metrics(proposals, mutation):
    source, run = source_and_run(proposals)
    value = source.model_dump(mode="json")
    if mutation == "input_missing":
        value.pop("reviews")
    elif mutation == "input_extra":
        value["unapproved"] = True
    elif mutation == "input_reviews_null":
        value["reviews"] = None
    elif mutation == "entity_run_altered":
        value["entity_run"]["mentions"] = []
    elif mutation == "missing_evidence":
        value["evidence"] = []
    elif mutation == "foreign_evidence_id":
        value["evidence"][0]["id"] = str(uuid4())
    elif mutation == "foreign_parse":
        value["evidence"][0]["source"]["parse_version_id"] = str(uuid4())
    elif mutation == "source_quote":
        value["evidence"][0]["span"]["quote"] = "fabricated"
    elif mutation == "span_start_string":
        value["evidence"][0]["span"]["start"] = "0"
    elif mutation == "span_null":
        value["evidence"][0]["span"] = None
    elif mutation == "page_index_string":
        value["evidence"][0]["source"]["page_index"] = "0"
    elif mutation.startswith("geometry_"):
        geometry = value["evidence"][0]["page_geometry"]
        if mutation == "geometry_missing":
            geometry.pop("rotation")
        elif mutation == "geometry_extra":
            geometry["unapproved"] = True
        elif mutation == "geometry_number_string":
            geometry["width"] = "612.0"
        else:
            geometry["width"] = 613.0
    elif mutation == "boxes_null":
        value["evidence"][0]["boxes"] = None
    elif mutation == "box_extra":
        value["evidence"][0]["boxes"][0]["unapproved"] = True
    elif mutation == "box_wrong":
        value["evidence"][0]["boxes"][0]["x0"] = 41.0
    elif mutation == "metric_altered":
        value["metrics"][0]["cue_phrases"] = ["unapproved"]
    elif mutation == "metric_missing":
        value["metrics"] = []
    else:
        value["metrics"].append(value["metrics"][0])
    with connect_database(proposals.database) as connection:
        with pytest.raises(psycopg.Error), connection.transaction():
            insert_run(connection, proposals, source, run, input_value=value)
    assert_no_proposals(proposals)


@pytest.mark.parametrize(
    "mutation",
    [
        "bundle_missing",
        "bundle_extra",
        "bundle_null",
        "wrong_collection",
        "draft_extra",
        "draft_missing",
        "subject_unknown",
        "subject_mention_unknown",
        "object_unknown",
        "object_mention_unknown",
        "metric_unknown",
        "relation_wrong",
        "span_quote",
        "span_start_string",
        "span_extra",
        "span_foreign",
        "primary_text",
        "duplicate_span",
        "raw_value_unknown",
        "raw_role_extra",
        "raw_role_number",
        "issue_extra",
        "issue_foreign",
        "issue_null",
        "issue_code",
        "duplicate_draft",
    ],
)
def test_sql_frozen_bundles_fail_closed_on_unknown_ids_context_and_poison(proposals, mutation):
    source, run = source_and_run(proposals)
    value = run.bundle.model_dump(mode="json")
    draft = value["numeric_facts"][0]
    relation = value["relations"][0]
    if mutation == "bundle_missing":
        value.pop("issues")
    elif mutation == "bundle_extra":
        value["unapproved"] = True
    elif mutation == "bundle_null":
        value["numeric_facts"] = None
    elif mutation == "wrong_collection":
        value["narrative_facts"].append(value["numeric_facts"].pop())
    elif mutation == "draft_extra":
        draft["unapproved"] = True
    elif mutation == "draft_missing":
        draft.pop("raw_quantity")
    elif mutation in {"subject_unknown", "subject_mention_unknown", "metric_unknown"}:
        field = {
            "subject_unknown": "subject_entity_id",
            "subject_mention_unknown": "subject_mention_id",
            "metric_unknown": "metric_id",
        }[mutation]
        draft[field] = str(uuid4())
    elif mutation in {"object_unknown", "object_mention_unknown"}:
        relation["object_entity_id" if mutation == "object_unknown" else "object_mention_id"] = str(
            uuid4()
        )
    elif mutation == "relation_wrong":
        relation["relation_type"] = "UNSUPPORTED"
    elif mutation.startswith("span_"):
        span = draft["supports"][0]
        if mutation == "span_quote":
            span["quote"] = "fabricated"
            draft["raw_text"] = "fabricated"
        elif mutation == "span_start_string":
            span["start"] = str(span["start"])
        elif mutation == "span_extra":
            span["unapproved"] = True
        else:
            span["evidence_id"] = str(uuid4())
    elif mutation == "primary_text":
        draft["raw_text"] = "unsupported narrative"
    elif mutation == "duplicate_span":
        draft["supports"].append(draft["supports"][0])
    elif mutation == "raw_value_unknown":
        draft["raw_quantity"]["value"]["quote"] = "fabricated"
    elif mutation == "raw_role_extra":
        draft["raw_quantity"]["unapproved"] = None
    elif mutation == "raw_role_number":
        draft["raw_quantity"]["unit"] = 1
    elif mutation.startswith("issue_"):
        value["issues"] = [
            {"code": "MISSING_VALUE", "evidence_ids": [], "message": "Authored issue"}
        ]
        if mutation == "issue_extra":
            value["issues"][0]["unapproved"] = True
        elif mutation == "issue_foreign":
            value["issues"][0]["evidence_ids"] = [str(uuid4())]
        elif mutation == "issue_null":
            value["issues"][0]["code"] = None
        else:
            value["issues"][0]["code"] = "UNSUPPORTED"
    else:
        value["numeric_facts"].append(draft)
    count = sum(
        len(value.get(key) or []) for key in ("numeric_facts", "narrative_facts", "relations")
    )
    with connect_database(proposals.database) as connection:
        with pytest.raises(psycopg.Error), connection.transaction():
            insert_run(connection, proposals, source, run, bundle_value=value, count=count)
    assert_no_proposals(proposals)


def test_terminal_run_without_complete_items_rolls_back_atomically(proposals):
    source, run = source_and_run(proposals)
    with connect_database(proposals.database) as connection:
        with (
            pytest.raises(psycopg.errors.CheckViolation, match="complete.*atomically"),
            connection.transaction(),
        ):
            insert_run(connection, proposals, source, run)
    assert_no_proposals(proposals)


def test_mid_transaction_failure_rolls_back_run_candidates_and_raw_context(proposals):
    source, run = source_and_run(proposals)
    with connect_database(proposals.database) as connection:
        with pytest.raises(RuntimeError, match="Authored interruption"), connection.transaction():
            insert_run(connection, proposals, source, run)
            insert_items(connection, proposals, run)
            raise RuntimeError("Authored interruption")
    assert_no_proposals(proposals)


@pytest.mark.parametrize(
    "mutation",
    ["candidate_id", "subject", "text", "quantity_id", "normalized", "basis", "raw_unit"],
)
def test_run_members_must_equal_exact_materialized_draft_and_unknown_context(proposals, mutation):
    source, run = source_and_run(proposals)
    records, quantities = list(run.candidates), list(run.quantities)
    if mutation in {"candidate_id", "subject", "text"}:
        records[0] = CandidateRecord.model_validate(
            records[0].model_dump(mode="python")
            | {
                {"candidate_id": "id", "subject": "subject_entity_id", "text": "raw_text"}[
                    mutation
                ]: "unsupported" if mutation == "text" else str(uuid4()),
            }
        )
    else:
        item = quantities[0].model_dump(mode="python")
        if mutation == "quantity_id":
            item["id"] = str(uuid4())
            records[0] = CandidateRecord.model_validate(
                records[0].model_dump(mode="python") | {"quantitative_context_id": item["id"]}
            )
        else:
            item["quantity"][
                {"normalized": "normalized_value", "basis": "basis", "raw_unit": "raw_unit"}[
                    mutation
                ]
            ] = {
                "normalized": Decimal("1234.50"),
                "basis": "CONSOLIDATED",
                "raw_unit": "million",
            }[mutation]
        quantities[0] = QuantitativeContextRecord.model_validate(item)
    with connect_database(proposals.database) as connection:
        with pytest.raises(psycopg.Error), connection.transaction():
            insert_run(connection, proposals, source, run)
            insert_items(
                connection, proposals, run, records=tuple(records), quantities=tuple(quantities)
            )
    assert_no_proposals(proposals)


def test_review_snapshot_rejection_suppresses_exact_identity_and_keeps_history(proposals):
    before = proposals.repository.extract(
        proposals.entity_run.id, proposals.metric_ids, proposals.user
    )
    source, _ = source_and_run(proposals)
    mention = next(
        item
        for item in proposals.entity_run.mentions
        if item.support.quote == "Beta Solar Limited" and item.resolution.state == "RESOLVED"
    )
    review = EntityReview(
        id=str(uuid4()),
        run_id=proposals.entity_run.id,
        mention_id=mention.id,
        decision="REJECT",
        entity_id=None,
        support_evidence_ids=(mention.support.evidence_id,),
        review_note="Authored rejection demonstrates reviewed identity precedence.",
    )
    proposals.repository.entities.review(review, proposals.user)
    after = proposals.repository.extract(
        proposals.entity_run.id, proposals.metric_ids, proposals.user
    )
    assert before.id != after.id and before.input_sha256 != after.input_sha256
    assert len(before.bundle.relations) == 1 and not after.bundle.relations
    assert proposals.repository.get_run(before.id) == before
    assert proposals.repository.get_run(after.id) == after
    stale = materialize(source, current_configuration(), extract(source))
    with connect_database(proposals.database) as connection:
        with (
            pytest.raises(psycopg.errors.CheckViolation, match="all current audited"),
            connection.transaction(),
        ):
            insert_run(connection, proposals, source, stale)


def test_multiple_review_snapshot_order_matches_repository(proposals):
    targets = [
        mention
        for mention in proposals.entity_run.mentions
        if mention.resolution.state == "RESOLVED"
    ][:2]
    assert len(targets) == 2
    for mention in reversed(targets):
        proposals.repository.entities.review(
            EntityReview(
                id=str(uuid4()),
                run_id=proposals.entity_run.id,
                mention_id=mention.id,
                decision="RESOLVE",
                entity_id=mention.resolution.entity_id,
                support_evidence_ids=(mention.support.evidence_id,),
                review_note="Authored review snapshot.",
            ),
            proposals.user,
        )
    run = proposals.repository.extract(
        proposals.entity_run.id, proposals.metric_ids, proposals.user
    )
    assert proposals.repository.get_run(run.id) == run


@pytest.mark.parametrize("table", ["metric_definitions", "candidate_runs", "candidate_run_items"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_new_stage_rows_are_immutable_and_cannot_be_truncated(proposals, table, operation):
    proposals.repository.extract(proposals.entity_run.id, proposals.metric_ids, proposals.user)
    assignment = {
        "metric_definitions": "auth_version=auth_version",
        "candidate_runs": "candidate_count=candidate_count",
        "candidate_run_items": "draft_bytes=draft_bytes",
    }[table]
    sql = (
        f"UPDATE regintel.{table} SET {assignment}"
        if operation == "UPDATE"
        else f"DELETE FROM regintel.{table}"
        if operation == "DELETE"
        else f"TRUNCATE regintel.{table} CASCADE"
    )
    with connect_database(proposals.database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation, match="Immutable"):
            connection.execute(sql)


@pytest.mark.parametrize("mutation", ["count", "hash", "run_id", "auth_version"])
def test_run_counts_fingerprints_identity_and_admin_version_are_gated(proposals, mutation):
    source, run = source_and_run(proposals)
    options = {
        "count": {"count": len(run.candidates) + 1},
        "hash": {"hashes_valid": False},
        "run_id": {"run_id": str(uuid4())},
        "auth_version": {"auth_version": proposals.user.auth_version + 1},
    }[mutation]
    with connect_database(proposals.database) as connection:
        with pytest.raises(psycopg.Error), connection.transaction():
            insert_run(connection, proposals, source, run, **options)
    assert_no_proposals(proposals)


def test_candidate_stage_cannot_open_later_financial_authority(proposals):
    run = proposals.repository.extract(
        proposals.entity_run.id, proposals.metric_ids, proposals.user
    )
    with connect_database(proposals.database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation, match="approved publication transaction"):
            connection.execute(
                "INSERT INTO regintel.acceptance_audits"
                "(id,candidate_id,parse_version_id,actor_user_id,decision,"
                "validator_configuration_sha256) "
                "VALUES(%s,%s,%s,%s,'ACCEPTED',%s)",
                (
                    str(uuid4()),
                    run.candidates[0].id,
                    run.parse_version_id,
                    proposals.user.id,
                    "0" * 64,
                ),
            )
        with pytest.raises(psycopg.errors.CheckViolation, match="approved publication transaction"):
            connection.execute(
                "INSERT INTO regintel.corpus_versions(id,state,configuration_sha256) "
                "VALUES(%s,'BUILDING',%s)",
                (str(uuid4()), "0" * 64),
            )


@pytest.mark.parametrize("proposals", [{"alias_collision": True}], indirect=True)
def test_audited_resolution_enables_prior_ambiguous_endpoint_without_overwriting(proposals):
    before = proposals.repository.extract(
        proposals.entity_run.id,
        proposals.metric_ids,
        proposals.user,
    )
    assert not before.bundle.relations
    target = next(
        mention
        for mention in proposals.entity_run.mentions
        if mention.support.quote == "Beta Solar Limited"
    )
    assert target.resolution.state == "REVIEW"
    beta = next(
        entity
        for entity in proposals.repository.entities.snapshot().entities
        if entity.legal_name == "Beta Solar Limited"
    )
    proposals.repository.entities.review(
        EntityReview(
            id=str(uuid4()),
            run_id=proposals.entity_run.id,
            mention_id=target.id,
            decision="RESOLVE",
            entity_id=beta.id,
            support_evidence_ids=(target.support.evidence_id,),
            review_note="Authored source-based identity selection; no relation acceptance.",
        ),
        proposals.user,
    )
    after = proposals.repository.extract(
        proposals.entity_run.id,
        proposals.metric_ids,
        proposals.user,
    )
    assert after.id != before.id and len(after.bundle.relations) == 1
    assert after.bundle.relations[0].object_entity_id == beta.id
    assert proposals.repository.get_run(before.id) == before
    assert proposals.repository.entities.get_run(proposals.entity_run.id) == proposals.entity_run


@pytest.mark.parametrize(
    "proposals",
    [
        {
            "source": "Alpha Solar Limited owns Beta Solar Limited.\n"
            "Alpha Solar Limited revenue was Rs. 12 crore.",
        }
    ],
    indirect=True,
)
def test_rupee_abbreviation_is_one_supported_statement_in_python_and_sql(proposals):
    run = proposals.repository.extract(
        proposals.entity_run.id,
        proposals.metric_ids,
        proposals.user,
    )
    assert len(run.bundle.numeric_facts) == 1
    assert run.quantities[0].quantity.raw_value == "12"
    assert run.quantities[0].quantity.raw_currency == "Rs."
    assert proposals.repository.get_run(run.id) == run


def test_zero_result_is_sealed_with_explicit_issue_and_cannot_gain_late_members(proposals):
    source, proposed = source_and_run(proposals)
    relation = next(record for record in proposed.candidates if record.kind == "relation")
    for mention in proposals.entity_run.mentions:
        if mention.resolution.state == "RESOLVED":
            proposals.repository.entities.review(
                EntityReview(
                    id=str(uuid4()),
                    run_id=proposals.entity_run.id,
                    mention_id=mention.id,
                    decision="REJECT",
                    entity_id=None,
                    support_evidence_ids=(mention.support.evidence_id,),
                    review_note="Authored rejection for explicit zero-output state.",
                ),
                proposals.user,
            )
    run = proposals.repository.extract(
        proposals.entity_run.id,
        proposals.metric_ids,
        proposals.user,
    )
    assert not run.candidates and not run.quantities
    assert any(issue.code == "NO_SUPPORTED_CANDIDATE" for issue in run.bundle.issues)
    assert proposals.repository.get_run(run.id) == run
    with connect_database(proposals.database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            proposals.repository._candidate(connection, relation)
            connection.execute(
                "INSERT INTO regintel.candidate_run_items"
                "(run_id,candidate_id,parse_version_id,draft_bytes) VALUES(%s,%s,%s,%s)",
                (
                    run.id,
                    relation.id,
                    run.parse_version_id,
                    raw_bytes(proposed.bundle.relations[0].model_dump(mode="json")),
                ),
            )
        assert connection.execute("SELECT count(*) FROM regintel.candidates").fetchone() == (0,)


@pytest.mark.parametrize("payload_kind", ["configuration", "bundle", "draft", "metric"])
def test_noncanonical_proposal_payloads_cannot_poison_stable_identity(proposals, payload_kind):
    source, run = source_and_run(proposals)
    with connect_database(proposals.database) as connection:
        with pytest.raises(psycopg.Error), connection.transaction():
            if payload_kind == "metric":
                value = proposals.metrics[0].model_dump(mode="json") | {
                    "id": str(uuid4()),
                    "key": "noncanonical",
                }
                payload = json.dumps(value).encode()
                connection.execute(
                    "INSERT INTO regintel.metric_definitions"
                    "(id,metric_key,definition_bytes,definition_sha256,registered_by,auth_version) "
                    "VALUES(%s,%s,%s,%s,%s,%s)",
                    (
                        value["id"],
                        value["key"],
                        payload,
                        sha(payload),
                        proposals.user.id,
                        proposals.user.auth_version,
                    ),
                )
            else:
                configuration = (
                    json.dumps(run.configuration.model_dump(mode="json")).encode()
                    if payload_kind == "configuration"
                    else raw_bytes(run.configuration.model_dump(mode="json"))
                )
                bundle = (
                    json.dumps(run.bundle.model_dump(mode="json")).encode()
                    if payload_kind == "bundle"
                    else raw_bytes(run.bundle.model_dump(mode="json"))
                )
                input_bytes = raw_bytes(source.model_dump(mode="json"))
                identity = stable_id("candidate-run:" + sha(input_bytes) + ":" + sha(configuration))
                connection.execute(
                    """INSERT INTO regintel.candidate_runs
                    (id,entity_run_id,parse_version_id,input_bytes,input_sha256,configuration_bytes,
                     configuration_sha256,bundle_bytes,bundle_sha256,candidate_count,submitted_by,auth_version)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        identity,
                        run.entity_run_id,
                        run.parse_version_id,
                        input_bytes,
                        sha(input_bytes),
                        configuration,
                        sha(configuration),
                        bundle,
                        sha(bundle),
                        len(run.candidates),
                        proposals.user.id,
                        proposals.user.auth_version,
                    ),
                )
                if payload_kind == "draft":
                    draft = drafts(run.bundle)[0]
                    payload = json.dumps(draft.model_dump(mode="json")).encode()
                    record = CandidateRecord.model_validate(
                        run.candidates[0].model_dump(mode="python")
                        | {
                            "id": stable_id("candidate:" + identity + ":" + sha(payload)),
                        }
                    )
                    for quantity in run.quantities:
                        proposals.repository._quantity(connection, quantity)
                    proposals.repository._candidate(connection, record)
                    connection.execute(
                        "INSERT INTO regintel.candidate_run_items"
                        "(run_id,candidate_id,parse_version_id,draft_bytes) VALUES(%s,%s,%s,%s)",
                        (identity, record.id, run.parse_version_id, payload),
                    )
    assert_no_proposals(proposals)


@pytest.mark.parametrize("separator", ["\u0085", "\u00a0", "\u2028"])
def test_unicode_whitespace_cannot_join_different_statements_into_one_proposal(
    proposals,
    separator,
):
    source, run = source_and_run(proposals)
    value = run.bundle.model_dump(mode="json")
    draft = value["numeric_facts"][0]
    # The original source contains a real newline; preserve exact source while
    # validating the boundary classifier separately with equivalent Unicode spaces.
    text = (
        "Alpha Solar Limited owns Beta Solar Limited."
        + separator
        + ("Alpha Solar Limited revenue was INR 12 crore.")
    )
    with connect_database(proposals.database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation, match="bounded source statement"):
            connection.execute(
                "SELECT regintel.validate_candidate_draft(%s::jsonb,%s::jsonb,'numeric_fact')",
                (
                    raw_bytes(
                        value["numeric_facts"][0]
                        | {
                            "raw_text": text,
                            "supports": [draft["supports"][0] | {"quote": text}],
                        }
                    ).decode(),
                    raw_bytes(source.model_dump(mode="json")).decode(),
                ),
            )
