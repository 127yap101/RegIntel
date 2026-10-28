"""Authored acceptance contracts retain full proof and never claim corpus membership."""

import hashlib
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.tests.test_numerical_candidate_models import candidate
from regintel.entities.models import canonical_bytes
from regintel.numerical.acceptance_models import (
    NumericalAcceptanceRecord,
    NumericalAcceptanceRequest,
    StoredNumericalAcceptance,
    numerical_acceptance_identity,
)


def acceptance(tmp_path, decision="ACCEPT"):
    value = candidate(tmp_path)
    proposed = value.preparation.proposed_input
    assert proposed is not None
    request = NumericalAcceptanceRequest(
        candidate_id=value.record.id,
        decision=decision,
        evidence_ids=proposed.gate.evidence_ids,
        note="Authored explicit numerical decision; no real filing approval.",
    )
    record = NumericalAcceptanceRecord(
        id=numerical_acceptance_identity(value.record.id),
        request=request,
        candidate_record_sha256=hashlib.sha256(canonical_bytes(value.record)).hexdigest(),
        candidate_preparation_sha256=value.preparation.sha256,
        configuration_sha256="c" * 64,
        reviewed_by=str(uuid4()),
        auth_version=1,
        checks=value.preparation.checks if decision == "ACCEPT" else (),
        state="ACCEPTED_UNPUBLISHED" if decision == "ACCEPT" else "REJECTED",
        mandatory_m1_validation_complete=decision == "ACCEPT",
    )
    return StoredNumericalAcceptance(record=record, candidate=value)


@pytest.mark.parametrize("decision", ["ACCEPT", "REJECT"])
def test_decisions_keep_exact_proof_decimal_and_unpublished_state(tmp_path, decision):
    stored = acceptance(tmp_path, decision)
    prepared = stored.candidate.preparation.proposed_input
    assert prepared is not None and len(prepared.gate.evidence_ids) > 16
    assert len(stored.record.checks) == (16 if decision == "ACCEPT" else 0)
    assert not stored.record.publishes_fact and stored.record.published_corpus_version_id is None
    assert StoredNumericalAcceptance.model_validate_json(canonical_bytes(stored)) == stored


@pytest.mark.parametrize(
    "change",
    [
        "id",
        "candidate",
        "record_hash",
        "preparation_hash",
        "evidence",
        "check",
        "state",
        "mandatory",
        "publication",
        "corpus",
    ],
)
def test_acceptance_cannot_mix_sources_skip_checks_or_publish(tmp_path, change):
    stored = acceptance(tmp_path)
    payload = stored.model_dump(mode="json")
    record = payload["record"]
    if change == "id":
        record["id"] = str(uuid4())
    elif change == "candidate":
        record["request"]["candidate_id"] = str(uuid4())
    elif change == "record_hash":
        record["candidate_record_sha256"] = "d" * 64
    elif change == "preparation_hash":
        record["candidate_preparation_sha256"] = "d" * 64
    elif change == "evidence":
        record["request"]["evidence_ids"].pop()
    elif change == "check":
        record["checks"][0]["state"] = "REVIEW"
    elif change == "state":
        record["state"] = "REJECTED"
    elif change == "mandatory":
        record["mandatory_m1_validation_complete"] = False
    elif change == "publication":
        record["publishes_fact"] = True
    else:
        record["published_corpus_version_id"] = str(uuid4())
    with pytest.raises(ValidationError):
        StoredNumericalAcceptance.model_validate(payload)


@pytest.mark.parametrize("field", ["checks", "quantity", "reviewed_by", "publishes_fact"])
def test_request_cannot_supply_checks_values_actor_or_publication(field):
    with pytest.raises(ValidationError):
        NumericalAcceptanceRequest.model_validate(
            {
                "candidate_id": str(uuid4()),
                "decision": "ACCEPT",
                "evidence_ids": [str(uuid4())],
                "note": "Authored explicit decision.",
                field: "forged",
            }
        )


@pytest.mark.parametrize("note", [" ", "\x00", "x" * 2001])
def test_decisions_need_a_bounded_storable_explanation(note):
    with pytest.raises(ValidationError):
        NumericalAcceptanceRequest(
            candidate_id=str(uuid4()), decision="REJECT", evidence_ids=(str(uuid4()),), note=note
        )


def test_rejection_cannot_claim_fresh_validation(tmp_path):
    stored = acceptance(tmp_path, "REJECT")
    payload = stored.model_dump(mode="json")
    payload["record"]["checks"] = stored.candidate.preparation.model_dump(mode="json")["checks"]
    with pytest.raises(ValidationError):
        StoredNumericalAcceptance.model_validate(payload)
