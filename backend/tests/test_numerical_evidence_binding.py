"""Exact M1 word bindings, using declared engineering fixtures rather than real financial facts."""

import hashlib
import json
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from backend.tests.numerical_binding_fixtures import BindingFixture, complete_artifact
from backend.tests.test_numerical_context_records import record
from regintel.contracts.models import TextSpan
from regintel.db.migrations import DatabaseConnection
from regintel.evidence.projection import ProjectionError, project_parse
from regintel.numerical import evidence_binding_models
from regintel.numerical.evidence_binding import EvidenceBindingError, bind_context_evidence
from regintel.numerical.evidence_binding_models import NumericalEvidenceBinding, binding_identity
from regintel.numerical.evidence_binding_repository import _sealed_parse
from regintel.numerical.repository import NumericalSourceError
from regintel.parsing.configuration import canonical_configuration_bytes
from regintel.parsing.models import ParseArtifact, ParseDiagnostic, canonical_artifact_bytes


@pytest.fixture
def fixture(tmp_path: Path) -> BindingFixture:
    return complete_artifact(record(tmp_path))


def bind(
    fixture: BindingFixture, artifact: ParseArtifact | None = None
) -> NumericalEvidenceBinding:
    return bind_context_evidence(
        fixture.record, artifact or fixture.artifact, fixture.configuration
    )


def test_binds_existing_exact_word_ids_and_retained_grid_without_acceptance(
    fixture: BindingFixture,
):
    result = bind(fixture)
    assert NumericalEvidenceBinding.model_validate_json(result.model_dump_json()) == result
    assert bind(fixture) == result
    projected = {
        item.id for item in project_parse(fixture.artifact, fixture.configuration).evidence
    }
    linked = {word.evidence.id for phrase in result.phrases for word in phrase.words}
    captures = {page.id for page in fixture.record.source_input.pages}
    assert linked <= projected and not (linked & captures)
    assert tuple(cell.role for cell in result.cells) == ("value", "row_label", "period_header")
    assert result.cells[0].column_index == 2 and result.cells[0].row_index == 1
    assert all(
        word.evidence.source.page_index == 1 for phrase in result.phrases for word in phrase.words
    )
    assert not result.acceptance_eligible and not result.mandatory_m1_validation_complete
    assert result.review_required


@pytest.mark.parametrize("field", ["filing_version_id", "source_blob_id", "source_sha256"])
def test_same_text_cannot_cross_source_identity(fixture: BindingFixture, field: str):
    value = "0" * 64 if field.endswith("sha256") else str(uuid4())
    wrong = fixture.artifact.model_copy(update={field: value})
    with pytest.raises(EvidenceBindingError, match="SOURCE_MISMATCH"):
        bind(fixture, wrong)


def test_sparse_page_preparation_cannot_be_called_a_complete_parse(fixture: BindingFixture):
    wrong = fixture.artifact.model_copy(
        update={"pages": fixture.artifact.pages[:1], "blocks": (), "tables": ()}
    )
    with pytest.raises(EvidenceBindingError, match="PAGE_COVERAGE_MISMATCH"):
        bind(fixture, wrong)


def test_different_sdk_cannot_reuse_preparation(fixture: BindingFixture):
    configuration = fixture.configuration.model_copy(update={"sdk_configuration_sha256": "0" * 64})
    provenance = fixture.artifact.provenance.model_copy(update={"configuration_sha256": "0" * 64})
    wrong = fixture.artifact.model_copy(update={"provenance": provenance})
    with pytest.raises(EvidenceBindingError, match="SOURCE_MISMATCH"):
        bind_context_evidence(fixture.record, wrong, configuration)


@pytest.mark.parametrize("change", ["removed", "ocr", "geometry", "raw_quad"])
def test_missing_or_changed_native_word_blocks_binding(fixture: BindingFixture, change: str):
    index = fixture.record.source_input.draft.value.phrase.words[0].word_index
    blocks = list(fixture.artifact.blocks)
    block = blocks[index]
    if change == "removed":
        blocks.pop(index)
    elif change == "ocr":
        blocks[index] = block.model_copy(update={"from_ocr": True})
    elif change == "geometry":
        assert block.boxes is not None
        blocks[index] = block.model_copy(
            update={"boxes": (block.boxes[0].model_copy(update={"x0": block.boxes[0].x0 - 1}),)}
        )
    else:
        raw = block.provenance[0].raw_rectangle
        assert raw is not None
        # Rotate the first corner, preserving a valid convex rectangle and envelope.
        # Equal envelopes must still not substitute for identical original corners.
        changed = raw.model_copy(
            update={
                "r_x0": raw.r_x1,
                "r_y0": raw.r_y1,
                "r_x1": raw.r_x2,
                "r_y1": raw.r_y2,
                "r_x2": raw.r_x3,
                "r_y2": raw.r_y3,
                "r_x3": raw.r_x0,
                "r_y3": raw.r_y0,
            }
        )
        blocks[index] = block.model_copy(
            update={
                "provenance": (block.provenance[0].model_copy(update={"raw_rectangle": changed}),)
            }
        )
    wrong = fixture.artifact.model_copy(update={"blocks": tuple(blocks)})
    with pytest.raises((EvidenceBindingError, ProjectionError)) as error:
        bind(fixture, wrong)
    assert error.value.code == (
        "ARTIFACT_INVALID" if change == "geometry" else "WORD_SUPPORT_UNAVAILABLE"
    )


