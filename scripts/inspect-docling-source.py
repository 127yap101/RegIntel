"""Read selected pinned public source files without account credentials."""

import urllib.request
from pathlib import Path

FILES = (
    "docling/models/stages/table_structure/table_structure_model.py",
    "docling/models/stages/layout/object_detection_model.py",
    "docling/models/stages/layout/layout_object_detection_model.py",
    "docling/datamodel/pipeline_options.py",
    "docling/models/stages/ocr/rapid_ocr_model.py",
    "docling/backend/docling_parse_backend.py",
    "docling/backend/docling_parse_v4_backend.py",
    "docling/backend/docling_parse_v2_backend.py",
    "docling/models/stages/table_structure/table_structure_model_options.py",
    "docling/models/inference_engines/object_detection/__init__.py",
    "docling/models/inference_engines/object_detection/transformers_engine.py",
    "docling/models/inference_engines/object_detection/transformers.py",
    "docling/datamodel/stage_model_specs.py",
    "docling/backend/docling_parse_utils.py",
    "docling/backend/docling_parse_backend.py",
    "docling/pipeline/standard_pdf_pipeline.py",
    "docling/datamodel/base_models.py",
    "docling/models/inference_engines/object_detection/hf_base.py",
    "docling/models/stages/page_preprocessing/page_preprocessing_model.py",
)


def main() -> None:
    root = Path(__file__).resolve().parents[1] / ".cache" / "docling-source-v2.134.0"
    root.mkdir(parents=True, exist_ok=True)
    for relative in FILES:
        url = f"https://raw.githubusercontent.com/docling-project/docling/v2.134.0/{relative}"
        target = root / Path(relative).name
        if target.exists():
            continue
        try:
            # Anonymous public requests: no credential store or token discovery.
            with urllib.request.urlopen(url, timeout=45) as response:
                body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                raise ValueError("Source response exceeds the explicit inspection bound")
            target.write_bytes(body)
            print(f"{relative}: {len(body)} bytes, {target.name}", flush=True)
        except urllib.error.HTTPError as error:
            print(f"{relative}: HTTP {error.code}")


if __name__ == "__main__":
    main()
