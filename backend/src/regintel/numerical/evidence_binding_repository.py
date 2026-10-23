"""Read-only administrator binding to actual sealed M1 parse/evidence rows."""

import json
from uuid import UUID

import psycopg
from pydantic import TypeAdapter

from regintel.auth.types import User
from regintel.contracts.primitives import CanonicalId
from regintel.db.migrations import DatabaseConnection, MigrationError
from regintel.evidence.projection import (
    MAX_ARTIFACT_BYTES,
    MAX_CONFIGURATION_BYTES,
    ProjectionError,
)
from regintel.ingestion.storage import UploadError
from regintel.numerical.context_storage import _history
from regintel.numerical.evidence_binding import bind_context_evidence
from regintel.numerical.evidence_binding_models import NumericalEvidenceBinding
from regintel.numerical.repository import (
    NumericalAuthorizationError,
    NumericalNotFound,
    NumericalRepository,
    NumericalSourceError,
    NumericalUnavailable,
    _authorize,
    _blob,
    _checked,
)
from regintel.parsing.configuration import ParserRuntimeConfiguration
from regintel.parsing.models import ParseArtifact, artifact_sha256
from regintel.parsing.native_context import NativeContextConfiguration


def _sealed_parse(
    connection: DatabaseConnection,
    parse_id: str,
) -> tuple[ParseArtifact, ParserRuntimeConfiguration | NativeContextConfiguration]:
    row = connection.execute(
        "SELECT a.artifact_bytes,a.configuration_bytes,p.artifact_sha256,p.configuration_sha256,"
        "p.filing_version_id,p.source_blob_id,p.page_count,j.page_count,v.filing_id,s.sha256 "
        "FROM regintel.parse_versions p JOIN regintel.parse_artifacts a ON a.parse_version_id=p.id "
        "JOIN regintel.filing_jobs j ON j.id=a.job_id AND j.state='PARSED' "
        "AND j.parse_version_id=p.id "
        "JOIN regintel.filing_versions v ON v.id=p.filing_version_id "
        "JOIN regintel.source_blobs s ON s.id=p.source_blob_id "
        "WHERE p.id=%s",
        (UUID(parse_id),),
    ).fetchone()
    if row is None:
        raise NumericalNotFound(
            "A complete sealed M1 parse is required for exact evidence binding."
        )
    artifact = ParseArtifact.model_validate_json(_checked(row[0], row[2], MAX_ARTIFACT_BYTES))
    configuration_bytes = _checked(row[1], row[3], MAX_CONFIGURATION_BYTES)
    configuration: ParserRuntimeConfiguration | NativeContextConfiguration
    if json.loads(configuration_bytes).get("schema_version") == "1.1.0":
        configuration = NativeContextConfiguration.model_validate_json(configuration_bytes)
    else:
        configuration = ParserRuntimeConfiguration.model_validate_json(configuration_bytes)
    if (
        artifact.id != parse_id
        or artifact.filing_version_id != str(row[4])
        or artifact.source_blob_id != str(row[5])
        or len(artifact.pages) != row[6]
        or row[6] != row[7]
        or artifact.filing_id != str(row[8])
        or artifact.source_sha256 != row[9]
        or artifact_sha256(artifact) != row[2]
        or configuration.processing_configuration_sha256 != row[3]
    ):
        raise NumericalSourceError(
            "The sealed parse differs from its original job and configuration."
        )
    return artifact, configuration


def _stored_evidence(connection: DatabaseConnection, binding: NumericalEvidenceBinding) -> None:
    expected = {
        word.evidence.id: word.evidence for phrase in binding.phrases for word in phrase.words
    }
    identities = [UUID(identity) for identity in expected]
    actual = connection.execute(
        "SELECT e.id,e.parse_version_id,e.filing_version_id,e.page_id,e.block_id,e.start_offset,"
        "e.end_offset,e.quote,e.box_count,p.page_index,b.text,p.parse_version_id,p.filing_version_id,"
        "b.parse_version_id,b.page_id,p.width,p.height,p.media_x0,p.media_y0,p.media_x1,p.media_y1,"
        "p.crop_x0,p.crop_y0,p.crop_x1,p.crop_y1,p.rotation,p.coordinate_space,p.origin "
        "FROM regintel.evidence e "
        "JOIN regintel.pages p ON p.id=e.page_id JOIN regintel.blocks b ON b.id=e.block_id "
        "WHERE e.id=ANY(%s) AND e.kind='text'",
        (identities,),
    ).fetchall()
    wanted = {
        (
            UUID(item.id),
            UUID(item.source.parse_version_id),
            UUID(item.source.filing_version_id),
            UUID(item.source.page_id),
            UUID(item.span.block_id),
            item.span.start,
            item.span.end,
            item.span.quote,
            len(item.boxes),
            item.source.page_index,
            item.span.quote,
            UUID(item.source.parse_version_id),
            UUID(item.source.filing_version_id),
            UUID(item.source.parse_version_id),
            UUID(item.source.page_id),
            item.page_geometry.width,
            item.page_geometry.height,
            item.page_geometry.media_box.x0,
            item.page_geometry.media_box.y0,
            item.page_geometry.media_box.x1,
            item.page_geometry.media_box.y1,
            item.page_geometry.crop_box.x0,
            item.page_geometry.crop_box.y0,
            item.page_geometry.crop_box.x1,
            item.page_geometry.crop_box.y1,
            item.page_geometry.rotation,
            item.page_geometry.coordinate_space,
            item.page_geometry.origin,
        )
        for item in expected.values()
    }
    if set(actual) != wanted:
        raise NumericalSourceError("Linked words differ from the actual sealed M1 evidence.")
    boxes = connection.execute(
        "SELECT evidence_id,box_index,x0,y0,x1,y1 FROM regintel.evidence_boxes "
        "WHERE evidence_id=ANY(%s)",
        (identities,),
    ).fetchall()
    wanted_boxes = {
        (UUID(item.id), index, box.x0, box.y0, box.x1, box.y1)
        for item in expected.values()
        for index, box in enumerate(item.boxes)
    }
    if set(boxes) != wanted_boxes:
        raise NumericalSourceError("Linked word rectangles differ from sealed M1 evidence.")


class NumericalEvidenceBindingRepository:
    def __init__(self, source: NumericalRepository) -> None:
        self.source = source

    def bind(self, record_id: str, parse_id: str, user: User) -> NumericalEvidenceBinding:
        for identity in (record_id, parse_id):
            TypeAdapter(CanonicalId).validate_python(identity)
        try:
            with self.source.connect() as connection, connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                _authorize(connection, user)
                record = _history(connection, record_id)
                artifact, configuration = _sealed_parse(connection, parse_id)
                self.source.storage.verify(_blob(connection, record.filing_version_id))
                binding = bind_context_evidence(record, artifact, configuration)
                _stored_evidence(connection, binding)
                return binding
        except (NumericalAuthorizationError, NumericalNotFound, NumericalSourceError):
            raise
        except (
            psycopg.OperationalError,
            psycopg.InterfaceError,
            psycopg.errors.UndefinedTable,
            MigrationError,
        ):
            raise NumericalUnavailable(
                "Numerical evidence binding storage is unavailable."
            ) from None
        except (psycopg.Error, ValueError, OSError, UploadError, ProjectionError):
            raise NumericalSourceError(
                "The numerical context cannot bind to exact sealed M1 evidence."
            ) from None
