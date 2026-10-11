"""Narrow optional SDK boundary with explicit CPU/local-only configuration.

The native API never imports the heavy parser. Structured SDK output is captured
as untrusted parser data, then validated by the separate artifact adapter.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
from typing import Protocol, cast

from regintel.parsing.assets import HERON_REVISION, RAPID_FOLDER, verify_models
from regintel.parsing.models import PackageVersion, package_manifest_sha256

PINS = {
    "docling-slim": "2.134.0",
    "docling-core": "2.99.0",
    "docling-parse": "7.22.1",
    "docling-ibm-models": "4.0.3",
    "rapidocr": "3.9.2",
    "rtree": "1.4.1",
    "scipy": "1.18.1",
    "onnxruntime": "1.30.0",
    "torch": "2.13.0+cpu",
    "torchvision": "0.28.0+cpu",
}


class Dumpable(Protocol):
    def model_dump(self, *, mode: str) -> dict[str, object]: ...


class OptionsFactory(Protocol):
    def __call__(self, **kwargs: object) -> Dumpable: ...


class Exportable(Protocol):
    def export_to_dict(self) -> dict[str, object]: ...


class SdkPage(Protocol):
    page_no: int
    parsed_page: Dumpable | None
    cells: list[Dumpable]


class SdkResult(Protocol):
    status: object
    document: Exportable
    pages: list[SdkPage]
    errors: list[Dumpable]


class Converter(Protocol):
    def convert(
        self, source: Path, *, max_num_pages: int, max_file_size: int, raises_on_error: bool
    ) -> SdkResult: ...


class ConverterFactory(Protocol):
    def __call__(self, **kwargs: object) -> Converter: ...


def _options(module: str, name: str, /, **kwargs: object) -> Dumpable:
    factory = cast(OptionsFactory, getattr(importlib.import_module(module), name))
    return factory(**kwargs)


def installed_packages() -> tuple[PackageVersion, ...]:
    if any(importlib.metadata.version(name) != version for name, version in PINS.items()):
        raise ValueError("The parser environment differs from its tested exact pins")
    # Retain the actual transitive production environment, not just direct pins.
    versions: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"]
        if not isinstance(name, str) or not name:
            raise ValueError("Installed package metadata has no identity")
        canonical = name.lower().replace("_", "-").replace(".", "-")
        if canonical in versions and versions[canonical] != distribution.version:
            raise ValueError("Conflicting installed package metadata")
        versions[canonical] = distribution.version
    return tuple(
        PackageVersion(name=name, version=version) for name, version in sorted(versions.items())
    )


def canonical_pipeline_options(value: dict[str, object]) -> dict[str, object]:
    """Sort only SDK set-valued engine metadata; ordered option lists stay ordered.

    Pydantic JSON serialization turns ``supported_engines`` sets into lists whose
    order depends on the process hash seed. Their order has no SDK semantics.
    Retain every resolved option, including disabled defaults, in a stable form.
    """

    def normalize(item: object, key: str | None = None) -> object:
        if key == "supported_engines":
            # Optional SDK metadata uses null when no engine restriction is declared.
            if item is None:
                return None
            if (
                not isinstance(item, list)
                or any(not isinstance(engine, str) for engine in item)
                or len(set(item)) != len(item)
            ):
                raise ValueError("SDK engine metadata must be a duplicate-free string set")
            return sorted(cast(list[str], item))
        if isinstance(item, dict):
            if any(not isinstance(name, str) for name in item):
                raise ValueError("SDK option keys must be strings")
            return {
                name: normalize(option, name)
                for name, option in cast(dict[str, object], item).items()
            }
        if isinstance(item, list):
            return [normalize(option) for option in item]
        return item

    return cast(dict[str, object], normalize(value))


def create_converter(model_root: Path) -> tuple[Converter, dict[str, object]]:
    _, model_hash = verify_models(model_root)
    if any(os.environ.get(name) != "1" for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")):
        raise ValueError("Explicit offline model environment is required")
    packages = installed_packages()
    pipeline_module = "docling.datamodel.pipeline_options"
    cpu = _options(
        "docling.datamodel.accelerator_options", "AcceleratorOptions", device="cpu", num_threads=2
    )
    rapid_root = model_root / RAPID_FOLDER
    ocr = _options(
        pipeline_module,
        "RapidOcrOptions",
        lang=["en"],
        backend="onnxruntime",
        model_size="tiny",
        mode="pdf_aware_layout_regions",
        scale=3.0,
        text_score=0.5,
        use_det=True,
        use_cls=True,
        use_rec=True,
        print_verbose=False,
        det_model_path=str(rapid_root / "PP-OCRv6_det_tiny.onnx"),
        cls_model_path=str(rapid_root / "ch_ppocr_mobile_v2.0_cls_mobile.onnx"),
        rec_model_path=str(rapid_root / "PP-OCRv6_rec_tiny.onnx"),
        rec_keys_path=str(rapid_root / "ppocrv6_tiny_dict.txt"),
    )
    spec = _options(
        "docling.datamodel.stage_model_specs",
        "ObjectDetectionModelSpec",
        name="layout_heron",
        repo_id="docling-project/docling-layout-heron",
        revision=HERON_REVISION,
    )
    engine = _options(
        "docling.datamodel.object_detection_engine_options",
        "TransformersObjectDetectionEngineOptions",
        torch_dtype="float32",
    )
    layout = _options(
        pipeline_module, "LayoutObjectDetectionOptions", model_spec=spec, engine_options=engine
    )
    table = _options(
        pipeline_module, "TableStructureOptions", mode="accurate", do_cell_matching=True
    )
    pipeline = _options(
        pipeline_module,
        "PdfPipelineOptions",
        artifacts_path=model_root,
        accelerator_options=cpu,
        ocr_options=ocr,
        layout_options=layout,
        table_structure_options=table,
        do_ocr=True,
        do_table_structure=True,
        document_timeout=180.0,
        enable_remote_services=False,
        allow_external_plugins=False,
        do_code_enrichment=False,
        do_formula_enrichment=False,
        do_picture_classification=False,
        do_picture_description=False,
        generate_parsed_pages=True,
        generate_page_images=False,
        generate_picture_images=False,
        ocr_batch_size=1,
        layout_batch_size=1,
        table_batch_size=1,
        queue_max_size=4,
    )
    backend_module = importlib.import_module("docling.backend.docling_parse_backend")
    backend = backend_module.ThreadedDoclingParseDocumentBackend
    pipeline_class = importlib.import_module(
        "docling.pipeline.standard_pdf_pipeline"
    ).StandardPdfPipeline
    option = _options(
        "docling.document_converter",
        "PdfFormatOption",
        pipeline_options=pipeline,
        pipeline_cls=pipeline_class,
        backend=backend,
    )
    input_pdf = importlib.import_module("docling.datamodel.base_models").InputFormat.PDF
    factory = cast(
        ConverterFactory, (importlib.import_module("docling.document_converter")).DocumentConverter
    )
    converter = factory(allowed_formats=[input_pdf], format_options={input_pdf: option})
    backend_file = Path(cast(str, backend_module.__file__))
    configuration: dict[str, object] = {
        "adapter": "regintel-docling-v1",
        "backend": "ThreadedDoclingParseDocumentBackend",
        "backend_code_sha256": hashlib.sha256(backend_file.read_bytes()).hexdigest(),
        "packages": [package.model_dump(mode="json") for package in packages],
        "package_manifest_sha256": package_manifest_sha256(packages),
        "model_manifest_sha256": model_hash,
        "pipeline_options": canonical_pipeline_options(pipeline.model_dump(mode="json")),
    }
    encoded = json.dumps(
        configuration, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    configuration["configuration_sha256"] = hashlib.sha256(encoded).hexdigest()
    return converter, configuration


def capture_conversion(converter: Converter, source: Path) -> dict[str, object]:
    result = converter.convert(
        source, max_num_pages=2000, max_file_size=64 * 1024 * 1024, raises_on_error=False
    )
    status = getattr(result.status, "value", None)
    if not isinstance(status, str):
        raise ValueError("SDK conversion status is unavailable")
    return {
        "status": status,
        "document": result.document.export_to_dict(),
        "pages": [
            {
                "page_no": page.page_no,
                "parsed_page": (
                    page.parsed_page.model_dump(mode="json")
                    if page.parsed_page is not None
                    else None
                ),
                "cells": [cell.model_dump(mode="json") for cell in page.cells],
            }
            for page in result.pages
        ],
        "errors": [error.model_dump(mode="json") for error in result.errors],
    }
