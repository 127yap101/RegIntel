"""Identify table/transcription risks without creating source evidence.

The sealed artifact's retained table provenance is used only to withhold automatic
interpretation of overlapping original text. Missing or unrepresentable geometry
widens the risk region conservatively; it never supplies an exact cell/header.
"""

from regintel.contracts.models import PdfRectangle, TextEvidence
from regintel.evidence.projection import _eligible, _evidence_id
from regintel.parsing.adapter import _canonical_box
from regintel.parsing.geometry import CoordinateFrame
from regintel.parsing.models import ParseArtifact, ParsedTable


def _table_scope(
    artifact: ParseArtifact, table: ParsedTable, frame: CoordinateFrame
) -> tuple[set[str], dict[str, tuple[PdfRectangle, ...]]]:
    pages = {page.page_index + 1: page for page in artifact.pages}
    whole_pages: set[str] = set()
    mapped: dict[str, list[PdfRectangle]] = {}
    regions = {region.page_id: region.boxes for region in table.page_regions}
    if not table.provenance:
        # The table may belong anywhere in this artifact; preview cells cannot
        # repair its absent provenance.
        whole_pages.update(page.id for page in artifact.pages)
    for entry in table.provenance:
        page = pages.get(entry.page_no) if entry.page_no is not None else None
        if page is None:
            whole_pages.update(item.id for item in artifact.pages)
            continue
        box = _canonical_box(entry.raw_box, page, frame)
        if box is None:
            whole_pages.add(page.id)
        else:
            mapped.setdefault(page.id, []).append(box)
    for page_id, boxes in mapped.items():
        if tuple(boxes) != regions.get(page_id):
            # Neither a mismatched processed region nor a guessed replacement
            # has a trustworthy boundary for excluding nearby original text.
            whole_pages.add(page_id)
    for region in table.page_regions:
        if region.page_id not in mapped:
            whole_pages.add(region.page_id)
    known_pages = {
        pages[entry.page_no].id
        for entry in table.provenance
        if entry.page_no is not None and entry.page_no in pages
    }
    known_pages.update(region.page_id for region in table.page_regions)
    for cell in table.cells:
        if cell.page_id is not None and cell.page_id not in known_pages:
            # A retained cell on an additional page signals table scope only,
            # never exact cell support or a reconstructed table rectangle.
            whole_pages.add(cell.page_id)
    if {
        "GEOMETRY_UNAVAILABLE",
        "RAW_GEOMETRY_UNAVAILABLE",
        "UNSUPPORTED_GEOMETRY_FRAME",
        "PAGE_MAPPING_UNAVAILABLE",
    }.intersection(table.unavailable_reasons):
        whole_pages.update(known_pages)
    return whole_pages, {page_id: tuple(boxes) for page_id, boxes in mapped.items()}


def _overlaps(left: PdfRectangle, right: PdfRectangle) -> bool:
    # Strictly positive intersection, without multiplying potentially large
    # coordinates. Boundary contact has no shared area.
    return min(left.x1, right.x1) > max(left.x0, right.x0) and min(left.y1, right.y1) > max(
        left.y0, right.y0
    )


def _source_records(
    artifact: ParseArtifact,
    evidence: tuple[TextEvidence, ...],
) -> tuple[ParseArtifact, tuple[TextEvidence, ...]]:
    artifact = ParseArtifact.model_validate(artifact.model_dump(mode="python"))
    records = tuple(
        TextEvidence.model_validate(record.model_dump(mode="python")) for record in evidence
    )
    if len({record.id for record in records}) != len(records):
        raise ValueError("Table scope requires distinct original-text evidence IDs.")
    frame = CoordinateFrame(artifact.provenance.coordinate_frame)
    pages = {page.id: page for page in artifact.pages}
    blocks = {block.id: block for block in artifact.blocks}
    for record in records:
        source, span = record.source, record.span
        page, block = pages.get(source.page_id), blocks.get(span.block_id)
        if (
            source.parse_version_id != artifact.id
            or source.filing_id != artifact.filing_id
            or source.filing_version_id != artifact.filing_version_id
            or page is None
            or page.page_index != source.page_index
            or record.page_geometry != page.geometry
            or block is None
            or block.page_id != page.id
            or block.page_index != page.page_index
            or span not in block.exact_spans
            or record.boxes != block.boxes
            or record.id
            != _evidence_id(artifact.id, span.block_id, span.start, span.end, span.quote)
            or not _eligible(block, page, frame)
        ):
            raise ValueError("Table scope requires exact original evidence from one sealed parse.")
    return artifact, records


def table_evidence_ids(
    artifact: ParseArtifact, evidence: tuple[TextEvidence, ...]
) -> tuple[str, ...]:
    """Return sorted original-text IDs whose table context needs review.

    Callers must load the sealed artifact, not a client-provided preview. Source
    identity/page/span/geometry are rechecked even for model-copy instances.
    No table/cell evidence or quantitative interpretation is created here.
    """
    artifact, records = _source_records(artifact, evidence)
    frame = CoordinateFrame(artifact.provenance.coordinate_frame)
    whole_pages: set[str] = set()
    table_boxes: dict[str, list[PdfRectangle]] = {}
    for table in artifact.tables:
        unavailable, mapped = _table_scope(artifact, table, frame)
        whole_pages.update(unavailable)
        for page_id, boxes in mapped.items():
            table_boxes.setdefault(page_id, []).extend(boxes)
    return tuple(
        sorted(
            record.id
            for record in records
            if record.source.page_id in whole_pages
            or any(
                _overlaps(source_box, table_box)
                for source_box in record.boxes
                for table_box in table_boxes.get(record.source.page_id, ())
            )
        )
    )


def transcription_evidence_ids(
    artifact: ParseArtifact, evidence: tuple[TextEvidence, ...]
) -> tuple[str, ...]:
    """Withhold approval of OCR/unknown-origin text without inventing a score.

    A well-formed OCR number can still be a transcription error. This stage has
    no original-image review/attestation capability, so geometry and Decimal
    syntax alone cannot upgrade its transcription to validated financial support.
    """
    artifact, records = _source_records(artifact, evidence)
    blocks = {block.id: block for block in artifact.blocks}
    return tuple(
        sorted(
            record.id for record in records if blocks[record.span.block_id].from_ocr is not False
        )
    )
