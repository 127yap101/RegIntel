"""Live prepublication gates with authored sources; never research gold data."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest

from backend.tests.evidence_fixtures import synthetic_artifact
from backend.tests.integration.test_evidence_storage import context, parsed, persist
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.auth.types import User
from regintel.candidates.models import MetricDefinition
from regintel.candidates.repository import CandidateRepository
from regintel.db.config import DatabaseSettings
from regintel.db.migrations import DatabaseConnection, connect_database
from regintel.entities.models import EntityRegistration, EntityReview, EvidenceAnchor
from regintel.entities.repository import EntityRepository
from regintel.entities.resolution import EntityResolver
from regintel.entities.resolution import current_configuration as entity_configuration
from regintel.validation.gate import validate
from regintel.validation.models import (
    NumericMetricPolicy,
    ReviewDecision,
    ValidationInput,
    ValidationRun,
)
from regintel.validation.repository import (
    ValidationAuthorizationError,
    ValidationConflict,
    ValidationNotFound,
    ValidationRepository,
    ValidationSourceError,
)

pytestmark = pytest.mark.integration

SOURCE = (
    "Exact Lead 😀 e\u0301\n"
    "Alpha Solar Limited supplies to Beta Solar Limited.\n"
    "Alpha Solar Limited revenue was INR 1,234.50 crore on a consolidated basis "
    "from 1 April 2023 to 31 March 2024.\n"
    "Alpha Solar Limited business is manufacture of solar modules."
)


def raw_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class ValidationContext:
    database: DatabaseSettings
    repository: ValidationRepository
    user: User
    candidate_run_id: str
    policy: NumericMetricPolicy
    entity_run_id: str


@pytest.fixture
def validated(auth_database: DatabaseSettings, request: pytest.FixtureRequest) -> ValidationContext:
    options = getattr(request, "param", {})
    source_text = options.get("source", SOURCE)
    fixture = context(
        auth_database,
        document_type=options.get("document_type", "RHP"),
        published_on=options.get("published_on"),
    )
    artifact = synthetic_artifact(
        configuration=fixture.configuration,
        blob=fixture.blob,
        parse_id=fixture.artifact.id,
        filing_id=fixture.artifact.filing_id,
        filing_version_id=fixture.artifact.filing_version_id,
        original=source_text,
    )
    if not options.get("table"):
        artifact = artifact.model_validate(artifact.model_dump(mode="python") | {"tables": ()})
    if options.get("ocr"):
        blocks = list(artifact.blocks)
        blocks[0] = blocks[0].model_validate(
            blocks[0].model_dump(mode="python") | {"from_ocr": True}
        )
        artifact = artifact.model_validate(
            artifact.model_dump(mode="python") | {"blocks": tuple(blocks)}
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
        entities.register(
            EntityRegistration(
                id=str(uuid4()),
                kind="COMPANY",
                legal_name=name,
                legal_name_support=EvidenceAnchor(
                    evidence_id=evidence[0].id, start=start, end=start + len(name), quote=name
                ),
                aliases=(),
                identifiers=(),
                review_note="Authored engineering fixture identity.",
            ),
            user,
        )
    entity_run = EntityResolver(entities.snapshot(), entity_configuration()).run(
        evidence, artifact_sha
    )
    entities.save_run(entity_run, user)
    candidates = CandidateRepository(auth_database)
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
        candidates.register_metric(metric, user)
    run = candidates.extract(entity_run.id, tuple(metric.id for metric in metrics), user)
    repository = ValidationRepository(auth_database)
    policy = NumericMetricPolicy(
        id=str(uuid4()),
        metric_id=metrics[0].id,
        quantity_kind="MONEY",
        period_kind="DURATION",
        allowed_unit_labels=options.get("allowed_unit_labels", ("crore",)),
        required_reporting_basis=True,
        review_note="Authored engineering fixture reviewed monetary meaning.",
    )
    if not options.get("no_policy"):
        repository.register_policy(policy, user)
    return ValidationContext(auth_database, repository, user, run.id, policy, entity_run.id)


def source_and_run(fixture: ValidationContext) -> tuple[ValidationInput, ValidationRun]:
    source = fixture.repository.input_for_run(fixture.candidate_run_id)
    return source, validate(source)


def insert_run(
    connection: DatabaseConnection,
    fixture: ValidationContext,
    source: ValidationInput,
    run: ValidationRun,
    *,
    input_value: object | None = None,
    run_value: object | None = None,
    configuration_value: object | None = None,
    count: int | None = None,
    actor: str | None = None,
    auth_version: int | None = None,
    invalid_hash: bool = False,
) -> None:
    from regintel.candidates.records import stable_id

    source_bytes = raw_bytes(source.model_dump(mode="json") if input_value is None else input_value)
    config_bytes = raw_bytes(
        run.configuration.model_dump(mode="json")
        if configuration_value is None
        else configuration_value
    )
    identity = stable_id("validation-run:" + sha(source_bytes) + ":" + sha(config_bytes))
    payload = run.model_dump(mode="json") if run_value is None else run_value
    payload = dict(payload) | {
        "id": identity,
        "input_sha256": sha(source_bytes),
        "configuration": json.loads(config_bytes),
    }
    run_bytes = raw_bytes(payload)
    connection.execute(
        """INSERT INTO regintel.validation_runs
        (id,candidate_run_id,parse_version_id,input_bytes,input_sha256,configuration_bytes,
         configuration_sha256,run_bytes,run_sha256,result_count,submitted_by,auth_version)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            identity,
            run.candidate_run_id,
            run.parse_version_id,
            source_bytes,
            "0" * 64 if invalid_hash else sha(source_bytes),
            config_bytes,
            sha(config_bytes),
            run_bytes,
            sha(run_bytes),
            len(run.results) if count is None else count,
            actor or fixture.user.id,
            fixture.user.auth_version if auth_version is None else auth_version,
        ),
    )


