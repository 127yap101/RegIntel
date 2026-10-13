"""Live M1.5 identity/source/audit gates using explicitly synthetic evidence."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from uuid import uuid4

import psycopg
import pytest

from backend.tests.evidence_fixtures import synthetic_artifact
from backend.tests.integration.test_evidence_storage import Context, context, parsed, persist
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.auth.types import User
from regintel.contracts.models import TextSpan
from regintel.db.config import DatabaseSettings
from regintel.db.migrations import DatabaseConnection, connect_database
from regintel.entities.models import (
    ApprovedAlias,
    ApprovedIdentifier,
    EntityRegistration,
    EntityReview,
    EntityRun,
    EvidenceAnchor,
    canonical_bytes,
)
from regintel.entities.repository import (
    EntityAuthorizationError,
    EntityConflict,
    EntityNotFound,
    EntityRegistryChanged,
    EntityRepository,
    EntitySourceError,
)
from regintel.entities.resolution import EntityResolver, current_configuration

pytestmark = pytest.mark.integration

SOURCE = (
    "Exact Lead 😀 e\u0301\nAlpha Solar Limited (Alpha Solar), CIN U12345MH2020PLC123456; "
    "ISIN INE040A01034.\nBeta Solar Limited (Alpha Solar)."
)


@dataclass(frozen=True)
class EntityContext:
    fixture: Context
    repository: EntityRepository
    user: User
    evidence_id: str
    span_start: int


@pytest.fixture
def entities(auth_database: DatabaseSettings) -> EntityContext:
    fixture = context(auth_database)
    artifact = synthetic_artifact(
        configuration=fixture.configuration,
        blob=fixture.blob,
        parse_id=fixture.artifact.id,
        filing_id=fixture.artifact.filing_id,
        filing_version_id=fixture.artifact.filing_version_id,
        original=SOURCE,
    )
    fixture = replace(fixture, artifact=artifact)
    with connect_database(auth_database) as connection, connection.transaction():
        persist(connection, fixture)
        parsed(connection, fixture)
    repository = EntityRepository(auth_database)
    evidence, _ = repository.evidence_for_parse(artifact.id)
    user = PostgreSQLAuthRepository(auth_database).get_by_username("admin")
    assert user is not None
    return EntityContext(fixture, repository, user, evidence[0].id, evidence[0].span.start)


def anchor(fixture: EntityContext, value: str) -> EvidenceAnchor:
    start = fixture.span_start + SOURCE.index(value)
    return EvidenceAnchor(
        evidence_id=fixture.evidence_id, start=start, end=start + len(value), quote=value
    )


def registration(fixture: EntityContext, *, beta: bool = False) -> EntityRegistration:
    name = "Beta Solar Limited" if beta else "Alpha Solar Limited"
    return EntityRegistration(
        id=str(uuid4()),
        kind="COMPANY",
        legal_name=name,
        legal_name_support=anchor(fixture, name),
        aliases=(ApprovedAlias(name="Alpha Solar", support=anchor(fixture, "Alpha Solar")),),
        identifiers=()
        if beta
        else (
            ApprovedIdentifier(
                kind="CIN",
                value="U12345MH2020PLC123456",
                support=anchor(fixture, "U12345MH2020PLC123456"),
            ),
            ApprovedIdentifier(
                kind="ISIN",
                value="INE040A01034",
                support=anchor(fixture, "INE040A01034"),
            ),
        ),
        review_note="Synthetic identity registration for engineering tests only.",
    )


def resolver_run(fixture: EntityContext) -> EntityRun:
    evidence, artifact_sha = fixture.repository.evidence_for_parse(fixture.fixture.artifact.id)
    return EntityResolver(fixture.repository.snapshot(), current_configuration()).run(
        evidence, artifact_sha
    )


def insert_run(
    connection: DatabaseConnection,
    fixture: EntityContext,
    run: EntityRun,
    *,
    payload: bytes | None = None,
) -> None:
    snapshot = fixture.repository.snapshot()
    registry_bytes = json.dumps(
        {"entities": [entity.model_dump(mode="json") for entity in snapshot.entities]},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    payload = payload or canonical_bytes(run)
    configuration_bytes = raw_bytes(json.loads(payload)["configuration"])
    connection.execute(
        """INSERT INTO regintel.entity_runs
        (id,parse_version_id,artifact_sha256,registry_revision,registry_sha256,
         configuration_sha256,configuration_bytes,registry_bytes,run_bytes,run_sha256,
         mention_count,submitted_by,auth_version)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            run.id,
            run.parse_version_id,
            run.artifact_sha256,
            run.registry_revision,
            run.registry_sha256,
            hashlib.sha256(configuration_bytes).hexdigest(),
            configuration_bytes,
            registry_bytes,
            payload,
            hashlib.sha256(payload).hexdigest(),
            len(run.mentions),
            fixture.user.id,
            fixture.user.auth_version,
        ),
    )


