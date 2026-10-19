"""Retain original word geometry and proposed table membership for one source page.

This preparation artifact is deliberately separate from a complete ParseArtifact.
Processed table coordinates propose membership only; original word rectangles
are retained unchanged. Nothing here establishes metric/context semantics.
"""

import hashlib
import io
import json
from pathlib import Path
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, TypeAdapter, model_validator
from pypdf import PdfReader

from regintel.contracts.models import ContractModel, PageGeometry, PdfRectangle
from regintel.contracts.primitives import RawText, SafeInteger, Sha256Hash
from regintel.parsing.adapter import (
    _canonical_box,
    _canonical_points,
    _integer,
    _items,
    _mapping,
    _rectangle_points,
)
from regintel.parsing.geometry import CoordinateFrame, GeometryError, geometry_from_pdf_page
from regintel.parsing.models import ParsedPage, ReportedBox, ReportedRectangle

MAX_WORDS = 20_000
MAX_CELLS = 2_000
MAX_CAPTURE_BYTES = 64 * 1024 * 1024
FRAME = CoordinateFrame.CROP_ROTATED_TOP_LEFT


class NativeWord(ContractModel):
    word_index: SafeInteger
    orig: Annotated[RawText, Field(max_length=20_000)] | None
    from_ocr: bool | None
    raw_rectangle: ReportedRectangle | None
    box: PdfRectangle | None


class CellPreview(ContractModel):
    """The parser's proposed grid identity, never an exact source cell by itself."""

    table_index: SafeInteger
    cell_index: SafeInteger
    row_index: SafeInteger
    column_index: SafeInteger
    row_span: Annotated[int, Field(strict=True, ge=1, le=2_000)]
    column_span: Annotated[int, Field(strict=True, ge=1, le=2_000)]
    table_rows: Annotated[int, Field(strict=True, ge=1, le=2_000)]
    table_columns: Annotated[int, Field(strict=True, ge=1, le=2_000)]
    text: Annotated[RawText, Field(max_length=20_000)]
    column_header: bool
    row_header: bool
    raw_box: ReportedBox | None
    box: PdfRectangle | None

    @model_validator(mode="after")
    def grid_membership(self) -> Self:
        if (
            self.row_index + self.row_span > self.table_rows
            or self.column_index + self.column_span > self.table_columns
        ):
            raise ValueError("Preview cell spans must fit their declared table.")
        return self


class WordMapping(ContractModel):
    table_index: SafeInteger
    cell_index: SafeInteger
    state: Literal["PROPOSED", "UNAVAILABLE"]
    reason: Literal[
        "EXACT_NATIVE_WORD_SEQUENCE",
        "TEXT_OR_GEOMETRY_UNAVAILABLE",
        "AMBIGUOUS_SOURCE_MEMBERSHIP",
    ]
    word_indices: Annotated[tuple[SafeInteger, ...], Field(strict=False, max_length=MAX_WORDS)]
    review_required: Literal[True] = True


def _page(geometry: PageGeometry, index: int) -> ParsedPage:
    # Internal geometry helper only; this ID never enters the preparation output or database.
    return ParsedPage(id=str(UUID(int=0, version=4)), page_index=index, geometry=geometry)


def _word_box(raw: ReportedRectangle | None, page: ParsedPage) -> PdfRectangle | None:
    if raw is None:
        return None
    try:
        return _canonical_points(_rectangle_points(raw), raw.coord_origin, page, FRAME)
    except GeometryError:
        return None


def _mappings(
    words: tuple[NativeWord, ...], cells: tuple[CellPreview, ...]
) -> tuple[WordMapping, ...]:
    if len(words) * len(cells) > 4_000_000:
        raise ValueError("The explicit word-membership comparison budget is exceeded.")
    proposed: list[tuple[int, ...]] = []
    for cell in cells:
        indices = tuple(
            word.word_index
            for word in words
            if word.box is not None
            and cell.box is not None
            and cell.box.x0 <= (word.box.x0 + word.box.x1) / 2 <= cell.box.x1
            and cell.box.y0 <= (word.box.y0 + word.box.y1) / 2 <= cell.box.y1
        )
        # Whitespace equivalence proposes a sequence, not a fabricated combined source span.
        matched = " ".join(" ".join(words[index].orig or "" for index in indices).split())
        original_available = all(word.box is not None for word in words) and all(
            words[index].orig and words[index].from_ocr is False for index in indices
        )
        proposed.append(
            indices
            if indices and original_available and matched == " ".join(cell.text.split())
            else ()
        )
    owners: dict[int, int] = {}
    for indices in proposed:
        for index in indices:
            owners[index] = owners.get(index, 0) + 1
    result = []
    for cell, indices in zip(cells, proposed, strict=True):
        ambiguous = any(owners[index] > 1 for index in indices)
        reason = (
            "AMBIGUOUS_SOURCE_MEMBERSHIP"
            if ambiguous
            else "EXACT_NATIVE_WORD_SEQUENCE"
            if indices
            else "TEXT_OR_GEOMETRY_UNAVAILABLE"
        )
        result.append(
            WordMapping.model_validate(
                {
                    "table_index": cell.table_index,
                    "cell_index": cell.cell_index,
                    "state": "PROPOSED" if indices and not ambiguous else "UNAVAILABLE",
                    "reason": reason,
                    "word_indices": indices if not ambiguous else (),
                }
            )
        )
    return tuple(result)