def decision(
    fixture: ValidationContext,
    run: ValidationRun,
    kind: str = "numeric_fact",
    outcome: str = "APPROVE_FOR_PUBLICATION",
) -> ReviewDecision:
    source = fixture.repository.input_for_run(fixture.candidate_run_id)
    selected = next(item for item in source.candidate_run.candidates if item.kind == kind)
    from regintel.candidates.records import drafts

    selected_draft = next(
        draft
        for item, draft in zip(
            source.candidate_run.candidates, drafts(source.candidate_run.bundle), strict=True
        )
        if item.id == selected.id
    )
    return ReviewDecision.model_validate(
        {
            "id": str(uuid4()),
            "validation_run_id": run.id,
            "candidate_id": selected.id,
            "decision": outcome,
            "supports": (selected_draft.supports[0],),
            "review_note": "Authored fixture review; no corporate observation or publication.",
        }
    )


def assert_closed(fixture: ValidationContext) -> None:
    with connect_database(fixture.database) as connection:
        for table in (
            "acceptance_audits",
            "fact_observations",
            "relation_observations",
            "corpus_versions",
        ):
            assert connection.execute(f"SELECT count(*) FROM regintel.{table}").fetchone() == (0,)


def test_complete_three_kind_validation_decimal_replay_and_staged_review(validated):
    source, expected = source_and_run(validated)
    with connect_database(validated.database) as connection:
        insert_run(connection, validated, source, expected)
    run = validated.repository.validate(validated.candidate_run_id, validated.user)
    assert run == expected
    assert validated.repository.validate(validated.candidate_run_id, validated.user) == run
    assert validated.repository.get_run(run.id) == run
    assert len(run.results) == 3
    numeric = next(item for item in run.results if item.quantity is not None)
    assert numeric.state == "PASS" and numeric.reviewer_eligible
    assert numeric.quantity.normalized_value == Decimal("1234.50")
    assert numeric.quantity.period.start_date == "2023-04-01"
    assert numeric.quantity.period.end_date == "2024-03-31"
    assert numeric.quantity.basis == "CONSOLIDATED"
    assert len(numeric.checks) == 16
    review = decision(validated, run)
    assert validated.repository.review(review, validated.user) is True
    assert validated.repository.review(review, validated.user) is False
    assert validated.repository.reviews(run.id) == (review,)
    for kind in ("narrative_fact", "relation"):
        other = decision(validated, run, kind=kind)
        result = next(item for item in run.results if item.candidate_id == other.candidate_id)
        assert result.reviewer_eligible
        assert validated.repository.review(other, validated.user)
    assert len(validated.repository.reviews(run.id)) == 3
    assert validated.repository.get_run(str(uuid4())) is None
    assert source.candidate_run.quantities[0].quantity.normalized_value is None
    assert_closed(validated)


