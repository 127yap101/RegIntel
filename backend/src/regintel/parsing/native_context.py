"""Versioned M1 projection of complete native source plus exact contextual SDK words.

All original native pages are retained in the bank. Public text evidence projects
only explicitly supplied contextual pages; layout/OCR/table coverage stays scoped
to those actual SDK captures. Financial validation/review is a separate boundary.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from regintel.contracts.models import EvidenceSource, TextEvidence
from regintel.contracts.primitives import Sha256Hash
from regintel.evidence.projection import (
    MAX_ARTIFACT_BYTES,
    MAX_CONFIGURATION_BYTES,
    ParseProjection,
    ProjectionError,
    _eligible,
    _evidence_id,
)
from regintel.ingestion.models import BlockRecord, PageRecord, ParseVersionRecord
from regintel.numerical.models import StoredNumericalPage
from regintel.numerical.source_pages import FRAME, build_page_capture, capture_bytes
from regintel.parsing.adapter import _Builder, _mapping, _opaque_id
from regintel.parsing.configuration import (
    ParserRuntimeConfiguration,
    RuntimeCodeHashes,
    SourceLimits,
    current_runtime_code_hashes,
)
from regintel.parsing.models import (
    ParseArtifact,
    ParsedPage,
    ParseProvenance,
    ReportedRectangle,
    artifact_sha256,
    canonical_artifact_bytes,
)
from regintel.parsing.native_source import (
    NativeSourceBank,
    NativeSourceConfiguration,
    NativeSourceWord,
    PageIndex,
    canonical_bytes,
    native_code_sha256,
    read_native_source,
)


class NativeContextConfiguration(RuntimeCodeHashes):
    schema_version: Literal["1.1.0"] = "1.1.0"
    adapter_name: Literal["regintel-native-context"] = "regintel-native-context"
    adapter_version: Literal["1.0.0"] = "1.0.0"
    coordinate_frame: Literal["CROP_ROTATED_TOP_LEFT"] = "CROP_ROTATED_TOP_LEFT"
    source_limits: SourceLimits
    sdk_configuration_sha256: Sha256Hash
    native_configuration_sha256: Sha256Hash
    model_manifest_sha256: Sha256Hash
    package_manifest_sha256: Sha256Hash
    backend_code_sha256: Sha256Hash
    native_source_configuration: NativeSourceConfiguration
    context_parser_configuration: ParserRuntimeConfiguration
    evidence_page_indices: Annotated[
        tuple[PageIndex, ...], Field(strict=False, min_length=1, max_length=32)
    ]
    native_coverage: Literal["ALL_ORIGINAL_PAGES"] = "ALL_ORIGINAL_PAGES"
    evidence_coverage: Literal["EXPLICIT_CONTEXT_PAGES"] = "EXPLICIT_CONTEXT_PAGES"

    @model_validator(mode="after")
    def stage_identities(self) -> Self:
        baseline, native = self.context_parser_configuration, self.native_source_configuration
        if (
            self.sdk_configuration_sha256 != baseline.sdk_configuration_sha256
            or self.native_configuration_sha256 != native.configuration_sha256
            or self.model_manifest_sha256 != baseline.model_manifest_sha256
            or self.package_manifest_sha256 != native.package_manifest_sha256
            or self.package_manifest_sha256 != baseline.package_manifest_sha256
            or self.backend_code_sha256 != native.backend_code_sha256
            or self.source_limits != baseline.source_limits
            or self.coordinate_frame != baseline.coordinate_frame
            or native.capture_code_sha256 != self.sdk_code_sha256
        ):
            raise ValueError(
                "Native and contextual stages must retain their actual separate identities."
            )
        if self.evidence_page_indices != tuple(sorted(set(self.evidence_page_indices))) or any(
            type(i) is not int or not 0 <= i < self.source_limits.max_pages
            for i in self.evidence_page_indices
        ):
            raise ValueError("Context evidence needs explicit unique ordered original pages.")
        return self

    @property
    def processing_configuration_sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


def _code_hashes() -> RuntimeCodeHashes:
    frozen = current_runtime_code_hashes()
    return RuntimeCodeHashes(
        adapter_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        geometry_code_sha256=frozen.geometry_code_sha256,
        sdk_code_sha256=native_code_sha256(),
        artifact_models_code_sha256=frozen.artifact_models_code_sha256,
    )


def configuration_for(
    native: NativeSourceConfiguration,
    baseline: ParserRuntimeConfiguration,
    selected_pages: tuple[int, ...],
) -> NativeContextConfiguration:
    return NativeContextConfiguration.model_validate(
        _code_hashes().model_dump(mode="python")
        | {
            "source_limits": baseline.source_limits,
            "sdk_configuration_sha256": baseline.sdk_configuration_sha256,
            "native_configuration_sha256": native.configuration_sha256,
            "model_manifest_sha256": baseline.model_manifest_sha256,
            "package_manifest_sha256": native.package_manifest_sha256,
            "backend_code_sha256": native.backend_code_sha256,
            "native_source_configuration": native,
            "context_parser_configuration": baseline,
            "evidence_page_indices": selected_pages,
        }
    )


@dataclass(frozen=True)
class ContextCapture:
    stored: StoredNumericalPage
    raw_bytes: bytes


@dataclass(frozen=True)
class NativeContextParse:
    artifact: ParseArtifact
    configuration: NativeContextConfiguration
    bank: NativeSourceBank
    captures: tuple[ContextCapture, ...]
    table_sources: tuple[tuple[str, str], ...]


def _top_left(word: NativeSourceWord, height: float) -> ReportedRectangle:
    raw = word.raw_rectangle.model_dump(mode="python")
    for index in range(4):
        raw[f"r_y{index}"] = height - getattr(word.raw_rectangle, f"r_y{index}")
    raw["coord_origin"] = "TOPLEFT"
    return ReportedRectangle.model_validate(raw)


def build_native_context_parse(
    bank: NativeSourceBank,
    *,
    source: Path,
    baseline: ParserRuntimeConfiguration,
    captures: tuple[ContextCapture, ...],
    parse_id: str,
    filing_id: str,
    filing_version_id: str,
    source_blob_id: str,
) -> NativeContextParse:
    """Keep native bottom-left words and actual SDK top-left originals separately."""
    checked = read_native_source(source, bank.directory / "manifest.json")
    if checked.manifest != bank.manifest or not 1 <= len(captures) <= 32:
        raise ValueError(
            "An exact complete native bank and bounded contextual captures are required."
        )
    selected = tuple(sorted(c.stored.capture.page_index for c in captures))
    configuration = configuration_for(bank.manifest.configuration, baseline, selected)
    if bank.manifest.configuration.capture_code_sha256 != native_code_sha256():
        raise ValueError("This native bank requires its recorded capture implementation.")
    current = current_runtime_code_hashes().model_dump(mode="python")
    if any(getattr(baseline, key) != value for key, value in current.items()):
        raise ValueError("The contextual parser differs from its frozen application identity.")
    by_page = {c.stored.capture.page_index: c for c in captures}
    source_pages = checked.pages()
    pages = []
    selected_native = {}
    for page in source_pages:
        parsed = ParsedPage(
            id=_opaque_id(parse_id, f"page/{page.page_index}"),
            page_index=page.page_index,
            geometry=page.page_geometry,
        )
        pages.append(parsed)
        if page.page_index in by_page:
            selected_native[page.page_index] = page
    builder = _Builder(parse_id, tuple(pages), FRAME)
    tables = []
    table_sources: list[tuple[str, str]] = []
    for page_index in selected:
        supplied = by_page[page_index]
        stored, prepared = supplied.stored, supplied.stored.capture
        if (
            stored.filing_version_id != filing_version_id
            or stored.source_blob_id != source_blob_id
            or prepared.source_sha256 != checked.manifest.source_sha256
            or prepared.source_page_count != len(pages)
        ):
            raise ValueError("Contextual words must belong to this exact uploaded native source.")
        if hashlib.sha256(supplied.raw_bytes).hexdigest() != prepared.raw_capture_sha256:
            raise ValueError("Contextual SDK bytes differ from their immutable preparation.")
        raw = json.loads(supplied.raw_bytes)
        rebuilt = build_page_capture(
            raw,
            source=source,
            pdf_page=page_index + 1,
            expected_source_sha256=prepared.source_sha256,
            expected_sdk_configuration_sha256=baseline.sdk_configuration_sha256,
        )
        if capture_bytes(rebuilt) != capture_bytes(prepared):
            raise ValueError("Contextual preparation differs from its actual original SDK data.")
        original = selected_native[page_index]
        geometry = original.page_geometry
        if (
            geometry.rotation != 0
            or geometry.crop_box != geometry.media_box
            or geometry.media_box.x0 != 0.0
            or geometry.media_box.y0 != 0.0
        ):
            raise ValueError(
                "This calibrated native/context bridge requires an unrotated full media box."
            )
        if geometry != prepared.page_geometry or len(original.words) != len(prepared.words):
            raise ValueError("Native/contextual page geometry or word count differs.")
        for native, contextual in zip(original.words, prepared.words, strict=True):
            if (
                native.index != contextual.word_index
                or native.orig != contextual.orig
                or contextual.from_ocr is not False
                or _top_left(native, geometry.height) != contextual.raw_rectangle
            ):
                raise ValueError(
                    "Native/contextual original word text and exact corner transform differ."
                )
            assert contextual.raw_rectangle is not None
            builder.low_level_cell(
                pages[page_index],
                {
                    "index": native.index,
                    "orig": native.orig,
                    "text": native.text,
                    "from_ocr": False,
                    "rect": contextual.raw_rectangle.model_dump(
                        mode="json", exclude={"coordinate_frame"}
                    ),
                },
                native.index,
            )
        # Each capture retains its local SDK references. A distinct opaque identity
        # namespaces those references; table_sources retains the exact capture link.
        sub_id = str(
            UUID(bytes=hashlib.sha256(f"{parse_id}:{stored.id}".encode()).digest()[:16], version=4)
        )
        sub = _Builder(sub_id, tuple(pages), FRAME)
        raw_document = _mapping(raw["document"])
        raw_tables = raw_document.get("tables")
        if not isinstance(raw_tables, list):
            raise ValueError("Contextual SDK tables must retain their actual local membership.")
        for index, table in enumerate(raw_tables):
            sub.document_table(table, index)
        tables.extend(sub.tables)
        table_sources.extend((table.id, stored.id) for table in sub.tables)
        builder.diagnostics.extend(sub.diagnostics)
    provenance = ParseProvenance(
        adapter_name=configuration.adapter_name,
        adapter_version=configuration.adapter_version,
        adapter_code_sha256=configuration.adapter_code_sha256,
        backend_name="DoclingPdfParser",
        backend_version="7.22.1",
        backend_code_sha256=configuration.backend_code_sha256,
        coordinate_frame=configuration.coordinate_frame,
        packages=checked.manifest.configuration.packages,
        package_manifest_sha256=configuration.package_manifest_sha256,
        configuration_sha256=configuration.sdk_configuration_sha256,
        model_manifest_sha256=configuration.model_manifest_sha256,
    )
    artifact = ParseArtifact(
        schema_version="1.0.0",
        id=parse_id,
        filing_id=filing_id,
        filing_version_id=filing_version_id,
        source_blob_id=source_blob_id,
        source_sha256=checked.manifest.source_sha256,
        provenance=provenance,
        pages=tuple(pages),
        blocks=tuple(builder.blocks),
        tables=tuple(tables),
        diagnostics=tuple(builder.diagnostics),
    )
    return NativeContextParse(artifact, configuration, checked, captures, tuple(table_sources))


def project_native_context(
    artifact: ParseArtifact,
    configuration: NativeContextConfiguration,
) -> ParseProjection:
    """Project the declared original-word support into M1's existing text contracts."""
    artifact = ParseArtifact.model_validate(artifact.model_dump(mode="python"))
    configuration = NativeContextConfiguration.model_validate(
        configuration.model_dump(mode="python")
    )
    if any(
        getattr(configuration, key) != value for key, value in _code_hashes().model_dump().items()
    ) or any(
        getattr(configuration.context_parser_configuration, key) != value
        for key, value in current_runtime_code_hashes().model_dump().items()
    ):
        raise ProjectionError("PARSER_CONFIGURATION_MISMATCH")
    p = artifact.provenance
    if (
        p.adapter_name != configuration.adapter_name
        or p.adapter_version != configuration.adapter_version
        or p.backend_name != "DoclingPdfParser"
        or p.backend_version != "7.22.1"
        or p.adapter_code_sha256 != configuration.adapter_code_sha256
        or p.backend_code_sha256 != configuration.backend_code_sha256
        or p.configuration_sha256 != configuration.sdk_configuration_sha256
        or p.coordinate_frame != configuration.coordinate_frame
        or p.package_manifest_sha256 != configuration.package_manifest_sha256
        or p.model_manifest_sha256 != configuration.model_manifest_sha256
        or len(artifact.pages) > configuration.source_limits.max_pages
    ):
        raise ProjectionError("PARSER_CONFIGURATION_MISMATCH")
    encoded = canonical_artifact_bytes(artifact)
    configuration_bytes = canonical_bytes(configuration)
    if len(encoded) > MAX_ARTIFACT_BYTES or len(configuration_bytes) > MAX_CONFIGURATION_BYTES:
        raise ProjectionError("ARTIFACT_INVALID")
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
    blocks = []
    evidence = []
    for block in artifact.blocks:
        if (
            block.page_id is None
            or block.orig is None
            or block.page_index not in configuration.evidence_page_indices
        ):
            raise ProjectionError("ARTIFACT_INVALID")
        blocks.append(
            BlockRecord(
                id=block.id, parse_version_id=artifact.id, page_id=block.page_id, text=block.orig
            )
        )
        page = by_id[block.page_id]
        if not _eligible(block, page, FRAME):
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
        adapter_name=p.adapter_name,
        adapter_version=p.adapter_version,
        configuration_sha256=configuration.processing_configuration_sha256,
        artifact_sha256=artifact_sha256(artifact),
        page_count=len(pages),
        block_count=len(blocks),
        table_count=0,
        cell_count=0,
        evidence_count=len(evidence),
    )
    return ParseProjection(
        version, pages, tuple(blocks), tuple(evidence), encoded, configuration_bytes
    )
