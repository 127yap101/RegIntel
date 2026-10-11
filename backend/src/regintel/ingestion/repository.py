"""Atomic ingestion identities, replayable outbox and serialized job state."""

import hashlib
import os
from collections.abc import Callable
from datetime import date
from uuid import UUID, uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict

from regintel.db.config import DatabaseSettings
from regintel.db.migrations import DatabaseConnection, connect_database
from regintel.ingestion.jobs import FilingJob, ParserFailure, UploadMetadata
from regintel.ingestion.models import SourceBlob
from regintel.ingestion.storage import StoredSource, UploadError
from regintel.parsing.configuration import ParserRuntimeConfiguration, validate_artifact_provenance
from regintel.parsing.models import ParseArtifact


def connect_ingestion(settings: DatabaseSettings, *, worker: bool = False) -> DatabaseConnection:
    if not worker:
        return connect_database(settings)
    # The foundation migration/auth helper remains loopback-only. The approved worker
    # can connect exclusively to the existing Compose PostgreSQL service.
    values = conninfo_to_dict(settings.database_url.get_secret_value())
    if (
        values["host"] != "postgres"
        or values["port"] != "5432"
        or values["dbname"] != "regintel"
        or "hostaddr" in values
        or "PGSERVICE" in os.environ
        or "PGSERVICEFILE" in os.environ
    ):
        raise ValueError("Worker database must be the existing Compose project service.")
    return psycopg.connect(
        host="postgres",
        port=5432,
        dbname="regintel",
        user=values["user"],
        password=values["password"],
        sslmode="disable",
        gssencmode="disable",
        require_auth="scram-sha-256",
        options="",
        autocommit=True,
        connect_timeout=5,
        application_name="regintel-ingestion-worker",
    )


_JOB_SELECT = """SELECT j.id, j.filing_version_id, j.source_blob_id, s.sha256,
    j.configuration_sha256, j.state, j.attempts, j.page_count, j.failure_code, j.parse_version_id
    FROM regintel.filing_jobs j JOIN regintel.source_blobs s ON s.id = j.source_blob_id"""


def _job(connection: DatabaseConnection, job_id: str) -> FilingJob | None:
    row = connection.execute(_JOB_SELECT + " WHERE j.id = %s", (job_id,)).fetchone()
    if row is None:
        return None
    names = (
        "id",
        "filing_version_id",
        "source_blob_id",
        "source_sha256",
        "configuration_sha256",
        "state",
        "attempts",
        "page_count",
        "failure_code",
        "parse_version_id",
    )
    values = dict(zip(names, row, strict=True))
    for name in names[:3]:
        values[name] = str(values[name])
    if values["parse_version_id"] is not None:
        values["parse_version_id"] = str(values["parse_version_id"])
    return FilingJob.model_validate(values)