def test_concurrent_validation_and_review_seal_one_exact_audit(validated):
    with ThreadPoolExecutor(max_workers=2) as executor:
        runs = list(
            executor.map(
                lambda _: validated.repository.validate(validated.candidate_run_id, validated.user),
                range(2),
            )
        )
    assert runs[0] == runs[1]
    review = decision(validated, runs[0])
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(lambda _: validated.repository.review(review, validated.user), range(2))
        )
    assert sorted(outcomes) == [False, True]
    with connect_database(validated.database) as connection:
        assert connection.execute("SELECT count(*) FROM regintel.validation_runs").fetchone() == (
            1,
        )
        assert connection.execute(
            "SELECT count(*) FROM regintel.validation_reviews"
        ).fetchone() == (1,)


@pytest.mark.parametrize(
    "validated",
    [{"source": "Alpha Solar Limited and Beta Solar Limited are mentioned."}],
    indirect=True,
)
def test_empty_proposal_run_seals_explicit_zero_validation_results(validated):
    run = validated.repository.validate(validated.candidate_run_id, validated.user)
    assert run.results == ()
    assert validated.repository.get_run(run.id) == run
    assert validated.repository.validate(validated.candidate_run_id, validated.user) == run
    assert_closed(validated)


@pytest.mark.parametrize(
    "validated",
    [
        {"table": True},
        {"ocr": True},
        {"no_policy": True},
        {
            "source": SOURCE.replace(
                "from 1 April 2023 to 31 March 2024", "for year ended 31 March 2024"
            )
        },
        {"source": SOURCE.replace("INR 1,234.50 crore", "1,234.50 crore")},
        {"source": SOURCE.replace("consolidated", "consolidated and standalone")},
    ],
    indirect=True,
)
def test_missing_context_and_table_ambiguity_cannot_be_review_overridden(validated):
    run = validated.repository.validate(validated.candidate_run_id, validated.user)
    review = decision(validated, run)
    result = next(item for item in run.results if item.candidate_id == review.candidate_id)
    assert result.state in {"REVIEW", "QUARANTINED"} and not result.reviewer_eligible
    with pytest.raises(ValidationConflict):
        validated.repository.review(review, validated.user)
    rejection = ReviewDecision.model_validate(
        review.model_dump(mode="python") | {"decision": "REJECT"}
    )
    assert validated.repository.review(rejection, validated.user)
    assert_closed(validated)


