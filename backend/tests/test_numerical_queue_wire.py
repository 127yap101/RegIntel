"""Actual authored queue capture round-trips complete Python JSON wire contracts."""

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from regintel.admin.models import AdminWire

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "name", ["all", "all_next", "confirmed", "empty", "rejected", "unreviewed"]
)
def test_authored_queue_http_fixture_retains_complete_queue_contract(name):
    fixture = json.loads((ROOT / "frontend/src/admin/numerical-queue.fixture.json").read_bytes())
    assert "fictional issuer" in fixture["fixture_notice"]
    body = fixture["pages"][name]["data"]
    value = TypeAdapter(AdminWire.model_fields["numerical_queue"].annotation).validate_json(
        json.dumps(body)
    )
    assert value.model_dump(mode="json") == body
    assert all(not item.gate.acceptance_eligible for item in value.items)


@pytest.mark.parametrize("index", [0, 1])
def test_authored_queue_packet_fixture_still_requires_complete_review_contract(index):
    fixture = json.loads((ROOT / "frontend/src/admin/numerical-queue.fixture.json").read_bytes())
    body = list(fixture["packets"].values())[index]["data"]
    value = TypeAdapter(AdminWire.model_fields["numerical_packet"].annotation).validate_json(
        json.dumps(body)
    )
    assert value.model_dump(mode="json") == body
