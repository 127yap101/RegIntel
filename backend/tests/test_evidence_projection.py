"""Exact projection excludes processed/assembled support and preserves Unicode."""

import hashlib
import json
from uuid import UUID

import pytest

from backend.tests.evidence_fixtures import synthetic_artifact, synthetic_configuration
from regintel.contracts.models import PdfRectangle
from regintel.evidence import projection
from regintel.evidence.projection import ProjectionError, project_parse
from regintel.parsing.models import ParseArtifact, ParsedBlock


def replace_block(artifact: ParseArtifact, block: ParsedBlock) -> ParseArtifact:
    return artifact.model_copy(update={"blocks": (block, *artifact.blocks[1:])})


def test_original_unicode_and_full_artifact_survive_projection():
    configuration = synthetic_configuration()
    artifact = synthetic_artifact(configuration=configuration)
    result = project_parse(artifact, configuration)
    assert result.version.block_count == 2
    assert result.version.evidence_count == 1
    assert result.version.table_count == result.version.cell_count == 0
    assert result.blocks[0].text == artifact.blocks[0].orig
    assert result.blocks[0].text != artifact.blocks[0].text
    assert result.evidence[0].span.quote == artifact.blocks[0].orig
    retained = ParseArtifact.model_validate_json(result.artifact_bytes)
    assert retained == artifact
    assert retained.tables[0].cells[0].orig is None
    assert retained.tables[0].cells[0].column_header is True
    assert result.version.artifact_sha256 == hashlib.sha256(result.artifact_bytes).hexdigest()
    assert (
        result.version.configuration_sha256
        == hashlib.sha256(result.configuration_bytes).hexdigest()
    )
    assert result.version.configuration_sha256 != artifact.provenance.configuration_sha256


def test_repeat_projection_has_stable_canonical_bytes_and_uuid4_evidence():
    configuration = synthetic_configuration()
    artifact = synthetic_artifact(configuration=configuration)
    first, repeated = project_parse(artifact, configuration), project_parse(artifact, configuration)
    assert first == repeated
    assert UUID(first.evidence[0].id).version == 4
    changed = artifact.model_copy(update={"id": str(UUID(int=16, version=4))})
    assert project_parse(changed, configuration).evidence[0].id != first.evidence[0].id


@pytest.mark.parametrize(
    "frame",
    [
        "RAW_PDF_BOTTOM_LEFT",
        "MEDIA_RELATIVE_BOTTOM_LEFT",
        "CROP_ROTATED_BOTTOM_LEFT",
        "CROP_ROTATED_TOP_LEFT",
    ],
)
def test_raw_quadrilateral_is_transformed_in_explicit_selected_frame(frame):
    configuration = synthetic_configuration(frame=frame)
    artifact = synthetic_artifact(configuration=configuration)
    assert project_parse(artifact, configuration).evidence[0].boxes == artifact.blocks[0].boxes


@pytest.mark.parametrize("mutation", ["canonical_box", "raw_quad", "degenerate_quad"])
def test_model_valid_raw_geometry_mismatch_is_rejected_before_persistence(mutation):
    configuration = synthetic_configuration()
    artifact = synthetic_artifact(configuration=configuration)
    block = artifact.blocks[0]
    if mutation == "canonical_box":
        block = block.model_copy(
            update={"boxes": (PdfRectangle(x0=41.0, y0=40.0, x1=201.0, y1=60.0),)}
        )
    else:
        reported = block.provenance[0]
        raw = reported.raw_rectangle
        assert raw is not None
        if mutation == "raw_quad":
            raw = raw.model_copy(update={"r_x0": raw.r_x0 + 1, "r_x3": raw.r_x3 + 1})
        else:
            raw = raw.model_copy(update={"r_x0": raw.r_x1, "r_x3": raw.r_x2})
        block = block.model_copy(
            update={"provenance": (reported.model_copy(update={"raw_rectangle": raw}),)}
        )
    malformed = ParseArtifact.model_validate(
        replace_block(artifact, block).model_dump(mode="python")
    )
    with pytest.raises(ProjectionError, match="^ARTIFACT_INVALID$"):
        project_parse(malformed, configuration)


