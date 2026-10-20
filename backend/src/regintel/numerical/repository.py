"""Append-only M1 source-page preparation, before numerical validation/publication."""

import hashlib
import json
from uuid import UUID

import psycopg
from pydantic import TypeAdapter

from regintel.auth.types import User
from regintel.contracts.primitives import CanonicalId
from regintel.db.config import DatabaseSettings
from regintel.db.connections import ConnectionFactory
from regintel.db.migrations import DatabaseConnection, MigrationError, connect_database
from regintel.ingestion.models import SourceBlob
from regintel.ingestion.storage import SourceStorage, UploadError
from regintel.numerical.models import (
    NumericalWordRef,
    ResolvedNumericalWord,
    StoredNumericalPage,
    page_capture_id,
)
from regintel.numerical.source_pages import (
    FRAME,
    MAX_CAPTURE_BYTES,
    NumericalPageCapture,
    build_page_capture,
    capture_bytes,
)
from regintel.parsing.configuration import ParserRuntimeConfiguration

LOCK_ID = 0x4E554D4552494341


class NumericalAuthorizationError(ValueError):
    """The actor is not a current active administrator."""


class NumericalNotFound(ValueError):
    """An uploaded source version or stored capture is unavailable."""


class NumericalSourceError(ValueError):
    """Immutable source bytes, capture membership or supporting text are invalid."""


class NumericalUnavailable(ValueError):
    """Database/migration or source-storage prerequisites are unavailable."""


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NumericalSourceError("Duplicate capture object keys are invalid.")
        result[key] = value
    return result


def _checked(value: object, sha: object, maximum: int = MAX_CAPTURE_BYTES) -> bytes:
    if not isinstance(value, (bytes, memoryview)):
        raise NumericalSourceError("Capture storage is invalid.")
    body = bytes(value)
    if not 0 < len(body) <= maximum or hashlib.sha256(body).hexdigest() != sha:
        raise NumericalSourceError("Capture storage fingerprint is invalid.")
    return body


def _authorize(connection: DatabaseConnection, user: User) -> None:
    row = connection.execute(
        "SELECT role,is_active,auth_version FROM regintel.users WHERE id=%s FOR SHARE", (user.id,)
    ).fetchone()
    if row != ("admin", True, user.auth_version):
        raise NumericalAuthorizationError("Numerical preparation requires a current administrator.")


def _blob(connection: DatabaseConnection, filing_version_id: str) -> SourceBlob:
    row = connection.execute(
        "SELECT s.id,s.sha256,s.byte_size,s.storage_key FROM regintel.filing_versions v "
        "JOIN regintel.source_blobs s ON s.id=v.source_blob_id WHERE v.id=%s",
        (UUID(filing_version_id),),
    ).fetchone()
    if row is None:
        raise NumericalNotFound("An uploaded immutable filing version is required.")
    return SourceBlob.model_validate(
        dict(
            zip(("id", "sha256", "byte_size", "storage_key"), (str(row[0]), *row[1:]), strict=True)
        )
    )


def _stored(connection: DatabaseConnection, identity: str) -> StoredNumericalPage:
    row = connection.execute(
        "SELECT filing_version_id,source_blob_id,prepared_bytes,prepared_sha256,"
        "raw_capture_bytes,raw_capture_sha256,submitted_by,auth_version "
        "FROM regintel.numerical_page_captures WHERE id=%s",
        (UUID(identity),),
    ).fetchone()
    if row is None:
        raise NumericalNotFound("The stored numerical page is unavailable.")
    prepared = _checked(row[2], row[3])
    _checked(row[4], row[5])
    capture = NumericalPageCapture.model_validate_json(prepared)
    if capture.raw_capture_sha256 != row[5] or capture_bytes(capture) != prepared:
        raise NumericalSourceError("Stored preparation bytes are not the sealed canonical page.")
    words = connection.execute(
        "SELECT word_index,word_bytes,word_sha256 FROM regintel.numerical_source_words "
        "WHERE capture_id=%s ORDER BY word_index",
        (UUID(identity),),
    ).fetchall()
    if len(words) != len(capture.words) or any(
        actual[0] != word.word_index
        or _checked(actual[1], actual[2], 262_144) != _json_bytes(word.model_dump(mode="json"))
        for actual, word in zip(words, capture.words, strict=True)
    ):
        raise NumericalSourceError("Stored original words differ from their sealed capture.")
    blob = _blob(connection, str(row[0]))
    if str(row[1]) != blob.id or capture.source_sha256 != blob.sha256:
        raise NumericalSourceError("Stored preparation differs from its uploaded source.")
    return StoredNumericalPage(
        id=identity,
        filing_version_id=str(row[0]),
        source_blob_id=str(row[1]),
        prepared_sha256=str(row[3]),
        submitted_by=UUID(str(row[6])),
        auth_version=int(str(row[7])),
        capture=capture,
    )


