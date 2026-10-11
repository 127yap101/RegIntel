"""Explicit coordinate transforms; these do not calibrate an extractor's frame.

Canonical values are raw unrotated PDF coordinates with a bottom-left origin.
Crop/display frames use the visible MediaBox/CropBox intersection, applying
clockwise PDF /Rotate exactly once. Bounds are strict: no fitting or clamping.
"""

import math
from collections.abc import Callable
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import ValidationError
from pypdf import PageObject
from pypdf.generic import RectangleObject

from regintel.contracts.models import PageGeometry, PdfRectangle

Point = tuple[float, float]
GeometryCode = Literal[
    "INVALID_GEOMETRY", "UNAVAILABLE_GEOMETRY", "OUTSIDE_GEOMETRY", "UNKNOWN_FRAME"
]


class GeometryError(ValueError):
    """Geometry cannot be represented exactly in the caller's selected frame."""

    def __init__(self, code: GeometryCode, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class CoordinateFrame(StrEnum):
    RAW_PDF_BOTTOM_LEFT = "RAW_PDF_BOTTOM_LEFT"
    MEDIA_RELATIVE_BOTTOM_LEFT = "MEDIA_RELATIVE_BOTTOM_LEFT"
    CROP_ROTATED_BOTTOM_LEFT = "CROP_ROTATED_BOTTOM_LEFT"
    CROP_ROTATED_TOP_LEFT = "CROP_ROTATED_TOP_LEFT"


def _page_geometry(geometry: PageGeometry | None) -> PageGeometry:
    if not isinstance(geometry, PageGeometry):
        raise GeometryError("UNAVAILABLE_GEOMETRY", "Original page geometry is required.")
    try:
        # Validate even model_construct/model_copy instances supplied by an adapter.
        return PageGeometry.model_validate(geometry.model_dump(mode="python"))
    except ValidationError:
        raise GeometryError("INVALID_GEOMETRY", "Original page geometry is invalid.") from None


def _frame(frame: CoordinateFrame) -> CoordinateFrame:
    if not isinstance(frame, CoordinateFrame):
        raise GeometryError("UNKNOWN_FRAME", "Select a declared coordinate frame explicitly.")
    return frame


def _rectangle(rectangle: PdfRectangle | None) -> PdfRectangle:
    if not isinstance(rectangle, PdfRectangle):
        raise GeometryError("UNAVAILABLE_GEOMETRY", "An exact source rectangle is required.")
    try:
        return PdfRectangle.model_validate(rectangle.model_dump(mode="python"))
    except ValidationError:
        raise GeometryError(
            "INVALID_GEOMETRY", "Source rectangle must be finite with positive area."
        ) from None


def _point(point: Point) -> Point:
    try:
        x, y = point
        if (
            isinstance(x, bool)
            or isinstance(y, bool)
            or not math.isfinite(x)
            or not math.isfinite(y)
        ):
            raise ValueError
        return float(x), float(y)
    except (TypeError, ValueError, OverflowError):
        raise GeometryError(
            "INVALID_GEOMETRY", "Source point must have two finite coordinates."
        ) from None


def _visible_crop(geometry: PageGeometry) -> PdfRectangle:
    media, crop = geometry.media_box, geometry.crop_box
    x0, y0 = max(media.x0, crop.x0), max(media.y0, crop.y0)
    x1, y1 = min(media.x1, crop.x1), min(media.y1, crop.y1)
    if x1 <= x0 or y1 <= y0:
        raise GeometryError("UNAVAILABLE_GEOMETRY", "MediaBox and CropBox have no visible area.")
    return PdfRectangle(x0=x0, y0=y0, x1=x1, y1=y1)


def visible_crop_box(geometry: PageGeometry | None) -> PdfRectangle:
    """Return the explicitly defined PDF visible intersection, retaining raw metadata."""
    return _visible_crop(_page_geometry(geometry))


def _frame_bounds(geometry: PageGeometry, frame: CoordinateFrame) -> PdfRectangle:
    if frame is CoordinateFrame.RAW_PDF_BOTTOM_LEFT:
        return geometry.media_box
    if frame is CoordinateFrame.MEDIA_RELATIVE_BOTTOM_LEFT:
        media = geometry.media_box
        width, height = media.x1 - media.x0, media.y1 - media.y0
    else:
        crop = _visible_crop(geometry)
        width, height = crop.x1 - crop.x0, crop.y1 - crop.y0
        if geometry.rotation in (90, 270):
            width, height = height, width
    return PdfRectangle(x0=0.0, y0=0.0, x1=width, y1=height)


def frame_bounds(geometry: PageGeometry | None, *, frame: CoordinateFrame) -> PdfRectangle:
    """Finite coordinate bounds for the required, caller-selected input/output frame."""
    return _frame_bounds(_page_geometry(geometry), _frame(frame))


def _inside(point: Point, bounds: PdfRectangle) -> Point:
    if not (bounds.x0 <= point[0] <= bounds.x1 and bounds.y0 <= point[1] <= bounds.y1):
        raise GeometryError("OUTSIDE_GEOMETRY", "Coordinates lie outside their declared frame.")
    return point


def _to_pdf(point: Point, geometry: PageGeometry, frame: CoordinateFrame) -> Point:
    x, y = point
    if frame is CoordinateFrame.RAW_PDF_BOTTOM_LEFT:
        return point
    if frame is CoordinateFrame.MEDIA_RELATIVE_BOTTOM_LEFT:
        return geometry.media_box.x0 + x, geometry.media_box.y0 + y
    crop = _visible_crop(geometry)
    width, height = crop.x1 - crop.x0, crop.y1 - crop.y0
    if frame is CoordinateFrame.CROP_ROTATED_TOP_LEFT:
        display_height = width if geometry.rotation in (90, 270) else height
        y = display_height - y
    if geometry.rotation == 0:
        raw_x, raw_y = x, y
    elif geometry.rotation == 90:
        raw_x, raw_y = width - y, x
    elif geometry.rotation == 180:
        raw_x, raw_y = width - x, height - y
    else:  # Geometry validation permits only 270 here.
        raw_x, raw_y = y, height - x
    return crop.x0 + raw_x, crop.y0 + raw_y


def _from_pdf(point: Point, geometry: PageGeometry, frame: CoordinateFrame) -> Point:
    x, y = point
    if frame is CoordinateFrame.RAW_PDF_BOTTOM_LEFT:
        return point
    if frame is CoordinateFrame.MEDIA_RELATIVE_BOTTOM_LEFT:
        return x - geometry.media_box.x0, y - geometry.media_box.y0
    crop = _visible_crop(geometry)
    width, height = crop.x1 - crop.x0, crop.y1 - crop.y0
    raw_x, raw_y = x - crop.x0, y - crop.y0
    if geometry.rotation == 0:
        display_x, display_y = raw_x, raw_y
    elif geometry.rotation == 90:
        display_x, display_y = raw_y, width - raw_x
    elif geometry.rotation == 180:
        display_x, display_y = width - raw_x, height - raw_y
    else:
        display_x, display_y = height - raw_y, raw_x
    if frame is CoordinateFrame.CROP_ROTATED_TOP_LEFT:
        display_height = width if geometry.rotation in (90, 270) else height
        display_y = display_height - display_y
    return display_x, display_y


def to_pdf_point(point: Point, geometry: PageGeometry | None, *, frame: CoordinateFrame) -> Point:
    page, selected = _page_geometry(geometry), _frame(frame)
    source = _inside(_point(point), _frame_bounds(page, selected))
    return _inside(_point(_to_pdf(source, page, selected)), page.media_box)


def from_pdf_point(point: Point, geometry: PageGeometry | None, *, frame: CoordinateFrame) -> Point:
    page, selected = _page_geometry(geometry), _frame(frame)
    canonical = _inside(_point(point), page.media_box)
    return _inside(_point(_from_pdf(canonical, page, selected)), _frame_bounds(page, selected))


def _corners(rectangle: PdfRectangle) -> tuple[Point, Point, Point, Point]:
    return (
        (rectangle.x0, rectangle.y0),
        (rectangle.x0, rectangle.y1),
        (rectangle.x1, rectangle.y0),
        (rectangle.x1, rectangle.y1),
    )


def _map_box(
    rectangle: PdfRectangle,
    source_bounds: PdfRectangle,
    target_bounds: PdfRectangle,
    transform: Callable[[Point], Point],
) -> PdfRectangle:
    transformed = tuple(
        _inside(_point(transform(_inside(point, source_bounds))), target_bounds)
        for point in _corners(rectangle)
    )
    try:
        return PdfRectangle(
            x0=min(point[0] for point in transformed),
            y0=min(point[1] for point in transformed),
            x1=max(point[0] for point in transformed),
            y1=max(point[1] for point in transformed),
        )
    except ValidationError:
        raise GeometryError(
            "UNAVAILABLE_GEOMETRY",
            "Transformed corners do not retain a representable positive area.",
        ) from None


def to_pdf_box(
    rectangle: PdfRectangle | None, geometry: PageGeometry | None, *, frame: CoordinateFrame
) -> PdfRectangle:
    """Transform all corners into canonical raw PDF points, never guessing a frame."""
    page, selected = _page_geometry(geometry), _frame(frame)
    return _map_box(
        _rectangle(rectangle),
        _frame_bounds(page, selected),
        page.media_box,
        lambda point: _to_pdf(point, page, selected),
    )


def from_pdf_box(
    rectangle: PdfRectangle | None, geometry: PageGeometry | None, *, frame: CoordinateFrame
) -> PdfRectangle:
    """Forward canonical-to-selected-frame counterpart of to_pdf_box."""
    page, selected = _page_geometry(geometry), _frame(frame)
    return _map_box(
        _rectangle(rectangle),
        page.media_box,
        _frame_bounds(page, selected),
        lambda point: _from_pdf(point, page, selected),
    )


def _pdf_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise GeometryError("INVALID_GEOMETRY", "PDF page coordinates must be numeric.")
    number = float(value)
    if not math.isfinite(number):
        raise GeometryError("INVALID_GEOMETRY", "PDF page coordinates must be finite.")
    return number


def _pdf_rectangle(rectangle: RectangleObject) -> PdfRectangle:
    return PdfRectangle(
        x0=_pdf_number(rectangle.left),
        y0=_pdf_number(rectangle.bottom),
        x1=_pdf_number(rectangle.right),
        y1=_pdf_number(rectangle.top),
    )


def geometry_from_pdf_page(page: PageObject) -> PageGeometry:
    """Read original boxes and canonical /Rotate; unsupported metadata is unavailable.

    pypdf resolves inherited/default page boxes. Non-default /UserUnit is rejected
    because this contract has no unit-scale field; its physical points must not be
    guessed. This function does not inspect or identify a Docling output frame.
    """
    try:
        media, crop = _pdf_rectangle(page.mediabox), _pdf_rectangle(page.cropbox)
        rotation: object = page.get("/Rotate", 0)
        if (
            isinstance(rotation, bool)
            or not isinstance(rotation, int)
            or rotation not in (0, 90, 180, 270)
        ):
            raise GeometryError("INVALID_GEOMETRY", "PDF rotation must be canonical 0/90/180/270.")
        if _pdf_number(page.get("/UserUnit", 1)) != 1.0:
            raise GeometryError(
                "UNAVAILABLE_GEOMETRY", "Non-default PDF user units require an explicit contract."
            )
        return PageGeometry.model_validate(
            {
                "width": media.x1 - media.x0,
                "height": media.y1 - media.y0,
                "media_box": media,
                "crop_box": crop,
                "rotation": int(rotation),
                "coordinate_space": "UNROTATED_PDF_POINTS",
                "origin": "BOTTOM_LEFT",
            }
        )
    except GeometryError:
        raise
    except (ValidationError, TypeError, ValueError, IndexError, KeyError, OverflowError):
        raise GeometryError("INVALID_GEOMETRY", "Original PDF page metadata is invalid.") from None
