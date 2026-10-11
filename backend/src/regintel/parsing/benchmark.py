"""Deterministic engineering transcription checks against frozen authored recipes.

This module neither runs a parser nor accepts evidence. It uses page-local original
TextCell strings, never Markdown or a best-looking alternative transcription.
"""

import argparse
import hashlib
import json
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Literal, Self, cast

from pydantic import Field, model_validator

from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import PositiveSafeInteger, Sha256Hash
from regintel.fixtures.sources import DocumentSource, fixture_sources, source_text_catalog
from regintel.ingestion.models import StoredText

MAX_EDIT_COMPARISONS = 20_000_000
MAX_PAGE_TEXT = 100_000
NORMALIZATION = "NFC; collapse Unicode whitespace to one ASCII space; case/punctuation retained"
FixtureKey = Literal["base", "corrigendum", "later_conflict"]
BoundedText = Annotated[StoredText, Field(max_length=MAX_PAGE_TEXT)]
Seconds = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]


class BenchmarkCell(ContractModel):
    orig: BoundedText
    text: BoundedText
    from_ocr: bool


class BenchmarkPage(ContractModel):
    page_no: Annotated[PositiveSafeInteger, Field(le=2_000)]
    cells: Annotated[tuple[BenchmarkCell, ...], Field(strict=False, max_length=100_000)]

    @model_validator(mode="after")
    def bound_text(self) -> Self:
        if sum(len(cell.orig) + 1 for cell in self.cells) > MAX_PAGE_TEXT:
            raise ValueError("Original page text exceeds the engineering benchmark bound.")
        return self


class ProbeCapture(ContractModel):
    status: Annotated[StoredText, Field(min_length=1, max_length=128)]
    source_sha256: Sha256Hash
    configuration_sha256: Sha256Hash | None
    pages: Annotated[tuple[BenchmarkPage, ...], Field(strict=False, max_length=2_000)]

    @model_validator(mode="after")
    def unique_pages(self) -> Self:
        numbers = tuple(page.page_no for page in self.pages)
        if len(numbers) != len(set(numbers)):
            raise ValueError("Probe page numbers must be unique.")
        return self


class ProbeMeasurements(ContractModel):
    """Fields actually printed by the controlled Linux conversion probe."""

    status: Annotated[StoredText, Field(min_length=1, max_length=128)]
    initialization_seconds: Seconds
    conversion_seconds: Seconds
    max_rss_kib: PositiveSafeInteger
    network_attempts: Annotated[int, Field(strict=True, ge=0)]
    network_disabled: bool
    output_bytes: PositiveSafeInteger


class FixtureReference(ContractModel):
    document_key: FixtureKey
    source_sha256: Sha256Hash
    manifest_sha256: Sha256Hash


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("A JSON object with string keys is required.")
    return cast(dict[str, object], value)


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("A JSON array is required.")
    return cast(list[object], value)


def project_capture(value: object) -> ProbeCapture:
    """Project inspected SDK fields; leave the complete raw capture unmodified.

    Cells may also contain rect/index/confidence/font metadata. Those fields are
    not silently interpreted as calibrated geometry or OCR quality here.
    """
    raw = _object(value)
    pages: list[dict[str, object]] = []
    for page_value in _array(raw.get("pages")):
        page = _object(page_value)
        cells = [
            {key: _object(cell).get(key) for key in ("orig", "text", "from_ocr")}
            for cell in _array(page.get("cells"))
        ]
        pages.append({"page_no": page.get("page_no"), "cells": cells})
    configuration = raw.get("configuration")
    configuration_hash = (
        None if configuration is None else _object(configuration).get("configuration_sha256")
    )
    return ProbeCapture.model_validate(
        {
            "status": raw.get("status"),
            "source_sha256": raw.get("source_sha256"),
            "configuration_sha256": configuration_hash,
            "pages": pages,
        }
    )


def _document(key: FixtureKey) -> DocumentSource:
    return next(document for document in fixture_sources() if document.key == key)


def reference_from_manifest(manifest_bytes: bytes, key: FixtureKey) -> FixtureReference:
    """Bind the authored recipe to its existing sidecar's PDF hash, without generation."""
    raw = _object(json.loads(manifest_bytes))
    if raw.get("fixture_version") != "1.0.0" or raw.get("synthetic") is not True:
        raise ValueError("The existing versioned synthetic fixture manifest is required.")
    if raw.get("source_text") != source_text_catalog():
        raise ValueError("The fixture manifest's source text differs from its frozen recipe.")
    document = _document(key)
    matches = [
        _object(recipe)
        for recipe in _array(raw.get("recipes"))
        if _object(recipe).get("key") == key
    ]
    if len(matches) != 1 or matches[0].get("filename") != document.filename:
        raise ValueError("One matching fixture document is required.")
    recipe_pages = _array(matches[0].get("pages"))
    if len(recipe_pages) != len(document.pages):
        raise ValueError("Fixture manifest page coverage differs from its frozen recipe.")
    for value, page in zip(recipe_pages, document.pages, strict=True):
        recipe_page = _object(value)
        blocks = [_object(block) for block in _array(recipe_page.get("blocks"))]
        if (
            recipe_page.get("page_index") != page.page_index
            or recipe_page.get("raster_only") is not page.raster_only
            or [(block.get("alias"), block.get("text")) for block in blocks]
            != [(block.alias, block.text) for block in page.blocks]
        ):
            raise ValueError("Fixture manifest page text differs from its frozen recipe.")
    return FixtureReference.model_validate(
        {
            "document_key": key,
            "source_sha256": matches[0].get("sha256"),
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        }
    )


