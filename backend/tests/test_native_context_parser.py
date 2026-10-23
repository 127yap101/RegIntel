"""Native/context integration controls; fixture declarations are not native parser gold."""

import hashlib
import json
from dataclasses import replace

import pytest

from backend.tests.native_context_fixtures import native_case
from regintel.evidence.projection import ProjectionError
from regintel.numerical.evidence_binding import bind_context_evidence
from regintel.numerical.models import page_capture_id
from regintel.numerical.source_pages import build_page_capture, capture_bytes
from regintel.parsing.native_context import (
    ContextCapture,
    build_native_context_parse,
    project_native_context,
)


def test_complete_native_coverage_projects_actual_context_word_shapes_and_binds(tmp_path):
    case = native_case(tmp_path)
    result = case.result
    projection = project_native_context(result.artifact, result.configuration)
    assert len(projection.pages) == 2
    assert all(word.source.page_index == 1 for word in projection.evidence)
    assert projection.version.table_count == projection.version.cell_count == 0
    assert len(projection.evidence) == len(case.record.source_input.pages[0].capture.words)
    assert result.table_sources and result.configuration.schema_version == "1.1.0"
    binding = bind_context_evidence(case.record, result.artifact, result.configuration)
    assert binding.phrases[0].words[0].evidence.span.quote == "2,500.20"
    assert (
        binding.acceptance_eligible is False and binding.mandatory_m1_validation_complete is False
    )
    assert binding.review_required is True
    assert projection.artifact_bytes.startswith(b"{")


@pytest.mark.parametrize(
    "field",
    ["adapter_code_sha256", "sdk_code_sha256", "backend_code_sha256", "geometry_code_sha256"],
)
def test_native_projection_rejects_changed_runtime_identity(tmp_path, field):
    case = native_case(tmp_path)
    changed = case.result.configuration.model_copy(update={field: "f" * 64})
    with pytest.raises((ValueError, ProjectionError)):
        project_native_context(case.result.artifact, changed)


def test_native_context_rebuild_rejects_changed_or_wrong_raw_capture(tmp_path):
    case = native_case(tmp_path)
    source = case.result.captures[0]
    wrong = replace(source, raw_bytes=source.raw_bytes + b" ")
    result = case.result
    with pytest.raises(ValueError, match="immutable"):
        build_native_context_parse(
            result.bank,
            source=case.source,
            baseline=result.configuration.context_parser_configuration,
            captures=(wrong,),
            parse_id=result.artifact.id,
            filing_id=result.artifact.filing_id,
            filing_version_id=result.artifact.filing_version_id,
            source_blob_id=result.artifact.source_blob_id,
        )


def test_raw_native_corners_remain_bottom_left_and_contextual_corners_remain_top_left(tmp_path):
    case = native_case(tmp_path)
    native_page = list(case.result.bank.pages())[1]
    contextual = case.result.captures[0].stored.capture
    native = native_page.words[0].raw_rectangle
    top = contextual.words[0].raw_rectangle
    assert native.coord_origin == "BOTTOMLEFT" and top.coord_origin == "TOPLEFT"
    assert native_page.page_geometry.height - native.r_y0 == top.r_y0
    assert native != top
    before = hashlib.sha256(
        (case.result.bank.directory / "page-0001.json").read_bytes()
    ).hexdigest()
    project_native_context(case.result.artifact, case.result.configuration)
    assert (
        hashlib.sha256((case.result.bank.directory / "page-0001.json").read_bytes()).hexdigest()
        == before
    )


@pytest.mark.parametrize("change", ["duplicate", "source_version", "source_blob", "sdk_identity"])
def test_native_context_requires_unique_source_and_stage_membership(tmp_path, change):
    case = native_case(tmp_path)
    result = case.result
    captures = result.captures
    baseline = result.configuration.context_parser_configuration
    if change == "duplicate":
        captures = (*captures, *captures)
    elif change == "sdk_identity":
        baseline = baseline.model_copy(update={"sdk_configuration_sha256": "f" * 64})
    else:
        field = "filing_version_id" if change == "source_version" else "source_blob_id"
        stored = captures[0].stored.model_copy(
            update={field: "00000000-0000-4000-8000-000000000001"}
        )
        captures = (replace(captures[0], stored=stored),)
    with pytest.raises(ValueError):
        build_native_context_parse(
            result.bank,
            source=case.source,
            baseline=baseline,
            captures=captures,
            parse_id=result.artifact.id,
            filing_id=result.artifact.filing_id,
            filing_version_id=result.artifact.filing_version_id,
            source_blob_id=result.artifact.source_blob_id,
        )


@pytest.mark.parametrize("change", ["text", "corners"])
def test_native_context_rejects_rehashed_but_different_original_words(tmp_path, change):
    case = native_case(tmp_path)
    result = case.result
    supplied = result.captures[0]
    raw = json.loads(supplied.raw_bytes)
    word = raw["pages"][0]["parsed_page"]["word_cells"][0]
    if change == "text":
        word["orig"] = "Unsupported"
    else:
        word["rect"]["r_x0"] += 0.01
    body = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    prepared = build_page_capture(
        raw,
        source=case.source,
        pdf_page=2,
        expected_source_sha256=result.artifact.source_sha256,
        expected_sdk_configuration_sha256=result.configuration.sdk_configuration_sha256,
    )
    digest = hashlib.sha256(capture_bytes(prepared)).hexdigest()
    stored = supplied.stored.model_copy(
        update={
            "capture": prepared,
            "prepared_sha256": digest,
            "id": page_capture_id(
                supplied.stored.filing_version_id, supplied.stored.source_blob_id, digest
            ),
        }
    )
    with pytest.raises(ValueError, match="corner transform"):
        build_native_context_parse(
            result.bank,
            source=case.source,
            baseline=result.configuration.context_parser_configuration,
            captures=(ContextCapture(stored, body),),
            parse_id=result.artifact.id,
            filing_id=result.artifact.filing_id,
            filing_version_id=result.artifact.filing_version_id,
            source_blob_id=result.artifact.source_blob_id,
        )
