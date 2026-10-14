"""Synthetic table-risk classification tests; processed cells remain non-evidence."""

from collections.abc import Callable

import pytest

from backend.tests.evidence_fixtures import synthetic_artifact, synthetic_configuration
from regintel.contracts.models import PageGeometry, PdfRectangle, TextEvidence, TextSpan
from regintel.evidence.projection import project_parse
from regintel.fixtures.sources import fixture_id
from regintel.parsing.configuration import ParserRuntimeConfiguration, SelectedCoordinateFrame
from regintel.parsing.geometry import CoordinateFrame, from_pdf_box
from regintel.parsing.models import (
    BlockProvenance,
    ParseArtifact,
    ParsedPage,
    ReportedBox,
    ReportedRectangle,
    TablePageRegion,
)
from regintel.validation.scope import table_evidence_ids, transcription_evidence_ids


def rectangle(x0: float, y0: float, x1: float, y1: float) -> PdfRectangle:
    return PdfRectangle(x0=x0, y0=y0, x1=x1, y1=y1)


def source(
    *, frame: SelectedCoordinateFrame = "RAW_PDF_BOTTOM_LEFT", pages: int = 1
) -> tuple[ParserRuntimeConfiguration, ParseArtifact, tuple[TextEvidence, ...]]:
    configuration = synthetic_configuration(frame=frame)
    artifact = synthetic_artifact(configuration=configuration)
    if pages == 2:
        page = ParsedPage(id=fixture_id(880001), page_index=1, geometry=artifact.pages[0].geometry)
        block = artifact.blocks[0]
        original = block.orig
        assert original is not None
        second = block.model_copy(
            update={
                "id": fixture_id(880002),
                "page_id": page.id,
                "page_index": 1,
                "source_ref": "page/1/text-cell/0",
                "provenance": (
                    block.provenance[0].model_copy(
                        update={"source_ref": "page/1/text-cell/0", "page_no": 2}
                    ),
                ),
                "exact_spans": (
                    TextSpan(
                        block_id=fixture_id(880002),
                        start=0,
                        end=len(original),
                        quote=original,
                    ),
                ),
            }
        )
        artifact = ParseArtifact.model_validate(
            artifact.model_dump(mode="python")
            | {"pages": (*artifact.pages, page), "blocks": (*artifact.blocks, second)}
        )
    return configuration, artifact, project_parse(artifact, configuration).evidence


def located_table(
    artifact: ParseArtifact, box: PdfRectangle, *, page_index: int = 0
) -> ParseArtifact:
    page = artifact.pages[page_index]
    frame = CoordinateFrame(artifact.provenance.coordinate_frame)
    raw = from_pdf_box(box, page.geometry, frame=frame)
    top_left = frame is CoordinateFrame.CROP_ROTATED_TOP_LEFT
    provenance = BlockProvenance(
        source_ref="#/tables/0/prov/0",
        page_no=page_index + 1,
        text=None,
        charspan=None,
        raw_box=ReportedBox(
            left=raw.x0,
            top=raw.y0 if top_left else raw.y1,
            right=raw.x1,
            bottom=raw.y1 if top_left else raw.y0,
            coord_origin="TOPLEFT" if top_left else "BOTTOMLEFT",
            coordinate_frame="DOCLING_PAGE",
        ),
    )
    table = artifact.tables[0].model_copy(
        update={
            "provenance": (provenance,),
            "page_regions": (
                TablePageRegion(page_id=page.id, page_index=page_index, boxes=(box,)),
            ),
            "unavailable_reasons": (),
            "cells": (),
        }
    )
    return ParseArtifact.model_validate(artifact.model_dump(mode="python") | {"tables": (table,)})


@pytest.mark.parametrize(
    "frame",
    [
        "RAW_PDF_BOTTOM_LEFT",
        "MEDIA_RELATIVE_BOTTOM_LEFT",
        "CROP_ROTATED_BOTTOM_LEFT",
        "CROP_ROTATED_TOP_LEFT",
    ],
)
def test_retained_explicit_table_frame_identifies_overlapping_original_text(
    frame: SelectedCoordinateFrame,
) -> None:
    _, artifact, evidence = source(frame=frame)
    artifact = located_table(artifact, rectangle(30.0, 35.0, 205.0, 70.0))
    assert table_evidence_ids(artifact, evidence) == (evidence[0].id,)
    assert evidence[0].kind == "text"
    assert not artifact.tables[0].cells


@pytest.mark.parametrize(
    "box",
    [
        rectangle(30.0, 80.0, 205.0, 100.0),
        rectangle(200.0, 40.0, 220.0, 60.0),
        rectangle(40.0, 60.0, 200.0, 80.0),
    ],
)
def test_separated_table_or_boundary_contact_has_no_positive_area(box: PdfRectangle) -> None:
    _, artifact, evidence = source()
    assert not table_evidence_ids(located_table(artifact, box), evidence)


