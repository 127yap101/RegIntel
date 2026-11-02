"""Declared authored queue projections; not source review or real accepted filings."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from regintel.entities.models import canonical_bytes
from regintel.numerical.gate_models import BoundNumericalGateRun
from regintel.numerical.queue_models import (
    NumericalGateQueueItem,
    NumericalGateQueuePage,
    NumericalGateQueueRequest,
)
from regintel.numerical.queue_repository import queue_item
from regintel.numerical.repository import NumericalSourceError

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def recorded():
    fixture = json.loads((ROOT / "frontend/src/admin/numerical.fixture.json").read_bytes())
    source = fixture["manifest"]["new_acceptances"][0]["accepted"]["candidate"]["preparation"][
        "proposed_input"
    ]
    return source


def database_row(source):
    gate, review, proof = source["gate"], source["context_review"], source["proof"]
    encoded = json.dumps(gate, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    reviewed = json.dumps(
        review, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    request = json.dumps(
        review["request"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return [
        gate["id"],
        gate["context_record_id"],
        gate["parse_version_id"],
        gate["input_sha256"],
        encoded,
        hashlib.sha256(encoded).hexdigest(),
        gate["configuration_sha256"],
        gate["state"],
        proof["filing_version_id"],
        gate["source_sha256"],
        "Authored <script>name</script>",
        "PROSPECTUS",
        proof["filing_version_id"],
        proof["source_blob_id"],
        proof["source_blob_id"],
        gate["source_sha256"],
        review["id"],
        request,
        hashlib.sha256(request).hexdigest(),
        reviewed,
        hashlib.sha256(reviewed).hexdigest(),
        review["configuration_sha256"],
        review["reviewed_by"],
        review["auth_version"],
    ]


def page(item, **changes):
    return NumericalGateQueuePage.model_validate(
        {
            "scope": "RETAINED_HISTORY_ONLY",
            "state_filter": "ALL",
            "review_filter": "ALL",
            "query": "",
            "offset": 0,
            "limit": 20,
            "has_more": False,
            "items": [item],
        }
        | changes
    )


def test_queue_projection_retains_canonical_result_and_review_without_claiming_fresh_validation(
    recorded,
):
    item = queue_item(tuple(database_row(recorded)))
    assert item.gate.model_dump(mode="json") == recorded["gate"]
    assert item.review.model_dump(mode="json") == recorded["context_review"]
    assert item.company_name_raw == "Authored <script>name</script>"
    assert not item.gate.acceptance_eligible and not item.review.publishes_fact
    assert page(item).scope == "RETAINED_HISTORY_ONLY"


@pytest.mark.parametrize("column", [0, 1, 2, 3, 5, 6, 7, 9, 12, 13, 15, 16, 18, 20, 21, 22, 23])
def test_metadata_or_review_corruption_never_becomes_a_successful_queue_row(recorded, column):
    row = database_row(recorded)
    row[column] = 999 if column == 23 else str(uuid4())
    with pytest.raises((NumericalSourceError, ValidationError)):
        queue_item(tuple(row))


@pytest.mark.parametrize("column", [4, 17, 19])
def test_payload_mutation_requires_its_original_hash(recorded, column):
    row = database_row(recorded)
    row[column] += b" "
    with pytest.raises(NumericalSourceError):
        queue_item(tuple(row))


def test_noncanonical_bytes_and_partial_review_audits_are_rejected(recorded):
    row = database_row(recorded)
    row[4] += b" "
    row[5] = hashlib.sha256(row[4]).hexdigest()
    with pytest.raises(NumericalSourceError):
        queue_item(tuple(row))
    row = database_row(recorded)
    row[16] = None
    with pytest.raises(NumericalSourceError):
        queue_item(tuple(row))
    row[17:] = [None] * 7
    assert queue_item(tuple(row)).review is None


@pytest.mark.parametrize(
    "change",
    [
        "state",
        "review",
        "duplicate",
        "continuation",
        "scope",
        "review_gate",
        "review_hash",
        "review_evidence",
    ],
)
def test_queue_membership_filters_and_historical_scope_are_strict(recorded, change):
    item = queue_item(tuple(database_row(recorded))).model_dump(mode="json")
    overrides = {}
    if change == "state":
        overrides["state_filter"] = "QUARANTINED"
    if change == "review":
        overrides["review_filter"] = "UNREVIEWED"
    if change == "duplicate":
        overrides["items"] = [item, item]
    if change == "continuation":
        overrides["has_more"] = True
    if change == "scope":
        overrides["scope"] = "CURRENTLY_ACCEPTED"
    if change == "review_gate":
        item["review"]["request"]["gate_run_id"] = str(uuid4())
    if change == "review_hash":
        item["review"]["gate_result_sha256"] = "e" * 64
    if change == "review_evidence":
        item["review"]["request"]["evidence_ids"].pop()
    with pytest.raises(ValidationError):
        page(item, **overrides)


@pytest.mark.parametrize(
    "change",
    [
        {"offset": -1},
        {"offset": 10001},
        {"limit": 0},
        {"limit": 21},
        {"query": "x" * 121},
        {"query": "\x00"},
        {"state": "PUBLISHED"},
        {"review": "APPROVED"},
        {"offset": True},
    ],
)
def test_queue_selection_requires_bounded_literal_filters(change):
    with pytest.raises(ValidationError):
        NumericalGateQueueRequest.model_validate(
            {"state": "ALL", "review": "ALL", "query": "", "offset": 0, "limit": 20} | change
        )


def test_confirmed_review_cannot_be_attached_to_an_unresolved_gate(recorded):
    value = queue_item(tuple(database_row(recorded))).model_dump(mode="json")
    value["gate"]["checks"][0]["state"] = "REVIEW"
    value["gate"]["state"] = "REVIEW_REQUIRED"
    value["review"]["gate_result_sha256"] = hashlib.sha256(
        canonical_bytes(BoundNumericalGateRun.model_validate(value["gate"]))
    ).hexdigest()
    with pytest.raises(ValidationError):
        NumericalGateQueueItem.model_validate(value)


def test_queue_query_has_identical_validation_and_serialization_bounds():
    validation = NumericalGateQueueRequest.model_json_schema(mode="validation")["properties"][
        "query"
    ]
    serialization = NumericalGateQueueRequest.model_json_schema(mode="serialization")["properties"][
        "query"
    ]
    assert validation == serialization
    assert validation["maxLength"] == 120 and "pattern" in validation
