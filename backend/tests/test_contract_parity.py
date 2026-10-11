"""Curated synthetic JSON cases shared with the actual frontend runtime validator."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from regintel.contracts.models import CONTRACT_VERSION, PUBLIC_MODELS

DOCUMENT = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts/parity-vectors.json").read_text(
        encoding="utf-8"
    )
)
VECTORS = DOCUMENT["vectors"]


def test_shared_vectors_cover_every_exported_public_contract() -> None:
    assert DOCUMENT["contract_version"] == CONTRACT_VERSION
    assert {case["contract"] for case in VECTORS if case["valid"]} == set(PUBLIC_MODELS)
    assert len({case["name"] for case in VECTORS}) == len(VECTORS)


@pytest.mark.parametrize("vector", VECTORS, ids=[case["name"] for case in VECTORS])
def test_shared_wire_vector(vector: dict[str, object]) -> None:
    name = vector["contract"]
    assert isinstance(name, str)
    model = PUBLIC_MODELS[name]
    encoded = json.dumps(vector["payload"])
    if vector["valid"]:
        accepted = model.model_validate_json(encoded)
        assert json.loads(accepted.model_dump_json()) == vector["payload"]
    else:
        with pytest.raises(ValidationError):
            model.model_validate_json(encoded)
