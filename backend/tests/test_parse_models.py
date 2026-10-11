"""Parser artifact support/identity tests; fixture structure is not real extraction quality."""

import hashlib
import json

import pytest
from pydantic import ValidationError

from regintel.contracts.models import PageGeometry
from regintel.fixtures.sources import fixture_id
from regintel.parsing.models import (
    BlockProvenance,
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
    artifact_sha256,
    canonical_artifact_bytes,
    package_manifest_sha256,
)

PAGE_ID = fixture_id(15_001)
BLOCK_ID = fixture_id(15_002)
TABLE_ID = fixture_id(15_003)
CELL_ID = fixture_id(15_004)
ORIGINAL = "Revenue 🧾e\u0301 ₹51 –"
PROCESSED = "Revenue 🧾é INR 51 –"


def test_oriented_reported_corners_and_unknown_assembled_ocr_origin_are_retained() -> None:
    rectangle = ReportedRectangle(
        r_x0=10.0,
        r_y0=20.0,
        r_x1=30.0,
        r_y1=21.0,
        r_x2=29.0,
        r_y2=40.0,
        r_x3=9.0,
        r_y3=39.0,
        coord_origin="TOPLEFT",
        coordinate_frame="DOCLING_PAGE",
    )
    data = block_data()
    data["from_ocr"] = None
    data["unavailable_reasons"] = ["RAW_GEOMETRY_UNAVAILABLE"]
    block = ParsedBlock.model_validate(data)
    assert block.from_ocr is None and block.ocr_score is None
    provenance = BlockProvenance.model_validate(reported_data() | {"raw_rectangle": rectangle})
    assert provenance.raw_rectangle == rectangle
    with pytest.raises(ValidationError):
        ReportedRectangle.model_validate(rectangle.model_dump() | {"r_x3": float("nan")})
    with pytest.raises(ValidationError):
        ParsedBlock.model_validate(data | {"ocr_score": 0.8})


def test_selected_coordinate_frame_is_mandatory_and_changes_artifact_identity() -> None:
    top = ParseArtifact.model_validate(artifact_data())
    bottom = ParseArtifact.model_validate(
        artifact_data()
        | {
            "provenance": provenance_data()
            | {
                "coordinate_frame": "CROP_ROTATED_BOTTOM_LEFT",
            }
        },
    )
    assert top.pages == bottom.pages and top.blocks == bottom.blocks
    assert top.provenance.configuration_sha256 == bottom.provenance.configuration_sha256
    assert artifact_sha256(top) != artifact_sha256(bottom)
    omitted = provenance_data()
    omitted.pop("coordinate_frame")
    with pytest.raises(ValidationError):
        ParseProvenance.model_validate(omitted)


@pytest.mark.parametrize("frame", ["AUTO", "DOCLING_PAGE", None, 0, True])
def test_unknown_selected_coordinate_frames_are_rejected(frame: object) -> None:
    with pytest.raises(ValidationError):
        ParseProvenance.model_validate(provenance_data() | {"coordinate_frame": frame})


def geometry() -> PageGeometry:
    return PageGeometry.model_validate(
        {
            "width": 600.0,
            "height": 800.0,
            "media_box": {"x0": -20.0, "y0": -10.0, "x1": 580.0, "y1": 790.0},
            "crop_box": {"x0": 0.0, "y0": 0.0, "x1": 550.0, "y1": 750.0},
            "rotation": 90,
            "coordinate_space": "UNROTATED_PDF_POINTS",
            "origin": "BOTTOM_LEFT",
        }
    )


def reported_data() -> dict[str, object]:
    return {
        "source_ref": "#/texts/0",
        "page_no": 1,
        "text": PROCESSED,
        "charspan": {"start": 0, "end": len(PROCESSED)},
        "raw_box": {
            "l": 100.0,
            "t": 30.0,
            "r": 130.0,
            "b": 100.0,
            "coord_origin": "TOPLEFT",
            "coordinate_frame": "DOCLING_PAGE",
        },
    }


def block_data() -> dict[str, object]:
    start = ORIGINAL.index("₹51")
    return {
        "id": BLOCK_ID,
        "page_id": PAGE_ID,
        "page_index": 0,
        "source_ref": "page/0/text-cell/0",
        "source_cell_index": 0,
        "orig": ORIGINAL,
        "text": PROCESSED,
        "from_ocr": False,
        "ocr_score": None,
        "boxes": [{"x0": 30.0, "y0": 100.0, "x1": 100.0, "y1": 130.0}],
        "provenance": [reported_data()],
        "exact_spans": [{"block_id": BLOCK_ID, "start": start, "end": start + 3, "quote": "₹51"}],
        "unavailable_reasons": [],
    }


