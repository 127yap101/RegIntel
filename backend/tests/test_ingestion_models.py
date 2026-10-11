"""M1.1 storage shapes do not imply semantic acceptance or publication."""

import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from regintel.fixtures.adversarial import fixture_cases
from regintel.fixtures.sources import evidence_catalog, fixture_id
from regintel.ingestion.models import (
    BlockRecord,
    CandidateRecord,
    CellRecord,
    CorpusVersionRecord,
    FactObservationRecord,
    FilingRecord,
    FilingVersionRecord,
    ParseVersionRecord,
    QuantitativeContextRecord,
    SourceBlob,
    StoredEvidence,
)


def source_data() -> dict[str, object]:
    return {
        "id": fixture_id(8001),
        "sha256": "a" * 64,
        "byte_size": 10,
        "storage_key": f"sha256/{'a' * 64}.pdf",
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"sha256": "A" * 64},
        {"sha256": "a" * 63},
        {"byte_size": 0},
        {"byte_size": True},
        {"byte_size": 1.5},
        {"storage_key": "../outside.pdf"},
        {"storage_key": f"sha256/{'b' * 64}.pdf"},
        {"id": "00000000-0000-0000-0000-000000000001"},
    ],
)
def test_source_identity_rejects_invalid_or_inconsistent_shape(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SourceBlob.model_validate(source_data() | changes)


def test_content_identity_and_unknown_company_are_explicit_and_frozen() -> None:
    source = SourceBlob.model_validate(source_data())
    assert source.storage_key.endswith(f"{source.sha256}.pdf")
    with pytest.raises(ValidationError):
        source.byte_size = 20
    filing = FilingRecord(
        id=fixture_id(8002), company_name_raw="Helio Fixture Ltd", company_entity_id=None
    )
    assert filing.company_entity_id is None


def filing_version_data() -> dict[str, object]:
    return {
        "id": fixture_id(8003),
        "filing_id": fixture_id(8002),
        "source_blob_id": fixture_id(8001),
        "document_type": "RHP",
        "source_url": "https://example.invalid/filing.pdf",
        "published_on": None,
        "declared_parent_filing_version_id": None,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"source_url": "http://example.invalid/filing.pdf"},
        {"source_url": "https://user:secret@example.invalid/filing.pdf"},
        {"source_url": "https://example.invalid/filing.pdf#page=1"},
        {"source_url": "https://example.invalid:wrong/filing.pdf"},
        {"published_on": "2026-02-30"},
        {"document_type": "ANNUAL_REPORT"},
        {"declared_parent_filing_version_id": fixture_id(8003)},
    ],
)
def test_filing_metadata_never_creates_unsupported_dates_or_parent(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        FilingVersionRecord.model_validate(filing_version_data() | changes)


def test_publication_is_optional_and_distinct_from_financial_period() -> None:
    record = FilingVersionRecord.model_validate(filing_version_data())
    assert record.published_on is None
    assert record.declared_parent_filing_version_id is None


def test_complete_parse_shape_requires_artifact_identity_and_exact_counts() -> None:
    data: dict[str, object] = {
        "id": fixture_id(8004),
        "filing_version_id": fixture_id(8003),
        "source_blob_id": fixture_id(8001),
        "adapter_name": "fixture-only",
        "adapter_version": "1",
        "configuration_sha256": "b" * 64,
        "artifact_sha256": "c" * 64,
        "page_count": 1,
        "block_count": 0,
        "table_count": 0,
        "cell_count": 0,
        "evidence_count": 0,
    }
    assert ParseVersionRecord.model_validate(data).page_count == 1
    for changes in (
        {"page_count": 0},
        {"block_count": -1},
        {"artifact_sha256": None},
        {"evidence_count": True},
    ):
        with pytest.raises(ValidationError):
            ParseVersionRecord.model_validate(data | changes)


@pytest.mark.parametrize("text", ["null\x00point", "\ud800"])
def test_stored_text_rejects_unstorable_code_points(text: str) -> None:
    with pytest.raises(ValidationError):
        BlockRecord(
            id=fixture_id(8005),
            parse_version_id=fixture_id(8004),
            page_id=fixture_id(8006),
            text=text,
        )


def test_unicode_and_raw_blank_dash_cells_are_preserved() -> None:
    text = "Lead 😀 e\u0301\n"
    block = BlockRecord(
        id=fixture_id(8005), parse_version_id=fixture_id(8004), page_id=fixture_id(8006), text=text
    )
    assert block.text == text
    for raw in ("", "-", "100.00"):
        cell = CellRecord(
            id=fixture_id(8007),
            parse_version_id=fixture_id(8004),
            table_id=fixture_id(8008),
            page_id=fixture_id(8006),
            row_index=0,
            column_index=0,
            row_span=1,
            column_span=1,
            raw_text=raw,
        )
        assert cell.raw_text == raw
    with pytest.raises(ValidationError):
        CellRecord.model_validate(cell.model_dump() | {"column_index": 9007199254740991})


def test_evidence_shapes_keep_page_local_box_bounds() -> None:
    evidence = evidence_catalog()["owns_complete"]
    assert StoredEvidence(record=evidence).record == evidence
    data = evidence.model_dump(mode="json")
    data["boxes"] = [{"x0": -1000, "y0": 20, "x1": 20, "y1": 40}]
    with pytest.raises(ValidationError):
        StoredEvidence.model_validate({"record": data})


def test_exact_financial_wire_value_remains_decimal_and_null_stays_null() -> None:
    cases = fixture_cases().cases
    positive = next(
        c for c in cases if c.contract_name == "QuantitativeValue" and c.structurally_valid
    )
    assert positive.payload is not None
    payload = positive.payload | {"raw_value": "123.450", "normalized_value": "123.450"}
    context = QuantitativeContextRecord.model_validate_json(
        json.dumps(
            {"id": fixture_id(8009), "parse_version_id": fixture_id(8004), "quantity": payload}
        )
    )
    assert context.quantity.normalized_value == Decimal("123.450")
    assert json.loads(context.model_dump_json())["quantity"]["normalized_value"] == "123.450"
    payload |= {"raw_value": "-", "normalized_value": None}
    missing = QuantitativeContextRecord.model_validate_json(
        json.dumps(
            {"id": fixture_id(8009), "parse_version_id": fixture_id(8004), "quantity": payload}
        )
    )
    assert missing.quantity.normalized_value is None


def candidate_data() -> dict[str, object]:
    return {
        "id": fixture_id(8010),
        "parse_version_id": fixture_id(8004),
        "kind": "relation",
        "state": "CANDIDATE",
        "subject_entity_id": fixture_id(1),
        "object_entity_id": fixture_id(2),
        "metric_id": None,
        "relation_type": "OWNS",
        "raw_text": "Authored unvalidated relation",
        "quantitative_context_id": None,
        "evidence_ids": [fixture_id(8011)],
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"state": "ACCEPTED"},
        {"object_entity_id": None},
        {"relation_type": None},
        {"subject_entity_id": fixture_id(2)},
        {"metric_id": fixture_id(8012)},
        {"evidence_ids": [fixture_id(8011), fixture_id(8011)]},
        {
            "kind": "numeric_fact",
            "object_entity_id": None,
            "relation_type": None,
            "metric_id": fixture_id(8012),
            "quantitative_context_id": None,
        },
    ],
)
def test_candidate_schema_cannot_confer_acceptance(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CandidateRecord.model_validate(candidate_data() | changes)


def test_future_observation_shapes_require_anchors_and_no_inferred_corpus_parent() -> None:
    assert CandidateRecord.model_validate(candidate_data()).state == "CANDIDATE"
    with pytest.raises(ValidationError):
        FactObservationRecord(
            id=fixture_id(8013),
            candidate_id=fixture_id(8010),
            parse_version_id=fixture_id(8004),
            acceptance_audit_id=fixture_id(8014),
            corpus_version_id=fixture_id(8015),
            kind="numeric_fact",
            subject_entity_id=fixture_id(1),
            metric_id=fixture_id(8012),
            quantitative_context_id=None,
            raw_text="100",
        )
    with pytest.raises(ValidationError):
        CorpusVersionRecord(
            id=fixture_id(8015),
            parent_corpus_version_id=fixture_id(8015),
            state="PUBLISHED",
            configuration_sha256="a" * 64,
        )
