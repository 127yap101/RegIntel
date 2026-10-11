"""Synthetic fixture integrity; no future evidence gate or provider is executed."""

import json

import pytest
from pydantic import TypeAdapter

from regintel.contracts.models import PUBLIC_MODELS
from regintel.contracts.primitives import CanonicalId
from regintel.fixtures.adversarial import (
    REQUIRED_ADVERSARIAL_CATEGORIES,
    fixture_cases,
    verify_case_suite,
)
from regintel.fixtures.sources import evidence_catalog, fixture_id, source_text_catalog


def test_all_required_cases_are_reproducible_and_have_current_shape_decisions() -> None:
    suite = fixture_cases()
    verify_case_suite(suite)
    assert suite.model_dump_json() == fixture_cases().model_dump_json()
    assert REQUIRED_ADVERSARIAL_CATEGORIES <= {case.category for case in suite.cases}
    assert len(REQUIRED_ADVERSARIAL_CATEGORIES) == 18
    assert all(case.reason and case.future_expectation for case in suite.cases)


def test_case_helper_detects_unknown_source_alias_and_wrong_structural_expectation() -> None:
    suite = fixture_cases()
    first, *rest = suite.cases
    unknown = first.model_copy(update={"source_aliases": ("unknown-source",)})
    with pytest.raises(ValueError, match="unknown source"):
        verify_case_suite(suite.model_copy(update={"cases": (unknown, *rest)}))
    wrong_shape = first.model_copy(update={"structurally_valid": False})
    with pytest.raises(ValueError, match="structural decision"):
        verify_case_suite(suite.model_copy(update={"cases": (wrong_shape, *rest)}))


def test_fabricated_id_and_modified_quote_pass_shape_but_remain_unsupported_source_data() -> None:
    cases = fixture_cases().cases
    fabricated = next(case for case in cases if case.category == "fabricated_evidence_ids")
    assert fabricated.payload is not None and fabricated.contract_name is not None
    model = PUBLIC_MODELS[fabricated.contract_name].model_validate_json(
        json.dumps(fabricated.payload)
    )
    identifier = json.loads(model.model_dump_json())["evidence_ids"][0]
    assert TypeAdapter(CanonicalId).validate_python(identifier) == identifier
    assert identifier not in {record.id for record in evidence_catalog().values()}
    altered = next(case for case in cases if case.category == "modified_quotes")
    assert altered.payload is not None and altered.contract_name is not None
    evidence = PUBLIC_MODELS[altered.contract_name].model_validate_json(json.dumps(altered.payload))
    quote = json.loads(evidence.model_dump_json())["records"][0]["span"]["quote"]
    assert len(quote) == len(source_text_catalog()["owns_complete"])
    assert quote != source_text_catalog()["owns_complete"]


def test_mock_timeout_and_refusal_have_no_payload_or_structural_acceptance() -> None:
    events = [case for case in fixture_cases().cases if case.provider_event is not None]
    assert {case.provider_event for case in events} == {"timeout", "refusal"}
    assert all(case.payload is None and case.structurally_valid is None for case in events)


def test_incomplete_ownership_fixture_preserves_missing_stake_and_basis() -> None:
    case = next(
        case
        for case in fixture_cases().cases
        if case.category == "ownership_missing_denominator_date"
    )
    assert case.payload is not None
    assert case.payload["stake_kind"] is None and case.payload["raw_basis_label"] is None
    assert case.payload["denominator"] is None and case.payload["ownership_date"] is None
    assert case.payload["normalized_value"] == "30"


def test_explicit_effect_cases_preserve_unknown_effective_dates() -> None:
    suite = fixture_cases()
    effects = [case for case in suite.cases if case.contract_name == "AmendmentEffect"]
    assert {case.payload["effect_type"] for case in effects if case.payload is not None} == {
        "ADD",
        "CORRECT",
        "SUPPLEMENT",
        "SUPERSEDE",
        "REMOVE",
    }
    assert all(
        case.payload is not None and case.payload["effective_date"] is None for case in effects
    )
    for case in effects:
        assert case.payload is not None
        for field in ("affected_observation_ids", "new_observation_ids"):
            assert set(case.payload[field]) <= suite.observation_sources.keys()


def test_ocr_case_is_an_authored_corruption_of_the_image_transcription() -> None:
    case = next(case for case in fixture_cases().cases if case.category == "ocr_corruption")
    assert case.payload is not None and case.contract_name is not None
    evidence = PUBLIC_MODELS[case.contract_name].model_validate_json(json.dumps(case.payload))
    quote = json.loads(evidence.model_dump_json())["records"][0]["span"]["quote"]
    original = source_text_catalog()["ocr_region"]
    assert "1O crore" in quote and "10 crore" in original
    assert quote != original and len(quote) == len(original)


@pytest.mark.parametrize("evidence_alias", ["unlisted", "owns_complete"])
def test_effect_integrity_helper_rejects_unknown_or_unrelated_evidence(evidence_alias: str) -> None:
    suite = fixture_cases()
    case = next(case for case in suite.cases if case.name == "explicit correct")
    assert case.payload is not None
    identifier = (
        fixture_id(999999)
        if evidence_alias == "unlisted"
        else evidence_catalog()[evidence_alias].id
    )
    tampered = case.model_copy(update={"payload": {**case.payload, "evidence_ids": [identifier]}})
    broken = suite.model_copy(
        update={
            "cases": tuple(
                tampered if current.name == case.name else current for current in suite.cases
            )
        }
    )
    with pytest.raises(ValueError, match="effect evidence"):
        verify_case_suite(broken)
