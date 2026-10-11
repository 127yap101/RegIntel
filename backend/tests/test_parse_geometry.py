"""Independent coordinate references; no Docling frame or OCR calibration is claimed."""

from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import FloatObject, NameObject, NumberObject, RectangleObject

from regintel.contracts.models import PageGeometry, PdfRectangle
from regintel.fixtures.pdf import fixture_artifacts
from regintel.fixtures.sources import fixture_sources
from regintel.parsing.geometry import (
    CoordinateFrame,
    GeometryError,
    frame_bounds,
    from_pdf_box,
    from_pdf_point,
    geometry_from_pdf_page,
    to_pdf_box,
    to_pdf_point,
    visible_crop_box,
)


def rectangle(values: tuple[float, float, float, float]) -> PdfRectangle:
    return PdfRectangle(x0=values[0], y0=values[1], x1=values[2], y1=values[3])


def geometry(rotation: int = 0) -> PageGeometry:
    return PageGeometry.model_validate(
        {
            "width": 300.0,
            "height": 200.0,
            "media_box": {"x0": -20.0, "y0": -30.0, "x1": 280.0, "y1": 170.0},
            "crop_box": {"x0": -10.0, "y0": -5.0, "x1": 190.0, "y1": 95.0},
            "rotation": rotation,
            "coordinate_space": "UNROTATED_PDF_POINTS",
            "origin": "BOTTOM_LEFT",
        }
    )


RAW_BOX = (20.0, 15.0, 70.0, 45.0)
# Asymmetric hand-calculated references distinguish clockwise rotation, display
# origin, crop translation and min/max over all four rectangle corners.
DISPLAY_REFERENCES = (
    (0, (30.0, 20.0, 80.0, 50.0), (30.0, 50.0, 80.0, 80.0)),
    (90, (20.0, 120.0, 50.0, 170.0), (20.0, 30.0, 50.0, 80.0)),
    (180, (120.0, 50.0, 170.0, 80.0), (120.0, 20.0, 170.0, 50.0)),
    (270, (50.0, 30.0, 80.0, 80.0), (50.0, 120.0, 80.0, 170.0)),
)


@pytest.mark.parametrize("rotation,bottom,top", DISPLAY_REFERENCES)
def test_crop_display_forward_and_inverse_match_independent_rectangle_references(
    rotation: int, bottom: tuple[float, float, float, float], top: tuple[float, float, float, float]
) -> None:
    page, canonical = geometry(rotation), rectangle(RAW_BOX)
    for frame, expected in (
        (CoordinateFrame.CROP_ROTATED_BOTTOM_LEFT, bottom),
        (CoordinateFrame.CROP_ROTATED_TOP_LEFT, top),
    ):
        selected = rectangle(expected)
        assert from_pdf_box(canonical, page, frame=frame) == selected
        assert to_pdf_box(selected, page, frame=frame) == canonical
        # A second explicit round-trip also preserves the caller's input geometry.
        assert from_pdf_box(to_pdf_box(selected, page, frame=frame), page, frame=frame) == selected


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_raw_and_media_relative_frames_are_unrotated_and_use_original_media_origin(
    rotation: int,
) -> None:
    page, canonical = geometry(rotation), rectangle(RAW_BOX)
    assert to_pdf_box(canonical, page, frame=CoordinateFrame.RAW_PDF_BOTTOM_LEFT) == canonical
    assert from_pdf_box(canonical, page, frame=CoordinateFrame.RAW_PDF_BOTTOM_LEFT) == canonical
    relative = rectangle((40.0, 45.0, 90.0, 75.0))
    assert (
        from_pdf_box(canonical, page, frame=CoordinateFrame.MEDIA_RELATIVE_BOTTOM_LEFT) == relative
    )
    assert to_pdf_box(relative, page, frame=CoordinateFrame.MEDIA_RELATIVE_BOTTOM_LEFT) == canonical


@pytest.mark.parametrize(
    "rotation,bottom,top",
    [
        (0, (30.0, 20.0), (30.0, 80.0)),
        (90, (20.0, 170.0), (20.0, 30.0)),
        (180, (170.0, 80.0), (170.0, 20.0)),
        (270, (80.0, 30.0), (80.0, 170.0)),
    ],
)
def test_point_reference_rotations_apply_exactly_once(
    rotation: int, bottom: tuple[float, float], top: tuple[float, float]
) -> None:
    page, canonical = geometry(rotation), (20.0, 15.0)
    for frame, expected in (
        (CoordinateFrame.CROP_ROTATED_BOTTOM_LEFT, bottom),
        (CoordinateFrame.CROP_ROTATED_TOP_LEFT, top),
    ):
        assert from_pdf_point(canonical, page, frame=frame) == expected
        assert to_pdf_point(expected, page, frame=frame) == canonical


