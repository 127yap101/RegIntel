"""Immutable M1.3 parser artifacts; structure does not accept facts or publish evidence.

Reported Docling offsets/boxes are retained separately from canonical PDF geometry
and exact spans over ``orig``. Run timestamps, latency and job state are deliberately
absent from this content-addressed artifact.
"""

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, ConfigDict, Field, model_validator

from regintel.contracts.models import ContractModel, PageGeometry, PdfRectangle, TextSpan
from regintel.contracts.primitives import (
    MAX_SAFE_INTEGER,
    CanonicalId,
    FiniteCoordinate,
    PageIndex,
    PositiveSafeInteger,
    SafeInteger,
    Sha256Hash,
    integer_from_wire,
)
from regintel.ingestion.models import StoredLabel, StoredText

PARSE_ARTIFACT_VERSION: Literal["1.0.0"] = "1.0.0"
MAX_ARTIFACT_PAGES = 2_000  # The existing upload contract has the same hard ceiling.
MAX_ARTIFACT_BLOCKS = 1_000_000
MAX_ARTIFACT_TABLES = 10_000
MAX_ARTIFACT_CELLS = 1_000_000
MAX_ARTIFACT_DIAGNOSTICS = 10_000

EvidenceUnavailableReason = Literal[
    "PAGE_MAPPING_UNAVAILABLE",
    "GEOMETRY_UNAVAILABLE",
    "ORIGINAL_TEXT_UNAVAILABLE",
    "TEXT_SPAN_UNAVAILABLE",
    "PROVENANCE_SPAN_INVALID",
    "TABLE_CELL_MAPPING_UNAVAILABLE",
    "UNSUPPORTED_GEOMETRY_FRAME",
    "RAW_GEOMETRY_UNAVAILABLE",
]
ParseDiagnosticCode = Literal[
    "PAGE_MAPPING_UNAVAILABLE",
    "GEOMETRY_UNAVAILABLE",
    "ORIGINAL_TEXT_UNAVAILABLE",
    "TEXT_SPAN_UNAVAILABLE",
    "PROVENANCE_SPAN_INVALID",
    "TABLE_CELL_MAPPING_UNAVAILABLE",
    "UNSUPPORTED_GEOMETRY_FRAME",
    "RAW_GEOMETRY_UNAVAILABLE",
    "OCR_SCORE_UNAVAILABLE",
    "PARSE_PARTIAL",
    "BACKEND_ERROR",
    "TABLE_STRUCTURE_INCOMPLETE",
    "PAGE_TEXT_UNAVAILABLE",
]
OcrScore = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
ReportedOffset = Annotated[
    int,
    Field(strict=True, ge=-MAX_SAFE_INTEGER, le=MAX_SAFE_INTEGER),
    BeforeValidator(integer_from_wire),
]
CanonicalBoxes = Annotated[
    tuple[PdfRectangle, ...], Field(strict=False, min_length=1, max_length=10_000)
]
UnavailableReasons = Annotated[
    tuple[EvidenceUnavailableReason, ...], Field(strict=False, max_length=8)
]


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