@pytest.mark.parametrize(
    ("validated", "invalid"),
    [
        (
            {
                "source": SOURCE.replace("INR 1,234.50 crore", "INR 1,234.50 rupees"),
                "allowed_unit_labels": ("rupees",),
            },
            False,
        ),
        (
            {
                "source": SOURCE.replace("INR 1,234.50 crore", "USD 1,234.50 rupees"),
                "allowed_unit_labels": ("rupees",),
            },
            True,
        ),
        ({"source": SOURCE.replace("INR 1,234.50 crore", "USD 1,234.50 crore")}, False),
        ({}, False),
    ],
    indirect=["validated"],
)
def test_currency_unit_conflict_blocks_actual_staged_approval(validated, invalid):
    run = validated.repository.validate(validated.candidate_run_id, validated.user)
    review = decision(validated, run)
    result = next(item for item in run.results if item.candidate_id == review.candidate_id)
    assert result.state == ("QUARANTINED" if invalid else "PASS")
    assert result.reviewer_eligible is not invalid
    if invalid:
        with pytest.raises(ValidationConflict):
            validated.repository.review(review, validated.user)
    else:
        assert validated.repository.review(review, validated.user)
    assert validated.repository.get_run(run.id) == run
    assert_closed(validated)


def test_review_once_conflicts_different_ids_and_opposite_decisions(validated):
    run = validated.repository.validate(validated.candidate_run_id, validated.user)
    review = decision(validated, run)
    validated.repository.review(review, validated.user)
    for changes in ({"id": str(uuid4())}, {"decision": "REJECT"}):
        with pytest.raises(ValidationConflict):
            validated.repository.review(
                ReviewDecision.model_validate(review.model_dump(mode="python") | changes),
                validated.user,
            )


def test_entity_review_change_quarantines_old_candidate_and_rejects_stale_approval(validated):
    before = validated.repository.validate(validated.candidate_run_id, validated.user)
    source = validated.repository.input_for_run(validated.candidate_run_id)
    # Select the numeric candidate's exact subject mention, not the earlier relation mention.
    target_id = source.candidate_run.bundle.numeric_facts[0].subject_mention_id
    mention = next(item for item in source.source.entity_run.mentions if item.id == target_id)
    validated.repository.candidates.entities.review(
        EntityReview(
            id=str(uuid4()),
            run_id=validated.entity_run_id,
            mention_id=mention.id,
            decision="REJECT",
            entity_id=None,
            support_evidence_ids=(mention.support.evidence_id,),
            review_note="Authored identity rejection.",
        ),
        validated.user,
    )
    with pytest.raises(ValidationConflict):
        validated.repository.review(decision(validated, before), validated.user)
    with connect_database(validated.database) as connection:
        with (
            pytest.raises(psycopg.errors.CheckViolation, match="stale audited"),
            connection.transaction(),
        ):
            insert_review(
                connection, validated, decision(validated, before).model_dump(mode="json")
            )
    after = validated.repository.validate(validated.candidate_run_id, validated.user)
    assert after.id != before.id
    numeric = next(item for item in after.results if item.quantity is not None)
    assert numeric.state == "QUARANTINED" and not numeric.reviewer_eligible
    assert validated.repository.get_run(before.id) == before
    assert validated.repository.review(
        decision(validated, before, outcome="REJECT"), validated.user
    )


def test_policy_registration_replay_conflict_and_unknown_metric(validated):
    assert validated.repository.register_policy(validated.policy, validated.user) is False
    for changes in ({"review_note": "Changed"}, {"id": str(uuid4())}):
        with pytest.raises(ValidationConflict):
            validated.repository.register_policy(
                NumericMetricPolicy.model_validate(
                    validated.policy.model_dump(mode="python") | changes
                ),
                validated.user,
            )
    invalid = NumericMetricPolicy.model_validate(
        validated.policy.model_dump(mode="python") | {"id": str(uuid4()), "metric_id": str(uuid4())}
    )
    with pytest.raises(ValidationSourceError):
        validated.repository.register_policy(invalid, validated.user)
    with pytest.raises(ValidationNotFound):
        validated.repository.validate(str(uuid4()), validated.user)


@pytest.mark.parametrize("method", ["validate", "review", "register_policy"])
def test_current_admin_version_required_for_all_writes(validated, method):
    run = validated.repository.validate(validated.candidate_run_id, validated.user)
    stale = replace(validated.user, auth_version=validated.user.auth_version + 1)
    with pytest.raises(ValidationAuthorizationError):
        getattr(validated.repository, method)(
            decision(validated, run)
            if method == "review"
            else validated.policy
            if method == "register_policy"
            else validated.candidate_run_id,
            stale,
        )