def cell_data() -> dict[str, object]:
    return {
        "id": CELL_ID,
        "table_id": TABLE_ID,
        "source_ref": "#/tables/0/data/table_cells/0",
        "row_index": 0,
        "column_index": 0,
        "row_span": 1,
        "column_span": 1,
        "column_header": False,
        "row_header": True,
        "row_section": False,
        "orig": "Revenue",
        "text": "Revenue",
        "from_ocr": None,
        "ocr_score": None,
        "page_id": PAGE_ID,
        "page_index": 0,
        "boxes": [{"x0": 30.0, "y0": 50.0, "x1": 130.0, "y1": 70.0}],
        "provenance": [],
        "unavailable_reasons": [],
    }


def table_data() -> dict[str, object]:
    return {
        "id": TABLE_ID,
        "source_ref": "#/tables/0",
        "row_count": 1,
        "column_count": 2,
        "page_regions": [
            {
                "page_id": PAGE_ID,
                "page_index": 0,
                "boxes": [{"x0": 20.0, "y0": 40.0, "x1": 300.0, "y1": 90.0}],
            }
        ],
        "provenance": [reported_data() | {"text": None, "charspan": None}],
        "cells": [cell_data()],
        "unavailable_reasons": [],
    }


def provenance_data() -> dict[str, object]:
    packages = (
        PackageVersion(name="docling-core", version="2.99.0"),
        PackageVersion(name="docling-slim", version="2.134.0"),
    )
    return {
        "adapter_name": "regintel-docling",
        "adapter_version": "1.0.0",
        "adapter_code_sha256": "a" * 64,
        "backend_name": "ThreadedDoclingParseDocumentBackend",
        "backend_version": "7.22.1",
        "backend_code_sha256": "b" * 64,
        "coordinate_frame": "CROP_ROTATED_TOP_LEFT",
        "packages": packages,
        "package_manifest_sha256": package_manifest_sha256(packages),
        "configuration_sha256": "c" * 64,
        "model_manifest_sha256": "d" * 64,
    }


def artifact_data() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "id": fixture_id(15_005),
        "filing_id": fixture_id(15_006),
        "filing_version_id": fixture_id(15_007),
        "source_blob_id": fixture_id(15_008),
        "source_sha256": "e" * 64,
        "provenance": provenance_data(),
        "pages": [ParsedPage(id=PAGE_ID, page_index=0, geometry=geometry())],
        "blocks": [block_data()],
        "tables": [table_data()],
        "diagnostics": [],
    }


def test_original_unicode_support_processed_text_and_raw_geometry_remain_distinct() -> None:
    artifact = ParseArtifact.model_validate(artifact_data())
    block = artifact.blocks[0]
    assert block.orig == ORIGINAL
    assert block.text == PROCESSED
    assert block.exact_spans[0].quote == "₹51"
    assert block.exact_evidence_available
    assert block.provenance[0].charspan is not None
    assert block.provenance[0].charspan.end == len(PROCESSED)
    assert block.provenance[0].raw_box is not None
    assert block.provenance[0].raw_box.coord_origin == "TOPLEFT"
    assert block.boxes is not None
    assert block.boxes[0].y0 == 100.0
    assert artifact.pages[0].geometry.media_box.x0 == -20.0
    assert artifact.pages[0].geometry.rotation == 90
    assert artifact.tables[0].cells[0].row_header
    assert artifact.tables[0].cells[0].from_ocr is None


@pytest.mark.parametrize(
    "changes",
    [
        {"quote": "₹49"},  # Same length is not exact support.
        {"block_id": fixture_id(15_099)},
        {"start": 0, "end": 3},
        {"start": 500, "end": 503},
        {"start": True},
        {"end": "3"},
        {"quote": "51"},
    ],
)
def test_exact_span_checks_membership_offsets_and_original_slice(
    changes: dict[str, object],
) -> None:
    start = ORIGINAL.index("₹51")
    span = {"block_id": BLOCK_ID, "start": start, "end": start + 3, "quote": "₹51"}
    with pytest.raises(ValidationError):
        ParsedBlock.model_validate(block_data() | {"exact_spans": [span | changes]})


