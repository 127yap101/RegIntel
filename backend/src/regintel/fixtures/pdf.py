"""Deterministic PDF fixture generation and drift checks, without parsing application logic."""

import hashlib
import io
import json
from importlib.metadata import version
from pathlib import Path
from typing import cast

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from regintel.contracts.models import CONTRACT_VERSION
from regintel.fixtures.sources import (
    DocumentSource,
    PageSource,
    evidence_catalog,
    fixture_sources,
    source_text_catalog,
)

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

MANIFEST_FILENAME = "manifest.json"
FIXTURE_VERSION = "1.0.0"
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


class FixtureGenerationError(ValueError):
    """A fixture target, existing artifact or generated structure failed verification."""


def _header(canvas: Canvas, document: DocumentSource, page: PageSource) -> None:
    canvas.setFont("Helvetica-Bold", 14)
    canvas.drawString(40, 738, "SYNTHETIC TEST FIXTURE - INVENTED DISCLOSURES")
    canvas.setFont("Helvetica", 10)
    canvas.drawString(40, 716, f"{document.title} | source page {page.page_index + 1}")
    if document.parent_key is not None:
        canvas.drawString(
            40, 692, "Explicit parent: synthetic-base.pdf; unaffected facts are retained."
        )
    canvas.setFont("Helvetica", 8)
    canvas.drawString(
        40, 38, "Authored engineering fixture. Not a SEBI filing or research gold data."
    )


def _draw_table(canvas: Canvas) -> None:
    canvas.setLineWidth(0.5)
    for y in (670, 640, 610, 580, 550, 520, 490):
        canvas.line(34, y, 590, y)
    # The first unit header spans all four columns.
    for x in (190, 320, 450):
        canvas.line(x, 490, x, 640)
    canvas.line(34, 490, 34, 670)
    canvas.line(590, 490, 590, 670)


def _draw_native(canvas: Canvas, document: DocumentSource, page: PageSource) -> None:
    _header(canvas, document, page)
    if any(block.cell is not None for block in page.blocks):
        _draw_table(canvas)
    for block in page.blocks:
        canvas.setFont("Helvetica", block.font_size)
        for index, line in enumerate(block.text.split("\n")):
            if line:
                canvas.drawString(block.x, block.y - index * 14, line)


def _draw_raster(canvas: Canvas, document: DocumentSource, page: PageSource) -> None:
    """The entire page, including labels, is an image; no hidden text layer is added."""
    image = Image.new("RGB", (1224, 1584), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=20)
    draw.text((80, 108), "SYNTHETIC TEST FIXTURE - INVENTED DISCLOSURES", fill="black", font=font)
    draw.text(
        (80, 152), f"{document.title} | source page {page.page_index + 1}", fill="black", font=font
    )
    for block in page.blocks:
        for index, line in enumerate(block.text.split("\n")):
            draw.text(
                (block.x * 2, (792 - block.y + index * 14 - block.font_size) * 2),
                line,
                fill="black",
                font=ImageFont.load_default(size=block.font_size * 2),
            )
    draw.text(
        (80, 1500),
        "Authored image transcription in sidecar; no OCR has been run.",
        fill="black",
        font=ImageFont.load_default(size=16),
    )
    canvas.drawImage(ImageReader(image), 0, 0, width=612, height=792)