def raw_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


@pytest.mark.parametrize(
    "mutation,diagnostic",
    [
        ("kind_null", "Entity registration requires bounded audited source support"),
        ("kind_missing", "Entity registration requires bounded audited source support"),
        ("identifier_kind_null", "An approved identifier requires exact source support"),
        ("identifier_kind_missing", "An approved identifier requires exact source support"),
        ("quote_null", "Entity registration requires bounded audited source support"),
        ("quote_number", "Entity registration requires bounded audited source support"),
        ("span_string", "Entity support requires an exact Unicode source span"),
        ("span_null", "Entity support requires an exact Unicode source span"),
        ("legal_blank", "Entity registration requires bounded audited source support"),
        ("legal_punctuation", "Entity registration requires bounded audited source support"),
        ("alias_punctuation", "An approved alias requires exact source support"),
        ("duplicate_name", "Approved names must be distinct within an entity"),
        ("extra_key", "Entity registration requires bounded audited source support"),
        ("anchor_extra_key", "Entity support requires an exact Unicode source span"),
        ("person_cin", "An approved identifier requires exact source support"),
    ],
)
def test_raw_registration_nulls_and_types_cannot_create_immutable_identity(
    entities, mutation, diagnostic
):
    entity = registration(entities)
    value = entity.model_dump(mode="json")
    if mutation == "kind_null":
        value["kind"] = None
    elif mutation == "kind_missing":
        value.pop("kind")
    elif mutation.startswith("identifier_kind"):
        if mutation.endswith("null"):
            value["identifiers"][0]["kind"] = None
        else:
            value["identifiers"][0].pop("kind")
    elif mutation.startswith("quote"):
        value["legal_name_support"]["quote"] = None if mutation.endswith("null") else 123
    elif mutation.startswith("span"):
        value["legal_name_support"]["start"] = (
            str(value["legal_name_support"]["start"]) if mutation.endswith("string") else None
        )
    elif mutation.startswith("legal"):
        name = " " if mutation.endswith("blank") else "("
        value["legal_name"] = name
        value["legal_name_support"] = anchor(entities, name).model_dump(mode="json")
    elif mutation == "alias_punctuation":
        value["aliases"][0] = {
            "name": "(",
            "support": anchor(entities, "(").model_dump(mode="json"),
        }
    elif mutation == "duplicate_name":
        value["aliases"].append(
            {"name": value["legal_name"], "support": value["legal_name_support"]}
        )
    elif mutation == "extra_key":
        value["unapproved_field"] = True
    elif mutation == "anchor_extra_key":
        value["legal_name_support"]["unapproved_field"] = True
    elif mutation == "person_cin":
        value["kind"] = "PERSON"
    payload = raw_bytes(value)
    with connect_database(entities.repository.database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation) as caught, connection.transaction():
            connection.execute(
                "INSERT INTO regintel.entity_registrations "
                "(id,registration_bytes,registration_sha256,registered_by,auth_version) "
                "VALUES(%s,%s,%s,%s,%s)",
                (
                    entity.id,
                    payload,
                    hashlib.sha256(payload).hexdigest(),
                    entities.user.id,
                    entities.user.auth_version,
                ),
            )
        assert caught.value.diag.message_primary == diagnostic
    assert entities.repository.snapshot().revision == 0


