"""Storage materialization keeps raw financial uncertainty and exact draft identity."""

import hashlib
import json

import pytest
from pydantic import ValidationError

from backend.tests.test_candidate_models import ALPHA, make_input, metric
from regintel.candidates.extraction import current_configuration, extract
from regintel.candidates.records import CandidateRun, materialize


def run() -> CandidateRun:
    source = make_input(
        f"{ALPHA} revenue was INR (1,234.50) crore on a consolidated basis "
        "for year ended 31 March 2024.",
        start=37,
        metrics=(metric(),),
    )
    return materialize(source, current_configuration(), extract(source))


def test_quantity_preserves_raw_value_and_context_until_validation() -> None:
    proposal = run()
    quantity = proposal.quantities[0].quantity
    assert quantity.raw_value == "(1,234.50)"
    assert quantity.raw_unit == "crore"
    assert quantity.raw_currency == "INR"
    assert quantity.raw_basis_label == "consolidated"
    assert quantity.period.raw_label == "year ended 31 March 2024"
    assert quantity.normalized_value is None
    assert quantity.normalized_unit is None
    assert quantity.currency is None
    assert quantity.basis == "UNKNOWN"
    assert quantity.period.kind == "UNKNOWN"
    assert quantity.period.start_date is quantity.period.end_date is None
    assert proposal.candidates[0].state == "CANDIDATE"
    assert proposal.candidates[0].quantitative_context_id == proposal.quantities[0].id
    assert proposal.candidates[0].evidence_ids == quantity.evidence_ids
    assert proposal == CandidateRun.model_validate_json(proposal.model_dump_json())


@pytest.mark.parametrize(
    "field,value",
    (
        ("id", "00000000-0000-4000-8000-000000000123"),
        ("input_sha256", "e" * 64),
        ("parse_version_id", "00000000-0000-4000-8000-000000000123"),
    ),
)
def test_storage_id_tampering_is_rejected(field: str, value: object) -> None:
    payload = run().model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError):
        CandidateRun.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "field,value",
    (
        ("raw_text", "unsupported replacement"),
        ("subject_entity_id", "00000000-0000-4000-8000-000000000123"),
        ("metric_id", "00000000-0000-4000-8000-000000000123"),
        ("quantitative_context_id", "00000000-0000-4000-8000-000000000123"),
        ("evidence_ids", ["00000000-0000-4000-8000-000000000123"]),
    ),
)
def test_record_cannot_diverge_from_source_draft(field: str, value: object) -> None:
    payload = run().model_dump(mode="json")
    payload["candidates"][0][field] = value
    with pytest.raises(ValidationError):
        CandidateRun.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "field,value",
    (
        ("raw_value", "0"),
        ("normalized_value", "12345000000"),
        ("currency", "INR"),
        ("normalized_unit", "crore"),
        ("basis", "CONSOLIDATED"),
        ("denominator", "invented capital"),
        ("stake_kind", "inferred equity"),
        ("ownership_date", "2024-03-31"),
    ),
)
def test_stored_quantity_cannot_gain_interpretation(field: str, value: object) -> None:
    payload = run().model_dump(mode="json")
    payload["quantities"][0]["quantity"][field] = value
    with pytest.raises(ValidationError):
        CandidateRun.model_validate_json(json.dumps(payload))


def test_historical_input_byte_identity_survives_reserialization() -> None:
    source = make_input(metrics=())
    bundle = extract(source)
    configuration = current_configuration()
    original_bytes = source.model_dump_json(indent=2).encode()
    raw_sha = hashlib.sha256(original_bytes).hexdigest()
    original = materialize(source, configuration, bundle, input_sha256=raw_sha)
    decoded = source.model_validate_json(original_bytes)
    assert materialize(decoded, configuration, bundle, input_sha256=raw_sha) == original
    assert original.input_sha256 == raw_sha != source.sha256
