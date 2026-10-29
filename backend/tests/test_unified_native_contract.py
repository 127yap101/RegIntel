"""Immutable published native wire checks over explicitly authored HTTP evidence."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from regintel.publication.models import PublishedNumericalObservation
from regintel.reads.models import FactPage


def fact_payload():
    root = Path(__file__).resolve().parents[2]
    return json.loads((root / "frontend/src/published/native.fixture.json").read_bytes())["facts"][
        "data"
    ]


def test_native_public_fact_roundtrip_retains_the_complete_proof():
    page = FactPage.model_validate_json(json.dumps(fact_payload()))
    observation = page.facts[0].observation
    assert isinstance(observation, PublishedNumericalObservation)
    assert len(observation.supports) > 16
    assert FactPage.model_validate_json(page.model_dump_json()) == page
    assert observation.validation_run_id == observation.native_acceptance_id


@pytest.mark.parametrize(
    "change", ["support", "quantity_evidence", "parse", "proof", "kind", "acceptance", "context"]
)
def test_native_wire_cannot_hide_or_relabel_source_membership(change):
    payload = fact_payload()
    observation = payload["facts"][0]["observation"]
    if change == "support":
        observation["supports"].pop()
    elif change == "quantity_evidence":
        observation["quantity"]["evidence_ids"].pop()
    elif change == "parse":
        observation["parse_version_id"] = "00000000-0000-4000-8000-000000000001"
    elif change == "proof":
        observation["proof"]["phrases"][0]["words"].pop()
    elif change == "kind":
        observation["kind"] = "narrative_fact"
    elif change == "acceptance":
        observation["validation_run_id"] = "00000000-0000-4000-8000-000000000001"
    else:
        observation["context_supports"] = [{"role": "VALUE", "span": observation["supports"][0]}]
    with pytest.raises(ValidationError):
        FactPage.model_validate_json(json.dumps(payload))