class NumericalPageCapture(ContractModel):
    schema_version: Literal["numerical-source-page-1"] = "numerical-source-page-1"
    scope: Literal["SINGLE_ORIGINAL_PAGE_PREPARATION"] = "SINGLE_ORIGINAL_PAGE_PREPARATION"
    source_sha256: Sha256Hash
    source_page_count: Annotated[int, Field(strict=True, ge=1, le=2_000)]
    page_index: Annotated[int, Field(strict=True, ge=0, le=1_999)]
    page_geometry: PageGeometry
    sdk_configuration_sha256: Sha256Hash
    preparation_code_sha256: Sha256Hash
    raw_capture_sha256: Sha256Hash
    words: Annotated[tuple[NativeWord, ...], Field(strict=False, max_length=MAX_WORDS)]
    cells: Annotated[tuple[CellPreview, ...], Field(strict=False, max_length=MAX_CELLS)]
    mappings: Annotated[tuple[WordMapping, ...], Field(strict=False, max_length=MAX_CELLS)]
    acceptance_eligible: Literal[False] = False

    @model_validator(mode="after")
    def exact_internal_provenance(self) -> Self:
        if self.page_index >= self.source_page_count:
            raise ValueError("The selected original page must exist in this source.")
        if tuple(word.word_index for word in self.words) != tuple(range(len(self.words))):
            raise ValueError("Word indices must retain the original contiguous SDK ordering.")
        keys = [(cell.table_index, cell.cell_index) for cell in self.cells]
        if len(set(keys)) != len(keys):
            raise ValueError("Preview cell identities must be distinct.")
        page = _page(self.page_geometry, self.page_index)
        if any(word.box != _word_box(word.raw_rectangle, page) for word in self.words) or any(
            cell.box != _canonical_box(cell.raw_box, page, FRAME) for cell in self.cells
        ):
            raise ValueError("Canonical geometry must equal the unchanged original transform.")
        if self.mappings != _mappings(self.words, self.cells):
            raise ValueError("Membership proposals must retain exact native words and ambiguity.")
        return self


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def preparation_code_sha256() -> str:
    package = Path(__file__).resolve().parents[1]
    paths = (
        "numerical/source_pages.py",
        "parsing/adapter.py",
        "parsing/geometry.py",
        "parsing/models.py",
        "contracts/models.py",
        "contracts/primitives.py",
    )
    digest = hashlib.sha256()
    for relative in paths:
        contents = (package / relative).read_bytes()
        digest.update(
            relative.encode("ascii") + b"\0" + len(contents).to_bytes(8, "big") + contents
        )
    return digest.hexdigest()