def _lock(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big", signed=True)


class JobRepository:
    def __init__(self, database: DatabaseSettings, *, worker: bool = False) -> None:
        self.database = database
        self.worker = worker

    def connect(self) -> DatabaseConnection:
        return connect_ingestion(self.database, worker=self.worker)

    def submit(
        self,
        source: StoredSource,
        metadata: UploadMetadata,
        config: str,
        actor: UUID,
        auth_version: int,
    ) -> FilingJob:
        blob = source.blob
        with self.connect() as connection, connection.transaction():
            authorization = connection.execute(
                "SELECT role, is_active, auth_version FROM regintel.users WHERE id=%s FOR SHARE",
                (actor,),
            ).fetchone()
            if authorization is None or authorization[1:] != (True, auth_version):
                raise UploadError(401, "INVALID_AUTHORIZATION")
            if authorization[0] != "admin":
                raise UploadError(403, "ADMIN_REQUIRED")
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (_lock(blob.sha256),))
            connection.execute(
                """INSERT INTO regintel.source_blobs
                (id, sha256, byte_size, storage_key) VALUES (%s, %s, %s, %s)
                ON CONFLICT (sha256) DO NOTHING""",
                (blob.id, blob.sha256, blob.byte_size, blob.storage_key),
            )
            row = connection.execute(
                "SELECT id, byte_size, storage_key FROM regintel.source_blobs WHERE sha256 = %s",
                (blob.sha256,),
            ).fetchone()
            if row is None or row[1:] != (blob.byte_size, blob.storage_key):
                raise UploadError(409, "SOURCE_IDENTITY_CONFLICT")
            blob_id = str(row[0])
            identity = connection.execute(
                """SELECT filing_version_id, metadata_sha256
                FROM regintel.filing_ingestion_keys WHERE source_blob_id = %s""",
                (blob_id,),
            ).fetchone()
            if identity is not None:
                if identity[1] != metadata.sha256:
                    raise UploadError(409, "FILING_METADATA_CONFLICT")
                version_id = str(identity[0])
            else:
                filing_id, version_id = str(uuid4()), str(uuid4())
                parent = metadata.declared_parent_filing_version_id
                if parent is not None:
                    parent_row = connection.execute(
                        """SELECT f.company_name_raw
                        FROM regintel.filing_versions v JOIN regintel.filings f ON f.id=v.filing_id
                        WHERE v.id = %s""",
                        (parent,),
                    ).fetchone()
                    if parent_row is None or parent_row[0] != metadata.company_name_raw:
                        raise UploadError(409, "PARENT_CONTEXT_CONFLICT")
                connection.execute(
                    "INSERT INTO regintel.filings (id, company_name_raw) VALUES (%s, %s)",
                    (filing_id, metadata.company_name_raw),
                )
                connection.execute(
                    """INSERT INTO regintel.filing_versions
                    (id, filing_id, source_blob_id, document_type, source_url, published_on,
                     declared_parent_filing_version_id) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (
                        version_id,
                        filing_id,
                        blob_id,
                        metadata.document_type,
                        metadata.source_url,
                        date.fromisoformat(metadata.published_on)
                        if metadata.published_on
                        else None,
                        parent,
                    ),
                )
                connection.execute(
                    """INSERT INTO regintel.filing_ingestion_keys
                    (source_blob_id, filing_version_id, metadata_sha256) VALUES (%s, %s, %s)""",
                    (blob_id, version_id, metadata.sha256),
                )
            connection.execute(
                """INSERT INTO regintel.filing_jobs
                (id, filing_version_id, source_blob_id, configuration_sha256, submitted_by)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (filing_version_id, configuration_sha256) DO NOTHING""",
                (str(uuid4()), version_id, blob_id, config, actor),
            )
            created = connection.execute(
                """SELECT id FROM regintel.filing_jobs
                WHERE filing_version_id = %s AND configuration_sha256 = %s""",
                (version_id, config),
            ).fetchone()
            if created is None:
                raise UploadError(503, "JOB_STORAGE_UNAVAILABLE")
            job_id = str(created[0])
            connection.execute(
                "INSERT INTO regintel.job_dispatch (job_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (job_id,),
            )
            result = _job(connection, job_id)
            if result is None:
                raise UploadError(503, "JOB_STORAGE_UNAVAILABLE")
            return result

    def get(self, job_id: str) -> FilingJob | None:
        with self.connect() as connection:
            return _job(connection, job_id)

    def dispatch(
        self, sender: Callable[[str], None], *, limit: int = 100, job_id: str | None = None
    ) -> int:
        if not 1 <= limit <= 100:
            raise ValueError("Dispatch batch must be between 1 and 100.")
        sent = 0
        # Select each intent once per invocation, including failed sends.
        with self.connect() as connection, connection.transaction():
            rows = connection.execute(
                """SELECT job_id FROM regintel.job_dispatch
                WHERE sent_at IS NULL AND (%s::uuid IS NULL OR job_id=%s)
                ORDER BY job_id FOR UPDATE SKIP LOCKED LIMIT %s""",
                (job_id, job_id, limit),
            ).fetchall()
            for row in rows:
                job_id = str(row[0])
                try:
                    sender(job_id)
                except Exception:
                    connection.execute(
                        """UPDATE regintel.job_dispatch SET attempts = attempts + 1,
                        last_failure_code = 'BROKER_UNAVAILABLE' WHERE job_id = %s""",
                        (job_id,),
                    )
                else:
                    connection.execute(
                        """UPDATE regintel.job_dispatch SET attempts = attempts + 1,
                        sent_at = clock_timestamp(), last_failure_code = NULL WHERE job_id = %s""",
                        (job_id,),
                    )
                    sent += 1
        return sent

    def verify_job(self, job_id: str, config: str, verify: Callable[[SourceBlob], int]) -> None:
        # Session lock spans committed RUNNING state and file processing. Redelivery
        # after process loss can resume RUNNING; completed terminal jobs are no-ops.
        with self.connect() as connection:
            connection.execute("SELECT pg_advisory_lock(%s)", (_lock(job_id),))
            try:
                job = _job(connection, job_id)
                if job is None or job.state in {"SOURCE_VERIFIED", "PARSED", "FAILED"}:
                    return
                connection.execute(
                    "UPDATE regintel.filing_jobs SET state='RUNNING',"
                    " attempts=attempts+1 WHERE id=%s",
                    (job_id,),
                )
                code: str | None = None
                pages: int | None = None
                if job.configuration_sha256 != config:
                    code = "WORKER_CONFIGURATION_MISMATCH"
                else:
                    blob = SourceBlob(
                        id=job.source_blob_id,
                        sha256=job.source_sha256,
                        byte_size=self._blob_size(connection, job.source_blob_id),
                        storage_key=f"sha256/{job.source_sha256}.pdf",
                    )
                    try:
                        pages = verify(blob)
                    except UploadError as error:
                        code = (
                            error.code
                            if error.code
                            in {
                                "SOURCE_HASH_MISMATCH",
                                "INVALID_PDF",
                                "PAGE_LIMIT",
                                "ENCRYPTED_PDF",
                            }
                            else "SOURCE_UNAVAILABLE"
                        )
                    except (OSError, ValueError):
                        code = "SOURCE_UNAVAILABLE"
                connection.execute(
                    """UPDATE regintel.filing_jobs SET state=%s, page_count=%s,
                    failure_code=%s WHERE id=%s""",
                    ("FAILED" if code else "SOURCE_VERIFIED", pages, code, job_id),
                )
            finally:
                connection.execute("SELECT pg_advisory_unlock(%s)", (_lock(job_id),))

    def parse_job(
        self,
        job_id: str,
        configuration: ParserRuntimeConfiguration,
        parse: Callable[[SourceBlob, str, str, str], ParseArtifact],
    ) -> None:
        """Serialize conversion and atomically seal a complete exact-evidence result."""
        from regintel.evidence.repository import persist_parse

        with self.connect() as connection:
            connection.execute("SELECT pg_advisory_lock(%s)", (_lock(job_id),))
            try:
                job = _job(connection, job_id)
                if job is None or job.state in {"SOURCE_VERIFIED", "PARSED", "FAILED"}:
                    return
                connection.execute(
                    "UPDATE regintel.filing_jobs SET state='RUNNING',"
                    " attempts=attempts+1 WHERE id=%s",
                    (job_id,),
                )
                failure: str | None = None
                artifact: ParseArtifact | None = None
                if job.configuration_sha256 != configuration.processing_configuration_sha256:
                    failure = "WORKER_CONFIGURATION_MISMATCH"
                else:
                    row = connection.execute(
                        """SELECT v.filing_id, s.byte_size, s.storage_key
                        FROM regintel.filing_versions v
                        JOIN regintel.source_blobs s ON s.id=v.source_blob_id
                        WHERE v.id=%s AND s.id=%s""",
                        (job.filing_version_id, job.source_blob_id),
                    ).fetchone()
                    if row is None:
                        raise ValueError("Stored filing source is unavailable.")
                    blob = SourceBlob.model_validate(
                        {
                            "id": job.source_blob_id,
                            "sha256": job.source_sha256,
                            "byte_size": row[1],
                            "storage_key": row[2],
                        }
                    )
                    parse_id, filing_id = str(uuid4()), str(row[0])
                    try:
                        artifact = parse(blob, parse_id, filing_id, job.filing_version_id)
                        artifact = ParseArtifact.model_validate(artifact.model_dump(mode="python"))
                        if (
                            artifact.id != parse_id
                            or artifact.filing_id != filing_id
                            or artifact.filing_version_id != job.filing_version_id
                            or artifact.source_blob_id != job.source_blob_id
                            or artifact.source_sha256 != job.source_sha256
                            or len(artifact.pages) > configuration.source_limits.max_pages
                        ):
                            raise ValueError("Parser result membership differs from the job.")
                        validate_artifact_provenance(configuration, provenance=artifact.provenance)
                    except UploadError as error:
                        failure = (
                            error.code
                            if error.code
                            in {
                                "SOURCE_HASH_MISMATCH",
                                "INVALID_PDF",
                                "PAGE_LIMIT",
                                "ENCRYPTED_PDF",
                            }
                            else "SOURCE_UNAVAILABLE"
                        )
                    except ParserFailure as error:
                        failure = error.code
                    except OSError:
                        failure = "SOURCE_UNAVAILABLE"
                    except (ValueError, AttributeError):
                        failure = "ARTIFACT_INVALID"
                if failure is None and artifact is not None:
                    try:
                        with connection.transaction():
                            persist_parse(
                                connection,
                                job_id=job_id,
                                artifact=artifact,
                                configuration=configuration,
                            )
                            connection.execute(
                                """UPDATE regintel.filing_jobs SET state='PARSED', page_count=%s,
                                parse_version_id=%s WHERE id=%s""",
                                (len(artifact.pages), artifact.id, job_id),
                            )
                    except (psycopg.IntegrityError, ValueError):
                        failure = "ARTIFACT_INVALID"
                if failure is not None:
                    connection.execute(
                        "UPDATE regintel.filing_jobs SET state='FAILED',"
                        " failure_code=%s WHERE id=%s",
                        (failure, job_id),
                    )
            finally:
                connection.execute("SELECT pg_advisory_unlock(%s)", (_lock(job_id),))

    @staticmethod
    def _blob_size(connection: DatabaseConnection, blob_id: str) -> int:
        row = connection.execute(
            "SELECT byte_size FROM regintel.source_blobs WHERE id=%s", (blob_id,)
        ).fetchone()
        if row is None or not isinstance(row[0], int):
            raise ValueError("Stored source size is unavailable.")
        return row[0]
