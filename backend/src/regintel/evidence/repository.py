"""Atomic sealed parse persistence and source/evidence reads from PostgreSQL."""

import hashlib
from collections.abc import Callable
from typing import Literal
from uuid import UUID

from regintel.contracts.models import (
    EvidenceSource,
    PageGeometry,
    PdfRectangle,
    TextEvidence,
    TextSpan,
)
from regintel.db.config import DatabaseSettings
from regintel.db.migrations import DatabaseConnection, connect_database
from regintel.evidence.projection import (
    MAX_ARTIFACT_BYTES,
    ParseProjection,
    ProjectionError,
    project_parse,
)
from regintel.ingestion.models import SourceBlob
from regintel.parsing.configuration import ParserRuntimeConfiguration
from regintel.parsing.models import ParseArtifact, ParseProvenance


def persist_parse(
    connection: DatabaseConnection,
    *,
    job_id: str,
    artifact: ParseArtifact,
    configuration: ParserRuntimeConfiguration,
) -> None:
    """Retain the existing legacy projection/validation behavior unchanged."""
    if connection.info.transaction_status.name != "INTRANS":
        raise ProjectionError("ARTIFACT_INVALID")
    persist_projection(connection, job_id=job_id, projection=project_parse(artifact, configuration))


def persist_projection(
    connection: DatabaseConnection,
    *,
    job_id: str,
    projection: ParseProjection,
    sidecar_format: Literal["1.0.0", "1.1.0"] = "1.0.0",
    before_sidecar: Callable[[], None] | None = None,
) -> None:
    """Insert one complete tree/sidecar inside the caller's existing transaction.

    The caller changes the RUNNING job to PARSED before committing this same
    transaction. Deferred database gates reject an incomplete result or rollback.
    """
    if connection.info.transaction_status.name != "INTRANS":
        raise ProjectionError("ARTIFACT_INVALID")
    version = projection.version
    connection.execute(
        """INSERT INTO regintel.parse_versions
        (id,filing_version_id,source_blob_id,adapter_name,adapter_version,
         configuration_sha256,artifact_sha256,page_count,block_count,table_count,
         cell_count,evidence_count) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            version.id,
            version.filing_version_id,
            version.source_blob_id,
            version.adapter_name,
            version.adapter_version,
            version.configuration_sha256,
            version.artifact_sha256,
            version.page_count,
            version.block_count,
            version.table_count,
            version.cell_count,
            version.evidence_count,
        ),
    )
    for page in projection.pages:
        g, m, c = page.geometry, page.geometry.media_box, page.geometry.crop_box
        connection.execute(
            """INSERT INTO regintel.pages
            (id,parse_version_id,filing_version_id,page_index,width,height,
             media_x0,media_y0,media_x1,media_y1,crop_x0,crop_y0,crop_x1,crop_y1,
             rotation,coordinate_space,origin)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                page.id,
                page.parse_version_id,
                page.filing_version_id,
                page.page_index,
                g.width,
                g.height,
                m.x0,
                m.y0,
                m.x1,
                m.y1,
                c.x0,
                c.y0,
                c.x1,
                c.y1,
                g.rotation,
                g.coordinate_space,
                g.origin,
            ),
        )
    for block in projection.blocks:
        connection.execute(
            "INSERT INTO regintel.blocks (id,parse_version_id,page_id,text) VALUES (%s,%s,%s,%s)",
            (block.id, block.parse_version_id, block.page_id, block.text),
        )
    for item in projection.evidence:
        connection.execute(
            """INSERT INTO regintel.evidence
            (id,parse_version_id,filing_version_id,page_id,kind,block_id,
             start_offset,end_offset,quote,box_count)
             VALUES (%s,%s,%s,%s,'text',%s,%s,%s,%s,%s)""",
            (
                item.id,
                item.source.parse_version_id,
                item.source.filing_version_id,
                item.source.page_id,
                item.span.block_id,
                item.span.start,
                item.span.end,
                item.span.quote,
                len(item.boxes),
            ),
        )
        for index, box in enumerate(item.boxes):
            connection.execute(
                """INSERT INTO regintel.evidence_boxes
                (evidence_id,box_index,x0,y0,x1,y1) VALUES (%s,%s,%s,%s,%s,%s)""",
                (item.id, index, box.x0, box.y0, box.x1, box.y1),
            )
    if before_sidecar is not None:
        before_sidecar()
    if sidecar_format == "1.0.0":
        connection.execute(
            """INSERT INTO regintel.parse_artifacts
            (parse_version_id,job_id,artifact_bytes,configuration_bytes) VALUES (%s,%s,%s,%s)""",
            (version.id, job_id, projection.artifact_bytes, projection.configuration_bytes),
        )
    elif sidecar_format == "1.1.0":
        connection.execute(
            """INSERT INTO regintel.parse_artifacts
            (parse_version_id,job_id,artifact_bytes,configuration_bytes,format_version)
            VALUES (%s,%s,%s,%s,'1.1.0')""",
            (version.id, job_id, projection.artifact_bytes, projection.configuration_bytes),
        )
    else:
        raise ProjectionError("ARTIFACT_INVALID")