@pytest.mark.parametrize(
    "table", ["numeric_metric_policies", "validation_runs", "validation_reviews"]
)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_stage_audits_are_immutable_and_cannot_be_truncated(validated, table, operation):
    run = validated.repository.validate(validated.candidate_run_id, validated.user)
    validated.repository.review(decision(validated, run), validated.user)
    assignment = {
        "numeric_metric_policies": "auth_version=auth_version",
        "validation_runs": "result_count=result_count",
        "validation_reviews": "auth_version=auth_version",
    }[table]
    sql = (
        f"UPDATE regintel.{table} SET {assignment}"
        if operation == "UPDATE"
        else f"DELETE FROM regintel.{table}"
        if operation == "DELETE"
        else f"TRUNCATE regintel.{table} CASCADE"
    )
    with connect_database(validated.database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation, match="Immutable"):
            connection.execute(sql)


@pytest.mark.parametrize(
    "mutation",
    [
        "count",
        "hash",
        "auth_version",
        "source",
        "candidate",
        "reviews",
        "policies",
        "table_id",
        "table_duplicate",
        "transcription_id",
        "transcription_duplicate",
    ],
)
def test_direct_sql_sealed_source_and_dependency_mutations_are_rejected(validated, mutation):
    source, run = source_and_run(validated)
    value = source.model_dump(mode="json")
    options = {}
    if mutation == "count":
        options["count"] = len(run.results) + 1
    elif mutation == "hash":
        options["invalid_hash"] = True
    elif mutation == "auth_version":
        options["auth_version"] = validated.user.auth_version + 1
    elif mutation == "source":
        value["source"]["evidence"][0]["span"]["quote"] = "Altered source"
    elif mutation == "candidate":
        value["candidate_run"]["candidates"][0]["raw_text"] = "Invented text"
    elif mutation == "reviews":
        value["entity_reviews"] = [None]
    elif mutation == "policies":
        value["policies"] = []
    elif mutation == "table_id":
        value["table_evidence_ids"] = [str(uuid4())]
    elif mutation == "table_duplicate":
        value["table_evidence_ids"] = [source.source.evidence[0].id] * 2
    elif mutation == "transcription_id":
        value["transcription_evidence_ids"] = [str(uuid4())]
    else:
        value["transcription_evidence_ids"] = [source.source.evidence[0].id] * 2
    with connect_database(validated.database) as connection:
        with pytest.raises(psycopg.Error), connection.transaction():
            insert_run(connection, validated, source, run, input_value=value, **options)
        assert connection.execute("SELECT count(*) FROM regintel.validation_runs").fetchone() == (
            0,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "extra",
        "state",
        "eligible",
        "candidate_id",
        "quantity_number",
        "quantity_nan",
        "quantity_date",
        "quantity_unknown_period",
        "quantity_raw",
        "quantity_label",
        "quantity_extra",
        "witness_quote",
        "witness_role",
        "checks_missing",
        "checks_null",
        "checks_unknown",
        "checks_extra",
        "checks_message",
        "configuration_extra",
        "configuration_null",
    ],
)
def test_direct_sql_result_schema_decimal_context_and_state_poison_rejected(validated, mutation):
    source, run = source_and_run(validated)
    value = run.model_dump(mode="json")
    numeric = next(item for item in value["results"] if item["quantity"] is not None)
    options = {}
    if mutation == "missing":
        numeric.pop("state")
    elif mutation == "duplicate":
        value["results"][1] = numeric.copy()
    elif mutation == "extra":
        numeric["accepted"] = True
    elif mutation == "state":
        numeric["state"] = "QUARANTINED"
    elif mutation == "eligible":
        numeric["reviewer_eligible"] = False
    elif mutation == "candidate_id":
        numeric["candidate_id"] = str(uuid4())
    elif mutation == "quantity_number":
        numeric["quantity"]["normalized_value"] = 1234.5
    elif mutation == "quantity_nan":
        numeric["quantity"]["normalized_value"] = "NaN"
    elif mutation == "quantity_date":
        numeric["quantity"]["period"]["start_date"] = "2023-02-30"
    elif mutation == "quantity_unknown_period":
        numeric["quantity"]["period"]["kind"] = "UNKNOWN"
    elif mutation == "quantity_raw":
        numeric["quantity"]["raw_value"] = "999"
    elif mutation == "quantity_label":
        numeric["quantity"]["raw_unit"] = "million"
    elif mutation == "quantity_extra":
        numeric["quantity"]["formula"] = "trusted"
    elif mutation == "witness_quote":
        numeric["context_supports"][0]["span"]["quote"] = "Invented"
    elif mutation == "witness_role":
        numeric["context_supports"][0]["role"] = "FINANCE"
    elif mutation == "checks_missing":
        numeric["checks"] = numeric["checks"][:-1]
    elif mutation == "checks_null":
        numeric["checks"][0]["state"] = None
    elif mutation == "checks_unknown":
        numeric["checks"][0]["code"] = "SKIP"
    elif mutation == "checks_extra":
        numeric["checks"][0]["override"] = True
    elif mutation == "checks_message":
        numeric["checks"][0]["message"] = ""
    else:
        config = run.configuration.model_dump(mode="json")
        if mutation == "configuration_extra":
            config["skip"] = True
        else:
            config["code_sha256"] = None
        options["configuration_value"] = config
    with connect_database(validated.database) as connection:
        with pytest.raises(psycopg.Error), connection.transaction():
            insert_run(connection, validated, source, run, run_value=value, **options)
        assert connection.execute("SELECT count(*) FROM regintel.validation_runs").fetchone() == (
            0,
        )