def test_duplicate_native_word_identity_is_ambiguous(fixture: BindingFixture):
    index = fixture.record.source_input.draft.value.phrase.words[0].word_index
    block = fixture.artifact.blocks[index]
    identity = str(uuid4())
    duplicate = block.model_copy(
        update={
            "id": identity,
            "exact_spans": (
                TextSpan(
                    block_id=identity, start=0, end=len(block.orig or ""), quote=block.orig or ""
                ),
            ),
        }
    )
    wrong = fixture.artifact.model_copy(update={"blocks": (*fixture.artifact.blocks, duplicate)})
    with pytest.raises(EvidenceBindingError, match="WORD_SUPPORT_AMBIGUOUS"):
        bind(fixture, wrong)


@pytest.mark.parametrize("change", ["removed", "column", "raw_box"])
def test_processed_grid_must_match_exact_retained_membership(fixture: BindingFixture, change: str):
    table = fixture.artifact.tables[0]
    cells = list(table.cells)
    if change == "removed":
        cells.pop(5)
    elif change == "column":
        # Swap complete cell locations so the authored artifact remains structurally valid.
        cells[4], cells[5] = (
            cells[4].model_copy(update={"column_index": 2}),
            cells[5].model_copy(update={"column_index": 1}),
        )
    else:
        raw = cells[5].provenance[0].raw_box
        assert raw is not None
        cells[5] = cells[5].model_copy(
            update={
                "provenance": (
                    cells[5]
                    .provenance[0]
                    .model_copy(update={"raw_box": raw.model_copy(update={"left": raw.left - 1})}),
                )
            }
        )
    wrong = fixture.artifact.model_copy(
        update={"tables": (table.model_copy(update={"cells": tuple(cells)}),)}
    )
    with pytest.raises(EvidenceBindingError, match="TABLE_MEMBERSHIP_UNAVAILABLE"):
        bind(fixture, wrong)


def test_identical_processed_tables_remain_ambiguous(fixture: BindingFixture):
    table = fixture.artifact.tables[0]
    identity = str(uuid4())
    duplicate = table.model_copy(
        update={
            "id": identity,
            "cells": tuple(
                cell.model_copy(update={"id": str(uuid4()), "table_id": identity})
                for cell in table.cells
            ),
        }
    )
    wrong = fixture.artifact.model_copy(update={"tables": (table, duplicate)})
    with pytest.raises(EvidenceBindingError, match="TABLE_MEMBERSHIP_AMBIGUOUS"):
        bind(fixture, wrong)


@pytest.mark.parametrize("code", ["PARSE_PARTIAL", "BACKEND_ERROR"])
def test_partial_parse_diagnostic_cannot_be_disguised_as_complete(
    fixture: BindingFixture, code: str
):
    diagnostic = ParseDiagnostic.model_validate(
        {
            "code": code,
            "severity": "ERROR",
            "source_ref": None,
            "page_id": None,
            "block_id": None,
            "table_id": None,
            "cell_id": None,
            "detail": None,
        }
    )
    wrong = fixture.artifact.model_copy(update={"diagnostics": (diagnostic,)})
    with pytest.raises(EvidenceBindingError, match="PAGE_COVERAGE_MISMATCH"):
        bind(fixture, wrong)


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "parse_version_id",
        "acceptance_eligible",
        "mandatory_m1_validation_complete",
        "review_required",
    ],
)
def test_bound_contract_cannot_promote_or_rebind(fixture: BindingFixture, field: str):
    payload = bind(fixture).model_dump(mode="json")
    payload[field] = str(uuid4()) if field.endswith("id") else field != "review_required"
    with pytest.raises(ValidationError):
        NumericalEvidenceBinding.model_validate(payload)


def test_rehash_cannot_substitute_different_grid_evidence(fixture: BindingFixture):
    payload = bind(fixture).model_dump(mode="json")
    payload["cells"][0]["word_evidence_ids"] = [str(uuid4())]
    payload["id"] = binding_identity({key: value for key, value in payload.items() if key != "id"})
    with pytest.raises(ValidationError):
        NumericalEvidenceBinding.model_validate(payload)


def test_binding_byte_budget_does_not_truncate_words(
    fixture: BindingFixture, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(evidence_binding_models, "MAX_BINDING_BYTES", 10)
    with pytest.raises(ValidationError, match="byte budget"):
        bind(fixture)


@pytest.mark.parametrize("change", ["whitespace", "duplicate_key"])
def test_rehashed_noncanonical_sidecar_cannot_change_the_bound_artifact_fingerprint(
    fixture: BindingFixture, change: str
):
    artifact, configuration = fixture.artifact, fixture.configuration
    if change == "whitespace":
        body = artifact.model_dump_json(indent=2).encode()
    else:
        body = (
            b'{"id":'
            + json.dumps(artifact.id).encode()
            + b","
            + canonical_artifact_bytes(artifact)[1:]
        )
    row = (
        body,
        canonical_configuration_bytes(configuration),
        hashlib.sha256(body).hexdigest(),
        configuration.processing_configuration_sha256,
        UUID(artifact.filing_version_id),
        UUID(artifact.source_blob_id),
        len(artifact.pages),
        len(artifact.pages),
        UUID(artifact.filing_id),
        artifact.source_sha256,
    )

    class Cursor:
        def fetchone(self) -> tuple[object, ...]:
            return row

    class Connection:
        def execute(self, query: str, parameters: object) -> Cursor:
            return Cursor()

    # The raw bytes and their rehashed row agree. Their canonical artifact does not;
    # returning its different fingerprint would misidentify the retained sidecar.
    with pytest.raises(NumericalSourceError, match="sealed parse differs"):
        _sealed_parse(cast(DatabaseConnection, Connection()), artifact.id)
