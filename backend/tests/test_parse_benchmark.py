"""Benchmark arithmetic and source binding, without a claimed parser/OCR execution."""

import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from regintel.fixtures.sources import fixture_sources, source_text_catalog
from regintel.parsing import benchmark

SOURCE_HASH = "a" * 64


def _raw_capture(*, omit_page: int | None = None) -> dict[str, object]:
    document = fixture_sources()[0]
    pages: list[dict[str, object]] = []
    for page in document.pages:
        page_no = page.page_index + 1
        if page_no == omit_page:
            continue
        cells = [
            {
                "orig": line,
                "text": line,
                "from_ocr": page.raster_only,
                "rect": {"uninterpreted": "upstream geometry"},
                "confidence": 1.0,
            }
            for line in benchmark.fixture_page_text(document, page.page_index).splitlines()
        ]
        pages.append({"page_no": page_no, "cells": cells, "parsed_page": None})
    return {
        "source_sha256": SOURCE_HASH,
        "status": "success",
        "configuration": {"configuration_sha256": "b" * 64, "other_options": "retained raw"},
        "pages": pages,
        "document": {"texts": [{"text": "Must never become an alternative transcription"}]},
    }


def _reference() -> benchmark.FixtureReference:
    return benchmark.FixtureReference(
        document_key="base", source_sha256=SOURCE_HASH, manifest_sha256="c" * 64
    )


def _manifest() -> dict[str, object]:
    return {
        "fixture_version": "1.0.0",
        "synthetic": True,
        "source_text": source_text_catalog(),
        "recipes": [
            {
                "key": document.key,
                "filename": document.filename,
                "sha256": SOURCE_HASH,
                "pages": [
                    {
                        "page_index": page.page_index,
                        "raster_only": page.raster_only,
                        "blocks": [
                            {"alias": block.alias, "text": block.text} for block in page.blocks
                        ],
                    }
                    for page in document.pages
                ],
            }
            for document in fixture_sources()
        ],
    }


@pytest.mark.parametrize(
    ("reference", "observed", "distance"),
    [
        ("", "", 0),
        ("", "abc", 3),
        ("abc", "", 3),
        ("kitten", "sitting", 3),
        ("😀a", "😀b", 1),
        ("café", "cafe\u0301", 2),
        (("same", "missing"), ("same", "added"), 1),
        (("one", "two"), ("two", "one"), 2),
    ],
)
def test_edit_distance_counts_unicode_codepoints_or_explicit_tokens(
    reference: str | tuple[str, ...], observed: str | tuple[str, ...], distance: int
) -> None:
    assert benchmark.edit_distance(reference, observed) == distance
    assert benchmark.edit_distance(observed, reference) == distance


def test_edit_distance_bounds_work_after_trimming_equal_unicode() -> None:
    text = "😀" * 100_000
    assert benchmark.edit_distance(text, text) == 0
    assert benchmark.edit_distance(text + "x", text + "y") == 1
    with pytest.raises(ValueError, match="work exceeds"):
        benchmark.edit_distance("a" * 5_000, "b" * 5_000)


def test_metric_normalization_is_explicit_and_preserves_raw_numerics_and_case() -> None:
    score = benchmark.score_transcription("café\nINR\u00a010.00", "cafe\u0301  INR 10.00")
    assert score.reference_raw == "café\nINR\u00a010.00"
    assert score.observed_raw == "cafe\u0301  INR 10.00"
    assert score.raw_exact_match is False and score.normalized_exact_match is True
    assert score.character_edits == score.word_edits == 0
    assert score.reference_characters == len("café INR 10.00")
    changed = benchmark.score_transcription("INR 10.00", "inr 100.00")
    assert changed.character_edits == 4
    assert changed.word_edits == 2
    assert changed.character_error_rate == 4 / 9
    assert changed.word_error_rate == 1.0
    assert changed.normalized_exact_match is False


def test_empty_reference_is_unavailable_and_errors_can_exceed_one() -> None:
    empty = benchmark.score_transcription("", "hallucinated text")
    assert empty.character_edits == len("hallucinated text")
    assert empty.word_edits == 2
    assert empty.character_error_rate is None and empty.word_error_rate is None
    assert empty.unmatched_observed_lines == 1
    extra = benchmark.score_transcription("a", "abcde")
    assert extra.character_error_rate == 4.0
    with pytest.raises(ValueError, match="Text exceeds"):
        benchmark.score_transcription("a" * 100_001, "")