@pytest.mark.parametrize("mutation", ["index", "source_ref", "raw_missing", "reported_page"])
def test_missing_low_level_support_cannot_create_exact_evidence(mutation):
    configuration = synthetic_configuration()
    artifact = synthetic_artifact(configuration=configuration)
    block = artifact.blocks[0]
    if mutation == "index":
        block = block.model_copy(update={"source_cell_index": None})
    elif mutation == "source_ref":
        block = block.model_copy(update={"source_ref": "page/0/text-cell/1"})
    else:
        reported = block.provenance[0].model_copy(
            update={
                "raw_rectangle": None,
            }
            if mutation == "raw_missing"
            else {"page_no": 2}
        )
        block = block.model_copy(update={"provenance": (reported,)})
    result = project_parse(replace_block(artifact, block), configuration)
    assert result.version.block_count == 2
    assert result.evidence == ()


def test_ocr_is_explicit_support_without_semantic_acceptance():
    configuration = synthetic_configuration()
    artifact = synthetic_artifact(configuration=configuration)
    block = artifact.blocks[0].model_copy(update={"from_ocr": True, "ocr_score": 0.87})
    result = project_parse(replace_block(artifact, block), configuration)
    assert len(result.evidence) == 1
    assert json.loads(result.artifact_bytes)["blocks"][0]["ocr_score"] == 0.87


def test_unmapped_original_remains_sidecar_only():
    configuration = synthetic_configuration()
    artifact = synthetic_artifact(configuration=configuration)
    block = artifact.blocks[0].model_copy(
        update={
            "page_id": None,
            "page_index": None,
            "boxes": None,
            "unavailable_reasons": ("PAGE_MAPPING_UNAVAILABLE", "GEOMETRY_UNAVAILABLE"),
        }
    )
    result = project_parse(replace_block(artifact, block), configuration)
    assert result.version.block_count == 1
    assert result.evidence == ()
    assert ParseArtifact.model_validate_json(result.artifact_bytes).blocks[0].orig == block.orig


def test_model_copy_cannot_bypass_exact_unicode_validation():
    configuration = synthetic_configuration()
    artifact = synthetic_artifact(configuration=configuration)
    block = artifact.blocks[0].model_copy(update={"orig": "wrong original"})
    with pytest.raises(ProjectionError, match="^ARTIFACT_INVALID$"):
        project_parse(replace_block(artifact, block), configuration)


@pytest.mark.parametrize(
    "field",
    [
        "coordinate_frame",
        "sdk_configuration_sha256",
        "model_manifest_sha256",
        "package_manifest_sha256",
        "adapter_code_sha256",
    ],
)
def test_selected_configuration_mismatch_fails_closed(field):
    configuration = synthetic_configuration()
    artifact = synthetic_artifact(configuration=configuration)
    changed = configuration.model_copy(
        update={
            field: "CROP_ROTATED_TOP_LEFT" if field == "coordinate_frame" else "f" * 64,
        }
    )
    with pytest.raises(ProjectionError, match="^PARSER_CONFIGURATION_MISMATCH$"):
        project_parse(artifact, changed)


@pytest.mark.parametrize("name", ["MAX_ARTIFACT_BYTES", "MAX_CONFIGURATION_BYTES"])
def test_serialized_storage_limits_are_enforced_before_database_writes(monkeypatch, name):
    configuration = synthetic_configuration()
    artifact = synthetic_artifact(configuration=configuration)
    monkeypatch.setattr(projection, name, 1)
    with pytest.raises(ProjectionError, match="^ARTIFACT_INVALID$"):
        project_parse(artifact, configuration)
