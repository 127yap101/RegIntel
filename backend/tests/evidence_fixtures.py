"""Authored storage fixtures; they are not parser/effectiveness measurements."""

import hashlib
from uuid import uuid4

from regintel.contracts.models import PageGeometry, PdfRectangle, TextSpan
from regintel.ingestion.models import SourceBlob
from regintel.parsing.configuration import (
    ParserRuntimeConfiguration,
    SelectedCoordinateFrame,
    current_runtime_code_hashes,
)
from regintel.parsing.models import (
    BlockProvenance,
    PackageVersion,
    ParseArtifact,
    ParsedBlock,
    ParsedCell,
    ParsedPage,
    ParsedTable,
    ParseProvenance,
    ReportedBox,
    ReportedRectangle,
    package_manifest_sha256,
)


def synthetic_configuration(
    *, frame: SelectedCoordinateFrame = "RAW_PDF_BOTTOM_LEFT"
) -> ParserRuntimeConfiguration:
    packages = (PackageVersion(name="docling-parse", version="7.22.1"),)
    return ParserRuntimeConfiguration.model_validate(
        current_runtime_code_hashes().model_dump(mode="python")
        | {
            "coordinate_frame": frame,
            "sdk_configuration_sha256": hashlib.sha256(b"synthetic SDK options").hexdigest(),
            "model_manifest_sha256": hashlib.sha256(b"synthetic model manifest").hexdigest(),
            "package_manifest_sha256": package_manifest_sha256(packages),
            "backend_code_sha256": hashlib.sha256(b"synthetic backend").hexdigest(),
        }
    )


def synthetic_artifact(
    *,
    configuration: ParserRuntimeConfiguration | None = None,
    parse_id: str | None = None,
    filing_id: str | None = None,
    filing_version_id: str | None = None,
    blob: SourceBlob | None = None,
    original: str = "Lead 😀 e\u0301\nExact source quote.",
) -> ParseArtifact:
    configuration = configuration or synthetic_configuration()
    packages = (PackageVersion(name="docling-parse", version="7.22.1"),)
    page_id, block_id, assembly_id, table_id, cell_id = (str(uuid4()) for _ in range(5))
    geometry = PageGeometry(
        width=612.0,
        height=792.0,
        media_box=PdfRectangle(x0=0.0, y0=0.0, x1=612.0, y1=792.0),
        crop_box=PdfRectangle(x0=0.0, y0=0.0, x1=612.0, y1=792.0),
        rotation=0,
        coordinate_space="UNROTATED_PDF_POINTS",
        origin="BOTTOM_LEFT",
    )
    box = PdfRectangle(x0=40.0, y0=40.0, x1=200.0, y1=60.0)
    top_left = configuration.coordinate_frame == "CROP_ROTATED_TOP_LEFT"
    y0, y1 = (752.0, 732.0) if top_left else (40.0, 60.0)
    raw = ReportedRectangle(
        r_x0=40.0,
        r_y0=y0,
        r_x1=200.0,
        r_y1=y0,
        r_x2=200.0,
        r_y2=y1,
        r_x3=40.0,
        r_y3=y1,
        coord_origin="TOPLEFT" if top_left else "BOTTOMLEFT",
        coordinate_frame="DOCLING_PAGE",
    )
    processed = original.replace("Exact", "Processed")
    block = ParsedBlock(
        id=block_id,
        page_id=page_id,
        page_index=0,
        source_ref="page/0/text-cell/0",
        source_cell_index=0,
        orig=original,
        text=processed,
        from_ocr=False,
        ocr_score=None,
        boxes=(box,),
        provenance=(
            BlockProvenance(
                source_ref="page/0/text-cell/0",
                page_no=1,
                text=processed,
                charspan=None,
                raw_box=None,
                raw_rectangle=raw,
            ),
        ),
        exact_spans=(TextSpan(block_id=block_id, start=0, end=len(original), quote=original),),
        unavailable_reasons=(),
    )
    preview = "Assembly preview only"
    assembled = ParsedBlock(
        id=assembly_id,
        page_id=page_id,
        page_index=0,
        source_ref="#/texts/0",
        source_cell_index=None,
        orig=preview,
        text=preview,
        from_ocr=None,
        ocr_score=None,
        boxes=(box,),
        provenance=(
            BlockProvenance(
                source_ref="#/texts/0",
                page_no=1,
                text=preview,
                charspan=None,
                raw_box=ReportedBox(
                    left=40.0,
                    top=60.0,
                    right=200.0,
                    bottom=40.0,
                    coord_origin="BOTTOMLEFT",
                    coordinate_frame="DOCLING_PAGE",
                ),
            ),
        ),
        exact_spans=(TextSpan(block_id=assembly_id, start=0, end=len(preview), quote=preview),),
        unavailable_reasons=("RAW_GEOMETRY_UNAVAILABLE",),
    )
    table = ParsedTable(
        id=table_id,
        source_ref="#/tables/0",
        row_count=1,
        column_count=1,
        page_regions=(),
        provenance=(
            BlockProvenance(
                source_ref="#/tables/0",
                page_no=1,
                text=None,
                charspan=None,
                raw_box=None,
            ),
        ),
        unavailable_reasons=("GEOMETRY_UNAVAILABLE",),
        cells=(
            ParsedCell(
                id=cell_id,
                table_id=table_id,
                source_ref="#/tables/0/cells/0",
                row_index=0,
                column_index=0,
                row_span=1,
                column_span=1,
                column_header=True,
                row_header=False,
                row_section=False,
                orig=None,
                text="Processed table header",
                from_ocr=None,
                ocr_score=None,
                page_id=page_id,
                page_index=0,
                boxes=None,
                provenance=(),
                unavailable_reasons=("ORIGINAL_TEXT_UNAVAILABLE", "GEOMETRY_UNAVAILABLE"),
            ),
        ),
    )
    return ParseArtifact(
        schema_version="1.0.0",
        id=parse_id or str(uuid4()),
        filing_id=filing_id or str(uuid4()),
        filing_version_id=filing_version_id or str(uuid4()),
        source_blob_id=blob.id if blob is not None else str(uuid4()),
        source_sha256=blob.sha256
        if blob is not None
        else hashlib.sha256(b"synthetic PDF").hexdigest(),
        provenance=ParseProvenance(
            adapter_name=configuration.adapter_name,
            adapter_version=configuration.adapter_version,
            adapter_code_sha256=configuration.adapter_code_sha256,
            backend_name="ThreadedDoclingParseDocumentBackend",
            backend_version="7.22.1",
            backend_code_sha256=configuration.backend_code_sha256,
            coordinate_frame=configuration.coordinate_frame,
            packages=packages,
            package_manifest_sha256=package_manifest_sha256(packages),
            configuration_sha256=configuration.sdk_configuration_sha256,
            model_manifest_sha256=configuration.model_manifest_sha256,
        ),
        pages=(ParsedPage(id=page_id, page_index=0, geometry=geometry),),
        blocks=(block, assembled),
        tables=(table,),
        diagnostics=(),
    )