def test_positive_area_intersection_is_detected_without_arbitrary_overlap_threshold() -> None:
    _, artifact, evidence = source()
    box = rectangle(199.999999, 40.0, 220.0, 60.0)
    assert table_evidence_ids(located_table(artifact, box), evidence) == (evidence[0].id,)


@pytest.mark.parametrize("rotation", [90, 180, 270])
@pytest.mark.parametrize("frame", ["CROP_ROTATED_BOTTOM_LEFT", "CROP_ROTATED_TOP_LEFT"])
def test_rotated_cropped_offset_pages_use_the_declared_frame_exactly_once(
    rotation: int, frame: SelectedCoordinateFrame
) -> None:
    configuration, artifact, _ = source(frame=frame)
    geometry = PageGeometry.model_validate(
        artifact.pages[0].geometry.model_dump(mode="python")
        | {
            "width": 600.0,
            "height": 800.0,
            "media_box": rectangle(-20.0, -10.0, 580.0, 790.0),
            "crop_box": rectangle(0.0, 0.0, 550.0, 750.0),
            "rotation": rotation,
        }
    )
    page = artifact.pages[0].model_copy(update={"geometry": geometry})
    block = artifact.blocks[0]
    assert block.boxes is not None
    raw = from_pdf_box(block.boxes[0], geometry, frame=CoordinateFrame(frame))
    top_left = frame == "CROP_ROTATED_TOP_LEFT"
    y0, y1 = (raw.y0, raw.y1) if top_left else (raw.y1, raw.y0)
    reported = ReportedRectangle(
        r_x0=raw.x0,
        r_y0=y0,
        r_x1=raw.x1,
        r_y1=y0,
        r_x2=raw.x1,
        r_y2=y1,
        r_x3=raw.x0,
        r_y3=y1,
        coord_origin="TOPLEFT" if top_left else "BOTTOMLEFT",
        coordinate_frame="DOCLING_PAGE",
    )
    block = block.model_copy(
        update={"provenance": (block.provenance[0].model_copy(update={"raw_rectangle": reported}),)}
    )
    artifact = ParseArtifact.model_validate(
        artifact.model_dump(mode="python")
        | {"pages": (page,), "blocks": (block, artifact.blocks[1])}
    )
    evidence = project_parse(artifact, configuration).evidence
    assert len(evidence) == 1
    overlap = located_table(artifact, rectangle(30.0, 35.0, 205.0, 70.0))
    separate = located_table(artifact, rectangle(30.0, 80.0, 205.0, 100.0))
    assert table_evidence_ids(overlap, evidence) == (evidence[0].id,)
    assert not table_evidence_ids(separate, evidence)


def test_missing_geometry_marks_whole_known_page_but_not_an_unrelated_page() -> None:
    _, artifact, evidence = source(pages=2)
    # The authored preview table has known page 1 but no retained raw geometry.
    assert table_evidence_ids(artifact, evidence) == (evidence[0].id,)
    assert artifact.tables[0].cells[0].orig is None


@pytest.mark.parametrize("page_no", [None, 99])
def test_unmapped_table_page_conservatively_marks_all_supplied_source_pages(
    page_no: int | None,
) -> None:
    _, artifact, evidence = source(pages=2)
    table = artifact.tables[0].model_copy(
        update={
            "provenance": (
                artifact.tables[0].provenance[0].model_copy(update={"page_no": page_no}),
            ),
            "unavailable_reasons": ("GEOMETRY_UNAVAILABLE", "PAGE_MAPPING_UNAVAILABLE"),
        }
    )
    artifact = ParseArtifact.model_validate(
        artifact.model_dump(mode="python") | {"tables": (table,)}
    )
    assert table_evidence_ids(artifact, tuple(reversed(evidence))) == tuple(
        sorted(record.id for record in evidence)
    )


def test_absent_provenance_is_not_repaired_using_processed_cell_page() -> None:
    _, artifact, evidence = source(pages=2)
    table = artifact.tables[0].model_copy(
        update={
            "provenance": (),
            "unavailable_reasons": ("GEOMETRY_UNAVAILABLE", "PAGE_MAPPING_UNAVAILABLE"),
        }
    )
    artifact = ParseArtifact.model_validate(
        artifact.model_dump(mode="python") | {"tables": (table,)}
    )
    assert table_evidence_ids(artifact, evidence) == tuple(sorted(record.id for record in evidence))


