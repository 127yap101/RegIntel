"""Validate captured Docling data without executing document instructions.

The caller selects a calibrated coordinate frame explicitly. Low-level original
text/corners stay separate from assembled document text and SDK-reported boxes.
Docling-core validates and may clamp assembled provenance/table-cell boxes before
export; those retained boxes are SDK output, not unmodified extractor geometry.
This adapter neither accepts financial facts nor writes authoritative state.
"""

import hashlib
import json
import math
from io import BytesIO
from pathlib import Path
from typing import Literal, cast
from uuid import UUID

from pydantic import TypeAdapter, ValidationError
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from regintel.contracts.models import PdfRectangle, TextSpan
from regintel.contracts.primitives import MAX_SAFE_INTEGER, CanonicalId, Sha256Hash
from regintel.parsing.geometry import (
    CoordinateFrame,
    GeometryError,
    frame_bounds,
    geometry_from_pdf_page,
    to_pdf_point,
)
from regintel.parsing.models import (
    MAX_ARTIFACT_BLOCKS,
    MAX_ARTIFACT_CELLS,
    MAX_ARTIFACT_DIAGNOSTICS,
    MAX_ARTIFACT_PAGES,
    MAX_ARTIFACT_TABLES,
    PARSE_ARTIFACT_VERSION,
    BlockProvenance,
    EvidenceUnavailableReason,
    PackageVersion,
    ParseArtifact,
    ParsedBlock,
    ParsedCell,
    ParseDiagnostic,
    ParsedPage,
    ParsedTable,
    ParseProvenance,
    ReportedBox,
    ReportedCharacterSpan,
    ReportedRectangle,
    TablePageRegion,
)

AdapterCode = Literal[
    "CAPTURE_INVALID",
    "PARSE_NOT_COMPLETE",
    "SOURCE_MISMATCH",
    "PAGE_COVERAGE_INVALID",
    "CONFIGURATION_INVALID",
    "SOURCE_GEOMETRY_INVALID",
    "STRUCTURE_INVALID",
]
Origin = Literal["TOPLEFT", "BOTTOMLEFT"]


class AdapterError(ValueError):
    """Fixed failure codes deliberately exclude untrusted text and source paths."""

    def __init__(self, code: AdapterCode) -> None:
        self.code = code
        super().__init__(code)


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise AdapterError("CAPTURE_INVALID")
    return cast(dict[str, object], value)


def _items(value: object, limit: int) -> list[object]:
    if not isinstance(value, list) or len(value) > limit:
        raise AdapterError("CAPTURE_INVALID")
    return cast(list[object], value)