def normalize_text(text: str) -> str:
    """Only metric comparison changes; stored input text is never normalized in place."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def edit_distance[T](reference: Sequence[T], observed: Sequence[T]) -> int:
    """Unit-cost Levenshtein distance, Unicode code points or explicit sequence tokens."""
    prefix = 0
    while prefix < min(len(reference), len(observed)) and reference[prefix] == observed[prefix]:
        prefix += 1
    reference, observed = reference[prefix:], observed[prefix:]
    suffix = 0
    while (
        suffix < min(len(reference), len(observed))
        and reference[len(reference) - suffix - 1] == observed[len(observed) - suffix - 1]
    ):
        suffix += 1
    if suffix:
        reference, observed = reference[:-suffix], observed[:-suffix]
    if len(reference) * len(observed) > MAX_EDIT_COMPARISONS:
        raise ValueError("Edit-distance work exceeds the bounded engineering benchmark.")
    if len(reference) < len(observed):
        reference, observed = observed, reference
    previous = list(range(len(observed) + 1))
    for reference_index, reference_token in enumerate(reference, start=1):
        current = [reference_index]
        for observed_index, observed_token in enumerate(observed, start=1):
            current.append(
                min(
                    previous[observed_index] + 1,
                    current[observed_index - 1] + 1,
                    previous[observed_index - 1] + (reference_token != observed_token),
                )
            )
        previous = current
    return previous[-1]


@dataclass(frozen=True, slots=True)
class TranscriptionScore:
    reference_raw: str
    observed_raw: str
    raw_exact_match: bool
    normalization: str
    normalized_exact_match: bool
    reference_characters: int
    observed_characters: int
    character_edits: int
    character_error_rate: float | None
    reference_words: int
    observed_words: int
    word_edits: int
    word_error_rate: float | None
    reference_lines: int
    observed_lines: int
    raw_exact_lines: int
    normalized_exact_lines: int
    unmatched_reference_lines: int
    unmatched_observed_lines: int
    ordered_line_edits: int


def score_transcription(reference_raw: str, observed_raw: str) -> TranscriptionScore:
    if max(len(reference_raw), len(observed_raw)) > MAX_PAGE_TEXT:
        raise ValueError("Text exceeds the engineering benchmark bound.")
    reference, observed = normalize_text(reference_raw), normalize_text(observed_raw)
    words, observed_words = reference.split(), observed.split()
    reference_lines = tuple(line for line in reference_raw.splitlines() if line.strip())
    observed_lines = tuple(line for line in observed_raw.splitlines() if line.strip())
    normalized_lines = tuple(normalize_text(line) for line in reference_lines)
    normalized_observed_lines = tuple(normalize_text(line) for line in observed_lines)
    raw_matches = sum((Counter(reference_lines) & Counter(observed_lines)).values())
    normalized_matches = sum(
        (Counter(normalized_lines) & Counter(normalized_observed_lines)).values()
    )
    character_edits = edit_distance(reference, observed)
    word_edits = edit_distance(words, observed_words)
    return TranscriptionScore(
        reference_raw,
        observed_raw,
        reference_raw == observed_raw,
        NORMALIZATION,
        reference == observed,
        len(reference),
        len(observed),
        character_edits,
        character_edits / len(reference) if reference else None,
        len(words),
        len(observed_words),
        word_edits,
        word_edits / len(words) if words else None,
        len(reference_lines),
        len(observed_lines),
        raw_matches,
        normalized_matches,
        len(reference_lines) - normalized_matches,
        len(observed_lines) - normalized_matches,
        edit_distance(normalized_lines, normalized_observed_lines),
    )


def fixture_page_text(document: DocumentSource, page_index: int) -> str:
    """Full drawn text, including labels, from the inspected native/raster recipes."""
    page = document.pages[page_index]
    lines = [
        "SYNTHETIC TEST FIXTURE - INVENTED DISCLOSURES",
        f"{document.title} | source page {page_index + 1}",
    ]
    if document.parent_key is not None and not page.raster_only:
        lines.append("Explicit parent: synthetic-base.pdf; unaffected facts are retained.")
    for block in page.blocks:
        lines.extend(line for line in block.text.split("\n") if line)
    lines.append(
        "Authored image transcription in sidecar; no OCR has been run."
        if page.raster_only
        else "Authored engineering fixture. Not a SEBI filing or research gold data."
    )
    return "\n".join(lines)


def benchmark_fixture(
    capture: ProbeCapture,
    reference: FixtureReference,
    measurements: ProbeMeasurements | None = None,
) -> dict[str, object]:
    if capture.source_sha256 != reference.source_sha256:
        raise ValueError("Probe bytes differ from the selected authored fixture source hash.")
    if measurements is not None and measurements.status != capture.status:
        raise ValueError("The actual runtime summary and capture statuses differ.")
    document = _document(reference.document_key)
    pages = {page.page_no: page for page in capture.pages}
    if set(pages) - set(range(1, len(document.pages) + 1)):
        raise ValueError("Probe includes a page outside the selected fixture.")
    reports: list[dict[str, object]] = []
    for source_page in document.pages:
        page_no = source_page.page_index + 1
        page = pages.get(page_no)
        cells = () if page is None else page.cells
        observed = "\n".join(cell.orig for cell in cells)
        normalized_observed = normalize_text(observed)
        blocks: list[dict[str, object]] = []
        for block in source_page.blocks:
            blocks.append(
                {
                    "alias": block.alias,
                    "reference_raw": block.text,
                    "visible_text": bool(block.text),
                    "raw_substring_present": block.text in observed if block.text else None,
                    "normalized_substring_present": (
                        normalize_text(block.text) in normalized_observed if block.text else None
                    ),
                }
            )
        reports.append(
            {
                "page_no": page_no,
                "capture_page_present": page is not None,
                "reference_raster_only": source_page.raster_only,
                "reference_rotation": source_page.geometry.rotation,
                "observed_cells": len(cells),
                "observed_native_cells": sum(not cell.from_ocr for cell in cells),
                "observed_ocr_cells": sum(cell.from_ocr for cell in cells),
                "processed_text_differs_from_orig_cells": sum(
                    cell.text != cell.orig for cell in cells
                ),
                "transcription": asdict(
                    score_transcription(
                        fixture_page_text(document, source_page.page_index), observed
                    )
                ),
                "authored_blocks": blocks,
            }
        )
    return {
        "benchmark_version": "1.0.0",
        "reference_kind": "AUTHORED_ENGINEERING_RECIPE",
        "fixture_key": reference.document_key,
        "source_sha256": capture.source_sha256,
        "reference_manifest_sha256": reference.manifest_sha256,
        "configuration_sha256": capture.configuration_sha256,
        "conversion_status": capture.status,
        "expected_pages": len(document.pages),
        "observed_pages": len(capture.pages),
        "pages": reports,
        "runtime_measurements": (
            None if measurements is None else measurements.model_dump(mode="json")
        ),
        "runtime_semantics": {
            "initialization_seconds": "Converter construction and imports; not model loading.",
            "conversion_seconds": "Cold conversion, including lazily loaded model initialization.",
            "max_rss_kib": "Linux process lifetime peak resident set; not a conversion-only delta.",
        },
        "limitations": [
            "Authored synthetic text is not manually annotated real-filing gold data.",
            "PDF clipping, source rendering and parser cell segmentation require visual review.",
            "Line counts depend on cell segmentation; exact matches use one-to-one multisets.",
            "Substring presence does not establish table context, geometry or accepted facts.",
            "Blank authored cells have no visible text and receive no transcription success.",
            "Measured OCR text is a transcription; its exact quote does not prove source truth.",
            "Runtime summary is supplied separately; this module never invents timing or memory.",
        ],
    }


def _read_bounded(path: Path) -> bytes:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ValueError("An existing absolute regular file is required.")
    with path.open("rb") as handle:
        payload = handle.read(64 * 1024 * 1024 + 1)
    if len(payload) > 64 * 1024 * 1024:
        raise ValueError("Benchmark input exceeds its bounded file size.")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--reference-manifest", required=True, type=Path)
    parser.add_argument(
        "--fixture-key", required=True, choices=["base", "corrigendum", "later_conflict"]
    )
    parser.add_argument("--measurements", type=Path)
    arguments = parser.parse_args()
    capture_bytes = _read_bounded(arguments.capture)
    capture = project_capture(json.loads(capture_bytes))
    reference = reference_from_manifest(
        _read_bounded(arguments.reference_manifest), cast(FixtureKey, arguments.fixture_key)
    )
    measurements = (
        None
        if arguments.measurements is None
        else ProbeMeasurements.model_validate_json(_read_bounded(arguments.measurements))
    )
    if measurements is not None and measurements.output_bytes != len(capture_bytes):
        raise ValueError("The runtime summary byte count differs from the actual capture file.")
    report = benchmark_fixture(capture, reference, measurements)
    report["capture_file_sha256"] = hashlib.sha256(capture_bytes).hexdigest()
    # Escaped JSON survives Windows legacy stdout codecs without changing decoded
    # original Unicode or the hash of the unmodified UTF-8 capture file.
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