def build_page_capture(
    captured: object,
    *,
    source: Path,
    pdf_page: int,
    expected_source_sha256: str,
    expected_sdk_configuration_sha256: str,
) -> NumericalPageCapture:
    """Check a bounded SDK page capture against immutable original bytes and geometry.

    Hashes bind preparation inputs; they do not independently verify parser text
    against the rendered source or establish authority/reviewed financial context.
    """
    TypeAdapter(Sha256Hash).validate_python(expected_source_sha256)
    TypeAdapter(Sha256Hash).validate_python(expected_sdk_configuration_sha256)
    if type(pdf_page) is not int or not 1 <= pdf_page <= 2_000:
        raise ValueError("Select one explicit original PDF page in the source bounds.")
    if not source.is_absolute() or source.is_symlink() or not source.is_file():
        raise ValueError("An explicit regular original source path is required.")
    with source.open("rb") as handle:
        original = handle.read(MAX_CAPTURE_BYTES + 1)
    if not 0 < len(original) <= MAX_CAPTURE_BYTES:
        raise ValueError("The original source exceeds the byte bound.")
    if hashlib.sha256(original).hexdigest() != expected_source_sha256:
        raise ValueError("Original source bytes do not match the expected hash.")
    reader = PdfReader(io.BytesIO(original), strict=True)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 2_000 or pdf_page > len(reader.pages):
        raise ValueError("The selected original page is unavailable.")
    raw = _mapping(captured)
    raw_bytes = _canonical(raw)
    if len(raw_bytes) > MAX_CAPTURE_BYTES:
        raise ValueError("The captured SDK page exceeds the byte bound.")
    if (
        raw.get("status") != "success"
        or raw.get("errors") != []
        or raw.get("original_source_sha256") != expected_source_sha256
        or type(raw.get("requested_original_pdf_page")) is not int
        or raw.get("requested_original_pdf_page") != pdf_page
    ):
        raise ValueError("A successful capture of this exact original page is required.")
    config = _mapping(raw.get("configuration"))
    config_hash = config.get("configuration_sha256")
    actual_config = hashlib.sha256(
        _canonical({key: value for key, value in config.items() if key != "configuration_sha256"})
    ).hexdigest()
    if config_hash != actual_config or config_hash != expected_sdk_configuration_sha256:
        raise ValueError("Captured SDK settings differ from the selected pinned configuration.")
    pages = _items(raw.get("pages"), 1)
    page_raw = _mapping(pages[0]) if pages else {}
    if type(page_raw.get("page_no")) is not int or page_raw.get("page_no") != pdf_page:
        raise ValueError("The SDK must retain the selected original page number.")
    document = _mapping(raw.get("document"))
    document_pages = _mapping(document.get("pages"))
    if (
        set(document_pages) != {str(pdf_page)}
        or type(_mapping(document_pages[str(pdf_page)]).get("page_no")) is not int
        or _mapping(document_pages[str(pdf_page)]).get("page_no") != pdf_page
    ):
        raise ValueError("The SDK document page mapping differs from the original page.")
    geometry = geometry_from_pdf_page(reader.pages[pdf_page - 1])
    page = _page(geometry, pdf_page - 1)
    words = []
    parsed = _mapping(page_raw.get("parsed_page"))
    for position, value in enumerate(_items(parsed.get("word_cells"), MAX_WORDS)):
        word = _mapping(value)
        if type(word.get("index")) is not int or word.get("index") != position:
            raise ValueError("Original SDK word indices are unavailable or ambiguous.")
        rect = word.get("rect")
        rectangle = (
            ReportedRectangle.model_validate(_mapping(rect) | {"coordinate_frame": "DOCLING_PAGE"})
            if rect is not None
            else None
        )
        words.append(
            NativeWord.model_validate(
                {
                    "word_index": position,
                    "orig": word.get("orig"),
                    "from_ocr": word.get("from_ocr"),
                    "raw_rectangle": rectangle,
                    "box": _word_box(rectangle, page),
                }
            )
        )
    cells = []
    for table_index, value in enumerate(_items(document.get("tables"), 8)):
        table = _mapping(value)
        provenance = tuple(_mapping(entry) for entry in _items(table.get("prov"), 8))
        if not provenance or any(
            type(entry.get("page_no")) is not int or entry.get("page_no") != pdf_page
            for entry in provenance
        ):
            raise ValueError("A table preview must belong to the selected original page.")
        data = _mapping(table.get("data"))
        for cell_index, value in enumerate(_items(data.get("table_cells"), MAX_CELLS)):
            cell = _mapping(value)
            box_raw = cell.get("bbox")
            box = (
                ReportedBox.model_validate(_mapping(box_raw) | {"coordinate_frame": "DOCLING_PAGE"})
                if box_raw is not None
                else None
            )
            preview = CellPreview.model_validate(
                {
                    "table_index": table_index,
                    "cell_index": cell_index,
                    "row_index": cell.get("start_row_offset_idx"),
                    "column_index": cell.get("start_col_offset_idx"),
                    "row_span": cell.get("row_span"),
                    "column_span": cell.get("col_span"),
                    "table_rows": data.get("num_rows"),
                    "table_columns": data.get("num_cols"),
                    "text": cell.get("text"),
                    "column_header": cell.get("column_header"),
                    "row_header": cell.get("row_header"),
                    "raw_box": box,
                    "box": _canonical_box(box, page, FRAME),
                }
            )
            if (
                _integer(cell.get("end_row_offset_idx")) != preview.row_index + preview.row_span
                or _integer(cell.get("end_col_offset_idx"))
                != preview.column_index + preview.column_span
            ):
                raise ValueError("SDK table endpoints differ from their proposed spans.")
            cells.append(preview)
            if len(cells) > MAX_CELLS:
                raise ValueError("The source page exceeds the total preview-cell bound.")
    return NumericalPageCapture(
        source_sha256=expected_source_sha256,
        source_page_count=len(reader.pages),
        page_index=pdf_page - 1,
        page_geometry=geometry,
        sdk_configuration_sha256=expected_sdk_configuration_sha256,
        preparation_code_sha256=preparation_code_sha256(),
        raw_capture_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        words=tuple(words),
        cells=tuple(cells),
        mappings=_mappings(tuple(words), tuple(cells)),
    )


def capture_bytes(capture: NumericalPageCapture) -> bytes:
    return _canonical(capture.model_dump(mode="json"))
