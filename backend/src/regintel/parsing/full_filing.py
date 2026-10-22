"""Offline whole-original conversion experiment with an explicit timeout identity.

The frozen worker/defaults remain unchanged. This module neither persists a parse
nor creates evidence, approvals or facts. Complete SDK output still needs the M1
adapter, evidence gates and publication path.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, cast

from regintel.parsing.configuration import (
    ParserRuntimeConfiguration,
    build_runtime_configuration,
    current_runtime_code_hashes,
    validate_runtime_configuration,
)
from regintel.parsing.sdk import (
    Converter,
    ConverterFactory,
    canonical_pipeline_options,
    create_converter,
)

MAX_CAPTURE_BYTES = 512 * 1024 * 1024
MIN_TIMEOUT_SECONDS = 181
MAX_TIMEOUT_SECONDS = 3_600


class CopyableOptions(Protocol):
    def model_dump(self, *, mode: str) -> dict[str, object]: ...

    def model_copy(self, *, update: dict[str, object], deep: bool) -> CopyableOptions: ...


class PdfOptions(Protocol):
    pipeline_options: CopyableOptions

    def model_copy(self, *, update: dict[str, object], deep: bool) -> PdfOptions: ...


class ConfiguredConverter(Converter, Protocol):
    format_to_options: dict[object, PdfOptions]


def json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _timeout_options(
    original: PdfOptions, configuration: Mapping[str, object], seconds: int
) -> tuple[PdfOptions, dict[str, object]]:
    """Allow exactly one resolved SDK option to change; do not mutate the baseline."""
    if type(seconds) is not int or not MIN_TIMEOUT_SECONDS <= seconds <= MAX_TIMEOUT_SECONDS:
        raise ValueError("Select a bounded explicit long-filing timeout.")
    baseline = configuration.get("pipeline_options")
    if not isinstance(baseline, dict) or baseline.get("document_timeout") != 180.0:
        raise ValueError("The selected baseline must retain its frozen 180-second timeout.")
    if canonical_pipeline_options(original.pipeline_options.model_dump(mode="json")) != baseline:
        raise ValueError("Resolved baseline options differ from the selected configuration.")
    pipeline = original.pipeline_options.model_copy(
        update={"document_timeout": float(seconds)}, deep=True
    )
    actual = canonical_pipeline_options(pipeline.model_dump(mode="json"))
    expected = dict(baseline) | {"document_timeout": float(seconds)}
    if actual != expected:
        raise ValueError("The experiment may change only the declared document timeout.")
    options = original.model_copy(update={"pipeline_options": pipeline}, deep=True)
    if canonical_pipeline_options(options.pipeline_options.model_dump(mode="json")) != expected:
        raise ValueError("The fresh converter must retain the declared resolved options.")
    resolved = dict(configuration)
    resolved.pop("configuration_sha256", None)
    resolved["pipeline_options"] = actual
    resolved["configuration_sha256"] = hashlib.sha256(json_bytes(resolved)).hexdigest()
    return options, resolved


def create_full_filing_converter(
    model_root: Path, baseline: ParserRuntimeConfiguration, *, timeout_seconds: int
) -> tuple[Converter, dict[str, object], dict[str, object]]:
    """Create a fresh pinned converter, retaining both baseline and experiment identities.

    The selected runtime descriptor describes the resolved adapter/SDK identity.
    The separate experiment profile also binds this entry point and baseline.
    It does not replace the application's selected worker descriptor.
    """
    converter, original = create_converter(model_root)
    validate_runtime_configuration(baseline, resolved_sdk_configuration=original)
    pdf = importlib.import_module("docling.datamodel.base_models").InputFormat.PDF
    configured = cast(ConfiguredConverter, converter)
    options, resolved = _timeout_options(
        configured.format_to_options[pdf], original, timeout_seconds
    )
    factory = cast(
        ConverterFactory, importlib.import_module("docling.document_converter").DocumentConverter
    )
    fresh = factory(allowed_formats=[pdf], format_options={pdf: options})
    actual = cast(ConfiguredConverter, fresh).format_to_options[pdf].pipeline_options
    if canonical_pipeline_options(actual.model_dump(mode="json")) != resolved["pipeline_options"]:
        raise ValueError("Fresh converter options differ from the recorded experiment.")
    selected = build_runtime_configuration(
        resolved_sdk_configuration=resolved,
        coordinate_frame=baseline.coordinate_frame,
        code_hashes=current_runtime_code_hashes(),
        source_limits=baseline.source_limits,
    )
    validate_runtime_configuration(selected, resolved_sdk_configuration=resolved)
    profile: dict[str, object] = {
        "schema_version": "full-filing-timeout-experiment-1",
        "scope": "ALL_ORIGINAL_PAGES",
        "baseline_processing_configuration_sha256": baseline.processing_configuration_sha256,
        "baseline_sdk_configuration_sha256": baseline.sdk_configuration_sha256,
        "extension_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "document_timeout_seconds": timeout_seconds,
        "selected_runtime": selected.model_dump(mode="json"),
        "selected_processing_configuration_sha256": selected.processing_configuration_sha256,
        "sdk_configuration_sha256": resolved["configuration_sha256"],
        "acceptance_eligible": False,
    }
    profile["experiment_sha256"] = hashlib.sha256(json_bytes(profile)).hexdigest()
    return fresh, resolved, profile


def complete_page_coverage(captured: Mapping[str, object], source_pages: int) -> bool:
    """Status alone cannot certify an original's complete ordered page coverage."""
    if type(source_pages) is not int or not 1 <= source_pages <= 2_000:
        return False
    if captured.get("status") != "success" or captured.get("errors") != []:
        return False
    pages = captured.get("pages")
    document = captured.get("document")
    if not isinstance(pages, list) or not isinstance(document, dict):
        return False
    if len(pages) != source_pages or any(
        not isinstance(page, dict)
        or type(page.get("page_no")) is not int
        or page.get("page_no") != index
        or not isinstance(page.get("parsed_page"), dict)
        for index, page in enumerate(pages, start=1)
    ):
        return False
    assembled = document.get("pages")
    if not isinstance(assembled, dict) or set(assembled) != {
        str(index) for index in range(1, source_pages + 1)
    }:
        return False
    return all(
        isinstance(page, dict)
        and type(page.get("page_no")) is int
        and page.get("page_no") == int(key)
        for key, page in assembled.items()
    )


def write_capture(path: Path, captured: object) -> tuple[int, str]:
    """Stream complete JSON into a fresh file; an over-bound partial stays diagnostic.

    A failed/partial file is never returned as a successful capture. This larger
    experimental raw-capture bound does not alter M1's 64-MiB artifact limit.
    """
    encoder = json.JSONEncoder(
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    size, digest = 0, hashlib.sha256()
    with path.open("xb") as handle:
        for piece in encoder.iterencode(captured):
            encoded = piece.encode("utf-8")
            if size + len(encoded) > MAX_CAPTURE_BYTES:
                raise ValueError("The whole-filing capture exceeds its explicit byte bound.")
            handle.write(encoded)
            digest.update(encoded)
            size += len(encoded)
    return size, digest.hexdigest()