def test_line_matching_does_not_reuse_duplicates_or_hide_order_and_extras() -> None:
    score = benchmark.score_transcription("same\nsame\nlast", " last \nsame\nextra")
    assert score.reference_lines == score.observed_lines == 3
    assert score.raw_exact_lines == 1
    assert score.normalized_exact_lines == 2
    assert score.unmatched_reference_lines == score.unmatched_observed_lines == 1
    assert score.ordered_line_edits == 2
    assert score.raw_exact_match is False


def test_projection_reads_original_cells_without_export_or_confidence_fallback() -> None:
    raw = _raw_capture()
    projected = benchmark.project_capture(raw)
    assert projected.configuration_sha256 == "b" * 64
    assert projected.pages[2].cells[0].from_ocr is True
    assert projected.pages[3].cells[0].from_ocr is False
    assert raw["document"] == {
        "texts": [{"text": "Must never become an alternative transcription"}]
    }
    with pytest.raises(ValidationError):
        benchmark.BenchmarkCell(orig="x", text="x", from_ocr=True, confidence=0.99)


@pytest.mark.parametrize(
    "change", ["missing_orig", "string_boolean", "duplicate_page", "null_cells"]
)
def test_projection_rejects_unsupported_or_ambiguous_cell_input(change: str) -> None:
    raw = _raw_capture()
    pages = cast(list[dict[str, object]], raw["pages"])
    cells = cast(list[dict[str, object]], pages[0]["cells"])
    if change == "missing_orig":
        del cells[0]["orig"]
    elif change == "string_boolean":
        cells[0]["from_ocr"] = "false"
    elif change == "duplicate_page":
        pages[1]["page_no"] = 1
    else:
        pages[0]["cells"] = None
    with pytest.raises((ValidationError, ValueError)):
        benchmark.project_capture(raw)


def test_fixture_report_exposes_raster_page_three_native_page_four_and_blank_limit() -> None:
    report = benchmark.benchmark_fixture(benchmark.project_capture(_raw_capture()), _reference())
    assert report["expected_pages"] == report["observed_pages"] == 4
    assert report["runtime_measurements"] is None
    pages = cast(list[dict[str, object]], report["pages"])
    assert [page["reference_rotation"] for page in pages] == [0, 90, 180, 270]
    assert [page["reference_raster_only"] for page in pages] == [False, False, True, False]
    assert pages[2]["observed_native_cells"] == 0
    assert pages[3]["observed_ocr_cells"] == 0
    for page in pages:
        score = cast(dict[str, object], page["transcription"])
        assert score["raw_exact_match"] is True
        assert score["character_error_rate"] == score["word_error_rate"] == 0.0
    blocks = cast(list[dict[str, object]], pages[1]["authored_blocks"])
    blank = next(block for block in blocks if block["alias"] == "blank_value")
    dash = next(block for block in blocks if block["alias"] == "dash_value")
    assert blank["visible_text"] is False
    assert blank["raw_substring_present"] is blank["normalized_substring_present"] is None
    assert dash["reference_raw"] == "-" and dash["raw_substring_present"] is True
    assert "no OCR has been run" in benchmark.fixture_page_text(fixture_sources()[0], 2)


def test_missing_capture_page_scores_all_reference_text_as_deleted() -> None:
    report = benchmark.benchmark_fixture(
        benchmark.project_capture(_raw_capture(omit_page=3)), _reference()
    )
    pages = cast(list[dict[str, object]], report["pages"])
    missing = pages[2]
    assert report["observed_pages"] == 3
    assert missing["capture_page_present"] is False
    assert missing["observed_cells"] == 0
    score = cast(dict[str, object], missing["transcription"])
    assert score["character_error_rate"] == score["word_error_rate"] == 1.0


