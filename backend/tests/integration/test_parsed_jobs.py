"""Live sealed result, duplicate delivery, rollback and transient retry contracts."""

from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from pydantic import SecretStr
from pypdf import PdfWriter

from backend.tests.evidence_fixtures import synthetic_artifact, synthetic_configuration
from regintel.auth.repository import seed_users
from regintel.auth.types import SeedAccount
from regintel.ingestion.config import IngestionSettings
from regintel.ingestion.jobs import ParserFailure, UploadMetadata
from regintel.ingestion.repository import JobRepository
from regintel.ingestion.storage import SourceStorage, UploadError

pytestmark = pytest.mark.integration


@pytest.fixture
def queued(auth_database, tmp_path):
    selected = synthetic_configuration()
    seed_users(
        auth_database, (SeedAccount("admin", SecretStr("Synthetic parse job password!"), "admin"),)
    )
    repository = JobRepository(auth_database)
    settings = IngestionSettings(
        source_root=tmp_path / "sources",
        broker_url=SecretStr("redis://:synthetic@127.0.0.1:6379/0"),
        parser_configuration=selected,
    )
    storage = SourceStorage(settings)
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    pdf = tmp_path / "source.pdf"
    writer.write(pdf)
    stage = storage.stage()
    stage.write(pdf.read_bytes())
    source = stage.finish()
    with repository.connect() as connection:
        actor = connection.execute(
            "SELECT id FROM regintel.users WHERE username='admin'"
        ).fetchone()[0]
    metadata = UploadMetadata(company_name_raw="Synthetic Parse Company", document_type="RHP")
    job = repository.submit(source, metadata, settings.configuration_sha256, actor, 1)
    return repository, selected, source, metadata, actor, job


def convert(selected, blob, parse_id, filing_id, version_id):
    return synthetic_artifact(
        configuration=selected,
        parse_id=parse_id,
        filing_id=filing_id,
        filing_version_id=version_id,
        blob=blob,
    )


def test_atomic_parsed_result_and_concurrent_terminal_duplicates(queued):
    repository, selected, _, _, _, job = queued
    converted = []

    def parse(*args):
        converted.append(args[1])
        return convert(selected, *args)

    with ThreadPoolExecutor(max_workers=3) as executor:
        list(executor.map(lambda _: repository.parse_job(job.id, selected, parse), range(3)))
    result = repository.get(job.id)
    assert result.state == "PARSED" and result.attempts == 1 and result.page_count == 1
    assert result.parse_version_id == converted[0] and len(converted) == 1
    with repository.connect() as connection:
        assert connection.execute("SELECT count(*) FROM regintel.parse_artifacts").fetchone() == (
            1,
        )
        assert connection.execute("SELECT count(*) FROM regintel.evidence").fetchone()[0] > 0


@pytest.mark.parametrize(
    "failure,code",
    [
        (ParserFailure("PARSE_FAILED"), "PARSE_FAILED"),
        (ParserFailure("PARSER_CONFIGURATION_MISMATCH"), "PARSER_CONFIGURATION_MISMATCH"),
        (UploadError(400, "SOURCE_HASH_MISMATCH"), "SOURCE_HASH_MISMATCH"),
        (OSError("Temporary snapshot storage diagnostic"), "SOURCE_UNAVAILABLE"),
    ],
)
def test_terminal_failures_do_not_create_partial_trees(queued, failure, code):
    repository, selected, _, _, _, job = queued

    def parse(*args):
        raise failure

    repository.parse_job(job.id, selected, parse)
    result = repository.get(job.id)
    assert result.state == "FAILED" and result.failure_code == code and result.attempts == 1
    assert result.parse_version_id is None and result.page_count is None
    repository.parse_job(job.id, selected, lambda *args: pytest.fail("Terminal job must not parse"))
    with repository.connect() as connection:
        assert connection.execute("SELECT count(*) FROM regintel.parse_versions").fetchone() == (0,)


def test_wrong_source_membership_is_quarantined_before_persistence(queued):
    repository, selected, _, _, _, job = queued
    repository.parse_job(
        job.id,
        selected,
        lambda *args: convert(selected, *args).model_copy(update={"source_sha256": "f" * 64}),
    )
    assert repository.get(job.id).failure_code == "ARTIFACT_INVALID"
    with repository.connect() as connection:
        assert connection.execute("SELECT count(*) FROM regintel.parse_versions").fetchone() == (0,)


@pytest.mark.parametrize(
    "error_type,terminal", [(ValueError, True), (psycopg.OperationalError, False)]
)
def test_middle_transaction_failure_rolls_back_and_transient_retry_can_resume(
    queued, monkeypatch, error_type, terminal
):
    from regintel.evidence import repository as evidence_repository

    repository, selected, _, _, _, job = queued
    original = evidence_repository.persist_parse

    def fail_after_complete_insert(*args, **kwargs):
        original(*args, **kwargs)
        raise error_type("Synthetic mid-transaction failure")

    monkeypatch.setattr(evidence_repository, "persist_parse", fail_after_complete_insert)
    if terminal:
        repository.parse_job(job.id, selected, lambda *args: convert(selected, *args))
    else:
        with pytest.raises(psycopg.OperationalError):
            repository.parse_job(job.id, selected, lambda *args: convert(selected, *args))
    result = repository.get(job.id)
    assert result.state == ("FAILED" if terminal else "RUNNING") and result.parse_version_id is None
    with repository.connect() as connection:
        for table in ("parse_versions", "pages", "blocks", "evidence", "parse_artifacts"):
            assert connection.execute(f"SELECT count(*) FROM regintel.{table}").fetchone() == (0,)
    if not terminal:
        monkeypatch.setattr(evidence_repository, "persist_parse", original)
        repository.parse_job(job.id, selected, lambda *args: convert(selected, *args))
        assert repository.get(job.id).state == "PARSED" and repository.get(job.id).attempts == 2


def test_legacy_verified_job_preserved_when_new_processing_configuration_submitted(queued):
    repository, selected, source, metadata, actor, parsed_job = queued
    legacy = repository.submit(source, metadata, "b" * 64, actor, 1)
    repository.verify_job(legacy.id, "b" * 64, lambda blob: 1)
    repository.parse_job(
        legacy.id, selected, lambda *args: pytest.fail("Legacy result must stay terminal")
    )
    assert repository.get(legacy.id).state == "SOURCE_VERIFIED"
    repository.parse_job(parsed_job.id, selected, lambda *args: convert(selected, *args))
    assert repository.get(parsed_job.id).state == "PARSED"
