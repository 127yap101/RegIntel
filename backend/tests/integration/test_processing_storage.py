"""Real PostgreSQL stage atomicity, duplicate delivery and recovery; synthetic sources."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import psycopg
import pytest

from backend.tests.integration.test_evidence_storage import context, parsed, persist
from backend.tests.integration.test_validation_storage import (
    ValidationContext,
)
from backend.tests.integration.test_validation_storage import (
    validated as validated,
)
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.contracts.models import TextSpan
from regintel.db.migrations import connect_database
from regintel.entities.models import EntityRegistration, EntityReview, EvidenceAnchor
from regintel.evidence.projection import project_parse
from regintel.processing.configuration import current_configuration
from regintel.processing.models import EntityStageInput, ProcessingRequest
from regintel.processing.processor import Processor
from regintel.processing.repository import (
    ProcessingConflict,
    ProcessingFenced,
    ProcessingRepository,
    ProcessingUnavailable,
    lock_key,
)

pytestmark = pytest.mark.integration


def submitted(context: ValidationContext):
    repository = ProcessingRepository(context.database)
    source = context.repository.input_for_run(context.candidate_run_id)
    request = ProcessingRequest(
        idempotency_key=str(uuid4()),
        parse_version_id=source.candidate_run.parse_version_id,
        metric_ids=tuple(sorted(metric.id for metric in source.source.metrics)),
    )
    job = repository.submit(request, context.user)
    return repository, request, job


def assert_closed(context: ValidationContext):
    with connect_database(context.database) as connection:
        for table in (
            "acceptance_audits",
            "fact_observations",
            "relation_observations",
            "corpus_versions",
        ):
            assert connection.execute(f"SELECT count(*) FROM regintel.{table}").fetchone() == (0,)


def new_registry(context):
    entities = ProcessingRepository(context.database).entities
    evidence, _ = entities.evidence_for_parse(
        context.repository.input_for_run(context.candidate_run_id).candidate_run.parse_version_id
    )
    entities.register(
        EntityRegistration(
            id=str(uuid4()),
            kind="COMPANY",
            legal_name="Exact Lead",
            legal_name_support=EvidenceAnchor(
                evidence_id=evidence[0].id,
                start=evidence[0].span.start,
                end=evidence[0].span.start + len("Exact Lead"),
                quote="Exact Lead",
            ),
            aliases=(),
            identifiers=(),
            review_note="Authored third identity for recovery test.",
        ),
        context.user,
    )


def test_complete_pipeline_replays_and_never_approves_or_publishes(validated):
    repository, request, job = submitted(validated)
    assert repository.submit(request, validated.user) == job
    Processor(repository).run(job.id)
    result = repository.get(job.id)
    assert result is not None and result.state == "SUCCEEDED" and result.generation == 1
    assert tuple(item.stage for item in result.checkpoints) == ("ENTITY", "CANDIDATE", "VALIDATION")
    assert tuple(event.kind for event in result.events) == (
        "STARTED",
        "INPUT_FROZEN",
        "CHECKPOINT",
        "INPUT_FROZEN",
        "CHECKPOINT",
        "INPUT_FROZEN",
        "CHECKPOINT",
        "COMPLETED",
    )
    Processor(repository).run(job.id)
    assert repository.get(job.id) == result
    assert repository.dispatch(lambda _: pytest.fail("Terminal jobs must not be dispatched")) == 0
    with connect_database(validated.database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM regintel.validation_reviews"
        ).fetchone() == (0,)
    assert_closed(validated)


@pytest.mark.parametrize("stage", ["ENTITY", "CANDIDATE", "VALIDATION"])
def test_recovery_after_committed_checkpoint_skips_completed_stage(validated, stage):
    repository, _, job = submitted(validated)
    interrupted = False

    def boundary(actual, where):
        nonlocal interrupted
        if actual == stage and where == "checkpointed" and not interrupted:
            interrupted = True
            raise ProcessingUnavailable("Synthetic connection loss, private diagnostic.")

    with pytest.raises(ProcessingUnavailable):
        Processor(repository, boundary=boundary).run(job.id)
    before = repository.get(job.id)
    assert before is not None and before.state == "RUNNING"
    preserved = before.checkpoints
    assert preserved[-1].stage == stage
    Processor(repository).run(job.id)
    after = repository.get(job.id)
    assert after is not None and after.state == "SUCCEEDED" and after.generation == 2
    assert after.checkpoints[: len(preserved)] == preserved
    assert_closed(validated)


@pytest.mark.parametrize("stage", ["ENTITY", "CANDIDATE", "VALIDATION"])
def test_transactional_checkpoint_failure_rolls_back_new_domain_result(
    validated, stage, monkeypatch
):
    new_registry(validated)
    repository, _, job = submitted(validated)
    original = repository.checkpoint
    fired = False
    table = {
        "ENTITY": "entity_runs",
        "CANDIDATE": "candidate_runs",
        "VALIDATION": "validation_runs",
    }[stage]
    before_count = None

    def boundary(actual, where):
        nonlocal before_count
        if actual == stage and where == "frozen":
            with repository.connect() as connection:
                before_count = connection.execute(
                    f"SELECT count(*) FROM regintel.{table}"
                ).fetchone()[0]

    def checkpoint(connection, selected, actual, *args):
        nonlocal fired
        original(connection, selected, actual, *args)
        if actual == stage and not fired:
            fired = True
            assert (
                connection.execute(f"SELECT count(*) FROM regintel.{table}").fetchone()[0]
                == before_count + 1
            )
            raise ProcessingUnavailable("Synthetic failure before transaction commit.")

    monkeypatch.setattr(repository, "checkpoint", checkpoint)
    with pytest.raises(ProcessingUnavailable):
        Processor(repository, boundary=boundary).run(job.id)
    before = repository.get(job.id)
    assert before is not None and not any(item.stage == stage for item in before.checkpoints)
    with repository.connect() as connection:
        assert (
            connection.execute(f"SELECT count(*) FROM regintel.{table}").fetchone()[0]
            == before_count
        )
    monkeypatch.setattr(repository, "checkpoint", original)
    Processor(repository).run(job.id)
    after = repository.get(job.id)
    assert after is not None and after.state == "SUCCEEDED" and after.generation == 2
    assert_closed(validated)


def test_concurrent_deliveries_share_one_attempt_and_complete_result(validated):
    repository, _, job = submitted(validated)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: Processor(repository).run(job.id), range(2)))
    result = repository.get(job.id)
    assert result is not None and result.state == "SUCCEEDED" and result.generation == 1
    assert_closed(validated)


def test_conflicting_request_key_preserves_original_job(validated):
    repository, request, job = submitted(validated)
    conflict = ProcessingRequest.model_validate(
        request.model_dump(mode="python") | {"metric_ids": ()}
    )
    with pytest.raises(ProcessingConflict):
        repository.submit(conflict, validated.user)
    assert repository.get(job.id) == job


def test_old_attempt_is_fenced_from_checkpoint_and_terminal_writes(validated):
    repository, _, job = submitted(validated)
    with repository.connect() as connection:
        old = repository.claim(connection, job.id)
        current = repository.claim(connection, job.id)
    assert old is not None and current is not None and current.generation == old.generation + 1
    with pytest.raises(ProcessingFenced):
        repository.fail(old, "SOURCE_INVALID")
    assert repository.get(job.id) == current


def test_dispatch_recovers_orphaned_sent_job_and_retains_broker_failure(validated):
    repository, _, job = submitted(validated)
    sends = []
    assert repository.dispatch(sends.append, job_id=job.id) == 1
    assert repository.dispatch(sends.append, job_id=job.id) == 1
    assert sends == [job.id, job.id]

    def failed(_):
        raise RuntimeError("Synthetic private broker diagnostics.")

    assert repository.dispatch(failed, job_id=job.id) == 0
    with connect_database(validated.database) as connection:
        assert connection.execute(
            "SELECT attempts,sent_at IS NOT NULL,last_failure_code "
            "FROM regintel.processing_dispatch WHERE job_id=%s",
            (job.id,),
        ).fetchone() == (3, True, "BROKER_UNAVAILABLE")


def test_frozen_source_bytes_and_history_cannot_be_changed(validated):
    repository, _, job = submitted(validated)
    Processor(repository).run(job.id)
    for table in ("processing_inputs", "processing_checkpoints", "processing_events"):
        for command in (
            f"DELETE FROM regintel.{table}",
            f"TRUNCATE regintel.{table} CASCADE",
            f"UPDATE regintel.{table} SET generation=generation",
        ):
            with (
                connect_database(validated.database) as connection,
                pytest.raises(psycopg.errors.CheckViolation),
            ):
                connection.execute(command)
    assert_closed(validated)


def test_changed_installed_configuration_fails_without_work(validated, monkeypatch):
    repository, _, job = submitted(validated)
    changed = current_configuration().model_copy(update={"code_sha256": "a" * 64})
    monkeypatch.setattr("regintel.processing.processor.current_configuration", lambda: changed)
    Processor(repository).run(job.id)
    result = repository.get(job.id)
    assert result.state == "FAILED" and result.failure_code == "CONFIGURATION_CHANGED"
    assert result.checkpoints == ()
    assert_closed(validated)


def test_revoked_submitter_fails_without_domain_write(validated):
    repository, _, job = submitted(validated)
    with repository.connect() as connection:
        connection.execute(
            "UPDATE regintel.users SET is_active=false WHERE id=%s", (validated.user.id,)
        )
    Processor(repository).run(job.id)
    result = repository.get(job.id)
    assert result.state == "FAILED" and result.failure_code == "AUTHORIZATION_CHANGED"
    assert result.checkpoints == ()
    assert_closed(validated)


def test_revocation_after_last_checkpoint_blocks_completion_on_recovery(validated):
    repository, _, job = submitted(validated)

    def boundary(stage, where):
        if stage == "VALIDATION" and where == "checkpointed":
            raise ProcessingUnavailable("Authored interruption before final bookkeeping.")

    with pytest.raises(ProcessingUnavailable):
        Processor(repository, boundary=boundary).run(job.id)
    before = repository.get(job.id)
    assert before.state == "RUNNING" and len(before.checkpoints) == 3
    with repository.connect() as connection:
        connection.execute(
            "UPDATE regintel.users SET is_active=false WHERE id=%s", (validated.user.id,)
        )
    Processor(repository).run(job.id)
    after = repository.get(job.id)
    assert after.state == "FAILED" and after.failure_code == "AUTHORIZATION_CHANGED"
    assert after.checkpoints == before.checkpoints and after.generation == 2
    assert_closed(validated)


@pytest.mark.parametrize("stage", ["ENTITY", "CANDIDATE", "VALIDATION"])
def test_changed_frozen_dependencies_fail_without_replacing_snapshot(validated, stage):
    repository, _, job = submitted(validated)
    frozen = None

    def boundary(actual, where):
        nonlocal frozen
        if actual != stage or where != "frozen":
            return
        frozen = repository.input(job.id, stage)
        if stage == "ENTITY":
            new_registry(validated)
        else:
            current = repository.get(job.id)
            entity_id = current.checkpoints[0].output_id
            run = repository.entities.get_run(entity_id)
            mention = run.mentions[0]
            repository.entities.review(
                EntityReview(
                    id=str(uuid4()),
                    run_id=entity_id,
                    mention_id=mention.id,
                    decision="REJECT",
                    entity_id=None,
                    support_evidence_ids=(mention.support.evidence_id,),
                    review_note="Authored changed dependency after freeze.",
                ),
                validated.user,
            )

    Processor(repository, boundary=boundary).run(job.id)
    result = repository.get(job.id)
    assert result.state == "FAILED" and result.failure_code == "INPUT_CHANGED"
    assert repository.input(job.id, stage) == frozen
    assert not any(item.stage == stage for item in result.checkpoints)
    assert_closed(validated)


def test_dispatch_skips_live_worker_session_lock(validated):
    repository, _, job = submitted(validated)
    with repository.connect() as control:
        control.execute("SELECT pg_advisory_lock(%s)", (lock_key(job.id),))
        assert (
            repository.dispatch(lambda _: pytest.fail("Live worker must not be redispatched")) == 0
        )
        control.execute("SELECT pg_advisory_unlock(%s)", (lock_key(job.id),))
    assert repository.dispatch(lambda _: None) == 1


def test_immediate_consumer_can_claim_before_dispatch_transaction_commits(validated):
    repository, _, job = submitted(validated)
    assert (
        repository.dispatch(lambda identifier: Processor(repository).run(identifier), job_id=job.id)
        == 1
    )
    assert repository.get(job.id).state == "SUCCEEDED"


def test_unexpected_stage_error_is_terminal_and_safe(validated):
    repository, _, job = submitted(validated)

    def boundary(*_):
        raise RuntimeError("private source and connection details")

    Processor(repository, boundary=boundary).run(job.id)
    result = repository.get(job.id)
    assert result.state == "FAILED" and result.failure_code == "PROCESSING_FAILED"
    assert result.checkpoints == () and "private" not in result.model_dump_json()
    Processor(repository).run(job.id)
    assert repository.get(job.id) == result


def test_late_attempt_cannot_freeze_attach_or_finish(validated):
    repository, _, job = submitted(validated)

    def boundary(stage, where):
        if stage == "ENTITY" and where == "frozen":
            with repository.connect() as connection:
                assert repository.claim(connection, job.id).generation == 2

    Processor(repository, boundary=boundary).run(job.id)
    current = repository.get(job.id)
    assert current.state == "RUNNING" and current.generation == 2 and current.checkpoints == ()
    Processor(repository).run(job.id)
    result = repository.get(job.id)
    assert result.state == "SUCCEEDED" and result.generation == 3
    assert_closed(validated)


def test_transient_error_wrapped_by_domain_adapter_remains_retryable(validated, monkeypatch):
    repository, _, job = submitted(validated)
    original = repository.entities.save_run

    def unavailable(*args, **kwargs):
        from regintel.entities.repository import EntitySourceError

        try:
            raise psycopg.errors.DeadlockDetected("private storage diagnostics")
        except psycopg.Error:
            raise EntitySourceError("sanitized source adapter") from None

    monkeypatch.setattr(repository.entities, "save_run", unavailable)
    with pytest.raises(ProcessingUnavailable):
        Processor(repository).run(job.id)
    before = repository.get(job.id)
    assert before.state == "RUNNING" and before.events[-1].kind == "RETRY"
    monkeypatch.setattr(repository.entities, "save_run", original)
    Processor(repository).run(job.id)
    assert repository.get(job.id).state == "SUCCEEDED"


@pytest.mark.parametrize(
    "section,field,value",
    (
        ("entity", "max_proposals", "5"),
        ("entity", "max_proposals", 5.0),
        ("entity", "max_proposals", False),
        ("entity", "fuzzy_threshold", 85),
        ("entity", "spacy_version", None),
        ("entity", "untrusted", "override"),
        ("candidate", "max_window_chars", "20000"),
        ("candidate", "max_window_chars", 20000.0),
        ("candidate", "max_candidates", "1000"),
        ("candidate", "max_input_chars", "2000000"),
        ("validation", "code_sha256", "bad"),
        ("validation", "extra", True),
    ),
)
def test_sql_rejects_configuration_that_would_poison_typed_reads(validated, section, field, value):
    repository, request, _ = submitted(validated)
    payload = request.model_dump(mode="json") | {"idempotency_key": str(uuid4())}
    configuration = current_configuration().model_dump(mode="json")
    configuration[section][field] = value
    request_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    config_bytes = json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode()
    with repository.connect() as connection, pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            "INSERT INTO regintel.processing_jobs "
            "(id,idempotency_key,parse_version_id,request_bytes,request_sha256,"
            "configuration_bytes,configuration_sha256,submitted_by,submitted_auth_version) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                str(uuid4()),
                payload["idempotency_key"],
                payload["parse_version_id"],
                request_bytes,
                hashlib.sha256(request_bytes).hexdigest(),
                config_bytes,
                hashlib.sha256(config_bytes).hexdigest(),
                validated.user.id,
                validated.user.auth_version,
            ),
        )


@pytest.mark.parametrize(
    "table,command",
    (
        ("processing_jobs", "UPDATE regintel.processing_jobs SET state='SUCCEEDED',generation=1"),
        ("processing_jobs", "DELETE FROM regintel.processing_jobs"),
        ("processing_dispatch", "UPDATE regintel.processing_dispatch SET attempts=1"),
        (
            "processing_dispatch",
            "UPDATE regintel.processing_dispatch SET attempts=2,sent_at=clock_timestamp()",
        ),
        ("processing_dispatch", "DELETE FROM regintel.processing_dispatch"),
        ("processing_dispatch", "TRUNCATE regintel.processing_dispatch"),
    ),
)
def test_sql_rejects_unsupported_job_or_dispatch_transition(validated, table, command):
    repository, _, _ = submitted(validated)
    with repository.connect() as connection, pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(command)


def test_multiple_evidence_records_keep_source_order_and_sorted_membership(auth_database):
    fixture = context(auth_database)
    first = fixture.artifact.blocks[0]
    second_id = str(uuid4())
    second = first.model_copy(
        update={
            "id": second_id,
            "exact_spans": tuple(
                TextSpan(block_id=second_id, start=s.start, end=s.end, quote=s.quote)
                for s in first.exact_spans
            ),
        }
    )
    artifact = fixture.artifact.model_copy(update={"blocks": (first, second), "tables": ()})
    projected = project_parse(artifact, fixture.configuration)
    descending = sorted(projected.evidence, key=lambda e: e.id, reverse=True)
    by_id = {block.id: block for block in artifact.blocks}
    blocks = []
    for index, record in enumerate(descending):
        block = by_id[record.span.block_id]
        source_ref = f"page/0/text-cell/{index}"
        blocks.append(
            block.model_copy(
                update={
                    "source_cell_index": index,
                    "source_ref": source_ref,
                    "provenance": tuple(
                        p.model_copy(update={"source_ref": source_ref}) for p in block.provenance
                    ),
                }
            )
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
    repository = ProcessingRepository(auth_database)
    job = repository.submit(
        ProcessingRequest(
            idempotency_key=str(uuid4()),
            parse_version_id=artifact.id,
            metric_ids=(),
        ),
        user,
    )
    Processor(repository).run(job.id)
    result = repository.get(job.id)
    assert result.state == "SUCCEEDED"
    frozen = EntityStageInput.model_validate_json(repository.input(job.id, "ENTITY"))
    assert tuple(e.id for e in frozen.evidence) == tuple(e.id for e in descending)
    run = repository.entities.get_run(result.checkpoints[0].output_id)
    assert run.evidence_ids == tuple(sorted(e.id for e in frozen.evidence))
    assert run.evidence_ids != tuple(e.id for e in frozen.evidence)