def test_span_offsets_are_unicode_code_points_not_utf8_utf16_or_normalized_text() -> None:
    start = ORIGINAL.index("e\u0301")
    span = {"block_id": BLOCK_ID, "start": start, "end": start + 2, "quote": "e\u0301"}
    block = ParsedBlock.model_validate(block_data() | {"exact_spans": [span]})
    assert block.exact_spans[0].end - block.exact_spans[0].start == 2
    with pytest.raises(ValidationError):
        ParsedBlock.model_validate(block_data() | {"exact_spans": [span | {"quote": "é"}]})
    utf8_start = len(ORIGINAL[:start].encode("utf-8"))
    with pytest.raises(ValidationError):
        ParsedBlock.model_validate(
            block_data() | {"exact_spans": [span | {"start": utf8_start, "end": utf8_start + 2}]}
        )


@pytest.mark.parametrize(
    "reported_span", [{"start": 0, "end": 500}, {"start": -1, "end": 2}, {"start": 3, "end": 2}]
)
def test_invalid_upstream_span_is_retained_but_valid_orig_span_cannot_replace_it(
    reported_span: dict[str, int],
) -> None:
    reported = reported_data() | {"charspan": reported_span}
    with pytest.raises(ValidationError):
        ParsedBlock.model_validate(block_data() | {"provenance": [reported]})
    block = ParsedBlock.model_validate(
        block_data()
        | {"provenance": [reported], "unavailable_reasons": ["PROVENANCE_SPAN_INVALID"]}
    )
    assert not block.exact_evidence_available
    assert block.provenance[0].charspan is not None
    assert block.provenance[0].charspan.model_dump() == reported_span
    assert block.exact_spans[0].quote == "₹51"  # Independently verified, still unavailable.


def test_missing_upstream_text_for_reported_offsets_needs_explicit_unavailable_support() -> None:
    reported = reported_data() | {"text": None}
    with pytest.raises(ValidationError):
        ParsedBlock.model_validate(block_data() | {"provenance": [reported]})
    provenance = BlockProvenance.model_validate(reported)
    assert not provenance.reported_span_valid


@pytest.mark.parametrize(
    "value", [True, "1", float("nan"), 9_007_199_254_740_992, -9_007_199_254_740_992]
)
def test_reported_offsets_retain_only_exact_bounded_numeric_endpoints(value: object) -> None:
    with pytest.raises(ValidationError):
        ReportedCharacterSpan.model_validate({"start": value, "end": 2})


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.01, 1.01, "0.9", True])
def test_measured_ocr_scores_are_finite_bounded_numbers(score: object) -> None:
    with pytest.raises(ValidationError):
        ParsedBlock.model_validate(block_data() | {"from_ocr": True, "ocr_score": score})


def test_ocr_score_missing_is_explicit_and_native_default_confidence_is_rejected() -> None:
    ocr = ParsedBlock.model_validate(block_data() | {"from_ocr": True, "ocr_score": None})
    assert ocr.ocr_score is None
    measured = ParsedBlock.model_validate(block_data() | {"from_ocr": True, "ocr_score": 0.83})
    assert measured.ocr_score == 0.83
    with pytest.raises(ValidationError):
        ParsedBlock.model_validate(block_data() | {"ocr_score": 1.0})
    with pytest.raises(ValidationError):
        ParsedCell.model_validate(cell_data() | {"ocr_score": 1.0})