def test_explicit_frames_have_distinct_meanings_even_when_the_same_numbers_fit() -> None:
    box, page = rectangle((20.0, 20.0, 40.0, 40.0)), geometry()
    results = {
        frame: to_pdf_box(box, page, frame=frame)
        for frame in (
            CoordinateFrame.RAW_PDF_BOTTOM_LEFT,
            CoordinateFrame.MEDIA_RELATIVE_BOTTOM_LEFT,
            CoordinateFrame.CROP_ROTATED_BOTTOM_LEFT,
            CoordinateFrame.CROP_ROTATED_TOP_LEFT,
        )
    }
    assert len(set((r.x0, r.y0, r.x1, r.y1) for r in results.values())) == 4
    assert results[CoordinateFrame.RAW_PDF_BOTTOM_LEFT] == box
    assert results[CoordinateFrame.MEDIA_RELATIVE_BOTTOM_LEFT] == rectangle(
        (0.0, -10.0, 20.0, 10.0)
    )
    assert results[CoordinateFrame.CROP_ROTATED_BOTTOM_LEFT] == rectangle((10.0, 15.0, 30.0, 35.0))
    assert results[CoordinateFrame.CROP_ROTATED_TOP_LEFT] == rectangle((10.0, 55.0, 30.0, 75.0))


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_whole_crop_corners_transform_to_display_dimensions_with_inclusive_edges(
    rotation: int,
) -> None:
    page = geometry(rotation)
    expected = rectangle(
        (0.0, 0.0, 100.0, 200.0) if rotation in (90, 270) else (0.0, 0.0, 200.0, 100.0)
    )
    for frame in (CoordinateFrame.CROP_ROTATED_BOTTOM_LEFT, CoordinateFrame.CROP_ROTATED_TOP_LEFT):
        assert frame_bounds(page, frame=frame) == expected
        assert from_pdf_box(page.crop_box, page, frame=frame) == expected
        assert to_pdf_box(expected, page, frame=frame) == page.crop_box


def test_visible_crop_intersection_is_explicit_and_does_not_replace_original_metadata() -> None:
    page = geometry(90).model_copy(update={"crop_box": rectangle((-40.0, -40.0, 190.0, 95.0))})
    visible = rectangle((-20.0, -30.0, 190.0, 95.0))
    assert visible_crop_box(page) == visible
    assert frame_bounds(page, frame=CoordinateFrame.CROP_ROTATED_TOP_LEFT) == rectangle(
        (0.0, 0.0, 125.0, 210.0)
    )
    assert (
        to_pdf_box(
            rectangle((0.0, 0.0, 125.0, 210.0)), page, frame=CoordinateFrame.CROP_ROTATED_TOP_LEFT
        )
        == visible
    )
    assert page.crop_box == rectangle((-40.0, -40.0, 190.0, 95.0))


@pytest.mark.parametrize("frame", list(CoordinateFrame))
def test_outside_frame_boxes_are_rejected_without_clamping(frame: CoordinateFrame) -> None:
    page = geometry(90)
    bounds = frame_bounds(page, frame=frame)
    outside = rectangle((bounds.x0 - 0.001, bounds.y0, bounds.x1, bounds.y1))
    with pytest.raises(GeometryError) as failure:
        to_pdf_box(outside, page, frame=frame)
    assert failure.value.code == "OUTSIDE_GEOMETRY"


def test_canonical_box_outside_visible_crop_cannot_be_presented_as_crop_evidence() -> None:
    page, outside_crop = geometry(), rectangle((-20.0, -30.0, -10.0, -5.0))
    assert to_pdf_box(outside_crop, page, frame=CoordinateFrame.RAW_PDF_BOTTOM_LEFT) == outside_crop
    with pytest.raises(GeometryError, match="OUTSIDE_GEOMETRY"):
        from_pdf_box(outside_crop, page, frame=CoordinateFrame.CROP_ROTATED_BOTTOM_LEFT)


@pytest.mark.parametrize("coordinates", [(float("nan"), 0.0), (0.0, float("inf")), (True, 0.0)])
def test_points_must_be_finite_and_not_boolean(coordinates: tuple[float, float]) -> None:
    with pytest.raises(GeometryError, match="INVALID_GEOMETRY"):
        to_pdf_point(coordinates, geometry(), frame=CoordinateFrame.MEDIA_RELATIVE_BOTTOM_LEFT)


@pytest.mark.parametrize(
    "changes",
    [
        {"rotation": 45},
        {"rotation": True},
        {"crop_box": PdfRectangle.model_construct(x0=0.0, y0=0.0, x1=0.0, y1=20.0)},
        {"media_box": PdfRectangle.model_construct(x0=0.0, y0=0.0, x1=float("inf"), y1=20.0)},
        {"width": 1.0},
    ],
)
def test_invalid_constructed_page_metadata_is_revalidated(changes: dict[str, object]) -> None:
    with pytest.raises(GeometryError, match="INVALID_GEOMETRY"):
        to_pdf_box(
            rectangle(RAW_BOX),
            geometry().model_copy(update=changes),
            frame=CoordinateFrame.RAW_PDF_BOTTOM_LEFT,
        )