def _document_bytes(document: DocumentSource) -> bytes:
    intermediate = io.BytesIO()
    canvas = Canvas(
        intermediate, pagesize=(612, 792), invariant=1, pageCompression=0, pdfVersion=(1, 4)
    )
    canvas.setTitle(f"SYNTHETIC - {document.title}")
    canvas.setAuthor("RegIntel synthetic fixture authors")
    canvas.setSubject("Invented engineering test sources; no production facts or gold annotations")
    canvas.setCreator(f"RegIntel fixture generator {FIXTURE_VERSION}")
    for page in document.pages:
        if page.raster_only:
            _draw_raster(canvas, document, page)
        else:
            _draw_native(canvas, document, page)
        canvas.showPage()
    canvas.save()

    reader = PdfReader(io.BytesIO(intermediate.getvalue()), strict=True)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    for target, source in zip(writer.pages, document.pages, strict=True):
        media, crop = source.geometry.media_box, source.geometry.crop_box
        target.mediabox = RectangleObject((media.x0, media.y0, media.x1, media.y1))
        target.cropbox = RectangleObject((crop.x0, crop.y0, crop.x1, crop.y1))
        target.rotation = source.geometry.rotation
    writer.add_metadata(
        {
            "/CreationDate": "D:20000101000000Z",
            "/ModDate": "D:20000101000000Z",
            "/Producer": f"RegIntel fixture generator {FIXTURE_VERSION}",
        }
    )
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def fixture_artifacts() -> dict[str, bytes]:
    """Compute the whole family in memory before touching an output directory."""
    documents = fixture_sources()
    artifacts = {document.filename: _document_bytes(document) for document in documents}
    evidence = evidence_catalog()
    recipes: list[JsonValue] = []
    for document in documents:
        pages: list[JsonValue] = []
        for page in document.pages:
            blocks: list[JsonValue] = []
            for block in page.blocks:
                blocks.append(
                    {
                        "alias": block.alias,
                        "text": block.text,
                        "x": block.x,
                        "y": block.y,
                        "font_size": block.font_size,
                        "evidence_id": evidence[block.alias].id,
                        "cell": None
                        if block.cell is None
                        else cast(JsonObject, block.cell.model_dump(mode="json")),
                    }
                )
            pages.append(
                {
                    "page_id": page.page_id,
                    "page_index": page.page_index,
                    "geometry": cast(JsonObject, page.geometry.model_dump(mode="json")),
                    "raster_only": page.raster_only,
                    "blocks": blocks,
                }
            )
        recipes.append(
            {
                "key": document.key,
                "filename": document.filename,
                "title": document.title,
                "filing_id": document.filing_id,
                "filing_version_id": document.filing_version_id,
                "parse_version_id": document.parse_version_id,
                "publication_date": document.publication_date,
                "parent_key": document.parent_key,
                "sha256": hashlib.sha256(artifacts[document.filename]).hexdigest(),
                "pages": pages,
            }
        )
    manifest: JsonObject = {
        "fixture_version": FIXTURE_VERSION,
        "contract_version": CONTRACT_VERSION,
        "synthetic": True,
        "source_kind": "AUTHORED_TEST_RECIPE",
        "disclaimer": "No production facts, parser/OCR measurements or research gold data.",
        "dependencies": {name: version(name) for name in ("reportlab", "pypdf", "pillow")},
        "recipes": recipes,
        "evidence": {
            alias: cast(JsonObject, item.model_dump(mode="json"))
            for alias, item in sorted(evidence.items())
        },
        "source_text": cast(JsonObject, source_text_catalog()),
    }
    artifacts[MANIFEST_FILENAME] = (
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    return artifacts


def _safe_target(output_dir: Path, workspace_root: Path) -> Path:
    root = workspace_root.absolute()
    expected = root / "artifacts" / "fixtures"
    target = output_dir.absolute()
    if target != expected or target.resolve() != expected:
        raise FixtureGenerationError("Output must be the workspace artifacts/fixtures directory.")
    for path in (root, root / "artifacts", target):
        if path.is_symlink() or path.is_junction():
            raise FixtureGenerationError("Fixture output ancestors cannot be links or junctions.")
        if path.exists() and not path.is_dir():
            raise FixtureGenerationError("Fixture output ancestors must be directories.")
    return target


def generate_fixture_family(
    output_dir: Path | None = None, *, check: bool = False, workspace_root: Path = REPOSITORY_ROOT
) -> tuple[Path, ...]:
    """Create missing artifacts; refuse conflicts and perform read-only drift checks."""
    target = _safe_target(output_dir or workspace_root / "artifacts" / "fixtures", workspace_root)
    artifacts = fixture_artifacts()
    if target.exists():
        for existing in target.iterdir():
            if existing.name not in artifacts or existing.is_symlink() or not existing.is_file():
                raise FixtureGenerationError("Unexpected entry in fixture output directory.")
    for filename, expected in artifacts.items():
        path = target / filename
        if path.exists():
            if path.read_bytes() != expected:
                raise FixtureGenerationError(f"Fixture differs: {filename}.")
        elif check:
            raise FixtureGenerationError(f"Fixture is missing: {filename}.")
    if not check:
        target.mkdir(parents=True, exist_ok=True)
        for filename, expected in artifacts.items():
            path = target / filename
            if not path.exists():
                with path.open("xb") as output:
                    output.write(expected)
    return tuple(target / filename for filename in artifacts)