@pytest.mark.parametrize(
    "changes",
    [
        {"page_id": None},
        {"page_index": None},
        {"page_id": None, "page_index": None},
        {"boxes": None},
        {"boxes": []},
        {"orig": None},
        {"exact_spans": []},
        {"unavailable_reasons": ["PROVENANCE_SPAN_INVALID", "PROVENANCE_SPAN_INVALID"]},
        {"unavailable_reasons": ["MADE_UP_REASON"]},
        {"period": "FY2025"},
    ],
)
def test_missing_support_and_unknown_semantics_cannot_be_silently_accepted(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ParsedBlock.model_validate(block_data() | changes)


def test_unmapped_processed_text_is_preserved_without_fabricated_orig_page_box_or_quote() -> None:
    block = ParsedBlock.model_validate(
        block_data()
        | {
            "page_id": None,
            "page_index": None,
            "orig": None,
            "boxes": None,
            "exact_spans": [],
            "unavailable_reasons": [
                "PAGE_MAPPING_UNAVAILABLE",
                "GEOMETRY_UNAVAILABLE",
                "ORIGINAL_TEXT_UNAVAILABLE",
                "TEXT_SPAN_UNAVAILABLE",
            ],
        }
    )
    assert block.orig is None
    assert block.text == PROCESSED
    assert block.boxes is None
    assert block.exact_spans == ()
    assert not block.exact_evidence_available


@pytest.mark.parametrize("raw", ["", "-", "—"])
def test_blank_and_dash_cells_remain_exact_raw_text(raw: str) -> None:
    cell = ParsedCell.model_validate(cell_data() | {"orig": raw, "text": raw})
    assert cell.orig == raw
    assert cell.text == raw
    assert cell.exact_evidence_available


def test_missing_cell_box_stays_missing_even_when_table_geometry_exists() -> None:
    cell = cell_data() | {"boxes": None, "unavailable_reasons": ["GEOMETRY_UNAVAILABLE"]}
    table = ParsedTable.model_validate(table_data() | {"cells": [cell]})
    assert table.page_regions[0].boxes
    assert table.cells[0].boxes is None
    assert not table.cells[0].exact_evidence_available


def test_missing_cell_page_does_not_inherit_a_table_page() -> None:
    cell = cell_data() | {
        "page_id": None,
        "page_index": None,
        "boxes": None,
        "unavailable_reasons": ["PAGE_MAPPING_UNAVAILABLE", "GEOMETRY_UNAVAILABLE"],
    }
    artifact = ParseArtifact.model_validate(
        artifact_data() | {"tables": [table_data() | {"cells": [cell]}]}
    )
    assert artifact.tables[0].cells[0].page_id is None


@pytest.mark.parametrize(
    "changes",
    [
        {"table_id": fixture_id(15_099)},
        {"row_index": 1},
        {"column_index": 2},
        {"row_span": 2},
        {"column_span": 3},
        {"row_span": 0},
        {"column_header": "true"},
        {"row_index": True},
    ],
)
def test_cells_require_exact_table_membership_dimensions_and_header_flags(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ParsedTable.model_validate(table_data() | {"cells": [cell_data() | changes]})


def test_table_spans_and_header_flags_are_preserved_without_context_interpretation() -> None:
    cell = cell_data() | {"column_span": 2, "column_header": True, "row_section": True}
    table = ParsedTable.model_validate(table_data() | {"cells": [cell]})
    assert table.cells[0].column_span == 2
    assert table.cells[0].column_header
    assert table.cells[0].row_section
    with pytest.raises(ValidationError):
        ParsedCell.model_validate(cell | {"normalized_value": "51"})


def test_assembled_preview_geometry_does_not_grant_exact_evidence_availability() -> None:
    data = block_data() | {
        "from_ocr": None,
        "source_cell_index": None,
        "unavailable_reasons": ["RAW_GEOMETRY_UNAVAILABLE"],
    }
    block = ParsedBlock.model_validate(data)
    assert block.boxes and block.exact_spans
    assert not block.exact_evidence_available
    with pytest.raises(ValidationError, match="Assembled text"):
        ParsedBlock.model_validate(data | {"unavailable_reasons": []})


def test_table_provenance_is_mandatory_and_incomplete_geometry_cannot_be_hidden() -> None:
    data = table_data()
    del data["provenance"]
    with pytest.raises(ValidationError):
        ParsedTable.model_validate(data)
    entries = [reported_data() | {"text": None, "charspan": None}]
    entries.append(entries[0] | {"raw_box": None})
    with pytest.raises(ValidationError, match="Incomplete table geometry"):
        ParsedTable.model_validate(table_data() | {"provenance": entries})
    table = ParsedTable.model_validate(
        table_data() | {"provenance": entries, "unavailable_reasons": ["GEOMETRY_UNAVAILABLE"]}
    )
    assert len(table.provenance) == 2 and table.provenance[1].raw_box is None
    assert len(table.page_regions[0].boxes) == 1


def test_unknown_table_page_needs_explicit_unavailable_reason_in_the_artifact() -> None:
    unknown = reported_data() | {"page_no": 99, "text": None, "charspan": None}
    table = table_data() | {"provenance": [unknown]}
    with pytest.raises(ValidationError, match="Unknown table source pages"):
        ParseArtifact.model_validate(artifact_data() | {"tables": [table]})
    accepted = ParseArtifact.model_validate(
        artifact_data()
        | {"tables": [table | {"unavailable_reasons": ["PAGE_MAPPING_UNAVAILABLE"]}]}
    )
    assert accepted.tables[0].provenance[0].page_no == 99


@pytest.mark.parametrize("duplicate_id", [True, False])
def test_duplicate_cell_ids_or_anchor_positions_fail(duplicate_id: bool) -> None:
    second = cell_data() | {"id": fixture_id(15_009), "column_index": 1}
    second.update({"id": CELL_ID} if duplicate_id else {"column_index": 0})
    with pytest.raises(ValidationError):
        ParsedTable.model_validate(table_data() | {"cells": [cell_data(), second]})


@pytest.mark.parametrize(
    "changes",
    [
        {"page_id": fixture_id(15_099)},
        {"page_index": 1},
        {"boxes": [{"x0": -21.0, "y0": 100.0, "x1": 100.0, "y1": 130.0}]},
        {"boxes": [{"x0": -20.00000001, "y0": 100.0, "x1": 100.0, "y1": 130.0}]},
        {"boxes": [{"x0": 30.0, "y0": 100.0, "x1": 581.0, "y1": 130.0}]},
        {"boxes": [{"x0": 30.0, "y0": 100.0, "x1": 580.00000001, "y1": 130.0}]},
        {"boxes": [{"x0": 30.0, "y0": 100.0, "x1": 100.0, "y1": float("inf")}]},
    ],
)
def test_canonical_block_geometry_is_bound_to_exact_source_page(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ParseArtifact.model_validate(artifact_data() | {"blocks": [block_data() | changes]})


def test_canonical_cell_and_table_geometry_require_source_page_membership() -> None:
    with pytest.raises(ValidationError):
        ParseArtifact.model_validate(
            artifact_data()
            | {"tables": [table_data() | {"cells": [cell_data() | {"page_index": 1}]}]}
        )
    wrong_region = {"page_id": fixture_id(15_099), "page_index": 0, "boxes": cell_data()["boxes"]}
    with pytest.raises(ValidationError):
        ParseArtifact.model_validate(
            artifact_data() | {"tables": [table_data() | {"page_regions": [wrong_region]}]}
        )


def test_cross_page_support_stays_in_separate_page_local_blocks() -> None:
    page = ParsedPage(id=fixture_id(15_010), page_index=1, geometry=geometry())
    second_id = fixture_id(15_011)
    second = block_data() | {
        "id": second_id,
        "page_id": page.id,
        "page_index": 1,
        "source_ref": "page/1/text-cell/0",
        "orig": "continuation",
        "text": "continuation",
        "provenance": [],
        "exact_spans": [{"block_id": second_id, "start": 0, "end": 12, "quote": "continuation"}],
    }
    artifact = ParseArtifact.model_validate(
        artifact_data()
        | {
            "pages": [ParsedPage(id=PAGE_ID, page_index=0, geometry=geometry()), page],
            "blocks": [block_data(), second],
        }
    )
    assert tuple(block.page_index for block in artifact.blocks) == (0, 1)


@pytest.mark.parametrize("index", [1, 2])
def test_source_page_coverage_is_contiguous_zero_based(index: int) -> None:
    with pytest.raises(ValidationError):
        ParseArtifact.model_validate(
            artifact_data()
            | {"pages": [ParsedPage(id=PAGE_ID, page_index=index, geometry=geometry())]}
        )


def test_record_identity_cannot_be_reused_across_page_block_table_and_cell() -> None:
    with pytest.raises(ValidationError):
        ParseArtifact.model_validate(artifact_data() | {"id": PAGE_ID})
    cell = cell_data() | {"id": BLOCK_ID}
    with pytest.raises(ValidationError):
        ParseArtifact.model_validate(
            artifact_data() | {"tables": [table_data() | {"cells": [cell]}]}
        )


def diagnostic_data() -> dict[str, object]:
    return {
        "code": "OCR_SCORE_UNAVAILABLE",
        "severity": "WARNING",
        "source_ref": "page/0/text-cell/0",
        "page_id": PAGE_ID,
        "block_id": BLOCK_ID,
        "table_id": None,
        "cell_id": None,
        "detail": "The OCR engine did not return a score.",
    }


@pytest.mark.parametrize(
    "changes",
    [{"code": "ARBITRARY_ENGINE_MESSAGE"}, {"severity": "INFO"}, {"detail": "x" * 2_001}],
)
def test_diagnostics_are_fixed_code_and_bounded(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ParseDiagnostic.model_validate(diagnostic_data() | changes)


@pytest.mark.parametrize("field", ["page_id", "block_id", "table_id", "cell_id"])
def test_diagnostics_cannot_reference_foreign_artifact_records(field: str) -> None:
    with pytest.raises(ValidationError):
        ParseArtifact.model_validate(
            artifact_data() | {"diagnostics": [diagnostic_data() | {field: fixture_id(15_099)}]}
        )


def test_provenance_package_manifest_is_verified_and_requires_unique_sorted_names() -> None:
    provenance = ParseProvenance.model_validate(provenance_data())
    assert provenance.package_manifest_sha256 == package_manifest_sha256(provenance.packages)
    with pytest.raises(ValidationError):
        ParseProvenance.model_validate(provenance_data() | {"package_manifest_sha256": "f" * 64})
    for packages in (tuple(reversed(provenance.packages)), (provenance.packages[0],) * 2):
        with pytest.raises(ValidationError):
            ParseProvenance.model_validate(
                provenance_data()
                | {
                    "packages": packages,
                    "package_manifest_sha256": package_manifest_sha256(packages),
                }
            )


@pytest.mark.parametrize("field", ["source_sha256", "schema_version", "id"])
def test_source_version_and_parse_identity_are_strict(field: str) -> None:
    invalid = {"source_sha256": "E" * 64, "schema_version": "2.0.0", "id": "not-a-uuid"}
    with pytest.raises(ValidationError):
        ParseArtifact.model_validate(artifact_data() | {field: invalid[field]})


@pytest.mark.parametrize("field", ["orig", "text"])
def test_original_and_processed_text_reject_unstorable_unicode(field: str) -> None:
    with pytest.raises(ValidationError):
        ParsedBlock.model_validate(block_data() | {field: "bad\x00text"})
    with pytest.raises(ValidationError):
        ParsedCell.model_validate(cell_data() | {field: "bad\ud800text"})


def test_raw_reported_box_does_not_gain_canonical_geometry_validation_or_authority() -> None:
    raw = ReportedBox(
        l=20.0,
        t=20.0,
        r=20.0,
        b=20.0,
        coord_origin="BOTTOMLEFT",
        coordinate_frame="DOCLING_PAGE",
    )
    assert raw.left == raw.right  # Retained degenerate output, without canonical authority.
    with pytest.raises(ValidationError):
        ReportedBox.model_validate(raw.model_dump(by_alias=True) | {"l": float("nan")})
    reversed_span = BlockProvenance.model_validate(
        reported_data() | {"charspan": {"start": 3, "end": 2}}
    )
    assert not reversed_span.reported_span_valid


def test_artifact_is_frozen_and_json_round_trip_preserves_deterministic_identity() -> None:
    artifact = ParseArtifact.model_validate(artifact_data())
    encoded = canonical_artifact_bytes(artifact)
    assert ORIGINAL.encode("utf-8") in encoded
    assert artifact_sha256(artifact) == hashlib.sha256(encoded).hexdigest()
    decoded = ParseArtifact.model_validate_json(encoded)
    assert decoded == artifact
    assert canonical_artifact_bytes(decoded) == encoded
    reverse_keys = dict(reversed(list(artifact.model_dump(mode="json").items())))
    assert artifact_sha256(ParseArtifact.model_validate(reverse_keys)) == artifact_sha256(artifact)
    with pytest.raises(ValidationError):
        artifact.id = fixture_id(15_099)
    with pytest.raises(ValidationError):
        artifact.blocks[0].text = "changed"
    assert isinstance(artifact.pages, tuple)
    assert isinstance(artifact.tables[0].cells, tuple)


def test_source_provenance_originals_structure_and_diagnostics_change_artifact_hash() -> None:
    artifact = ParseArtifact.model_validate(artifact_data())
    original_hash = artifact_sha256(artifact)
    alternatives = [
        artifact_data() | {"source_sha256": "f" * 64},
        artifact_data() | {"provenance": provenance_data() | {"model_manifest_sha256": "f" * 64}},
        artifact_data() | {"blocks": [block_data() | {"text": "normalized differently"}]},
        artifact_data() | {"tables": [table_data() | {"column_count": 3}]},
        artifact_data() | {"diagnostics": [diagnostic_data()]},
    ]
    for data in alternatives:
        assert artifact_sha256(ParseArtifact.model_validate(data)) != original_hash


@pytest.mark.parametrize("field", ["elapsed_seconds", "started_at", "job_status", "run_report"])
def test_volatile_run_metadata_cannot_enter_canonical_artifact(field: str) -> None:
    with pytest.raises(ValidationError):
        ParseArtifact.model_validate(artifact_data() | {field: 1})
    artifact = ParseArtifact.model_validate(artifact_data())
    serialized = json.loads(canonical_artifact_bytes(artifact))
    assert field not in serialized
