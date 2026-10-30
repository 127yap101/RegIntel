"""Actual M1 sealing/binding on authored blank PDFs in an owned database; not gold data."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql

from backend.tests.integration.test_numerical_context_storage import InspectionContext, snapshot
from backend.tests.integration.test_numerical_context_storage import inspection as inspection
from backend.tests.native_context_fixtures import complete_raw, declared_bank, remap_draft
from backend.tests.test_numerical_context import ISSUER
from regintel.evidence.repository import EvidenceRepository, persist_projection
from regintel.ingestion.jobs import FilingJob, UploadMetadata
from regintel.ingestion.repository import JobRepository
from regintel.numerical.context_records import NumericalContextRecord
from regintel.numerical.context_storage import NumericalContextStorage
from regintel.numerical.evidence_binding_repository import NumericalEvidenceBindingRepository
from regintel.numerical.repository import NumericalAuthorizationError, NumericalSourceError
from regintel.parsing.native_context import (
    ContextCapture,
    NativeContextParse,
    build_native_context_parse,
    project_native_context,
)
from regintel.parsing.native_repository import NativeM1Producer, _persist_bank

pytestmark = pytest.mark.integration
TABLES = (
    "native_parse_manifests",
    "native_parse_source_pages",
    "native_parse_context_captures",
    "native_parse_table_sources",
)


@dataclass(frozen=True)
class NativeStoredFixture:
    source: InspectionContext
    result: NativeContextParse
    job: FilingJob
    record: NumericalContextRecord


def prepare_native_context(
    inspection: InspectionContext, tmp_path: Path, metadata: UploadMetadata | None = None
) -> NativeStoredFixture:
    source = inspection.source
    with source.connect() as connection:
        row = connection.execute(
            "SELECT raw_capture_bytes FROM regintel.numerical_page_captures WHERE id=%s",
            (UUID(inspection.draft.value.phrase.capture_id),),
        ).fetchone()
        owner = connection.execute(
            "SELECT filing_id FROM regintel.filing_versions WHERE id=%s",
            (UUID(inspection.draft.filing_version_id),),
        ).fetchone()
    assert row is not None and owner is not None
    raw = complete_raw(json.loads(bytes(row[0])))
    body = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    stored = source.save(inspection.draft.filing_version_id, body, 2, inspection.user)
    bank = declared_bank(tmp_path / "native-bank", inspection.source_path, stored)
    baseline = source.configuration.model_copy(
        update={"package_manifest_sha256": bank.manifest.configuration.package_manifest_sha256}
    )
    result = build_native_context_parse(
        bank,
        source=inspection.source_path,
        baseline=baseline,
        captures=(ContextCapture(stored, body),),
        parse_id=str(uuid4()),
        filing_id=str(owner[0]),
        filing_version_id=stored.filing_version_id,
        source_blob_id=stored.source_blob_id,
    )
    record = NumericalContextStorage(source).save(
        remap_draft(inspection.draft, stored), inspection.user
    )
    stage = source.storage.stage()
    stage.write(inspection.source_path.read_bytes())
    job = JobRepository(inspection.database).submit(
        stage.finish(),
        metadata or UploadMetadata(company_name_raw=ISSUER, document_type="RHP"),
        result.configuration.processing_configuration_sha256,
        inspection.user.id,
        inspection.user.auth_version,
    )
    return NativeStoredFixture(inspection, result, job, record)


@pytest.fixture
def unsealed(inspection: InspectionContext, tmp_path) -> NativeStoredFixture:
    return prepare_native_context(inspection, tmp_path)


@pytest.fixture
def native(unsealed: NativeStoredFixture) -> NativeStoredFixture:
    source = unsealed.source
    outcome = NativeM1Producer(source.source).run(unsealed.job.id, unsealed.result, source.user)
    assert outcome.state == "PARSED" and outcome.parse_version_id == unsealed.result.artifact.id
    return replace(unsealed, job=outcome)


def test_native_sealing_exposes_existing_m1_evidence_and_read_only_numerical_binding(native):
    source, result, record = native.source, native.result, native.record
    before = snapshot(source.database)
    bound = NumericalEvidenceBindingRepository(source.source).bind(
        record.id, result.artifact.id, source.user
    )
    value = bound.phrases[0].words[0].evidence
    actual = EvidenceRepository(source.database).get_evidence(value.id)
    assert actual is not None and actual[0] == value
    assert value.span.quote == "2,500.20" and value.source.page_index == 1
    assert not bound.acceptance_eligible and not bound.mandatory_m1_validation_complete
    assert NativeM1Producer(source.source).run(native.job.id, result, source.user) == native.job
    assert snapshot(source.database) == before
    with source.source.connect() as connection:
        row = connection.execute(
            "SELECT format_version FROM regintel.parse_artifacts WHERE parse_version_id=%s",
            (UUID(result.artifact.id),),
        ).fetchone()
        assert row == ("1.1.0",)
        assert connection.execute(
            "SELECT count(*) FROM regintel.native_parse_source_pages WHERE parse_version_id=%s",
            (UUID(result.artifact.id),),
        ).fetchone() == (2,)
        for table in ("acceptance_audits", "fact_observations", "corpus_versions"):
            assert connection.execute(
                sql.SQL("SELECT count(*) FROM regintel.{}").format(sql.Identifier(table))
            ).fetchone() == (0,)


def test_concurrent_native_jobs_seal_once(unsealed):
    fixture = unsealed
    source = fixture.source
    with ThreadPoolExecutor(max_workers=2) as workers:
        calls = [
            workers.submit(
                NativeM1Producer(source.source).run, fixture.job.id, fixture.result, source.user
            )
            for _ in range(2)
        ]
        results = [call.result(timeout=45) for call in calls]
    assert results[0] == results[1] and results[0].state == "PARSED"
    assert results[0].attempts == 1


@pytest.mark.parametrize("inspection", ["no_policy"], indirect=True)
def test_exact_native_links_do_not_replace_financial_approval(native):
    source = native.source
    assert native.record.source_input.policy is None
    bound = NumericalEvidenceBindingRepository(source.source).bind(
        native.record.id, native.result.artifact.id, source.user
    )
    assert bound.review_required and not bound.acceptance_eligible


@pytest.mark.parametrize("change", ["learner", "forged_role", "stale", "inactive", "demoted"])
def test_native_job_requires_current_administrator_before_writes(unsealed, change):
    source = unsealed.source
    user = source.user
    if change == "learner":
        user = source.learner
    elif change == "forged_role":
        user = replace(source.learner, role="admin")
    elif change == "stale":
        user = replace(user, auth_version=user.auth_version + 1)
    else:
        with source.source.connect() as connection:
            connection.execute(
                "UPDATE regintel.users SET is_active=false WHERE id=%s"
                if change == "inactive"
                else "UPDATE regintel.users SET role='learner' WHERE id=%s",
                (user.id,),
            )
    before = snapshot(source.database)
    with pytest.raises(NumericalAuthorizationError):
        NativeM1Producer(source.source).run(unsealed.job.id, unsealed.result, user)
    assert snapshot(source.database) == before


@pytest.mark.parametrize("change", ["modified", "missing"])
def test_native_job_reverifies_source_and_never_leaves_partial_parse(unsealed, change):
    source = unsealed.source
    if change == "modified":
        source.source_path.write_bytes(b"Authored changed original; not a genuine filing")
    else:
        source.source_path.unlink()
    with pytest.raises(NumericalSourceError, match="raw diagnostics omitted"):
        NativeM1Producer(source.source).run(unsealed.job.id, unsealed.result, source.user)
    outcome = JobRepository(source.database).get(unsealed.job.id)
    assert outcome is not None and outcome.state == "FAILED"
    assert outcome.failure_code == "ARTIFACT_INVALID"
    with source.source.connect() as connection:
        assert connection.execute(
            "SELECT count(*) FROM regintel.parse_versions WHERE id=%s",
            (UUID(unsealed.result.artifact.id),),
        ).fetchone() == (0,)


@pytest.mark.parametrize("change", ["word", "table_capture", "native_page"])
def test_native_job_rebuilds_from_retained_sources_before_sealing(unsealed, change):
    result, source = unsealed.result, unsealed.source
    if change == "word":
        block = result.artifact.blocks[0].model_copy(update={"orig": "Unsupported changed word"})
        result = replace(
            result,
            artifact=result.artifact.model_copy(
                update={"blocks": (block, *result.artifact.blocks[1:])}
            ),
        )
    elif change == "table_capture":
        result = replace(result, table_sources=((result.table_sources[0][0], str(uuid4())),))
    else:
        page = result.bank.directory / "page-0001.json"
        page.write_bytes(page.read_bytes() + b" ")
    with pytest.raises(NumericalSourceError):
        NativeM1Producer(source.source).run(unsealed.job.id, result, source.user)
    assert JobRepository(source.database).get(unsealed.job.id).state == "FAILED"


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize("action", ["UPDATE", "DELETE", "TRUNCATE"])
def test_native_source_sidecars_are_append_only(native, table, action):
    source = native.source
    before = snapshot(source.database)
    with pytest.raises(psycopg.Error), source.source.connect() as connection:
        if action == "UPDATE":
            statement = sql.SQL("UPDATE regintel.{} SET parse_version_id=parse_version_id")
        elif action == "DELETE":
            statement = sql.SQL("DELETE FROM regintel.{}")
        else:
            statement = sql.SQL("TRUNCATE regintel.{} CASCADE")
        connection.execute(statement.format(sql.Identifier(table)))
    assert snapshot(source.database) == before


@pytest.mark.parametrize("missing", ["all_pages", "context", "table_map", "sidecar"])
def test_database_rejects_incomplete_native_seal_atomically(unsealed, missing, monkeypatch):
    source, result = unsealed.source, unsealed.result
    projection = project_native_context(result.artifact, result.configuration)
    before = snapshot(source.database)

    def incomplete(connection):
        if missing == "all_pages":
            original = result.bank.pages
            monkeypatch.setattr(type(result.bank), "pages", lambda self: iter(list(original())[:1]))
        if missing == "context":
            changed = replace(result, captures=())
        elif missing == "table_map":
            changed = replace(result, table_sources=())
        else:
            changed = result
        _persist_bank(connection, unsealed.job.id, changed)

    with pytest.raises((ValueError, psycopg.Error)), source.source.connect() as connection:
        with connection.transaction():
            connection.execute(
                "UPDATE regintel.filing_jobs SET state='RUNNING',attempts=1 WHERE id=%s",
                (UUID(unsealed.job.id),),
            )
            persist_projection(
                connection,
                job_id=unsealed.job.id,
                projection=projection,
                sidecar_format="1.1.0",
                before_sidecar=None if missing == "sidecar" else lambda: incomplete(connection),
            )
            connection.execute(
                "UPDATE regintel.filing_jobs SET state='PARSED',page_count=2,"
                "parse_version_id=%s WHERE id=%s",
                (UUID(result.artifact.id), UUID(unsealed.job.id)),
            )
    assert snapshot(source.database) == before