def test_mandatory_gate_staging_does_not_open_authority(validated):
    run = validated.repository.validate(validated.candidate_run_id, validated.user)
    validated.repository.review(decision(validated, run), validated.user)
    with connect_database(validated.database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation, match="approved publication transaction"):
            connection.execute(
                "INSERT INTO regintel.acceptance_audits"
                "(id,candidate_id,parse_version_id,actor_user_id,decision,"
                "validator_configuration_sha256) VALUES(%s,%s,%s,%s,'ACCEPTED',%s)",
                (
                    str(uuid4()),
                    run.results[0].candidate_id,
                    run.parse_version_id,
                    validated.user.id,
                    run.configuration.sha256,
                ),
            )
        with pytest.raises(psycopg.errors.CheckViolation, match="approved publication transaction"):
            connection.execute(
                "INSERT INTO regintel.corpus_versions(id,state,configuration_sha256) "
                "VALUES(%s,'BUILDING',%s)",
                (str(uuid4()), run.configuration.sha256),
            )
    assert_closed(validated)


def insert_policy(connection: DatabaseConnection, fixture: ValidationContext, value: dict) -> None:
    payload = raw_bytes(value)
    connection.execute(
        "INSERT INTO regintel.numeric_metric_policies"
        "(id,metric_id,policy_bytes,policy_sha256,registered_by,auth_version) "
        "VALUES(%s,%s,%s,%s,%s,%s)",
        (
            value["id"],
            value["metric_id"],
            payload,
            sha(payload),
            fixture.user.id,
            fixture.user.auth_version,
        ),
    )


def insert_review(
    connection: DatabaseConnection,
    fixture: ValidationContext,
    value: dict,
    *,
    invalid_hash: bool = False,
) -> None:
    payload = raw_bytes(value)
    connection.execute(
        "INSERT INTO regintel.validation_reviews"
        "(id,validation_run_id,candidate_id,decision,review_bytes,review_sha256,"
        "reviewed_by,auth_version) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            value["id"],
            value["validation_run_id"],
            value["candidate_id"],
            value["decision"],
            payload,
            "0" * 64 if invalid_hash else sha(payload),
            fixture.user.id,
            fixture.user.auth_version,
        ),
    )