class PackageVersion(ContractModel):
    name: Annotated[StoredLabel, Field(pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")]
    version: StoredLabel


PackageVersions = Annotated[
    tuple[PackageVersion, ...], Field(strict=False, min_length=1, max_length=256)
]


def package_manifest_sha256(packages: tuple[PackageVersion, ...]) -> str:
    """Hash normalized package names/versions in their required canonical name order."""
    values = [package.model_dump(mode="json") for package in packages]
    return hashlib.sha256(_canonical_json_bytes(values)).hexdigest()


class ParseProvenance(ContractModel):
    adapter_name: StoredLabel
    adapter_version: StoredLabel
    adapter_code_sha256: Sha256Hash
    backend_name: StoredLabel
    backend_version: StoredLabel
    backend_code_sha256: Sha256Hash
    coordinate_frame: Literal[
        "RAW_PDF_BOTTOM_LEFT",
        "MEDIA_RELATIVE_BOTTOM_LEFT",
        "CROP_ROTATED_BOTTOM_LEFT",
        "CROP_ROTATED_TOP_LEFT",
    ]
    packages: PackageVersions
    package_manifest_sha256: Sha256Hash
    configuration_sha256: Sha256Hash
    model_manifest_sha256: Sha256Hash

    @model_validator(mode="after")
    def validate_package_manifest(self) -> Self:
        names = tuple(package.name for package in self.packages)
        if names != tuple(sorted(set(names))):
            raise ValueError("Package versions must have unique names in canonical name order.")
        if self.package_manifest_sha256 != package_manifest_sha256(self.packages):
            raise ValueError("Package manifest hash must match the retained package versions.")
        return self


class ReportedCharacterSpan(ContractModel):
    """Retained upstream endpoints, including bounded invalid ordering/signs.

    These are diagnostics data rather than validated offsets into stored ``orig``.
    Invalid reported offsets must remain visible instead of being repaired or
    replaced with a separately valid exact span.
    """

    start: ReportedOffset
    end: ReportedOffset


class ReportedBox(ContractModel):
    """Raw parser endpoints in its declared frame, never an exact evidence rectangle."""

    model_config = ConfigDict(validate_by_name=True)

    left: Annotated[FiniteCoordinate, Field(alias="l")]
    top: Annotated[FiniteCoordinate, Field(alias="t")]
    right: Annotated[FiniteCoordinate, Field(alias="r")]
    bottom: Annotated[FiniteCoordinate, Field(alias="b")]
    coord_origin: Literal["TOPLEFT", "BOTTOMLEFT"]
    coordinate_frame: Literal["DOCLING_PAGE"]


class ReportedRectangle(ContractModel):
    """The eight reported oriented-rectangle coordinates, before any envelope/transform."""

    r_x0: FiniteCoordinate
    r_y0: FiniteCoordinate
    r_x1: FiniteCoordinate
    r_y1: FiniteCoordinate
    r_x2: FiniteCoordinate
    r_y2: FiniteCoordinate
    r_x3: FiniteCoordinate
    r_y3: FiniteCoordinate
    coord_origin: Literal["TOPLEFT", "BOTTOMLEFT"]
    coordinate_frame: Literal["DOCLING_PAGE"]


class BlockProvenance(ContractModel):
    source_ref: StoredLabel
    page_no: PositiveSafeInteger | None
    text: StoredText | None
    charspan: ReportedCharacterSpan | None
    raw_box: ReportedBox | None
    raw_rectangle: ReportedRectangle | None = None

    @property
    def reported_span_valid(self) -> bool:
        """A reported offset indexes its own upstream text, never stored orig implicitly."""
        return self.charspan is None or (
            self.text is not None
            and 0 <= self.charspan.start <= self.charspan.end <= len(self.text)
        )


ProvenanceEntries = Annotated[tuple[BlockProvenance, ...], Field(strict=False, max_length=1_000)]
ExactSpans = Annotated[tuple[TextSpan, ...], Field(strict=False, max_length=1_000)]


def _validate_location(
    page_id: str | None,
    page_index: int | None,
    boxes: tuple[PdfRectangle, ...] | None,
    orig: str | None,
    reasons: tuple[EvidenceUnavailableReason, ...],
) -> None:
    if (page_id is None) != (page_index is None):
        raise ValueError("Page ID and page index must be present or unavailable together.")
    if len(reasons) != len(set(reasons)):
        raise ValueError("Unavailable reasons must be unique.")
    if page_id is None:
        if "PAGE_MAPPING_UNAVAILABLE" not in reasons:
            raise ValueError("Missing page mapping needs an explicit unavailable reason.")
        if boxes is not None:
            raise ValueError("Canonical boxes require a mapped source page.")
    if boxes is None and "GEOMETRY_UNAVAILABLE" not in reasons:
        raise ValueError("Missing canonical boxes need an explicit unavailable reason.")
    if orig is None and "ORIGINAL_TEXT_UNAVAILABLE" not in reasons:
        raise ValueError("Missing original text needs an explicit unavailable reason.")


def _validate_ocr(from_ocr: bool | None, score: float | None) -> None:
    if from_ocr is not True and score is not None:
        raise ValueError("Only explicitly OCR-derived text may carry a measured OCR score.")


def _validate_reported_support(
    provenance: tuple[BlockProvenance, ...], reasons: tuple[EvidenceUnavailableReason, ...]
) -> None:
    if any(not entry.reported_span_valid for entry in provenance):
        if "PROVENANCE_SPAN_INVALID" not in reasons:
            raise ValueError("Invalid reported support needs an explicit unavailable reason.")


class ParsedPage(ContractModel):
    id: CanonicalId
    page_index: PageIndex
    geometry: PageGeometry


class ParsedBlock(ContractModel):
    id: CanonicalId
    page_id: CanonicalId | None
    page_index: PageIndex | None
    source_ref: StoredLabel
    source_cell_index: SafeInteger | None
    orig: StoredText | None
    text: StoredText
    from_ocr: bool | None
    ocr_score: OcrScore | None
    boxes: CanonicalBoxes | None
    provenance: ProvenanceEntries
    exact_spans: ExactSpans
    unavailable_reasons: UnavailableReasons

    @model_validator(mode="after")
    def validate_original_support(self) -> Self:
        _validate_location(
            self.page_id, self.page_index, self.boxes, self.orig, self.unavailable_reasons
        )
        _validate_ocr(self.from_ocr, self.ocr_score)
        _validate_reported_support(self.provenance, self.unavailable_reasons)
        if self.from_ocr is None and "RAW_GEOMETRY_UNAVAILABLE" not in self.unavailable_reasons:
            raise ValueError("Assembled text needs an explicit unavailable raw-geometry reason.")
        if not self.exact_spans and "TEXT_SPAN_UNAVAILABLE" not in self.unavailable_reasons:
            raise ValueError("Missing exact spans need an explicit unavailable reason.")
        for span in self.exact_spans:
            if (
                span.block_id != self.id
                or self.orig is None
                or span.end > len(self.orig)
                or self.orig[span.start : span.end] != span.quote
            ):
                raise ValueError("Every exact quote must equal its stored original Unicode slice.")
        keys = tuple((span.start, span.end, span.quote) for span in self.exact_spans)
        if len(keys) != len(set(keys)):
            raise ValueError("Exact spans must be unique within each block.")
        return self

    @property
    def exact_evidence_available(self) -> bool:
        """Availability of exact source support is not semantic acceptance or OCR truth."""
        return not self.unavailable_reasons


class ParsedCell(ContractModel):
    id: CanonicalId
    table_id: CanonicalId
    source_ref: StoredLabel
    row_index: SafeInteger
    column_index: SafeInteger
    row_span: PositiveSafeInteger
    column_span: PositiveSafeInteger
    column_header: bool
    row_header: bool
    row_section: bool
    orig: StoredText | None
    text: StoredText
    from_ocr: bool | None
    ocr_score: OcrScore | None
    page_id: CanonicalId | None
    page_index: PageIndex | None
    boxes: CanonicalBoxes | None
    provenance: ProvenanceEntries
    unavailable_reasons: UnavailableReasons

    @model_validator(mode="after")
    def validate_source_shape(self) -> Self:
        _validate_location(
            self.page_id, self.page_index, self.boxes, self.orig, self.unavailable_reasons
        )
        _validate_ocr(self.from_ocr, self.ocr_score)
        _validate_reported_support(self.provenance, self.unavailable_reasons)
        if (
            self.row_index + self.row_span > MAX_SAFE_INTEGER
            or self.column_index + self.column_span > MAX_SAFE_INTEGER
        ):
            raise ValueError("Table cell endpoints must remain exact safe integers.")
        return self

    @property
    def exact_evidence_available(self) -> bool:
        return not self.unavailable_reasons


class TablePageRegion(ContractModel):
    page_id: CanonicalId
    page_index: PageIndex
    boxes: CanonicalBoxes


TablePageRegions = Annotated[
    tuple[TablePageRegion, ...], Field(strict=False, max_length=MAX_ARTIFACT_PAGES)
]
TableCells = Annotated[tuple[ParsedCell, ...], Field(strict=False, max_length=MAX_ARTIFACT_CELLS)]


class ParsedTable(ContractModel):
    id: CanonicalId
    source_ref: StoredLabel
    row_count: PositiveSafeInteger
    column_count: PositiveSafeInteger
    page_regions: TablePageRegions
    provenance: ProvenanceEntries
    cells: TableCells
    unavailable_reasons: UnavailableReasons

    @model_validator(mode="after")
    def validate_structure(self) -> Self:
        if len(set(self.unavailable_reasons)) != len(self.unavailable_reasons):
            raise ValueError("Unavailable reasons must be unique.")
        if not self.page_regions and "GEOMETRY_UNAVAILABLE" not in self.unavailable_reasons:
            raise ValueError("Missing table regions need an explicit unavailable reason.")
        if (
            not self.provenance or any(entry.page_no is None for entry in self.provenance)
        ) and "PAGE_MAPPING_UNAVAILABLE" not in self.unavailable_reasons:
            raise ValueError("Missing table page mappings need an explicit unavailable reason.")
        located_count = sum(len(region.boxes) for region in self.page_regions)
        if located_count > len(self.provenance):
            raise ValueError("Table regions cannot exceed their reported provenance entries.")
        if (
            not self.provenance
            or located_count < len(self.provenance)
            or any(entry.raw_box is None for entry in self.provenance)
        ) and "GEOMETRY_UNAVAILABLE" not in self.unavailable_reasons:
            raise ValueError("Incomplete table geometry needs an explicit unavailable reason.")
        region_ids = tuple(region.page_id for region in self.page_regions)
        if len(region_ids) != len(set(region_ids)):
            raise ValueError("A table has at most one region record per source page.")
        cell_ids: set[str] = set()
        anchors: set[tuple[int, int]] = set()
        for cell in self.cells:
            anchor = (cell.row_index, cell.column_index)
            if cell.id in cell_ids or anchor in anchors:
                raise ValueError("Table cell IDs and row/column anchors must be unique.")
            cell_ids.add(cell.id)
            anchors.add(anchor)
            if cell.table_id != self.id:
                raise ValueError("Every cell must belong to its retained table.")
            if (
                cell.row_index + cell.row_span > self.row_count
                or cell.column_index + cell.column_span > self.column_count
            ):
                raise ValueError("Table cell indices and spans must fit the table dimensions.")
        return self


class ParseDiagnostic(ContractModel):
    code: ParseDiagnosticCode
    severity: Literal["WARNING", "ERROR"]
    source_ref: StoredLabel | None
    page_id: CanonicalId | None
    block_id: CanonicalId | None
    table_id: CanonicalId | None
    cell_id: CanonicalId | None
    detail: Annotated[StoredText, Field(max_length=2_000)] | None


ArtifactPages = Annotated[
    tuple[ParsedPage, ...], Field(strict=False, min_length=1, max_length=MAX_ARTIFACT_PAGES)
]
ArtifactBlocks = Annotated[
    tuple[ParsedBlock, ...], Field(strict=False, max_length=MAX_ARTIFACT_BLOCKS)
]
ArtifactTables = Annotated[
    tuple[ParsedTable, ...], Field(strict=False, max_length=MAX_ARTIFACT_TABLES)
]
ArtifactDiagnostics = Annotated[
    tuple[ParseDiagnostic, ...], Field(strict=False, max_length=MAX_ARTIFACT_DIAGNOSTICS)
]


def _validate_page_reference(
    pages: dict[str, ParsedPage],
    page_id: str | None,
    page_index: int | None,
    boxes: tuple[PdfRectangle, ...] | None,
) -> None:
    if page_id is None:
        return
    page = pages.get(page_id)
    if page is None or page.page_index != page_index:
        raise ValueError("A mapped item must reference the exact retained source page and index.")
    if boxes is not None:
        media = page.geometry.media_box
        for box in boxes:
            if box.x0 < media.x0 or box.y0 < media.y0 or box.x1 > media.x1 or box.y1 > media.y1:
                raise ValueError("Canonical boxes must lie within their source media box.")


class ParseArtifact(ContractModel):
    schema_version: Literal["1.0.0"]
    id: CanonicalId
    filing_id: CanonicalId
    filing_version_id: CanonicalId
    source_blob_id: CanonicalId
    source_sha256: Sha256Hash
    provenance: ParseProvenance
    pages: ArtifactPages
    blocks: ArtifactBlocks
    tables: ArtifactTables
    diagnostics: ArtifactDiagnostics

    @model_validator(mode="after")
    def validate_membership(self) -> Self:
        if tuple(page.page_index for page in self.pages) != tuple(range(len(self.pages))):
            raise ValueError("Source pages must cover contiguous zero-based indices in order.")
        cells = tuple(cell for table in self.tables for cell in table.cells)
        if len(cells) > MAX_ARTIFACT_CELLS:
            raise ValueError("The artifact exceeds its bounded total cell count.")
        record_ids = (
            self.id,
            *(page.id for page in self.pages),
            *(block.id for block in self.blocks),
            *(table.id for table in self.tables),
            *(cell.id for cell in cells),
        )
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("Parse, page, block, table and cell IDs must be globally unique.")
        pages = {page.id: page for page in self.pages}
        block_ids = {block.id for block in self.blocks}
        table_ids = {table.id for table in self.tables}
        cell_ids = {cell.id for cell in cells}
        page_ids = set(pages)
        for block in self.blocks:
            _validate_page_reference(pages, block.page_id, block.page_index, block.boxes)
        for table in self.tables:
            if (
                any(
                    entry.page_no is not None and entry.page_no - 1 >= len(self.pages)
                    for entry in table.provenance
                )
                and "PAGE_MAPPING_UNAVAILABLE" not in table.unavailable_reasons
            ):
                raise ValueError("Unknown table source pages need an explicit unavailable reason.")
            for region in table.page_regions:
                _validate_page_reference(pages, region.page_id, region.page_index, region.boxes)
            for cell in table.cells:
                _validate_page_reference(pages, cell.page_id, cell.page_index, cell.boxes)
        for diagnostic in self.diagnostics:
            references = (
                (diagnostic.page_id, page_ids),
                (diagnostic.block_id, block_ids),
                (diagnostic.table_id, table_ids),
                (diagnostic.cell_id, cell_ids),
            )
            if any(value is not None and value not in ids for value, ids in references):
                raise ValueError("Diagnostic record IDs must belong to the retained artifact.")
        return self


def canonical_artifact_bytes(artifact: ParseArtifact) -> bytes:
    """Deterministic UTF-8 JSON; all retained structure/provenance contributes to identity."""
    return _canonical_json_bytes(artifact.model_dump(mode="json"))


def artifact_sha256(artifact: ParseArtifact) -> str:
    return hashlib.sha256(canonical_artifact_bytes(artifact)).hexdigest()
