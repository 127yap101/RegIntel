"""The portable authored browser fixture must satisfy every actual administrator contract."""

import base64
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from regintel.admin.models import AdminWire

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "kind",
    [
        "numerical_packet",
        "numerical_review_request",
        "numerical_review",
        "numerical_preparation",
        "numerical_candidate_request",
        "numerical_candidate",
        "numerical_acceptance_request",
        "numerical_acceptance",
        "manifest",
        "evidence",
    ],
)
def test_authored_numerical_browser_wire_uses_backend_contracts(kind):
    fixture = json.loads((ROOT / "frontend/src/admin/numerical.fixture.json").read_bytes())
    manifest = fixture["manifest"]
    accepted = manifest["new_acceptances"][0]["accepted"]
    candidate = accepted["candidate"]
    preparation = candidate["preparation"]
    source = preparation["proposed_input"]
    packet = {
        "gate": source["gate"],
        "binding": source["proof"],
        "review": source["context_review"],
    }
    values = {
        "numerical_packet": packet,
        "numerical_review_request": packet["review"]["request"],
        "numerical_review": packet["review"],
        "numerical_preparation": preparation,
        "numerical_candidate_request": candidate["record"]["request"],
        "numerical_candidate": candidate,
        "numerical_acceptance_request": accepted["record"]["request"],
        "numerical_acceptance": accepted,
        "manifest": manifest,
        "evidence": fixture["evidence"]["data"],
    }
    adapter = TypeAdapter(AdminWire.model_fields[kind].annotation)
    value = adapter.validate_python(values[kind])
    assert value.model_dump(mode="json") == values[kind]
    assert source["quantity"]["normalized_value"] == "2500.20"
    assert len(packet["gate"]["evidence_ids"]) == 51
    assert "Authored engineering fixture" in fixture["fixture_notice"]
    assert (
        hashlib.sha256(base64.b64decode(fixture["pdf_base64"])).hexdigest()
        == source["proof"]["source_sha256"]
    )


@pytest.mark.parametrize("kind", ["native_amendment_words", "publication_request", "manifest"])
def test_authored_amendment_browser_wire_uses_complete_backend_contracts(kind):
    fixture = json.loads((ROOT / "frontend/src/admin/amendment.fixture.json").read_bytes())
    values = {
        "native_amendment_words": fixture["request"]["effects"][0]["supports"][0],
        "publication_request": fixture["request"],
        "manifest": fixture["manifest"],
    }
    value = TypeAdapter(AdminWire.model_fields[kind].annotation).validate_python(values[kind])
    assert value.model_dump(mode="json") == values[kind]
    for identity, envelope in fixture["evidence"].items():
        evidence = TypeAdapter(AdminWire.model_fields["evidence"].annotation).validate_python(
            envelope["data"]
        )
        assert evidence.record.id == identity
    for version, encoded in fixture["pdfs"].items():
        filing = next(
            item for item in fixture["manifest"]["filings"] if item["filing_version_id"] == version
        )
        assert hashlib.sha256(base64.b64decode(encoded)).hexdigest() == filing["source_sha256"]