@pytest.mark.parametrize(
    "mutation,diagnostic",
    [
        ("state_null", "Entity mention must be an immutable run member"),
        ("state_missing", "Entity mention must be an immutable run member"),
        ("state_unknown", "Entity mention must be an immutable run member"),
        ("method_null", "Fuzzy proposals cannot independently resolve an entity"),
        ("method_unknown", "Fuzzy proposals cannot independently resolve an entity"),
        ("proposal_method_null", "Resolution proposals require supplied registry entity IDs"),
        ("proposal_method_unknown", "Resolution proposals require supplied registry entity IDs"),
        ("entity_null", "Resolution proposals require supplied registry entity IDs"),
        ("entity_unknown", "Resolution proposals require supplied registry entity IDs"),
        ("fuzzy_resolved", "Fuzzy proposals cannot independently resolve an entity"),
        ("method_missing", "Entity mention must be an immutable run member"),
        ("resolution_extra", "Entity mention must be an immutable run member"),
        ("score_missing", "Resolution proposals require supplied registry entity IDs"),
        ("configuration_bad", "Entity run must bind the sealed parse and current registry"),
    ],
)
def test_raw_resolution_nulls_unknown_ids_and_fuzzy_cannot_seal_run(entities, mutation, diagnostic):
    entities.repository.register(registration(entities), entities.user)
    run = resolver_run(entities)
    index = next(index for index, item in enumerate(run.mentions) if item.kind == "CIN")
    raw = run.model_dump(mode="json")
    resolution = raw["mentions"][index]["resolution"]
    if mutation.startswith("state"):
        if mutation == "state_missing":
            resolution.pop("state")
        else:
            resolution["state"] = None if mutation == "state_null" else "ACCEPTED"
    elif mutation.startswith("proposal_method"):
        resolution["proposals"][0]["method"] = (
            None if mutation.endswith("null") else "MODEL_ACCEPTED"
        )
    elif mutation == "method_missing":
        resolution.pop("method")
    elif mutation == "resolution_extra":
        resolution["unapproved_field"] = True
    elif mutation == "score_missing":
        resolution["proposals"][0].pop("score")
    elif mutation == "configuration_bad":
        raw["configuration"]["fuzzy_threshold"] = -1.0
    elif mutation.startswith("method"):
        resolution["method"] = None if mutation.endswith("null") else "MODEL_ACCEPTED"
    elif mutation.startswith("entity"):
        selected = None if mutation.endswith("null") else str(uuid4())
        resolution["proposals"][0]["entity_id"] = selected
        resolution["entity_id"] = str(uuid4()) if selected is None else selected
    else:
        resolution["method"] = "FUZZY"
        resolution["proposals"][0].update(method="FUZZY", score=99.0)
    mention = run.mentions[index]
    support = mention.support
    with connect_database(entities.repository.database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation) as caught, connection.transaction():
            insert_run(connection, entities, run, payload=raw_bytes(raw))
            connection.execute(
                "INSERT INTO regintel.entity_mentions "
                "(id,run_id,parse_version_id,evidence_id,start_offset,end_offset,quote,kind,"
                "mention_bytes) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    mention.id,
                    run.id,
                    run.parse_version_id,
                    support.evidence_id,
                    support.start,
                    support.end,
                    support.quote,
                    mention.kind,
                    raw_bytes(raw["mentions"][index]),
                ),
            )
        assert caught.value.diag.message_primary == diagnostic
        assert connection.execute("SELECT count(*) FROM regintel.entity_runs").fetchone() == (0,)


def test_database_requires_complete_exact_source_scan_not_a_valid_subset(entities):
    fixture = context(entities.repository.database)
    artifact = synthetic_artifact(
        configuration=fixture.configuration,
        blob=fixture.blob,
        parse_id=fixture.artifact.id,
        filing_id=fixture.artifact.filing_id,
        filing_version_id=fixture.artifact.filing_version_id,
        original=SOURCE,
    )
    block = artifact.blocks[0]
    split = SOURCE.index("Alpha Solar Limited")
    block = block.model_copy(
        update={
            "exact_spans": (
                TextSpan(block_id=block.id, start=0, end=split, quote=SOURCE[:split]),
                TextSpan(block_id=block.id, start=split, end=len(SOURCE), quote=SOURCE[split:]),
            )
        }
    )
    artifact = artifact.model_copy(update={"blocks": (block, *artifact.blocks[1:])})
    fixture = replace(fixture, artifact=artifact)
    with connect_database(entities.repository.database) as connection, connection.transaction():
        persist(connection, fixture)
        parsed(connection, fixture)
    evidence, artifact_sha = entities.repository.evidence_for_parse(artifact.id)
    assert len(evidence) == 2
    run = EntityResolver(entities.repository.snapshot(), current_configuration()).run(
        evidence, artifact_sha
    )
    chosen = next(item.id for item in evidence if item.span.quote == SOURCE[:split])
    partial = EntityRun.model_validate(
        run.model_dump(mode="python") | {"evidence_ids": (chosen,), "mentions": ()}
    )
    with connect_database(entities.repository.database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation) as caught, connection.transaction():
            insert_run(connection, entities, partial)
        assert caught.value.diag.message_primary == (
            "Entity run must bind the sealed parse and current registry"
        )
        assert connection.execute("SELECT count(*) FROM regintel.entity_runs").fetchone() == (0,)