def _integer(value: object, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= MAX_SAFE_INTEGER:
        raise AdapterError("STRUCTURE_INVALID")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise AdapterError("STRUCTURE_INVALID")
    return value


def _optional_text(value: object) -> str | None:
    return None if value is None else _text(value)


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise AdapterError("STRUCTURE_INVALID")
    return value


def _json_sha256(value: object) -> str:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise AdapterError("CONFIGURATION_INVALID") from None
    return hashlib.sha256(encoded).hexdigest()


def _opaque_id(parse_id: str, source_ref: str) -> str:
    digest = hashlib.sha256(f"{parse_id}\0{source_ref}".encode()).digest()
    return str(UUID(bytes=digest[:16], version=4))


def _provenance(configuration: object, frame: CoordinateFrame) -> ParseProvenance:
    config = _mapping(configuration)
    retained = {key: value for key, value in config.items() if key != "configuration_sha256"}
    if config.get("configuration_sha256") != _json_sha256(retained):
        raise AdapterError("CONFIGURATION_INVALID")
    packages = tuple(
        PackageVersion.model_validate(item) for item in _items(config.get("packages"), 256)
    )
    versions = {package.name: package.version for package in packages}
    backend_version = versions.get("docling-parse")
    if backend_version is None:
        raise AdapterError("CONFIGURATION_INVALID")
    return ParseProvenance.model_validate(
        {
            "adapter_name": "regintel-docling",
            "adapter_version": "1.0.0",
            "adapter_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "backend_name": config.get("backend"),
            "backend_version": backend_version,
            "backend_code_sha256": config.get("backend_code_sha256"),
            "coordinate_frame": frame.value,
            "packages": packages,
            "package_manifest_sha256": config.get("package_manifest_sha256"),
            "configuration_sha256": config.get("configuration_sha256"),
            "model_manifest_sha256": config.get("model_manifest_sha256"),
        }
    )


def _reported_box(value: object) -> ReportedBox | None:
    if value is None:
        return None
    try:
        raw = _mapping(value)
        return ReportedBox.model_validate(
            {key: raw.get(key) for key in ("l", "t", "r", "b", "coord_origin")}
            | {"coordinate_frame": "DOCLING_PAGE"}
        )
    except (AdapterError, ValidationError):
        return None


def _reported_rectangle(value: object) -> ReportedRectangle | None:
    if value is None:
        return None
    try:
        raw = _mapping(value)
        return ReportedRectangle.model_validate(
            {
                f"r_{axis}{index}": raw.get(f"r_{axis}{index}")
                for index in range(4)
                for axis in ("x", "y")
            }
            | {"coord_origin": raw.get("coord_origin"), "coordinate_frame": "DOCLING_PAGE"}
        )
    except (AdapterError, ValidationError):
        return None


def _rectangle_points(raw: ReportedRectangle) -> tuple[tuple[float, float], ...]:
    return (
        (raw.r_x0, raw.r_y0),
        (raw.r_x1, raw.r_y1),
        (raw.r_x2, raw.r_y2),
        (raw.r_x3, raw.r_y3),
    )


def _canonical_points(
    points: tuple[tuple[float, float], ...],
    origin: Origin,
    page: ParsedPage,
    frame: CoordinateFrame,
) -> PdfRectangle:
    turns = tuple(
        (points[(index + 1) % 4][0] - points[index][0])
        * (points[(index + 2) % 4][1] - points[(index + 1) % 4][1])
        - (points[(index + 1) % 4][1] - points[index][1])
        * (points[(index + 2) % 4][0] - points[(index + 1) % 4][0])
        for index in range(4)
    )
    if not all(math.isfinite(turn) for turn in turns) or not (
        all(turn > 0 for turn in turns) or all(turn < 0 for turn in turns)
    ):
        raise GeometryError("INVALID_GEOMETRY", "Reported corners lack a convex positive area.")
    selected_origin = "TOPLEFT" if frame is CoordinateFrame.CROP_ROTATED_TOP_LEFT else "BOTTOMLEFT"
    if origin != selected_origin:
        if frame is CoordinateFrame.RAW_PDF_BOTTOM_LEFT:
            raise GeometryError("UNKNOWN_FRAME", "Raw PDF frame requires bottom-left coordinates.")
        height = frame_bounds(page.geometry, frame=frame).y1
        points = tuple((x, height - y) for x, y in points)
    canonical = tuple(to_pdf_point(point, page.geometry, frame=frame) for point in points)
    try:
        return PdfRectangle(
            x0=min(x for x, _ in canonical),
            y0=min(y for _, y in canonical),
            x1=max(x for x, _ in canonical),
            y1=max(y for _, y in canonical),
        )
    except ValidationError:
        raise GeometryError("INVALID_GEOMETRY", "Reported corners have no positive area.") from None


def _canonical_box(
    raw: ReportedBox | None,
    page: ParsedPage | None,
    frame: CoordinateFrame,
) -> PdfRectangle | None:
    if raw is None or page is None:
        return None
    if (
        raw.right <= raw.left
        or (raw.coord_origin == "TOPLEFT" and raw.bottom <= raw.top)
        or (raw.coord_origin == "BOTTOMLEFT" and raw.top <= raw.bottom)
    ):
        return None
    try:
        return _canonical_points(
            (
                (raw.left, raw.top),
                (raw.right, raw.top),
                (raw.right, raw.bottom),
                (raw.left, raw.bottom),
            ),
            raw.coord_origin,
            page,
            frame,
        )
    except GeometryError:
        return None


def _entry(value: object, source_ref: str, text: str | None) -> BlockProvenance:
    raw = _mapping(value)
    offsets = raw.get("charspan")
    span = None
    if offsets is not None:
        if not isinstance(offsets, (list, tuple)) or len(offsets) != 2:
            raise AdapterError("STRUCTURE_INVALID")
        span = ReportedCharacterSpan.model_validate({"start": offsets[0], "end": offsets[1]})
    return BlockProvenance(
        source_ref=source_ref,
        page_no=None if raw.get("page_no") is None else _integer(raw.get("page_no"), minimum=1),
        text=text,
        charspan=span,
        raw_box=_reported_box(raw.get("bbox")),
    )


def _reasons(
    page: ParsedPage | None,
    boxes: tuple[PdfRectangle, ...] | None,
    orig: str | None,
) -> list[EvidenceUnavailableReason]:
    result: list[EvidenceUnavailableReason] = []
    if page is None:
        result.append("PAGE_MAPPING_UNAVAILABLE")
    if boxes is None:
        result.append("GEOMETRY_UNAVAILABLE")
    if orig is None:
        result.append("ORIGINAL_TEXT_UNAVAILABLE")
    return result


class _Builder:
    def __init__(
        self,
        parse_id: str,
        pages: tuple[ParsedPage, ...],
        frame: CoordinateFrame,
    ) -> None:
        self.parse_id, self.frame = parse_id, frame
        self.pages = {page.page_index + 1: page for page in pages}
        self.blocks: list[ParsedBlock] = []
        self.tables: list[ParsedTable] = []
        self.diagnostics: list[ParseDiagnostic] = []
        self.cell_count = 0

    def diagnostic(
        self,
        code: EvidenceUnavailableReason | Literal["OCR_SCORE_UNAVAILABLE", "PAGE_TEXT_UNAVAILABLE"],
        source_ref: str,
        *,
        page: ParsedPage | None = None,
        block_id: str | None = None,
        table_id: str | None = None,
        cell_id: str | None = None,
    ) -> None:
        if len(self.diagnostics) >= MAX_ARTIFACT_DIAGNOSTICS:
            raise AdapterError("STRUCTURE_INVALID")
        self.diagnostics.append(
            ParseDiagnostic(
                code=code,
                severity="WARNING",
                source_ref=source_ref,
                page_id=None if page is None else page.id,
                block_id=block_id,
                table_id=table_id,
                cell_id=cell_id,
                detail=None,
            )
        )

    def append_block(self, block: ParsedBlock) -> None:
        if len(self.blocks) >= MAX_ARTIFACT_BLOCKS:
            raise AdapterError("STRUCTURE_INVALID")
        self.blocks.append(block)
        for reason in block.unavailable_reasons:
            self.diagnostic(reason, block.source_ref, block_id=block.id)

    def low_level_cell(self, page: ParsedPage, value: object, position: int) -> None:
        cell = _mapping(value)
        ref = f"page/{page.page_index}/text-cell/{position}"
        block_id = _opaque_id(self.parse_id, ref)
        orig, text = _optional_text(cell.get("orig")), _text(cell.get("text"))
        from_ocr = _boolean(cell.get("from_ocr"))
        raw = _reported_rectangle(cell.get("rect"))
        box = None
        if raw is not None:
            try:
                box = _canonical_points(_rectangle_points(raw), raw.coord_origin, page, self.frame)
            except GeometryError:
                pass
        boxes = None if box is None else (box,)
        reasons = _reasons(page, boxes, orig)
        exact = (
            ()
            if not orig
            else (
                TextSpan(
                    block_id=block_id,
                    start=0,
                    end=len(orig),
                    quote=orig,
                ),
            )
        )
        if not exact:
            reasons.append("TEXT_SPAN_UNAVAILABLE")
        score = None
        if from_ocr:
            candidate = cell.get("confidence")
            if (
                not isinstance(candidate, bool)
                and isinstance(candidate, (float, int))
                and math.isfinite(candidate)
                and 0 <= candidate <= 1
            ):
                score = float(candidate)
            else:
                self.diagnostic("OCR_SCORE_UNAVAILABLE", ref, page=page, block_id=block_id)
        index = cell.get("index")
        source_index = None if index == -1 else _integer(index)
        self.append_block(
            ParsedBlock(
                id=block_id,
                page_id=page.id,
                page_index=page.page_index,
                source_ref=ref,
                source_cell_index=source_index,
                orig=orig,
                text=text,
                from_ocr=from_ocr,
                ocr_score=score,
                boxes=boxes,
                exact_spans=exact,
                unavailable_reasons=tuple(reasons),
                provenance=(
                    BlockProvenance(
                        source_ref=ref,
                        page_no=page.page_index + 1,
                        text=text,
                        charspan=None,
                        raw_box=None,
                        raw_rectangle=raw,
                    ),
                ),
            )
        )

    def document_text(self, value: object, position: int) -> None:
        item = _mapping(value)
        base_ref = f"#/texts/{position}"
        # Positional references cannot be replaced with document-supplied identity strings.
        if item.get("self_ref") != base_ref:
            raise AdapterError("STRUCTURE_INVALID")
        orig, text = _optional_text(item.get("orig")), _text(item.get("text"))
        entries = tuple(
            _entry(value, f"{base_ref}/prov/{index}", text)
            for index, value in enumerate(_items(item.get("prov"), 1_000))
        )
        page_numbers = {entry.page_no for entry in entries}
        # A reported span must index both original and processed strings unchanged.
        supports = all(
            entry.charspan is not None
            and entry.reported_span_valid
            and orig is not None
            and 0 <= entry.charspan.start < entry.charspan.end <= len(orig)
            and orig[entry.charspan.start : entry.charspan.end]
            == text[entry.charspan.start : entry.charspan.end]
            for entry in entries
        )
        if len(page_numbers) > 1 and supports:
            for index, entry in enumerate(entries):
                assert entry.charspan is not None and orig is not None
                start, end = entry.charspan.start, entry.charspan.end
                self.document_block(
                    f"{base_ref}/prov/{index}",
                    orig[start:end],
                    text[start:end],
                    (entry,),
                    offsets_local=True,
                )
        else:
            self.document_block(base_ref, orig, text, entries, offsets_local=False)

    def document_block(
        self,
        ref: str,
        orig: str | None,
        text: str,
        entries: tuple[BlockProvenance, ...],
        *,
        offsets_local: bool,
    ) -> None:
        block_id = _opaque_id(self.parse_id, ref)
        page_numbers = {entry.page_no for entry in entries}
        number = next(iter(page_numbers)) if len(page_numbers) == 1 else None
        page = self.pages.get(number) if number is not None else None
        located = tuple(
            box
            for entry in entries
            if (box := _canonical_box(entry.raw_box, page, self.frame)) is not None
        )
        # Do not quietly discard a missing region from otherwise present provenance.
        boxes = located if located and len(located) == len(entries) else None
        reasons = _reasons(page, boxes, orig)
        exact: list[TextSpan] = []
        # SDK assembly may clamp boxes before export. They remain preview data,
        # rather than independently exact source geometry, even when bounds fit.
        reasons.append("RAW_GEOMETRY_UNAVAILABLE")
        invalid = False
        for entry in entries:
            span = entry.charspan
            if offsets_local:
                assert orig is not None
                exact.append(TextSpan(block_id=block_id, start=0, end=len(orig), quote=orig))
            elif (
                span is not None
                and entry.reported_span_valid
                and orig is not None
                and 0 <= span.start < span.end <= len(orig)
                and orig[span.start : span.end] == text[span.start : span.end]
            ):
                candidate = TextSpan(
                    block_id=block_id,
                    start=span.start,
                    end=span.end,
                    quote=orig[span.start : span.end],
                )
                if candidate not in exact:
                    exact.append(candidate)
            else:
                invalid = True
        if invalid:
            reasons.append("PROVENANCE_SPAN_INVALID")
            # Incomplete assembly support is not repaired by a full-block replacement span.
            exact = []
        if page is None:
            exact = []
        if not exact:
            reasons.append("TEXT_SPAN_UNAVAILABLE")
        self.append_block(
            ParsedBlock(
                id=block_id,
                page_id=None if page is None else page.id,
                page_index=None if page is None else page.page_index,
                source_ref=ref,
                source_cell_index=None,
                orig=orig,
                text=text,
                from_ocr=None,
                ocr_score=None,
                boxes=boxes,
                provenance=entries,
                exact_spans=tuple(exact),
                unavailable_reasons=tuple(reasons),
            )
        )

    def document_table(self, value: object, position: int) -> None:
        raw = _mapping(value)
        ref = f"#/tables/{position}"
        if raw.get("self_ref") != ref:
            raise AdapterError("STRUCTURE_INVALID")
        table_id = _opaque_id(self.parse_id, ref)
        entries = tuple(
            _entry(value, f"{ref}/prov/{index}", None)
            for index, value in enumerate(_items(raw.get("prov"), 1_000))
        )
        grouped: dict[int, list[PdfRectangle]] = {}
        for entry in entries:
            page = self.pages.get(entry.page_no) if entry.page_no is not None else None
            box = _canonical_box(entry.raw_box, page, self.frame)
            if page is not None and box is not None:
                grouped.setdefault(page.page_index + 1, []).append(box)
        regions = tuple(
            TablePageRegion(
                page_id=self.pages[number].id, page_index=number - 1, boxes=tuple(boxes)
            )
            for number, boxes in sorted(grouped.items())
        )
        numbers = {entry.page_no for entry in entries}
        number = next(iter(numbers)) if len(numbers) == 1 else None
        page = self.pages.get(number) if number is not None else None
        data = _mapping(raw.get("data"))
        rows, columns = (
            _integer(data.get("num_rows"), minimum=1),
            _integer(data.get("num_cols"), minimum=1),
        )
        cells: list[ParsedCell] = []
        for index, value in enumerate(_items(data.get("table_cells"), MAX_ARTIFACT_CELLS)):
            self.cell_count += 1
            if self.cell_count > MAX_ARTIFACT_CELLS:
                raise AdapterError("STRUCTURE_INVALID")
            cell = _mapping(value)
            cell_ref = f"{ref}/data/table_cells/{index}"
            cell_id = _opaque_id(self.parse_id, cell_ref)
            row, column = (
                _integer(cell.get("start_row_offset_idx")),
                _integer(cell.get("start_col_offset_idx")),
            )
            row_span, column_span = (
                _integer(cell.get("row_span"), minimum=1),
                _integer(cell.get("col_span"), minimum=1),
            )
            if (
                _integer(cell.get("end_row_offset_idx"), minimum=1) != row + row_span
                or _integer(cell.get("end_col_offset_idx"), minimum=1) != column + column_span
            ):
                raise AdapterError("STRUCTURE_INVALID")
            raw_box = _reported_box(cell.get("bbox"))
            box = _canonical_box(raw_box, page, self.frame)
            boxes = None if box is None else (box,)
            # TableCell exposes processed text only; never manufacture an original field.
            orig, text = None, _text(cell.get("text"))
            reasons = _reasons(page, boxes, orig)
            if page is None:
                reasons.append("TABLE_CELL_MAPPING_UNAVAILABLE")
            result = ParsedCell(
                id=cell_id,
                table_id=table_id,
                source_ref=cell_ref,
                row_index=row,
                column_index=column,
                row_span=row_span,
                column_span=column_span,
                column_header=_boolean(cell.get("column_header")),
                row_header=_boolean(cell.get("row_header")),
                row_section=_boolean(cell.get("row_section")),
                orig=orig,
                text=text,
                from_ocr=None,
                ocr_score=None,
                page_id=None if page is None else page.id,
                page_index=None if page is None else page.page_index,
                boxes=boxes,
                provenance=(
                    BlockProvenance(
                        source_ref=cell_ref,
                        page_no=number,
                        text=text,
                        charspan=None,
                        raw_box=raw_box,
                    ),
                ),
                unavailable_reasons=tuple(reasons),
            )
            cells.append(result)
            for reason in reasons:
                self.diagnostic(reason, cell_ref, table_id=table_id, cell_id=cell_id)
        table_reasons: list[EvidenceUnavailableReason] = []
        if not entries or any(entry.page_no not in self.pages for entry in entries):
            table_reasons.append("PAGE_MAPPING_UNAVAILABLE")
        if not entries or sum(len(region.boxes) for region in regions) != len(entries):
            table_reasons.append("GEOMETRY_UNAVAILABLE")
        self.tables.append(
            ParsedTable(
                id=table_id,
                source_ref=ref,
                row_count=rows,
                column_count=columns,
                page_regions=regions,
                provenance=entries,
                cells=tuple(cells),
                unavailable_reasons=tuple(table_reasons),
            )
        )
        for reason in table_reasons:
            self.diagnostic(reason, ref, table_id=table_id)


def build_artifact(
    captured: object,
    *,
    source: Path,
    source_sha256: str,
    parse_id: str,
    filing_id: str,
    filing_version_id: str,
    source_blob_id: str,
    coordinate_frame: CoordinateFrame,
) -> ParseArtifact:
    """Build a deterministic draft artifact from complete, source-matched SDK output."""
    try:
        for value in (parse_id, filing_id, filing_version_id, source_blob_id):
            TypeAdapter(CanonicalId).validate_python(value)
        TypeAdapter(Sha256Hash).validate_python(source_sha256)
        if not isinstance(coordinate_frame, CoordinateFrame):
            raise AdapterError("SOURCE_GEOMETRY_INVALID")
        if (
            not source.is_absolute()
            or not source.is_file()
            or source.is_symlink()
            or source.stat().st_size > 64 * 1024 * 1024
        ):
            raise AdapterError("SOURCE_MISMATCH")
        with source.open("rb") as handle:
            source_bytes = handle.read(64 * 1024 * 1024 + 1)
        if len(source_bytes) > 64 * 1024 * 1024:
            raise AdapterError("SOURCE_MISMATCH")
        capture = _mapping(captured)
        if (
            capture.get("source_sha256") != source_sha256
            or hashlib.sha256(source_bytes).hexdigest() != source_sha256
        ):
            raise AdapterError("SOURCE_MISMATCH")
        if capture.get("status") != "success" or _items(capture.get("errors"), 10_000):
            raise AdapterError("PARSE_NOT_COMPLETE")
        provenance = _provenance(capture.get("configuration"), coordinate_frame)
        reader = PdfReader(BytesIO(source_bytes), strict=False)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= MAX_ARTIFACT_PAGES:
            raise AdapterError("PAGE_COVERAGE_INVALID")
        pages = tuple(
            ParsedPage(
                id=_opaque_id(parse_id, f"page/{index}"),
                page_index=index,
                geometry=geometry_from_pdf_page(page),
            )
            for index, page in enumerate(reader.pages)
        )
        raw_pages = tuple(
            _mapping(page) for page in _items(capture.get("pages"), MAX_ARTIFACT_PAGES)
        )
        if any(type(page.get("page_no")) is not int for page in raw_pages) or tuple(
            page.get("page_no") for page in raw_pages
        ) != tuple(range(1, len(pages) + 1)):
            raise AdapterError("PAGE_COVERAGE_INVALID")
        document = _mapping(capture.get("document"))
        document_pages = _mapping(document.get("pages"))
        if set(document_pages) != {str(index + 1) for index in range(len(pages))}:
            raise AdapterError("PAGE_COVERAGE_INVALID")
        if any(
            type(_mapping(value).get("page_no")) is not int
            or _mapping(value).get("page_no") != int(key)
            for key, value in document_pages.items()
        ):
            raise AdapterError("PAGE_COVERAGE_INVALID")
        builder = _Builder(parse_id, pages, coordinate_frame)
        for page, raw in zip(pages, raw_pages, strict=True):
            cells = _items(raw.get("cells"), MAX_ARTIFACT_BLOCKS)
            if not cells:
                builder.diagnostic("PAGE_TEXT_UNAVAILABLE", f"page/{page.page_index}", page=page)
            for index, cell in enumerate(cells):
                builder.low_level_cell(page, cell, index)
        for index, item in enumerate(_items(document.get("texts"), MAX_ARTIFACT_BLOCKS)):
            builder.document_text(item, index)
        for index, table in enumerate(_items(document.get("tables"), MAX_ARTIFACT_TABLES)):
            builder.document_table(table, index)
        return ParseArtifact(
            schema_version=PARSE_ARTIFACT_VERSION,
            id=parse_id,
            filing_id=filing_id,
            filing_version_id=filing_version_id,
            source_blob_id=source_blob_id,
            source_sha256=source_sha256,
            provenance=provenance,
            pages=pages,
            blocks=tuple(builder.blocks),
            tables=tuple(builder.tables),
            diagnostics=tuple(builder.diagnostics),
        )
    except AdapterError:
        raise
    except GeometryError:
        raise AdapterError("SOURCE_GEOMETRY_INVALID") from None
    except (ValidationError, TypeError, ValueError, OSError, PyPdfError, KeyError, OverflowError):
        raise AdapterError("STRUCTURE_INVALID") from None