def _binary(value: object) -> bytes:
    if not isinstance(value, (bytes, memoryview)):
        raise ProjectionError("ARTIFACT_INVALID")
    contents = bytes(value)
    if not 0 < len(contents) <= MAX_ARTIFACT_BYTES:
        raise ProjectionError("ARTIFACT_INVALID")
    return contents


class EvidenceRepository:
    def __init__(self, database: DatabaseSettings) -> None:
        self.database = database

    def get_source(self, filing_version_id: str) -> SourceBlob | None:
        with connect_database(self.database) as connection:
            row = connection.execute(
                """SELECT s.id,s.sha256,s.byte_size,s.storage_key
                FROM regintel.source_blobs s JOIN regintel.filing_versions v
                ON v.source_blob_id=s.id WHERE v.id=%s""",
                (UUID(filing_version_id),),
            ).fetchone()
        if row is None:
            return None
        return SourceBlob.model_validate(
            {"id": str(row[0]), "sha256": row[1], "byte_size": row[2], "storage_key": row[3]}
        )

    def get_evidence(
        self, evidence_id: str
    ) -> tuple[TextEvidence, ParseProvenance, str, str] | None:
        with connect_database(self.database) as connection:
            row = connection.execute(
                """SELECT e.id,v.filing_id,e.filing_version_id,e.parse_version_id,
                e.page_id,p.page_index,e.block_id,e.start_offset,e.end_offset,e.quote,
                p.width,p.height,p.media_x0,p.media_y0,p.media_x1,p.media_y1,
                p.crop_x0,p.crop_y0,p.crop_x1,p.crop_y1,p.rotation,p.coordinate_space,p.origin,
                a.artifact_bytes,r.artifact_sha256,s.sha256,r.configuration_sha256
                FROM regintel.evidence e
                JOIN regintel.pages p ON p.id=e.page_id
                JOIN regintel.parse_versions r ON r.id=e.parse_version_id
                JOIN regintel.filing_versions v ON v.id=e.filing_version_id
                JOIN regintel.source_blobs s ON s.id=v.source_blob_id
                JOIN regintel.parse_artifacts a ON a.parse_version_id=r.id
                JOIN regintel.filing_jobs j ON j.id=a.job_id AND j.state='PARSED'
                AND j.parse_version_id=r.id
                WHERE e.id=%s AND e.kind='text'""",
                (UUID(evidence_id),),
            ).fetchone()
            if row is None:
                return None
            boxes = connection.execute(
                """SELECT x0,y0,x1,y1 FROM regintel.evidence_boxes
                WHERE evidence_id=%s ORDER BY box_index""",
                (UUID(evidence_id),),
            ).fetchall()
        contents = _binary(row[23])
        if hashlib.sha256(contents).hexdigest() != row[24]:
            raise ProjectionError("ARTIFACT_INVALID")
        artifact = ParseArtifact.model_validate_json(contents)
        if artifact.id != str(row[3]) or artifact.source_sha256 != row[25]:
            raise ProjectionError("ARTIFACT_INVALID")
        geometry = PageGeometry.model_validate(
            {
                "width": row[10],
                "height": row[11],
                "media_box": dict(zip(("x0", "y0", "x1", "y1"), row[12:16], strict=True)),
                "crop_box": dict(zip(("x0", "y0", "x1", "y1"), row[16:20], strict=True)),
                "rotation": row[20],
                "coordinate_space": row[21],
                "origin": row[22],
            }
        )
        item = TextEvidence(
            id=str(row[0]),
            kind="text",
            source=EvidenceSource.model_validate(
                {
                    "filing_id": str(row[1]),
                    "filing_version_id": str(row[2]),
                    "parse_version_id": str(row[3]),
                    "page_id": str(row[4]),
                    "page_index": row[5],
                }
            ),
            page_geometry=geometry,
            boxes=tuple(
                PdfRectangle.model_validate(dict(zip(("x0", "y0", "x1", "y1"), box, strict=True)))
                for box in boxes
            ),
            span=TextSpan.model_validate(
                {"block_id": str(row[6]), "start": row[7], "end": row[8], "quote": row[9]}
            ),
        )
        return item, artifact.provenance, str(row[25]), str(row[26])