def test_registry_is_empty_then_audited_exact_and_replayable(entities):
    before = entities.repository.snapshot()
    assert before.revision == 0 and before.entities == ()
    entity = registration(entities)
    assert entities.repository.register(entity, entities.user) is True
    assert entities.repository.register(entity, entities.user) is False
    snapshot = entities.repository.snapshot()
    assert snapshot.revision == 1 and snapshot.entities == (entity,)
    assert before.sha256 != snapshot.sha256
    assert entity.legal_name_support.start == SOURCE.index(entity.legal_name)
    with connect_database(entities.repository.database) as connection:
        assert connection.execute(
            "SELECT registered_by,auth_version FROM regintel.entity_registrations"
        ).fetchone() == (entities.user.id, entities.user.auth_version)


def test_duplicate_identifier_rolls_back_registration_and_snapshot(entities):
    first = registration(entities)
    entities.repository.register(first, entities.user)
    snapshot = entities.repository.snapshot()
    second = registration(entities)
    with pytest.raises(EntityConflict):
        entities.repository.register(second, entities.user)
    assert entities.repository.snapshot() == snapshot
    with connect_database(entities.repository.database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM regintel.entity_identifiers"
        ).fetchone() == (2,)


def test_registration_payload_conflict_cannot_overwrite_existing_audit(entities):
    entity = registration(entities)
    entities.repository.register(entity, entities.user)
    changed = EntityRegistration.model_validate(
        entity.model_dump(mode="python") | {"review_note": "A different audited interpretation."}
    )
    with pytest.raises(EntityConflict):
        entities.repository.register(changed, entities.user)
    assert entities.repository.snapshot().entities == (entity,)


def test_wrong_exact_source_span_does_not_register_entity(entities):
    entity = registration(entities)
    support = EvidenceAnchor.model_validate(
        entity.legal_name_support.model_dump(mode="python")
        | {"start": entity.legal_name_support.start + 1, "end": entity.legal_name_support.end + 1}
    )
    changed = EntityRegistration.model_validate(
        entity.model_dump(mode="python") | {"legal_name_support": support}
    )
    with pytest.raises(EntitySourceError):
        entities.repository.register(changed, entities.user)
    assert entities.repository.snapshot().revision == 0


def test_registration_rechecks_revocation_even_on_idempotent_replay(entities):
    entity = registration(entities)
    entities.repository.register(entity, entities.user)
    with connect_database(entities.repository.database) as connection:
        connection.execute(
            "UPDATE regintel.users SET is_active=FALSE WHERE id=%s", (entities.user.id,)
        )
    with pytest.raises(EntityAuthorizationError):
        entities.repository.register(entity, entities.user)
    assert entities.repository.snapshot().revision == 1


def test_learner_role_cannot_write_registry(entities):
    with connect_database(entities.repository.database) as connection:
        connection.execute(
            "UPDATE regintel.users SET role='learner' WHERE id=%s", (entities.user.id,)
        )
    user = PostgreSQLAuthRepository(entities.repository.database).get_by_id(entities.user.id)
    assert user is not None
    with pytest.raises(EntityAuthorizationError):
        entities.repository.register(registration(entities), user)
    assert entities.repository.snapshot().revision == 0


def test_concurrent_registration_preserves_one_audit(entities):
    entity = registration(entities)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(lambda _: entities.repository.register(entity, entities.user), range(2))
        )
    assert sorted(results) == [False, True]
    assert entities.repository.snapshot().revision == 1


def test_bulk_exact_evidence_keeps_original_unicode_and_hash(entities):
    evidence, artifact_sha = entities.repository.evidence_for_parse(entities.fixture.artifact.id)
    assert len(evidence) == 1 and evidence[0].span.quote == SOURCE
    assert len(artifact_sha) == 64
    assert evidence[0].span.quote != entities.fixture.artifact.blocks[0].text
    with pytest.raises(EntityNotFound):
        entities.repository.evidence_for_parse(str(uuid4()))


