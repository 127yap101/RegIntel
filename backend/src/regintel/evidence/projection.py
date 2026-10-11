"""Bounded original-text projection of a complete immutable parser artifact."""

import hashlib
import json
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import ValidationError

from regintel.contracts.models import EvidenceSource, TextEvidence
from regintel.ingestion.models import BlockRecord, PageRecord, ParseVersionRecord
from regintel.parsing.adapter import _canonical_points, _rectangle_points
from regintel.parsing.configuration import (
    ParserRuntimeConfiguration,
    RuntimeConfigurationError,
    canonical_configuration_bytes,
    validate_artifact_provenance,
)
from regintel.parsing.geometry import CoordinateFrame, GeometryError
from regintel.parsing.models import (
    ParseArtifact,
    ParsedBlock,
    ParsedPage,
    artifact_sha256,
    canonical_artifact_bytes,
)

MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_CONFIGURATION_BYTES = 64 * 1024


class ProjectionError(ValueError):
    """Fixed diagnostics exclude filing text, source paths and runtime secrets."""

    def __init__(self, code: Literal["ARTIFACT_INVALID", "PARSER_CONFIGURATION_MISMATCH"]) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ParseProjection:
    version: ParseVersionRecord
    pages: tuple[PageRecord, ...]
    blocks: tuple[BlockRecord, ...]
    evidence: tuple[TextEvidence, ...]
    artifact_bytes: bytes
    configuration_bytes: bytes


def _eligible(block: ParsedBlock, page: ParsedPage, frame: CoordinateFrame) -> bool:
    if (
        block.unavailable_reasons
        or block.source_cell_index is None
        or block.orig is None
        or block.from_ocr is None
        or block.boxes is None
        or len(block.boxes) != 1
        or not block.exact_spans
        or len(block.provenance) != 1
        or block.source_ref != f"page/{page.page_index}/text-cell/{block.source_cell_index}"
    ):
        return False
    reported = block.provenance[0]
    if (
        reported.source_ref != block.source_ref
        or reported.page_no != page.page_index + 1
        or reported.charspan is not None
        or reported.raw_box is not None
        or reported.raw_rectangle is None
    ):
        return False
    # Reuse the frozen adapter's exact four-corner transform. The retained SDK
    # assembled boxes are never a substitute for this raw quadrilateral.
    try:
        box = _canonical_points(
            _rectangle_points(reported.raw_rectangle),
            reported.raw_rectangle.coord_origin,
            page,
            frame,
        )
    except GeometryError:
        raise ProjectionError("ARTIFACT_INVALID") from None
    if block.boxes != (box,):
        raise ProjectionError("ARTIFACT_INVALID")
    return True


def _evidence_id(parse_id: str, block_id: str, start: int, end: int, quote: str) -> str:
    identity = json.dumps(
        ("text-evidence-v1", parse_id, block_id, start, end, quote),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return str(UUID(bytes=hashlib.sha256(identity).digest()[:16], version=4))


def project_parse(
    artifact: ParseArtifact, configuration: ParserRuntimeConfiguration
) -> ParseProjection:
    """Revalidate support and retain complete bytes before any database writes."""
    try:
        artifact = ParseArtifact.model_validate(artifact.model_dump(mode="python"))
        processing_hash = validate_artifact_provenance(
            configuration, provenance=artifact.provenance
        )
        artifact_bytes = canonical_artifact_bytes(artifact)
        configuration_bytes = canonical_configuration_bytes(configuration)
        if not 0 < len(artifact_bytes) <= MAX_ARTIFACT_BYTES:
            raise ProjectionError("ARTIFACT_INVALID")
        if not 0 < len(configuration_bytes) <= MAX_CONFIGURATION_BYTES:
            raise ProjectionError("ARTIFACT_INVALID")
        if len(artifact.pages) > configuration.source_limits.max_pages:
            raise ProjectionError("ARTIFACT_INVALID")
        frame = CoordinateFrame(configuration.coordinate_frame)
    except RuntimeConfigurationError:
        raise ProjectionError("PARSER_CONFIGURATION_MISMATCH") from None
    except (AttributeError, ValidationError, UnicodeError, ValueError) as error:
        if isinstance(error, ProjectionError):
            raise
        raise ProjectionError("ARTIFACT_INVALID") from None

    pages = tuple(
        PageRecord(
            id=page.id,
            parse_version_id=artifact.id,
            filing_version_id=artifact.filing_version_id,
            page_index=page.page_index,
            geometry=page.geometry,
        )
        for page in artifact.pages
    )
    by_id = {page.id: page for page in artifact.pages}
    blocks: list[BlockRecord] = []
    evidence: list[TextEvidence] = []
    for block in artifact.blocks:
        if block.orig is None or block.page_id is None:
            continue
        blocks.append(
            BlockRecord(
                id=block.id,
                parse_version_id=artifact.id,
                page_id=block.page_id,
                text=block.orig,
            )
        )
        page = by_id[block.page_id]
        if not _eligible(block, page, frame):
            continue
        assert block.boxes is not None
        for span in block.exact_spans:
            evidence.append(
                TextEvidence(
                    id=_evidence_id(artifact.id, block.id, span.start, span.end, span.quote),
                    kind="text",
                    source=EvidenceSource(
                        filing_id=artifact.filing_id,
                        filing_version_id=artifact.filing_version_id,
                        parse_version_id=artifact.id,
                        page_id=page.id,
                        page_index=page.page_index,
                    ),
                    page_geometry=page.geometry,
                    boxes=block.boxes,
                    span=span,
                )
            )
    version = ParseVersionRecord(
        id=artifact.id,
        filing_version_id=artifact.filing_version_id,
        source_blob_id=artifact.source_blob_id,
        adapter_name=artifact.provenance.adapter_name,
        adapter_version=artifact.provenance.adapter_version,
        configuration_sha256=processing_hash,
        artifact_sha256=artifact_sha256(artifact),
        page_count=len(pages),
        block_count=len(blocks),
        table_count=0,
        cell_count=0,
        evidence_count=len(evidence),
    )
    return ParseProjection(
        version, pages, tuple(blocks), tuple(evidence), artifact_bytes, configuration_bytes
    )