def test_source_mismatch_and_out_of_fixture_page_refuse_benchmark() -> None:
    raw = _raw_capture()
    raw["source_sha256"] = "d" * 64
    with pytest.raises(ValueError, match="source hash"):
        benchmark.benchmark_fixture(benchmark.project_capture(raw), _reference())
    raw = _raw_capture()
    cast(list[dict[str, object]], raw["pages"])[0]["page_no"] = 5
    with pytest.raises(ValueError, match="outside"):
        benchmark.benchmark_fixture(benchmark.project_capture(raw), _reference())


def test_manifest_binding_retains_byte_hash_and_refuses_recipe_drift() -> None:
    value = _manifest()
    payload = json.dumps(value).encode()
    reference = benchmark.reference_from_manifest(payload, "base")
    assert reference.source_sha256 == SOURCE_HASH
    assert reference.manifest_sha256 == hashlib.sha256(payload).hexdigest()
    value["source_text"] = {"ocr_region": "invented replacement"}
    with pytest.raises(ValueError, match="source text differs"):
        benchmark.reference_from_manifest(json.dumps(value).encode(), "base")
    value = _manifest()
    recipes = cast(list[dict[str, object]], value["recipes"])
    pages = cast(list[dict[str, object]], recipes[0]["pages"])
    cast(list[dict[str, object]], pages[2]["blocks"])[0]["text"] = "changed raster source"
    with pytest.raises(ValueError, match="page text differs"):
        benchmark.reference_from_manifest(json.dumps(value).encode(), "base")


def test_runtime_is_supplied_exactly_and_nonfinite_or_mismatched_results_fail() -> None:
    data: dict[str, object] = {
        "status": "success",
        "initialization_seconds": 3.25,
        "conversion_seconds": 7.5,
        "max_rss_kib": 1024,
        "network_attempts": 0,
        "network_disabled": True,
        "output_bytes": 3000,
    }
    measurements = benchmark.ProbeMeasurements.model_validate(data)
    capture = benchmark.project_capture(_raw_capture())
    report = benchmark.benchmark_fixture(capture, _reference(), measurements)
    assert report["runtime_measurements"] == data
    data["conversion_seconds"] = float("nan")
    with pytest.raises(ValidationError):
        benchmark.ProbeMeasurements.model_validate(data)
    mismatch = measurements.model_copy(update={"status": "partial_success"})
    with pytest.raises(ValueError, match="statuses differ"):
        benchmark.benchmark_fixture(capture, _reference(), mismatch)


def test_cli_binds_actual_capture_file_hash_and_reads_no_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    capture_path = tmp_path / "capture.json"
    raw_capture = _raw_capture()
    pages = cast(list[dict[str, object]], raw_capture["pages"])
    cells = cast(list[dict[str, object]], pages[0]["cells"])
    cells[0]["orig"] = cells[0]["text"] = "Greek epsilon ε and emoji 😀"
    capture_bytes = json.dumps(raw_capture, ensure_ascii=False).encode()
    capture_path.write_bytes(capture_bytes)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark",
            "--capture",
            str(capture_path),
            "--reference-manifest",
            str(manifest_path),
            "--fixture-key",
            "base",
        ],
    )
    benchmark.main()
    stdout = capsys.readouterr().out
    assert stdout.isascii()
    output = json.loads(stdout)
    assert "Greek epsilon ε and emoji 😀" in output["pages"][0]["transcription"]["observed_raw"]
    assert output["capture_file_sha256"] == hashlib.sha256(capture_bytes).hexdigest()
    assert output["runtime_measurements"] is None
    assert len(list(tmp_path.iterdir())) == 2
    measurements_path = tmp_path / "runtime.json"
    measurements_path.write_text(
        json.dumps(
            {
                "status": "success",
                "initialization_seconds": 1.0,
                "conversion_seconds": 2.0,
                "max_rss_kib": 1024,
                "network_attempts": 0,
                "network_disabled": True,
                "output_bytes": len(capture_bytes) + 1,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--measurements", str(measurements_path)])
    with pytest.raises(ValueError, match="byte count differs"):
        benchmark.main()
    with pytest.raises(ValueError, match="absolute regular file"):
        benchmark._read_bounded(Path("relative.json"))
    assert asdict(benchmark.score_transcription("same", "same"))["raw_exact_match"] is True