def test_run_preserves_exact_and_unknown_identifiers_without_financial_authority(entities):
    entities.repository.register(registration(entities), entities.user)
    run = resolver_run(entities)
    assert entities.repository.save_run(run, entities.user) == run
    assert entities.repository.save_run(run, entities.user) == run
    assert entities.repository.get_run(run.id) == run
    assert entities.repository.get_run(str(uuid4())) is None
    assert any(mention.resolution.state == "RESOLVED" for mention in run.mentions)
    assert any(mention.resolution.state == "UNRESOLVED" for mention in run.mentions)
    with connect_database(entities.repository.database) as connection:
        for table in ("entity_runs", "entity_mentions"):
            count = 1 if table == "entity_runs" else len(run.mentions)
            assert connection.execute(f"SELECT count(*) FROM regintel.{table}").fetchone() == (
                count,
            )
        for table in (
            "candidates",
            "acceptance_audits",
            "fact_observations",
            "relation_observations",
            "corpus_versions",
        ):
            assert connection.execute(f"SELECT count(*) FROM regintel.{table}").fetchone() == (0,)


def test_stale_registry_run_is_rejected_and_old_stored_run_remains_readable(entities):
    first = resolver_run(entities)
    entities.repository.save_run(first, entities.user)
    entities.repository.register(registration(entities), entities.user)
    with pytest.raises(EntityRegistryChanged):
        entities.repository.save_run(first, entities.user)
    assert entities.repository.get_run(first.id) == first
    second = resolver_run(entities)
    assert entities.repository.save_run(second, entities.user) == second
    assert second.id != first.id


def test_concurrent_runs_are_single_complete_result(entities):
    entities.repository.register(registration(entities), entities.user)
    run = resolver_run(entities)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(lambda _: entities.repository.save_run(run, entities.user), range(2))
        )
    assert results == [run, run]


def test_rederived_run_rejects_omissions_and_forged_exact_results(entities):
    entities.repository.register(registration(entities), entities.user)
    run = resolver_run(entities)
    omitted = EntityRun.model_validate(run.model_dump(mode="python") | {"mentions": ()})
    with pytest.raises(EntitySourceError):
        entities.repository.save_run(omitted, entities.user)
    altered = EntityRun.model_validate(run.model_dump(mode="python") | {"id": str(uuid4())})
    with pytest.raises(EntitySourceError):
        entities.repository.save_run(altered, entities.user)
    assert entities.repository.get_run(run.id) is None


