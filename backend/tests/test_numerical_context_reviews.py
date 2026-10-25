"""Staged numerical reviews retain all mandatory gates; no authority is created."""

import hashlib
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.tests.test_bound_numerical_gate import packet
from backend.tests.test_numerical_context import Options
from regintel.entities.models import canonical_bytes
from regintel.numerical.bound_gate import validate_bound_numerical
from regintel.numerical.gate_models import StoredBoundNumericalGate
from regintel.numerical.review_models import (
    NumericalContextReviewRequest,
    ReviewedNumericalContext,
    require_reviewable,
    review_identity,
)


def gate(tmp_path, conditional=False):
    value = packet(tmp_path, Options() if conditional else None)
    return StoredBoundNumericalGate(
        source_input=value,
        result=validate_bound_numerical(value),
        submitted_by=str(uuid4()),
        auth_version=1,
    )


def request(value, decision="CONFIRM_CONTEXT"):
    return NumericalContextReviewRequest(
        gate_run_id=value.result.id,
        decision=decision,
        evidence_ids=value.result.evidence_ids,
        note="Authored engineering decision only; not human review of a real filing.",
    )


def test_supported_context_review_has_exact_identity_without_becoming_acceptance(tmp_path):
    value = gate(tmp_path)
    proposal = request(value)
    require_reviewable(value, proposal)
    result = ReviewedNumericalContext(
        id=review_identity(proposal, value.result.input_sha256, "a" * 64),
        request=proposal,
        gate_input_sha256=value.result.input_sha256,
        gate_result_sha256=hashlib.sha256(canonical_bytes(value.result)).hexdigest(),
        configuration_sha256="a" * 64,
        reviewed_by=str(uuid4()),
        auth_version=1,
    )
    assert ReviewedNumericalContext.model_validate_json(result.model_dump_json()) == result
    assert not result.acceptance_eligible and not result.mandatory_m1_validation_complete
    assert not result.publishes_fact


def test_conditional_context_cannot_be_confirmed_but_can_be_rejected(tmp_path):
    value = gate(tmp_path, conditional=True)
    with pytest.raises(ValueError, match="reviewer-overridden"):
        require_reviewable(value, request(value))
    require_reviewable(value, request(value, "REJECT"))


@pytest.mark.parametrize("change", ["missing", "foreign", "other_gate"])
def test_review_cannot_omit_or_mix_complete_evidence(tmp_path, change):
    value = gate(tmp_path)
    changes = (
        {"evidence_ids": value.result.evidence_ids[:-1]}
        if change == "missing"
        else (
            {"evidence_ids": tuple(sorted((*value.result.evidence_ids, str(uuid4()))))}
            if change == "foreign"
            else {"gate_run_id": str(uuid4())}
        )
    )
    with pytest.raises(ValueError, match="complete selected gate"):
        require_reviewable(value, request(value).model_copy(update=changes))


@pytest.mark.parametrize("note", ["", "   ", "\x00", "x" * 2001])
def test_review_explanation_is_explicit_and_storable(tmp_path, note):
    with pytest.raises(ValidationError):
        NumericalContextReviewRequest.model_validate(
            request(gate(tmp_path)).model_dump() | {"note": note}
        )