@pytest.mark.parametrize("mutation", ["raw_missing", "raw_outside", "wrong_origin", "wrong_region"])
def test_unreliable_table_bounds_mark_whole_page_instead_of_using_a_guessed_region(
    mutation: str,
) -> None:
    _, artifact, evidence = source()
    artifact = located_table(artifact, rectangle(30.0, 80.0, 205.0, 100.0))
    table = artifact.tables[0]
    entry = table.provenance[0]
    raw_box = entry.raw_box
    assert raw_box is not None
    if mutation == "raw_missing":
        entry = entry.model_copy(update={"raw_box": None})
        table = table.model_copy(update={"unavailable_reasons": ("GEOMETRY_UNAVAILABLE",)})
    elif mutation == "raw_outside":
        entry = entry.model_copy(update={"raw_box": raw_box.model_copy(update={"right": 1000.0})})
    elif mutation == "wrong_origin":
        entry = entry.model_copy(
            update={
                "raw_box": raw_box.model_copy(
                    update={"coord_origin": "TOPLEFT", "top": 80.0, "bottom": 100.0}
                )
            }
        )
    else:
        table = table.model_copy(
            update={
                "page_regions": (
                    table.page_regions[0].model_copy(
                        update={"boxes": (rectangle(300.0, 100.0, 400.0, 200.0),)}
                    ),
                )
            }
        )
    table = table.model_copy(update={"provenance": (entry,)})
    artifact = ParseArtifact.model_validate(
        artifact.model_dump(mode="python") | {"tables": (table,)}
    )
    assert table_evidence_ids(artifact, evidence) == (evidence[0].id,)


@pytest.mark.parametrize(
    "reason",
    [
        "GEOMETRY_UNAVAILABLE",
        "RAW_GEOMETRY_UNAVAILABLE",
        "UNSUPPORTED_GEOMETRY_FRAME",
        "PAGE_MAPPING_UNAVAILABLE",
    ],
)
def test_explicit_unavailable_geometry_is_conservative_even_with_a_located_region(
    reason: str,
) -> None:
    _, artifact, evidence = source()
    artifact = located_table(artifact, rectangle(30.0, 80.0, 205.0, 100.0))
    table = artifact.tables[0].model_copy(update={"unavailable_reasons": (reason,)})
    artifact = ParseArtifact.model_validate(
        artifact.model_dump(mode="python") | {"tables": (table,)}
    )
    assert table_evidence_ids(artifact, evidence) == (evidence[0].id,)


def test_cell_on_additional_page_signals_scope_without_creating_exact_cell_evidence() -> None:
    _, artifact, evidence = source(pages=2)
    cell = (
        artifact.tables[0]
        .cells[0]
        .model_copy(update={"page_id": artifact.pages[1].id, "page_index": 1})
    )
    artifact = located_table(artifact, rectangle(30.0, 80.0, 205.0, 100.0))
    table = artifact.tables[0].model_copy(update={"cells": (cell,)})
    artifact = ParseArtifact.model_validate(
        artifact.model_dump(mode="python") | {"tables": (table,)}
    )
    assert table_evidence_ids(artifact, evidence) == (evidence[1].id,)
    assert cell.orig is None


def test_no_table_and_no_evidence_produce_no_risk_ids() -> None:
    _, artifact, evidence = source()
    artifact = ParseArtifact.model_validate(artifact.model_dump(mode="python") | {"tables": ()})
    assert table_evidence_ids(artifact, evidence) == ()
    assert table_evidence_ids(artifact, ()) == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"parse_version_id": fixture_id(881000)},
        {"filing_id": fixture_id(881001)},
        {"filing_version_id": fixture_id(881002)},
        {"page_id": fixture_id(881003)},
        {"page_index": 1},
    ],
)
def test_foreign_source_parse_filing_page_or_index_is_rejected(changes: dict[str, object]) -> None:
    _, artifact, evidence = source()
    record = evidence[0].model_copy(
        update={"source": evidence[0].source.model_copy(update=changes)}
    )
    with pytest.raises(ValueError, match="one sealed parse"):
        table_evidence_ids(artifact, (record,))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda record: record.model_copy(update={"id": fixture_id(881004)}),
        lambda record: record.model_copy(
            update={"span": record.span.model_copy(update={"block_id": fixture_id(881005)})}
        ),
        lambda record: record.model_copy(update={"boxes": (rectangle(40.0, 40.0, 201.0, 60.0),)}),
        lambda record: record.model_copy(
            update={"page_geometry": record.page_geometry.model_copy(update={"rotation": 90})}
        ),
        lambda record: record.model_copy(
            update={"span": record.span.model_copy(update={"quote": "X" + record.span.quote[1:]})}
        ),
    ],
)
def test_foreign_id_block_or_modified_exact_support_is_rejected(
    mutate: Callable[[TextEvidence], TextEvidence],
) -> None:
    _, artifact, evidence = source()
    with pytest.raises(ValueError, match="one sealed parse"):
        table_evidence_ids(artifact, (mutate(evidence[0]),))


