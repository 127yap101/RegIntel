"""Live PostgreSQL ingestion, auth, outbox replay and duplicate worker boundaries."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pypdf import PdfWriter

from regintel.auth.config import AuthSettings
from regintel.auth.repository import PostgreSQLAuthRepository, seed_users
from regintel.auth.service import AuthService
from regintel.auth.types import SeedAccount
from regintel.db.config import DatabaseSettings
from regintel.db.migrations import connect_database
from regintel.ingestion.api import IngestionService
from regintel.ingestion.config import IngestionSettings
from regintel.ingestion.jobs import FilingJobEnvelope, UploadMetadata
from regintel.ingestion.repository import JobRepository
from regintel.ingestion.storage import UploadError
from regintel.main import create_app

pytestmark = pytest.mark.integration
PASSWORD = "Synthetic ingestion password 2026!"
METADATA = {"company_name_raw": "Synthetic Filing Company", "document_type": "RHP"}


def pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


@pytest.fixture
def ingestion(auth_database: DatabaseSettings, tmp_path: Path) -> IngestionService:
    seed_users(
        auth_database,
        (
            SeedAccount("admin", SecretStr(PASSWORD), "admin"),
            SeedAccount("learner", SecretStr(PASSWORD), "learner"),
        ),
    )
    settings = IngestionSettings(
        source_root=tmp_path / "sources",
        broker_url=SecretStr("redis://:synthetic@127.0.0.1:6379/0"),
    )

    def unavailable(job_id: str) -> None:
        raise OSError("Synthetic secret diagnostic")

    return IngestionService(settings, JobRepository(auth_database), unavailable)


@pytest.fixture
def client(ingestion: IngestionService) -> Iterator[TestClient]:
    auth = AuthService(
        PostgreSQLAuthRepository(ingestion.repository.database),
        AuthSettings(jwt_secret=SecretStr("ab" * 32)),
    )
    with TestClient(create_app(auth_service=auth, ingestion_service=ingestion)) as value:
        yield value


def headers(client: TestClient, username: str = "admin") -> dict[str, str]:
    result = client.post(
        "/v1/auth/token",
        data={"grant_type": "password", "username": username, "password": PASSWORD},
    )
    assert result.status_code == 200
    return {
        "Authorization": f"Bearer {result.json()['access_token']}",
        "Content-Type": "application/pdf",
    }


def submit(client: TestClient, **metadata: str):
    return client.post(
        "/v1/filings", params={**METADATA, **metadata}, headers=headers(client), content=pdf_bytes()
    )


def test_durable_upload_broker_failure_replay_and_source_verification(
    client: TestClient, ingestion: IngestionService
):
    result = submit(client)
    assert result.status_code == 202
    envelope = FilingJobEnvelope.model_validate_json(result.text)
    job = envelope.data
    assert job.state == "QUEUED" and job.attempts == 0 and job.page_count is None
    assert envelope.meta.versions.filing_version_id == job.filing_version_id
    assert envelope.meta.versions.parse_version_id is None
    assert envelope.meta.versions.corpus_version_id is None
    assert result.headers["cache-control"] == "no-store"
    with ingestion.repository.connect() as connection:
        intent = connection.execute(
            "SELECT attempts, sent_at, last_failure_code"
            " FROM regintel.job_dispatch WHERE job_id=%s",
            (job.id,),
        ).fetchone()
        assert intent == (1, None, "BROKER_UNAVAILABLE")
        assert connection.execute("SELECT count(*) FROM regintel.parse_versions").fetchone() == (0,)
    delivered: list[str] = []
    assert ingestion.repository.dispatch(delivered.append) == 1
    assert delivered == [job.id]
    assert ingestion.repository.dispatch(delivered.append) == 0
    ingestion.repository.verify_job(
        job.id, ingestion.settings.configuration_sha256, ingestion.storage.verify
    )
    read = client.get(f"/v1/filing-jobs/{job.id}", headers=headers(client))
    verified = FilingJobEnvelope.model_validate_json(read.text).data
    assert verified.state == "SOURCE_VERIFIED" and verified.page_count == 1
    assert verified.attempts == 1

    # Repeat delivery is a no-op and cannot introduce a new failure or overwrite result.
    def must_not_read(blob):
        raise AssertionError("Terminal duplicate must not access source")

    ingestion.repository.verify_job(job.id, ingestion.settings.configuration_sha256, must_not_read)
    assert ingestion.repository.get(job.id) == verified


def test_duplicate_and_conflicting_metadata_preserve_original(
    client: TestClient, ingestion: IngestionService
):
    first, duplicate = submit(client), submit(client)
    assert first.status_code == duplicate.status_code == 202
    assert first.json()["data"]["id"] == duplicate.json()["data"]["id"]
    conflict = submit(client, company_name_raw="Different company")
    assert conflict.status_code == 409
    with ingestion.repository.connect() as connection:
        for table in ("source_blobs", "filings", "filing_versions", "filing_jobs", "job_dispatch"):
            assert connection.execute(f"SELECT count(*) FROM regintel.{table}").fetchone() == (1,)
    assert list((ingestion.storage.root / "staging").iterdir()) == []


def test_concurrent_deduplication_and_worker_delivery(
    client: TestClient, ingestion: IngestionService
):
    auth = headers(client)
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(
            executor.map(
                lambda _: client.post(
                    "/v1/filings", params=METADATA, headers=auth, content=pdf_bytes()
                ),
                range(4),
            )
        )
    assert all(response.status_code == 202 for response in responses)
    ids = {response.json()["data"]["id"] for response in responses}
    assert len(ids) == 1
    job_id = ids.pop()
    calls: list[str] = []

    def verify(blob):
        calls.append(blob.id)
        return ingestion.storage.verify(blob)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(
            executor.map(
                lambda _: ingestion.repository.verify_job(
                    job_id, ingestion.settings.configuration_sha256, verify
                ),
                range(4),
            )
        )
    assert len(calls) == 1
    assert ingestion.repository.get(job_id).attempts == 1


def test_authentication_revocation_before_storage(client: TestClient, ingestion: IngestionService):
    assert client.post("/v1/filings", params=METADATA, content=pdf_bytes()).status_code == 401
    learner = headers(client, "learner")
    assert (
        client.post(
            "/v1/filings", params=METADATA, headers=learner, content=pdf_bytes()
        ).status_code
        == 403
    )
    admin = headers(client)
    with ingestion.repository.connect() as connection:
        connection.execute(
            "UPDATE regintel.users SET auth_version=auth_version+1 WHERE username='admin'"
        )
    assert (
        client.post("/v1/filings", params=METADATA, headers=admin, content=pdf_bytes()).status_code
        == 401
    )
    assert list((ingestion.storage.root / "sha256").iterdir()) == []
    assert list((ingestion.storage.root / "staging").iterdir()) == []
    assert client.get(f"/v1/filing-jobs/{uuid4()}", headers=learner).status_code == 403


@pytest.mark.parametrize(
    "kind,status",
    [
        ("mime", 415),
        ("html", 400),
        ("truncated", 400),
        ("byte_limit", 413),
        ("unknown_metadata", 422),
    ],
)
def test_bad_uploads_create_no_database_identity(
    client: TestClient, ingestion: IngestionService, kind: str, status: int
):
    auth = headers(client)
    params = dict(METADATA)
    data = pdf_bytes()
    if kind == "mime":
        auth["Content-Type"] = "text/html"
    elif kind == "html":
        data = b"<html>Secret private error</html>"
    elif kind == "truncated":
        data = data[:-10]
    elif kind == "byte_limit":
        ingestion.settings = ingestion.settings.model_copy(update={"max_bytes": 1024})
        ingestion.storage.settings = ingestion.settings
        data = b"x" * 1025
    else:
        params["company_entity_id"] = str(uuid4())
    result = client.post("/v1/filings", params=params, headers=auth, content=data)
    assert result.status_code == status
    assert "Secret private" not in result.text
    with ingestion.repository.connect() as connection:
        assert connection.execute("SELECT count(*) FROM regintel.filings").fetchone() == (0,)
    assert list((ingestion.storage.root / "staging").iterdir()) == []


def test_source_tampering_is_sanitized_terminal_failure(
    client: TestClient, ingestion: IngestionService
):
    job = FilingJobEnvelope.model_validate_json(submit(client).text).data
    (ingestion.storage.root / f"sha256/{job.source_sha256}.pdf").write_bytes(b"tampered private")
    ingestion.repository.verify_job(
        job.id, ingestion.settings.configuration_sha256, ingestion.storage.verify
    )
    failed = ingestion.repository.get(job.id)
    assert failed.state == "FAILED" and failed.failure_code == "SOURCE_HASH_MISMATCH"
    assert failed.page_count is None


def test_parent_metadata_must_be_registered_and_compatible(
    client: TestClient, ingestion: IngestionService
):
    result = submit(client, declared_parent_filing_version_id=str(uuid4()))
    assert result.status_code == 409
    with ingestion.repository.connect() as connection:
        assert connection.execute("SELECT count(*) FROM regintel.source_blobs").fetchone() == (0,)


def test_storage_transition_guards_and_preserved_actor(
    client: TestClient, ingestion: IngestionService
):
    job = FilingJobEnvelope.model_validate_json(submit(client).text).data
    with connect_database(ingestion.repository.database) as connection:
        actor = connection.execute(
            "SELECT id FROM regintel.users WHERE username='admin'"
        ).fetchone()[0]
        assert connection.execute(
            "SELECT submitted_by FROM regintel.filing_jobs WHERE id=%s", (job.id,)
        ).fetchone() == (actor,)
        for command in (
            "UPDATE regintel.filing_jobs SET state='SOURCE_VERIFIED',page_count=1 WHERE id=%s",
            "DELETE FROM regintel.filing_jobs WHERE id=%s",
            "UPDATE regintel.filing_jobs SET id=gen_random_uuid() WHERE id=%s",
            "UPDATE regintel.filing_jobs SET configuration_sha256=repeat('f',64) WHERE id=%s",
            "UPDATE regintel.filing_jobs SET submitted_by=gen_random_uuid() WHERE id=%s",
            "UPDATE regintel.filing_jobs SET source_blob_id=gen_random_uuid() WHERE id=%s",
            "UPDATE regintel.filing_jobs SET filing_version_id=gen_random_uuid() WHERE id=%s",
        ):
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(command, (UUID(job.id),))
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute("TRUNCATE regintel.filing_jobs CASCADE")
    assert ingestion.repository.get(job.id) == job


def test_running_redelivery_and_configuration_mismatch(
    client: TestClient, ingestion: IngestionService
):
    job = FilingJobEnvelope.model_validate_json(submit(client).text).data
    with ingestion.repository.connect() as connection:
        connection.execute(
            "UPDATE regintel.filing_jobs SET state='RUNNING', attempts=1 WHERE id=%s", (job.id,)
        )
    ingestion.repository.verify_job(job.id, "0" * 64, ingestion.storage.verify)
    resumed = ingestion.repository.get(job.id)
    assert resumed.state == "FAILED" and resumed.attempts == 2
    assert resumed.failure_code == "WORKER_CONFIGURATION_MISMATCH"


def test_new_configuration_appends_job_and_keeps_same_filing(
    client: TestClient, ingestion: IngestionService
):
    first = FilingJobEnvelope.model_validate_json(submit(client).text).data
    metadata = UploadMetadata.model_validate(METADATA)
    with ingestion.repository.connect() as connection:
        actor = connection.execute(
            "SELECT id FROM regintel.users WHERE username='admin'"
        ).fetchone()[0]
    stage = ingestion.storage.stage()
    stage.write(pdf_bytes())
    source = stage.finish()
    second = ingestion.repository.submit(source, metadata, "0" * 64, actor, 1)
    assert first.id != second.id and first.filing_version_id == second.filing_version_id
    assert ingestion.repository.get(first.id) == first


def test_sent_delivery_then_lost_outbox_commit_replays_safely(
    client: TestClient, ingestion: IngestionService, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = FilingJobEnvelope.model_validate_json(submit(client).text).data
    original_connect = ingestion.repository.connect
    connection = original_connect()
    deliveries: list[str] = []

    def delivered_then_connection_lost(job_id: str) -> None:
        deliveries.append(job_id)
        # The real worker can see the committed job while dispatch's transaction
        # still holds its intent. It completes, then the producer loses its session.
        other = JobRepository(ingestion.repository.database)
        other.verify_job(job_id, ingestion.settings.configuration_sha256, ingestion.storage.verify)
        connection.close()

    with monkeypatch.context() as patch:
        patch.setattr(ingestion.repository, "connect", lambda: connection)
        with pytest.raises((psycopg.OperationalError, psycopg.InterfaceError)):
            ingestion.repository.dispatch(delivered_then_connection_lost, job_id=job.id)
    with original_connect() as inspect:
        assert inspect.execute(
            "SELECT sent_at FROM regintel.job_dispatch WHERE job_id=%s", (job.id,)
        ).fetchone() == (None,)

    def redeliver(job_id: str) -> None:
        deliveries.append(job_id)
        ingestion.repository.verify_job(
            job_id, ingestion.settings.configuration_sha256, ingestion.storage.verify
        )

    assert ingestion.repository.dispatch(redeliver, job_id=job.id) == 1
    assert deliveries == [job.id, job.id]
    assert ingestion.repository.get(job.id).attempts == 1


def test_revocation_during_upload_rechecked_at_transaction(
    client: TestClient, ingestion: IngestionService
) -> None:
    auth = headers(client)
    with ingestion.repository.connect() as connection:
        actor, version = connection.execute(
            "SELECT id, auth_version FROM regintel.users WHERE username='admin'"
        ).fetchone()
        connection.execute(
            "UPDATE regintel.users SET auth_version=auth_version+1 WHERE id=%s", (actor,)
        )
    stage = ingestion.storage.stage()
    stage.write(pdf_bytes())
    source = stage.finish()
    with pytest.raises(UploadError) as error:
        ingestion.repository.submit(
            source,
            UploadMetadata.model_validate(METADATA),
            ingestion.settings.configuration_sha256,
            actor,
            version,
        )
    assert error.value.status == 401
    with ingestion.repository.connect() as connection:
        assert connection.execute("SELECT count(*) FROM regintel.source_blobs").fetchone() == (0,)
    assert (
        client.post("/v1/filings", params=METADATA, headers=auth, content=pdf_bytes()).status_code
        == 401
    )