def test_missing_geometry_and_disjoint_crop_remain_unavailable() -> None:
    with pytest.raises(GeometryError, match="UNAVAILABLE_GEOMETRY"):
        to_pdf_box(rectangle(RAW_BOX), None, frame=CoordinateFrame.RAW_PDF_BOTTOM_LEFT)
    with pytest.raises(GeometryError, match="UNAVAILABLE_GEOMETRY"):
        to_pdf_box(None, geometry(), frame=CoordinateFrame.RAW_PDF_BOTTOM_LEFT)
    page = geometry().model_copy(update={"crop_box": rectangle((300.0, 200.0, 400.0, 300.0))})
    with pytest.raises(GeometryError, match="UNAVAILABLE_GEOMETRY"):
        visible_crop_box(page)
    with pytest.raises(GeometryError, match="UNAVAILABLE_GEOMETRY"):
        frame_bounds(page, frame=CoordinateFrame.CROP_ROTATED_BOTTOM_LEFT)


def test_missing_or_undeclared_frame_cannot_be_guessed() -> None:
    with pytest.raises(TypeError):
        to_pdf_box(rectangle(RAW_BOX), geometry())  # type: ignore[call-arg]
    with pytest.raises(GeometryError, match="UNKNOWN_FRAME"):
        to_pdf_box(rectangle(RAW_BOX), geometry(), frame="fit-the-page")  # type: ignore[arg-type]


def test_original_fixture_pdf_boxes_and_rotations_are_read_without_display_substitution() -> None:
    artifacts = fixture_artifacts()
    for document in fixture_sources():
        reader = PdfReader(BytesIO(artifacts[document.filename]), strict=True)
        for page, authored in zip(reader.pages, document.pages, strict=True):
            extracted = geometry_from_pdf_page(page)
            assert extracted == authored.geometry
            assert extracted.width == 612.0 and extracted.height == 792.0
            assert extracted.media_box.x0 == -10.0 and extracted.media_box.y0 == -20.0
            assert extracted.crop_box.x0 == -5.0 and extracted.crop_box.y0 == -15.0
            display = frame_bounds(extracted, frame=CoordinateFrame.CROP_ROTATED_BOTTOM_LEFT)
            expected = (780.0, 600.0) if extracted.rotation in (90, 270) else (600.0, 780.0)
            assert (display.x1, display.y1) == expected


@pytest.mark.parametrize(
    "rotation", [NumberObject(45), NumberObject(-90), NumberObject(360), FloatObject(90.5)]
)
def test_broken_or_noncanonical_pdf_rotation_is_not_rounded(
    rotation: NumberObject | FloatObject,
) -> None:
    page = PdfWriter().add_blank_page(width=300, height=200)
    page[NameObject("/Rotate")] = rotation
    with pytest.raises(GeometryError, match="INVALID_GEOMETRY"):
        geometry_from_pdf_page(page)


def test_missing_crop_defaults_to_original_media_and_broken_crop_is_rejected() -> None:
    page = PdfWriter().add_blank_page(width=300, height=200)
    page.mediabox = RectangleObject([-20, -30, 280, 170])
    original = geometry_from_pdf_page(page)
    assert original.crop_box == original.media_box
    page.cropbox = RectangleObject([0, 0, 0, 10])
    with pytest.raises(GeometryError, match="INVALID_GEOMETRY"):
        geometry_from_pdf_page(page)


def test_nondefault_pdf_user_unit_is_unavailable_instead_of_guessed() -> None:
    page = PdfWriter().add_blank_page(width=300, height=200)
    page[NameObject("/UserUnit")] = NumberObject(2)
    with pytest.raises(GeometryError, match="UNAVAILABLE_GEOMETRY"):
        geometry_from_pdf_page(page)


def test_float_cancellation_cannot_silently_turn_a_positive_rectangle_into_zero_area() -> None:
    page = PageGeometry.model_validate(
        {
            "width": 2.0,
            "height": 2.0,
            "media_box": {"x0": 1e16, "y0": 0.0, "x1": 1e16 + 2.0, "y1": 2.0},
            "crop_box": {"x0": 1e16, "y0": 0.0, "x1": 1e16 + 2.0, "y1": 2.0},
            "rotation": 0,
            "coordinate_space": "UNROTATED_PDF_POINTS",
            "origin": "BOTTOM_LEFT",
        }
    )
    with pytest.raises(GeometryError, match="UNAVAILABLE_GEOMETRY"):
        to_pdf_box(
            rectangle((0.0, 0.0, 1.0, 1.0)), page, frame=CoordinateFrame.MEDIA_RELATIVE_BOTTOM_LEFT
        )