def test_duplicate_evidence_is_rejected_instead_of_silently_deduplicated() -> None:
    _, artifact, evidence = source()
    with pytest.raises(ValueError, match="distinct"):
        table_evidence_ids(artifact, (evidence[0], evidence[0]))


def test_forged_preview_block_cannot_become_original_text_evidence() -> None:
    _, artifact, evidence = source()
    block = artifact.blocks[0].model_copy(update={"source_cell_index": None})
    artifact = ParseArtifact.model_validate(
        artifact.model_dump(mode="python") | {"blocks": (block, artifact.blocks[1])}
    )
    with pytest.raises(ValueError, match="one sealed parse"):
        table_evidence_ids(artifact, evidence)


@pytest.mark.parametrize("ocr", [False, True, None])
def test_transcription_origin_is_recorded_without_inventing_a_confidence_score(
    ocr: bool | None,
) -> None:
    configuration, artifact, evidence = source()
    block = artifact.blocks[0].model_copy(
        update={
            "from_ocr": ocr,
            "ocr_score": None,
            "unavailable_reasons": ("RAW_GEOMETRY_UNAVAILABLE",) if ocr is None else (),
        }
    )
    artifact = ParseArtifact.model_validate(
        artifact.model_dump(mode="python") | {"blocks": (block, artifact.blocks[1])}
    )
    actual_projection = project_parse(artifact, configuration).evidence
    if ocr is None:
        # M1A does not publish exact evidence for unknown origins. The risk
        # helper rejects this unsealed source rather than changing its origin.
        assert actual_projection == ()
        with pytest.raises(ValueError, match="one sealed parse"):
            table_evidence_ids(artifact, evidence)
        with pytest.raises(ValueError, match="one sealed parse"):
            transcription_evidence_ids(artifact, evidence)
    else:
        assert actual_projection == evidence
        assert transcription_evidence_ids(artifact, evidence) == (
            () if ocr is False else (evidence[0].id,)
        )
    assert artifact.blocks[0].from_ocr is ocr
    assert artifact.blocks[0].ocr_score is None


def test_a_measured_ocr_score_does_not_authorize_financial_transcription() -> None:
    configuration, artifact, _ = source()
    block = artifact.blocks[0].model_copy(update={"from_ocr": True, "ocr_score": 1.0})
    artifact = ParseArtifact.model_validate(
        artifact.model_dump(mode="python") | {"blocks": (block, artifact.blocks[1])}
    )
    evidence = project_parse(artifact, configuration).evidence
    assert transcription_evidence_ids(artifact, evidence) == (evidence[0].id,)


def test_native_text_on_a_table_risk_page_is_not_mislabelled_as_ocr() -> None:
    _, artifact, evidence = source()
    assert table_evidence_ids(artifact, evidence) == (evidence[0].id,)
    assert transcription_evidence_ids(artifact, evidence) == ()


def test_transcription_risk_is_sorted_and_cannot_cross_sealed_source_membership() -> None:
    configuration, artifact, _ = source(pages=2)
    blocks = tuple(
        block.model_copy(update={"from_ocr": True})
        if block.source_cell_index is not None
        else block
        for block in artifact.blocks
    )
    artifact = ParseArtifact.model_validate(artifact.model_dump(mode="python") | {"blocks": blocks})
    evidence = project_parse(artifact, configuration).evidence
    assert transcription_evidence_ids(artifact, tuple(reversed(evidence))) == tuple(
        sorted(record.id for record in evidence)
    )
    assert transcription_evidence_ids(artifact, ()) == ()
    with pytest.raises(ValueError, match="distinct"):
        transcription_evidence_ids(artifact, (evidence[0], evidence[0]))
    foreign = evidence[0].model_copy(
        update={
            "source": evidence[0].source.model_copy(update={"parse_version_id": fixture_id(881007)})
        }
    )
    with pytest.raises(ValueError, match="one sealed parse"):
        transcription_evidence_ids(artifact, (foreign,))


def test_unknown_origin_cannot_use_assembled_preview_geometry_as_original_support() -> None:
    _, artifact, evidence = source()
    block = artifact.blocks[0].model_copy(
        update={
            "from_ocr": None,
            "source_cell_index": None,
            "unavailable_reasons": ("RAW_GEOMETRY_UNAVAILABLE",),
        }
    )
    artifact = ParseArtifact.model_validate(
        artifact.model_dump(mode="python") | {"blocks": (block, artifact.blocks[1])}
    )
    with pytest.raises(ValueError, match="one sealed parse"):
        transcription_evidence_ids(artifact, evidence)
