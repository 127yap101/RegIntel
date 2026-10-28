"""Authored numerical candidate snapshots preserve proof and cannot claim acceptance."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.tests.test_numerical_context_reviews import gate
from backend.tests.test_numerical_publication_input import confirmation
from regintel.entities.models import canonical_bytes
from regintel.numerical.candidate_models import (
    NumericalCandidateRecord,
    NumericalCandidateRequest,
    StoredNumericalCandidate,
    numerical_candidate_identity,
)
from regintel.numerical.publication_input import prepare_numerical_publication


def candidate(tmp_path):
    source = gate(tmp_path)
    preparation = prepare_numerical_publication(source, confirmation(source))
    proposed = preparation.proposed_input
    assert proposed is not None
    request = NumericalCandidateRequest(gate_run_id=source.result.id, prepared_input_id=proposed.id)
    record = NumericalCandidateRecord(
        id=numerical_candidate_identity(proposed.id),
        request=request,
        preparation_sha256=preparation.sha256,
        storage_configuration_sha256="a" * 64,
        submitted_by=str(uuid4()),
        auth_version=1,
    )
    return StoredNumericalCandidate(record=record, preparation=preparation)


def test_candidate_retains_the_complete_preparation_without_acceptance(tmp_path):
    value = candidate(tmp_path)
    prepared = value.preparation.proposed_input
    assert prepared is not None and len(prepared.gate.evidence_ids) > 16
    assert value.record.state == "CANDIDATE"
    assert not value.record.acceptance_eligible and not value.record.publishes_fact
    assert not value.record.mandatory_m1_validation_complete
    assert StoredNumericalCandidate.model_validate_json(canonical_bytes(value)) == value


@pytest.mark.parametrize(
    "change",
    [
        "id",
        "gate",
        "prepared_input",
        "preparation_hash",
        "acceptance",
        "mandatory",
        "publish",
        "state",
    ],
)
def test_a_candidate_cannot_mix_inputs_or_promote_itself(tmp_path, change):
    value = candidate(tmp_path)
    payload = value.model_dump(mode="json")
    record = payload["record"]
    if change == "id":
        record["id"] = str(uuid4())
    elif change == "gate":
        record["request"]["gate_run_id"] = str(uuid4())
    elif change == "prepared_input":
        record["request"]["prepared_input_id"] = str(uuid4())
    elif change == "preparation_hash":
        record["preparation_sha256"] = "b" * 64
    elif change == "state":
        record["state"] = "ACCEPTED"
    else:
        key = {
            "acceptance": "acceptance_eligible",
            "mandatory": "mandatory_m1_validation_complete",
            "publish": "publishes_fact",
        }[change]
        record[key] = True
    with pytest.raises(ValidationError):
        StoredNumericalCandidate.model_validate(payload)


def test_a_blocked_preparation_cannot_be_stored_as_a_candidate(tmp_path):
    value = candidate(tmp_path)
    source = gate(tmp_path / "unreviewed")
    blocked = prepare_numerical_publication(source, None)
    with pytest.raises(ValidationError):
        StoredNumericalCandidate(record=value.record, preparation=blocked)


@pytest.mark.parametrize(
    "injection", ["quantity", "submitted_by", "acceptance_eligible", "reviewed_by"]
)
def test_creation_request_cannot_supply_values_or_authority(injection):
    with pytest.raises(ValidationError):
        NumericalCandidateRequest.model_validate(
            {
                "gate_run_id": str(uuid4()),
                "prepared_input_id": str(uuid4()),
                injection: "forged",
            }
        )
