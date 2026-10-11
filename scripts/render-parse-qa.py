"""Create a disposable annotated PDF from canonical parser boxes, never edit a source."""

import argparse
import hashlib
import io
import subprocess
from pathlib import Path

from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.pdfgen import canvas

from regintel.parsing.geometry import geometry_from_pdf_page
from regintel.parsing.models import ParseArtifact, artifact_sha256


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    arguments = parser.parse_args()
    source: Path = arguments.source
    artifact_path: Path = arguments.artifact
    if (
        not source.is_absolute()
        or not artifact_path.is_absolute()
        or source.is_symlink()
        or artifact_path.is_symlink()
    ):
        raise ValueError("Explicit regular original source and artifact paths are required")
    if source.stat().st_size > 64 * 1024 * 1024 or artifact_path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("QA source/artifact exceeds the fixed inspection bound")
    artifact = ParseArtifact.model_validate_json(artifact_path.read_bytes())
    source_bytes = source.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != artifact.source_sha256:
        raise ValueError("The original PDF hash differs from parser provenance")
    reader = PdfReader(io.BytesIO(source_bytes))
    if len(reader.pages) != len(artifact.pages):
        raise ValueError("Original source page coverage differs")
    target_root = Path(__file__).resolve().parents[1] / ".cache" / "parse-qa"
    target_root.mkdir(parents=True, exist_ok=True)
    output_root = target_root / artifact_sha256(artifact)
    if output_root.exists():
        raise ValueError("QA output already exists; inspect it rather than overwrite")
    output_root.mkdir()
    writer = PdfWriter()
    for page_record, original in zip(artifact.pages, reader.pages, strict=True):
        geometry = geometry_from_pdf_page(original)
        if geometry != page_record.geometry:
            raise ValueError("Original source geometry differs from parser provenance")
        overlay_bytes = io.BytesIO()
        layer = canvas.Canvas(overlay_bytes, pagesize=(geometry.width, geometry.height))
        layer.translate(-geometry.media_box.x0, -geometry.media_box.y0)
        layer.setLineWidth(0.8)
        layer.setStrokeColorRGB(1, 0, 0)
        for block in artifact.blocks:
            if block.page_id != page_record.id or block.boxes is None:
                continue
            for box in block.boxes:
                layer.rect(box.x0, box.y0, box.x1 - box.x0, box.y1 - box.y0, fill=0)
        layer.setStrokeColorRGB(0, 0.3, 1)
        for table in artifact.tables:
            for cell in table.cells:
                if cell.page_id != page_record.id or cell.boxes is None:
                    continue
                for box in cell.boxes:
                    layer.rect(box.x0, box.y0, box.x1 - box.x0, box.y1 - box.y0, fill=0)
        layer.showPage()
        layer.save()
        overlay = PdfReader(overlay_bytes).pages[0]
        overlay.add_transformation(
            Transformation().translate(tx=geometry.media_box.x0, ty=geometry.media_box.y0)
        )
        # Preserve source MediaBox/CropBox/Rotate; the overlay uses unrotated points.
        overlay.mediabox = original.mediabox
        overlay.cropbox = original.cropbox
        original.merge_page(overlay, over=True)
        writer.add_page(original)
    pdf_path = output_root / "annotated.pdf"
    with pdf_path.open("xb") as handle:
        writer.write(handle)
    subprocess.run(
        ["pdftoppm", "-scale-to", "1800", "-png", str(pdf_path), str(output_root / "page")],
        check=True,
        timeout=120,
        capture_output=True,
    )
    print(output_root)


if __name__ == "__main__":
    main()