def test_database_terminal_run_without_mentions_rolls_back(entities):
    run = resolver_run(entities)
    assert run.mentions
    with connect_database(entities.repository.database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            insert_run(connection, entities, run)
        assert connection.execute("SELECT count(*) FROM regintel.entity_runs").fetchone() == (0,)


def test_database_requires_complete_identifier_registration_atomically(entities):
    entity = registration(entities)
    payload = canonical_bytes(entity)
    with connect_database(entities.repository.database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(
                "INSERT INTO regintel.entity_registrations "
                "(id,registration_bytes,registration_sha256,registered_by,auth_version) "
                "VALUES(%s,%s,%s,%s,%s)",
                (
                    entity.id,
                    payload,
                    hashlib.sha256(payload).hexdigest(),
                    entities.user.id,
                    entities.user.auth_version,
                ),
            )
    assert entities.repository.snapshot().revision == 0


@pytest.mark.parametrize(
    "value,valid",
    [
        ("INE040A01034", True),
        ("INE040A01035", False),
        ("US0378331005", True),
        ("US0378331006", False),
    ],
)
def test_database_isin_check_digit_matches_identifier_contract(entities, value, valid):
    with connect_database(entities.repository.database) as connection:
        assert connection.execute(
            "SELECT regintel.valid_entity_identifier('ISIN',%s)", (value,)
        ).fetchone() == (valid,)


def ambiguous_review(fixture: EntityContext) -> tuple[EntityRun, EntityReview]:
    alpha, beta = registration(fixture), registration(fixture, beta=True)
    fixture.repository.register(alpha, fixture.user)
    fixture.repository.register(beta, fixture.user)
    run = resolver_run(fixture)
    fixture.repository.save_run(run, fixture.user)
    mention = next(item for item in run.mentions if item.support.quote == "Alpha Solar")
    assert mention.resolution.state == "REVIEW"
    decision = EntityReview(
        id=str(uuid4()),
        run_id=run.id,
        mention_id=mention.id,
        decision="RESOLVE",
        entity_id=alpha.id,
        support_evidence_ids=(fixture.evidence_id,),
        review_note="Synthetic source context reviewed; no financial acceptance.",
    )
    return run, decision


def test_audited_review_preserves_original_ambiguity_and_replay(entities):
    run, decision = ambiguous_review(entities)
    assert entities.repository.review(decision, entities.user) is True
    assert entities.repository.review(decision, entities.user) is False
    assert entities.repository.reviews(run.id) == (decision,)
    assert entities.repository.get_run(run.id) == run
    new_receipt_id = EntityReview.model_validate(
        decision.model_dump(mode="python") | {"id": str(uuid4())}
    )
    with pytest.raises(EntityConflict):
        entities.repository.review(new_receipt_id, entities.user)
    mention = next(item for item in run.mentions if item.id == decision.mention_id)
    changed = EntityReview.model_validate(
        decision.model_dump(mode="python")
        | {
            "id": str(uuid4()),
            "entity_id": next(
                x.entity_id
                for x in mention.resolution.proposals
                if x.entity_id != decision.entity_id
            ),
        }
    )
    with pytest.raises(EntityConflict):
        entities.repository.review(changed, entities.user)


def test_review_cannot_select_unknown_entity_or_wrong_source(entities):
    run, decision = ambiguous_review(entities)
    wrong_entity = EntityReview.model_validate(
        decision.model_dump(mode="python") | {"entity_id": str(uuid4())}
    )
    with pytest.raises(EntityConflict):
        entities.repository.review(wrong_entity, entities.user)
    wrong_source = EntityReview.model_validate(
        decision.model_dump(mode="python") | {"support_evidence_ids": (str(uuid4()),)}
    )
    with pytest.raises(EntitySourceError):
        entities.repository.review(wrong_source, entities.user)
    assert entities.repository.reviews(run.id) == ()


def test_review_rechecks_revoked_role_on_replay(entities):
    _, decision = ambiguous_review(entities)
    entities.repository.review(decision, entities.user)
    with connect_database(entities.repository.database) as connection:
        connection.execute(
            "UPDATE regintel.users SET role='learner' WHERE id=%s", (entities.user.id,)
        )
    with pytest.raises(EntityAuthorizationError):
        entities.repository.review(decision, entities.user)


@pytest.mark.parametrize("mutation", ["entity_missing", "extra_key", "entity_boolean"])
def test_raw_rejected_review_cannot_create_an_unreadable_audit(entities, mutation):
    run, resolved = ambiguous_review(entities)
    decision = EntityReview.model_validate(
        resolved.model_dump(mode="python") | {"decision": "REJECT", "entity_id": None}
    )
    value = decision.model_dump(mode="json")
    if mutation == "entity_missing":
        value.pop("entity_id")
    elif mutation == "extra_key":
        value["unapproved_field"] = True
    else:
        value["entity_id"] = False
    payload = raw_bytes(value)
    with connect_database(entities.repository.database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(
                "INSERT INTO regintel.entity_reviews "
                "(id,run_id,mention_id,decision,entity_id,review_bytes,review_sha256,"
                "reviewed_by,auth_version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    decision.id,
                    run.id,
                    decision.mention_id,
                    "REJECT",
                    None,
                    payload,
                    hashlib.sha256(payload).hexdigest(),
                    entities.user.id,
                    entities.user.auth_version,
                ),
            )
    assert entities.repository.reviews(run.id) == ()
    assert entities.repository.get_run(run.id) == run


def test_concurrent_review_returns_one_final_immutable_decision(entities):
    run, decision = ambiguous_review(entities)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(lambda _: entities.repository.review(decision, entities.user), range(2))
        )
    assert sorted(results) == [False, True]
    assert entities.repository.reviews(run.id) == (decision,)


@pytest.mark.parametrize(
    "table",
    [
        "entity_registrations",
        "entity_identifiers",
        "entity_runs",
        "entity_mentions",
        "entity_reviews",
    ],
)
@pytest.mark.parametrize("action", ["update", "delete", "truncate"])
def test_all_entity_sources_and_audits_are_immutable(entities, table, action):
    ambiguous_review(entities)
    if table == "entity_reviews":
        run = resolver_run(entities)
        mention = next(item for item in run.mentions if item.resolution.state == "REVIEW")
        entities.repository.review(
            EntityReview(
                id=str(uuid4()),
                run_id=run.id,
                mention_id=mention.id,
                decision="REJECT",
                entity_id=None,
                support_evidence_ids=(entities.evidence_id,),
                review_note="Synthetic rejected ambiguous identity.",
            ),
            entities.user,
        )
    column = "entity_id" if table == "entity_identifiers" else "id"
    commands = {
        "update": f"UPDATE regintel.{table} SET {column}={column}",
        "delete": f"DELETE FROM regintel.{table}",
        "truncate": f"TRUNCATE regintel.{table} CASCADE",
    }
    with connect_database(entities.repository.database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(commands[action])
