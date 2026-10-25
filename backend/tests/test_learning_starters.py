"""Starter content remains unreviewed; Decimal examples are hypothetical arithmetic."""

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from regintel.learning.draft_pack import LearningStarterPack, load_starter_pack
from regintel.learning.examples import calculate_example


def test_starter_sources_are_explicit_without_metric_mapping_or_human_approval():
    pack = load_starter_pack()
    assert pack.status == "DRAFT_UNREVIEWED" and pack.prepared_by == "CODEX_DRAFT"
    assert pack.reviewed_by is None and pack.reviewed_on is None
    assert len(pack.drafts) == 7
    assert all(not item.draft.metric_ids and len(item.draft.sources) == 1 for item in pack.drafts)
    assert {item.draft.sources[0].url.split("/")[2] for item in pack.drafts} == {"www.ifrs.org"}


def test_hypothetical_examples_match_independently_written_arithmetic_expectations():
    pack = load_starter_pack()
    expected = {
        "profit_or_loss": Decimal("200.00"),
        "comparative_information": Decimal("25"),
        "cash_flow_statement": Decimal("30.00"),
    }
    actual = {}
    for item in pack.drafts:
        if item.draft.example:
            calculated = calculate_example(item.draft.example)
            assert calculated.state == "AVAILABLE"
            actual[item.key] = calculated.result
    assert actual == expected


@pytest.mark.parametrize(
    "change", ["approved", "reviewer", "duplicate", "mapping", "unverified_source"]
)
def test_starter_packet_cannot_claim_review_or_assume_m1_mapping(change):
    payload = load_starter_pack().model_dump(mode="json")
    if change == "approved":
        payload["status"] = "APPROVED"
    elif change == "reviewer":
        payload["reviewed_by"] = "Invented review"
    elif change == "duplicate":
        payload["drafts"].append(payload["drafts"][0])
    elif change == "mapping":
        payload["drafts"][0]["draft"]["metric_ids"] = [str(uuid4())]
    else:
        payload["drafts"][0]["draft"]["sources"][0]["url"] = "javascript:alert(1)"
    with pytest.raises(ValidationError):
        LearningStarterPack.model_validate(payload)


def test_oversized_starter_bytes_fail_before_loading_unbounded_content(tmp_path):
    path = tmp_path / "oversized.json"
    path.write_bytes(b"x" * 1048577)
    with pytest.raises(ValueError, match="byte budget"):
        load_starter_pack(path)
