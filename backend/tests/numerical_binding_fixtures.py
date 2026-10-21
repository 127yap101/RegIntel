"""Authored complete-artifact fixtures; blank PDFs do not prove transcription accuracy."""

from dataclasses import dataclass
from uuid import uuid4

from backend.tests.evidence_fixtures import synthetic_artifact, synthetic_configuration
from regintel.contracts.models import PdfRectangle, TextSpan
from regintel.numerical.context_records import NumericalContextRecord
from regintel.parsing.configuration import ParserRuntimeConfiguration
from regintel.parsing.models import (
    BlockProvenance,
    ParseArtifact,
    ParsedBlock,
    ParsedCell,
    ParsedPage,
    ParsedTable,
    ReportedBox,
    TablePageRegion,
)


@dataclass(frozen=True)
class BindingFixture:
    record: NumericalContextRecord
    artifact: ParseArtifact
    configuration: ParserRuntimeConfiguration


def complete_artifact(
    record: NumericalContextRecord, *, filing_id: str | None = None
) -> BindingFixture:
    """The authored two-page source has native-word declarations only on its second page."""
    capture = record.source_input.pages[0].capture
    configuration = synthetic_configuration(frame="CROP_ROTATED_TOP_LEFT").model_copy(
        update={"sdk_configuration_sha256": capture.sdk_configuration_sha256}
    )
    template = synthetic_artifact(configuration=configuration)
    pages = tuple(
        ParsedPage(id=str(uuid4()), page_index=index, geometry=capture.page_geometry)
        for index in range(capture.source_page_count)
    )
    page = pages[capture.page_index]
    blocks = []
    for word in capture.words:
        assert word.orig is not None and word.box is not None and word.raw_rectangle is not None
        identity = str(uuid4())
        source_ref = f"page/{capture.page_index}/text-cell/{word.word_index}"
        blocks.append(
            ParsedBlock(
                id=identity,
                page_id=page.id,
                page_index=page.page_index,
                source_ref=source_ref,
                source_cell_index=word.word_index,
                orig=word.orig,
                text=word.orig,
                from_ocr=False,
                ocr_score=None,
                boxes=(word.box,),
                provenance=(
                    BlockProvenance(
                        source_ref=source_ref,
                        page_no=page.page_index + 1,
                        text=word.orig,
                        charspan=None,
                        raw_box=None,
                        raw_rectangle=word.raw_rectangle,
                    ),
                ),
                exact_spans=(
                    TextSpan(block_id=identity, start=0, end=len(word.orig), quote=word.orig),
                ),
                unavailable_reasons=(),
            )
        )
    table_id = str(uuid4())
    cells = []
    for preview in capture.cells:
        assert preview.raw_box is not None and preview.box is not None
        source_ref = f"#/tables/0/cells/{preview.cell_index}"
        cells.append(
            ParsedCell(
                id=str(uuid4()),
                table_id=table_id,
                source_ref=source_ref,
                row_index=preview.row_index,
                column_index=preview.column_index,
                row_span=preview.row_span,
                column_span=preview.column_span,
                column_header=preview.column_header,
                row_header=preview.row_header,
                row_section=False,
                orig=None,
                text=preview.text,
                from_ocr=None,
                ocr_score=None,
                page_id=page.id,
                page_index=page.page_index,
                boxes=(preview.box,),
                provenance=(
                    BlockProvenance(
                        source_ref=source_ref,
                        page_no=page.page_index + 1,
                        text=preview.text,
                        charspan=None,
                        raw_box=preview.raw_box,
                    ),
                ),
                unavailable_reasons=("ORIGINAL_TEXT_UNAVAILABLE",),
            )
        )
    boxes = [cell.boxes[0] for cell in cells if cell.boxes]
    box = PdfRectangle(
        x0=min(b.x0 for b in boxes),
        y0=min(b.y0 for b in boxes),
        x1=max(b.x1 for b in boxes),
        y1=max(b.y1 for b in boxes),
    )
    table = ParsedTable(
        id=table_id,
        source_ref="#/tables/0",
        row_count=capture.cells[0].table_rows,
        column_count=capture.cells[0].table_columns,
        page_regions=(TablePageRegion(page_id=page.id, page_index=page.page_index, boxes=(box,)),),
        provenance=(
            BlockProvenance(
                source_ref="#/tables/0",
                page_no=page.page_index + 1,
                text=None,
                charspan=None,
                raw_box=ReportedBox(
                    left=box.x0,
                    right=box.x1,
                    top=capture.page_geometry.height - box.y1,
                    bottom=capture.page_geometry.height - box.y0,
                    coord_origin="TOPLEFT",
                    coordinate_frame="DOCLING_PAGE",
                ),
            ),
        ),
        cells=tuple(cells),
        unavailable_reasons=(),
    )
    artifact = ParseArtifact.model_validate(
        template.model_dump(mode="python")
        | {
            "filing_id": filing_id or str(uuid4()),
            "filing_version_id": record.filing_version_id,
            "source_blob_id": record.source_blob_id,
            "source_sha256": record.source_sha256,
            "pages": pages,
            "blocks": tuple(blocks),
            "tables": (table,),
            "diagnostics": (),
        }
    )
    return BindingFixture(record, artifact, configuration)
