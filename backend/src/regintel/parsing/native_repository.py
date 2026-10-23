"""Administrator-only M1 native/context job sealing through existing source/evidence tables."""

from __future__ import annotations

import hashlib
from uuid import UUID

import psycopg

from regintel.auth.types import User
from regintel.db.migrations import DatabaseConnection
from regintel.evidence.repository import persist_projection
from regintel.ingestion.jobs import FilingJob
from regintel.ingestion.repository import _job, _lock
from regintel.ingestion.storage import UploadError
from regintel.numerical.models import StoredNumericalPage
from regintel.numerical.repository import (
    NumericalRepository,
    NumericalSourceError,
    NumericalUnavailable,
    _authorize,
    _blob,
    _checked,
    _stored,
)
from regintel.parsing.models import canonical_artifact_bytes
from regintel.parsing.native_context import (
    ContextCapture,
    NativeContextParse,
    build_native_context_parse,
    project_native_context,
)
from regintel.parsing.native_source import canonical_bytes


def _persist_bank(connection: DatabaseConnection, job_id: str, result: NativeContextParse) -> None:
    parse_id = result.artifact.id
    manifest = result.bank.manifest
    connection.execute(
        "INSERT INTO regintel.native_parse_manifests "
        "(parse_version_id,job_id,manifest_bytes,manifest_sha256,native_configuration_sha256) "
        "VALUES (%s,%s,%s,%s,%s)",
        (
            parse_id,
            job_id,
            canonical_bytes(manifest),
            manifest.sha256,
            manifest.configuration.configuration_sha256,
        ),
    )
    for page, receipt in zip(result.bank.pages(), manifest.pages, strict=True):
        payload = canonical_bytes(page)
        connection.execute(
            "INSERT INTO regintel.native_parse_source_pages "
            "(parse_version_id,page_index,page_bytes,page_sha256,word_count) "
            "VALUES (%s,%s,%s,%s,%s)",
            (parse_id, page.page_index, payload, receipt.sha256, receipt.word_count),
        )
    for capture in result.captures:
        connection.execute(
            "INSERT INTO regintel.native_parse_context_captures "
            "(parse_version_id,capture_id,page_index) VALUES (%s,%s,%s)",
            (parse_id, capture.stored.id, capture.stored.capture.page_index),
        )
    for table_id, capture_id in result.table_sources:
        connection.execute(
            "INSERT INTO regintel.native_parse_table_sources "
            "(parse_version_id,artifact_table_id,capture_id) VALUES (%s,%s,%s)",
            (parse_id, table_id, capture_id),
        )


def _stored_capture(connection: DatabaseConnection, capture_id: str) -> ContextCapture:
    stored: StoredNumericalPage = _stored(connection, capture_id)
    row = connection.execute(
        "SELECT raw_capture_bytes,raw_capture_sha256 "
        "FROM regintel.numerical_page_captures WHERE id=%s",
        (UUID(capture_id),),
    ).fetchone()
    if row is None:
        raise NumericalSourceError("An immutable contextual capture is required.")
    raw = _checked(row[0], row[1])
    if hashlib.sha256(raw).hexdigest() != stored.capture.raw_capture_sha256:
        raise NumericalSourceError("Contextual source bytes differ from their retained capture.")
    return ContextCapture(stored, raw)


class NativeM1Producer:
    """Process one explicitly selected M1 job; no provider, review, fact or publication writes.

    The caller uses JobRepository.submit with this configuration fingerprint.
    The existing source version and admin-created contextual captures must exist.
    This programmatic producer is not selected by the legacy Celery worker.
    """

    def __init__(self, source: NumericalRepository) -> None:
        self.source = source

    def run(self, job_id: str, result: NativeContextParse, user: User) -> FilingJob:
        with self.source.connect() as connection:
            connection.execute("SELECT pg_advisory_lock(%s)", (_lock(job_id),))
            try:
                with connection.transaction():
                    _authorize(connection, user)
                    ready = connection.execute(
                        "SELECT to_regclass('regintel.native_parse_manifests'),"
                        "to_regclass('regintel.native_parse_source_pages'),"
                        "to_regclass('regintel.native_parse_context_captures'),"
                        "to_regclass('regintel.native_parse_table_sources')"
                    ).fetchone()
                    if ready is None or any(table is None for table in ready):
                        raise NumericalUnavailable(
                            "The versioned native M1 producer migration is required."
                        )
                    job = _job(connection, job_id)
                    if job is None:
                        raise NumericalSourceError("An explicitly submitted M1 job is required.")
                    if (
                        job.configuration_sha256
                        != result.configuration.processing_configuration_sha256
                        or job.filing_version_id != result.artifact.filing_version_id
                        or job.source_blob_id != result.artifact.source_blob_id
                        or job.source_sha256 != result.artifact.source_sha256
                    ):
                        raise NumericalSourceError(
                            "The native result differs from its submitted M1 job."
                        )
                    if job.state in {"PARSED", "FAILED", "SOURCE_VERIFIED"}:
                        return job
                    connection.execute(
                        "UPDATE regintel.filing_jobs SET state='RUNNING',attempts=attempts+1 "
                        "WHERE id=%s",
                        (job_id,),
                    )
                try:
                    blob = _blob(connection, job.filing_version_id)
                    self.source.storage.verify(blob)
                    captures = tuple(
                        _stored_capture(connection, c.stored.id) for c in result.captures
                    )
                    rebuilt = build_native_context_parse(
                        result.bank,
                        source=self.source.storage.root / blob.storage_key,
                        baseline=result.configuration.context_parser_configuration,
                        captures=captures,
                        parse_id=result.artifact.id,
                        filing_id=result.artifact.filing_id,
                        filing_version_id=job.filing_version_id,
                        source_blob_id=job.source_blob_id,
                    )
                    if (
                        canonical_artifact_bytes(rebuilt.artifact)
                        != canonical_artifact_bytes(result.artifact)
                        or rebuilt.configuration != result.configuration
                        or rebuilt.table_sources != result.table_sources
                    ):
                        raise NumericalSourceError(
                            "The native result does not replay from its actual M1 sources."
                        )
                    projection = project_native_context(rebuilt.artifact, rebuilt.configuration)
                    with connection.transaction():
                        _authorize(connection, user)
                        persist_projection(
                            connection,
                            job_id=job_id,
                            projection=projection,
                            sidecar_format="1.1.0",
                            before_sidecar=lambda: _persist_bank(connection, job_id, rebuilt),
                        )
                        connection.execute(
                            "UPDATE regintel.filing_jobs SET state='PARSED',page_count=%s,"
                            "parse_version_id=%s WHERE id=%s",
                            (len(rebuilt.artifact.pages), rebuilt.artifact.id, job_id),
                        )
                except (ValueError, OSError, psycopg.Error, UploadError):
                    connection.execute(
                        "UPDATE regintel.filing_jobs SET state='FAILED',"
                        "failure_code='ARTIFACT_INVALID' WHERE id=%s",
                        (job_id,),
                    )
                    raise NumericalSourceError(
                        "The native M1 parse could not seal; raw diagnostics omitted."
                    ) from None
                final = _job(connection, job_id)
                if final is None:
                    raise NumericalSourceError("The native M1 job outcome is unavailable.")
                return final
            finally:
                connection.execute("SELECT pg_advisory_unlock(%s)", (_lock(job_id),))