class NumericalRepository:
    def __init__(
        self,
        database: DatabaseSettings,
        storage: SourceStorage,
        configuration: ParserRuntimeConfiguration,
        *,
        connect: ConnectionFactory | None = None,
    ) -> None:
        if configuration.coordinate_frame != FRAME.value:
            raise ValueError("Numerical preparation requires its calibrated original SDK frame.")
        self.database, self.storage, self.configuration = database, storage, configuration
        self._connect = connect

    def connect(self) -> DatabaseConnection:
        return self._connect() if self._connect is not None else connect_database(self.database)

    def save(
        self,
        filing_version_id: str,
        raw_bytes: bytes,
        pdf_page: int,
        user: User,
    ) -> StoredNumericalPage:
        TypeAdapter(CanonicalId).validate_python(filing_version_id)
        try:
            with self.connect() as connection, connection.transaction():
                _authorize(connection, user)
                blob = _blob(connection, filing_version_id)
                if not isinstance(raw_bytes, bytes) or not 0 < len(raw_bytes) <= MAX_CAPTURE_BYTES:
                    raise NumericalSourceError("A bounded retained raw SDK page is required.")
                captured: object = json.loads(raw_bytes, object_pairs_hook=_unique_object)
                self.storage.verify(blob)
                capture = build_page_capture(
                    captured,
                    source=self.storage.root / blob.storage_key,
                    pdf_page=pdf_page,
                    expected_source_sha256=blob.sha256,
                    expected_sdk_configuration_sha256=self.configuration.sdk_configuration_sha256,
                )
                prepared = capture_bytes(capture)
                raw = _json_bytes(captured)
                digest = hashlib.sha256(prepared).hexdigest()
                identity = page_capture_id(filing_version_id, blob.id, digest)
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
                existing = connection.execute(
                    "SELECT id FROM regintel.numerical_page_captures WHERE id=%s", (UUID(identity),)
                ).fetchone()
                if existing is not None:
                    return _stored(connection, identity)
                connection.execute(
                    """INSERT INTO regintel.numerical_page_captures
                    (id,filing_version_id,source_blob_id,source_sha256,page_index,source_page_count,
                     sdk_configuration_sha256,preparation_code_sha256,raw_capture_bytes,
                     raw_capture_sha256,prepared_bytes,prepared_sha256,word_count,cell_count,
                     submitted_by,auth_version)
                     VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        UUID(identity),
                        UUID(filing_version_id),
                        UUID(blob.id),
                        blob.sha256,
                        capture.page_index,
                        capture.source_page_count,
                        capture.sdk_configuration_sha256,
                        capture.preparation_code_sha256,
                        raw,
                        capture.raw_capture_sha256,
                        prepared,
                        digest,
                        len(capture.words),
                        len(capture.cells),
                        user.id,
                        user.auth_version,
                    ),
                )
                for word in capture.words:
                    body = _json_bytes(word.model_dump(mode="json"))
                    connection.execute(
                        "INSERT INTO regintel.numerical_source_words "
                        "(capture_id,word_index,word_bytes,word_sha256) VALUES(%s,%s,%s,%s)",
                        (UUID(identity), word.word_index, body, hashlib.sha256(body).hexdigest()),
                    )
                return _stored(connection, identity)
        except (NumericalAuthorizationError, NumericalNotFound, NumericalSourceError):
            raise
        except (
            psycopg.OperationalError,
            psycopg.InterfaceError,
            psycopg.errors.UndefinedTable,
            MigrationError,
        ):
            raise NumericalUnavailable("Numerical preparation storage is unavailable.") from None
        except (psycopg.Error, OSError, ValueError, RecursionError, UploadError):
            raise NumericalSourceError(
                "The original source or numerical capture is invalid."
            ) from None

    def get(self, identity: str, user: User) -> StoredNumericalPage:
        TypeAdapter(CanonicalId).validate_python(identity)
        try:
            with self.connect() as connection, connection.transaction():
                _authorize(connection, user)
                return _stored(connection, identity)
        except (NumericalAuthorizationError, NumericalNotFound, NumericalSourceError):
            raise
        except (
            psycopg.OperationalError,
            psycopg.InterfaceError,
            psycopg.errors.UndefinedTable,
            MigrationError,
        ):
            raise NumericalUnavailable("Numerical preparation storage is unavailable.") from None
        except (psycopg.Error, ValueError):
            raise NumericalSourceError("Stored numerical preparation is invalid.") from None

    def resolve_word(self, reference: NumericalWordRef, user: User) -> ResolvedNumericalWord:
        reference = NumericalWordRef.model_validate(reference.model_dump(mode="python"))
        stored = self.get(reference.capture_id, user)
        capture = stored.capture
        if reference.word_index >= len(capture.words):
            raise NumericalSourceError("The word does not belong to this captured page.")
        word = capture.words[reference.word_index]
        if (
            word.orig is None
            or word.from_ocr is not False
            or word.box is None
            or word.raw_rectangle is None
            or reference.end > len(word.orig)
            or word.orig[reference.start : reference.end] != reference.quote
        ):
            raise NumericalSourceError("The reference lacks exact native original-word support.")
        return ResolvedNumericalWord(
            reference=reference,
            filing_version_id=stored.filing_version_id,
            source_blob_id=stored.source_blob_id,
            source_sha256=capture.source_sha256,
            page_index=capture.page_index,
            page_geometry=capture.page_geometry,
            raw_rectangle=word.raw_rectangle,
            box=word.box,
        )
