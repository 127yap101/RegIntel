"""Append-only context-inspection snapshots; no financial acceptance or publication writes."""

import hashlib
from uuid import UUID

import psycopg
from pydantic import TypeAdapter

from regintel.auth.types import User
from regintel.contracts.primitives import CanonicalId
from regintel.db.migrations import DatabaseConnection, MigrationError
from regintel.entities.models import canonical_bytes
from regintel.ingestion.storage import UploadError
from regintel.numerical.context_gate import inspect_context
from regintel.numerical.context_inputs import load_context_input
from regintel.numerical.context_models import (
    NumericalContextDraft,
    NumericalContextInput,
    NumericalContextInspection,
)
from regintel.numerical.context_records import (
    MAX_INPUT_BYTES,
    MAX_INSPECTION_BYTES,
    NumericalContextRecord,
    context_record_id,
    storage_configuration_sha256,
)
from regintel.numerical.repository import (
    NumericalAuthorizationError,
    NumericalNotFound,
    NumericalRepository,
    NumericalSourceError,
    NumericalUnavailable,
    _authorize,
    _blob,
    _checked,
    _stored,
)

UNAVAILABLE = (
    psycopg.OperationalError,
    psycopg.InterfaceError,
    psycopg.errors.UndefinedTable,
    MigrationError,
)
RETRYABLE = (psycopg.errors.SerializationFailure, psycopg.errors.DeadlockDetected)


def _history(connection: DatabaseConnection, identity: str) -> NumericalContextRecord:
    row = connection.execute(
        "SELECT filing_version_id,source_blob_id,source_sha256,input_bytes,input_sha256,"
        "inspection_bytes,inspection_sha256,storage_configuration_sha256,submitted_by,auth_version "
        "FROM regintel.numerical_context_records WHERE id=%s",
        (UUID(identity),),
    ).fetchone()
    if row is None:
        raise NumericalNotFound("The numerical context record is unavailable.")
    source_bytes = _checked(row[3], row[4], MAX_INPUT_BYTES)
    result_bytes = _checked(row[5], row[6], MAX_INSPECTION_BYTES)
    source = NumericalContextInput.model_validate_json(source_bytes)
    result = NumericalContextInspection.model_validate_json(result_bytes)
    if canonical_bytes(source) != source_bytes or canonical_bytes(result) != result_bytes:
        raise NumericalSourceError("Stored context bytes are not canonical immutable inputs.")
    record = NumericalContextRecord.model_validate(
        {
            "id": identity,
            "filing_version_id": str(row[0]),
            "source_blob_id": str(row[1]),
            "source_sha256": row[2],
            "input_sha256": row[4],
            "inspection_sha256": row[6],
            "storage_configuration_sha256": row[7],
            "submitted_by": row[8],
            "auth_version": row[9],
            "source_input": source,
            "inspection": result,
        }
    )
    actual = connection.execute(
        "SELECT capture_id FROM regintel.numerical_context_pages "
        "WHERE record_id=%s ORDER BY ordinal",
        (UUID(identity),),
    ).fetchall()
    if tuple(str(item[0]) for item in actual) != source.draft.capture_ids:
        raise NumericalSourceError("Stored context page membership is incomplete.")
    for page in source.pages:
        if _stored(connection, page.id) != page:
            raise NumericalSourceError("Context history differs from its sealed original page.")
    blob = _blob(connection, record.filing_version_id)
    if (blob.id, blob.sha256) != (record.source_blob_id, record.source_sha256):
        raise NumericalSourceError("Context history differs from its uploaded primary source.")
    # The record model replays only known current code, never a different historical configuration.
    return record


class NumericalContextStorage:
    def __init__(self, source: NumericalRepository) -> None:
        self.source = source

    def _save(self, draft: NumericalContextDraft, user: User) -> NumericalContextRecord:
        with self.source.connect() as connection, connection.transaction():
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            _authorize(connection, user)
            source, blob = load_context_input(connection, self.source, draft)
            result = inspect_context(source)
            storage_sha = storage_configuration_sha256()
            identity = context_record_id(result.id, storage_sha)
            existing = connection.execute(
                "SELECT id FROM regintel.numerical_context_records WHERE id=%s", (UUID(identity),)
            ).fetchone()
            if existing is not None:
                return _history(connection, identity)
            source_bytes, result_bytes = canonical_bytes(source), canonical_bytes(result)
            if (
                not 0 < len(source_bytes) <= MAX_INPUT_BYTES
                or not 0 < len(result_bytes) <= MAX_INSPECTION_BYTES
            ):
                raise NumericalSourceError("Context history exceeds its explicit storage budget.")
            inserted = connection.execute(
                """INSERT INTO regintel.numerical_context_records
                (id,filing_version_id,source_blob_id,source_sha256,input_bytes,input_sha256,
                 inspection_id,inspection_bytes,inspection_sha256,context_configuration_sha256,
                 storage_configuration_sha256,page_count,submitted_by,auth_version)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING RETURNING id""",
                (
                    UUID(identity),
                    UUID(draft.filing_version_id),
                    UUID(blob.id),
                    blob.sha256,
                    source_bytes,
                    hashlib.sha256(source_bytes).hexdigest(),
                    UUID(result.id),
                    result_bytes,
                    hashlib.sha256(result_bytes).hexdigest(),
                    result.configuration_sha256,
                    storage_sha,
                    len(source.pages),
                    user.id,
                    user.auth_version,
                ),
            ).fetchone()
            if inserted is None:
                return _history(connection, identity)
            for ordinal, page in enumerate(source.pages):
                connection.execute(
                    "INSERT INTO regintel.numerical_context_pages(record_id,ordinal,capture_id) "
                    "VALUES(%s,%s,%s)",
                    (UUID(identity), ordinal, UUID(page.id)),
                )
            return _history(connection, identity)

    def save(self, draft: NumericalContextDraft, user: User) -> NumericalContextRecord:
        draft = NumericalContextDraft.model_validate(draft.model_dump(mode="python"))
        for attempt in range(3):
            try:
                return self._save(draft, user)
            except RETRYABLE:
                if attempt == 2:
                    raise NumericalUnavailable(
                        "Concurrent context recording must be retried."
                    ) from None
            except (NumericalAuthorizationError, NumericalNotFound, NumericalSourceError):
                raise
            except UNAVAILABLE:
                raise NumericalUnavailable("Numerical context storage is unavailable.") from None
            except (psycopg.Error, OSError, ValueError, UploadError):
                raise NumericalSourceError(
                    "Numerical context source or snapshot is invalid."
                ) from None
        raise NumericalUnavailable("Numerical context storage is unavailable.")

    def get(self, identity: str, user: User) -> NumericalContextRecord:
        TypeAdapter(CanonicalId).validate_python(identity)
        try:
            with self.source.connect() as connection, connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                _authorize(connection, user)
                return _history(connection, identity)
        except (NumericalAuthorizationError, NumericalNotFound, NumericalSourceError):
            raise
        except UNAVAILABLE:
            raise NumericalUnavailable("Numerical context history is unavailable.") from None
        except (psycopg.Error, OSError, ValueError):
            raise NumericalSourceError("Stored numerical context is invalid.") from None