@pytest.mark.parametrize("note", ["\t", "\n", "\u00a0", "\u2003", "\u001f", "\u3000"])
@pytest.mark.parametrize("payload_kind", ["policy", "review"])
@pytest.mark.parametrize("validated", [{"no_policy": True}], indirect=True)
def test_whitespace_only_review_notes_cannot_poison_immutable_readability(
    validated, note, payload_kind
):
    with connect_database(validated.database) as connection:
        if payload_kind == "policy":
            value = validated.policy.model_dump(mode="json") | {"review_note": note}
            with pytest.raises(psycopg.Error), connection.transaction():
                insert_policy(connection, validated, value)
        else:
            run = validated.repository.validate(validated.candidate_run_id, validated.user)
            value = decision(validated, run, outcome="REJECT").model_dump(mode="json") | {
                "review_note": note
            }
            with pytest.raises(psycopg.Error), connection.transaction():
                insert_review(connection, validated, value)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "null",
        "extra",
        "wrong_family",
        "duplicate_unit",
        "float_basis",
        "narrative_metric",
    ],
)
@pytest.mark.parametrize("validated", [{"no_policy": True}], indirect=True)
def test_policy_schema_matching_numeric_metric_and_unit_family(validated, mutation):
    value = validated.policy.model_dump(mode="json")
    if mutation == "missing":
        value.pop("quantity_kind")
    elif mutation == "null":
        value["quantity_kind"] = None
    elif mutation == "extra":
        value["override"] = True
    elif mutation == "wrong_family":
        value["allowed_unit_labels"] = ["MW"]
    elif mutation == "duplicate_unit":
        value["allowed_unit_labels"] = ["crore", "crore"]
    elif mutation == "float_basis":
        value["required_reporting_basis"] = 1
    else:
        source = validated.repository.input_for_run(validated.candidate_run_id)
        value["metric_id"] = next(
            metric.id for metric in source.source.metrics if metric.kind == "narrative_fact"
        )
    with connect_database(validated.database) as connection:
        with pytest.raises(psycopg.Error), connection.transaction():
            insert_policy(connection, validated, value)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "null",
        "partial",
        "outside",
        "unknown_candidate",
        "unknown_run",
        "hash",
        "duplicate",
    ],
)
def test_direct_review_requires_exact_full_owned_source_and_bounded_audit(validated, mutation):
    run = validated.repository.validate(validated.candidate_run_id, validated.user)
    value = decision(validated, run).model_dump(mode="json")
    if mutation == "missing":
        value.pop("review_note")
    elif mutation == "extra":
        value["accepted"] = True
    elif mutation == "null":
        value["review_note"] = None
    elif mutation == "partial":
        value["supports"][0]["quote"] = value["supports"][0]["quote"][:-1]
        value["supports"][0]["end"] -= 1
    elif mutation == "outside":
        source = validated.repository.input_for_run(validated.candidate_run_id)
        record = source.source.evidence[0]
        value["supports"] = [
            {
                "evidence_id": record.id,
                "start": record.span.start,
                "end": record.span.end,
                "quote": record.span.quote,
            }
        ]
    elif mutation == "unknown_candidate":
        value["candidate_id"] = str(uuid4())
    elif mutation == "unknown_run":
        value["validation_run_id"] = str(uuid4())
    elif mutation == "duplicate":
        value["supports"] *= 2
    with connect_database(validated.database) as connection:
        with pytest.raises(psycopg.Error), connection.transaction():
            insert_review(connection, validated, value, invalid_hash=mutation == "hash")
        assert connection.execute(
            "SELECT count(*) FROM regintel.validation_reviews"
        ).fetchone() == (0,)
