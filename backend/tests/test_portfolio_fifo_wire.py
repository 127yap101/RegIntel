"""Frozen authored FIFO HTTP responses must retain complete Python wire contracts."""

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from regintel.module_contracts import ModuleWire

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("key", ["opening", "buy", "purchases", "partial", "closed", "reopened"])
@pytest.mark.parametrize("kind", ["portfolio", "ledger", "analytics"])
def test_owned_fifo_http_fixture_round_trips_the_complete_module_wire(key, kind):
    fixture = json.loads((ROOT / "frontend/src/modules/fifo.fixture.json").read_bytes())
    assert "fixed engineering prices" in fixture["fixture_notice"]
    envelope = fixture["snapshots"][key][kind]
    value = TypeAdapter(ModuleWire.model_fields[kind].annotation).validate_json(
        json.dumps(envelope["data"])
    )
    assert value.model_dump(mode="json") == envelope["data"]
    assert envelope["meta"]["versions"]["portfolio_version_id"] == value.portfolio_version_id
