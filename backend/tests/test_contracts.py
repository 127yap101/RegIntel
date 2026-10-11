"""Meaningful wire/structural checks; these are not filing support or acceptance tests."""

import copy
import json
from decimal import Decimal

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from regintel.contracts.models import (
    CONTRACT_VERSION,
    MODULE_OWNERSHIP,
    PUBLIC_MODELS,
    RELATION_DIRECTIONS,
    AmendmentEffect,
    ApiError,
    CellReference,
    ErrorEnvelope,
    EvidenceSource,
    EvidenceSupport,
    FilingLineage,
    FinancialPeriod,
    PageGeometry,
    PdfRectangle,
    QuantitativeValue,
    RelationReference,
    SuccessEnvelope,
    TextSpan,
    UserEnvelope,
    UserIdentity,
    VersionContext,
)
from regintel.contracts.primitives import (
    DATE_PATTERN,
    DECIMAL_PATTERN,
    ID_PATTERN,
    MAX_SAFE_INTEGER,
    CanonicalId,
    DateString,
    DecimalValue,
    RawText,
    decimal_to_wire,
)

ID1 = "00000000-0000-4000-8000-000000000001"
ID2 = "00000000-0000-4000-9000-000000000002"
ID3 = "00000000-0000-4000-a000-000000000003"
ID4 = "00000000-0000-4000-b000-000000000004"


def wire[M: BaseModel](model: type[M], payload: dict[str, object]) -> M:
    return model.model_validate_json(json.dumps(payload))


def period(**changes: object) -> dict[str, object]:
    result: dict[str, object] = {
        "kind": "UNKNOWN",
        "start_date": None,
        "end_date": None,
        "instant_date": None,
        "raw_label": None,
    }
    result.update(changes)
    return result


def quantitative(value: object = "12345678901234567890.012300") -> dict[str, object]:
    return {
        "raw_value": "  12,345,678,901,234,567,890.012300  ",
        "normalized_value": value,
        "raw_unit": "INR crore",
        "normalized_unit": None,
        "raw_currency": "₹",
        "currency": "INR",
        "period": period(raw_label="period not stated"),
        "basis": "UNKNOWN",
        "raw_basis_label": "basis unclear",
        "denominator": None,
        "stake_kind": None,
        "ownership_date": None,
        "evidence_ids": [ID1],
    }


def rectangle(**changes: object) -> dict[str, object]:
    result: dict[str, object] = {"x0": -10, "y0": -20, "x1": 602, "y1": 772}
    result.update(changes)
    return result


def geometry(**changes: object) -> dict[str, object]:
    result: dict[str, object] = {
        "width": 612,
        "height": 792,
        "media_box": rectangle(),
        "crop_box": rectangle(x0=-5, y0=-15, x1=595, y1=765),
        "rotation": 90,
        "coordinate_space": "UNROTATED_PDF_POINTS",
        "origin": "BOTTOM_LEFT",
    }
    result.update(changes)
    return result


def source(page_index: object = 0) -> dict[str, object]:
    return {
        "filing_id": ID1,
        "filing_version_id": ID2,
        "parse_version_id": ID3,
        "page_id": ID4,
        "page_index": page_index,
    }


def span(**changes: object) -> dict[str, object]:
    result: dict[str, object] = {"block_id": ID1, "start": 10, "end": 14, "quote": "A💰é"}
    result.update(changes)
    return result


def cell(**changes: object) -> dict[str, object]:
    result: dict[str, object] = {
        "table_id": ID1,
        "cell_id": ID2,
        "row_index": 0,
        "column_index": 1,
        "row_span": 2,
        "column_span": 1,
        "row_label_cell_ids": [ID3, ID4],
        "period_column_cell_ids": [ID3],
        "unit_header_cell_ids": [],
        "basis_header_cell_ids": [],
    }
    result.update(changes)
    return result


def text_evidence(evidence_id: str = ID1, page_index: int = 0) -> dict[str, object]:
    return {
        "id": evidence_id,
        "kind": "text",
        "source": source(page_index),
        "page_geometry": geometry(),
        "boxes": [rectangle(x0=-5, y0=100, x1=100, y1=115)],
        "span": span(),
    }


def cell_evidence() -> dict[str, object]:
    return {
        "id": ID2,
        "kind": "table_cell",
        "source": source(1),
        "page_geometry": geometry(),
        "boxes": [rectangle(x0=10, y0=50, x1=100, y1=70)],
        "cell": cell(),
    }


def versions() -> dict[str, object]:
    return {
        "corpus_version_id": None,
        "filing_version_id": None,
        "parse_version_id": None,
        "glossary_version_id": None,
        "quote_version_id": None,
        "portfolio_version_id": None,
    }


def meta() -> dict[str, object]:
    return {"request_id": ID1, "contract_version": CONTRACT_VERSION, "versions": versions()}


def relation(**changes: object) -> dict[str, object]:
    result: dict[str, object] = {
        "id": ID1,
        "relation_type": "SUBSIDIARY_OF",
        "subject_entity_id": ID2,
        "object_entity_id": ID3,
        "state": "CANDIDATE",
        "evidence_ids": [ID4],
        "quantitative_context": None,
    }
    result.update(changes)
    return result


def effect(**changes: object) -> dict[str, object]:
    result: dict[str, object] = {
        "id": ID1,
        "effect_type": "SUPERSEDE",
        "affected_observation_ids": [ID2],
        "new_observation_ids": [ID3],
        "evidence_ids": [ID4],
        "reviewed_decision_id": None,
        "effective_date": None,
    }
    result.update(changes)
    return result


@pytest.mark.parametrize("value", [ID1, ID2, ID3, ID4])
def test_canonical_id_accepts_all_rfc_variants(value: str) -> None:
    assert TypeAdapter(CanonicalId).validate_python(value) == value


@pytest.mark.parametrize(
    "value",
    [
        ID3.upper(),
        ID1.replace("4000", "1000"),
        ID1.replace("4000", "7000"),
        ID1.replace("8000", "c000"),
        "00000000-0000-0000-0000-000000000000",
        ID1 + "\n",
        " " + ID1,
        True,
        1,
    ],
)
def test_noncanonical_ids_reject(value: object) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(CanonicalId).validate_python(value)


@pytest.mark.parametrize("value", ["2024-02-29", "0001-01-01", "9999-12-31"])
def test_dates_are_real_calendar_dates(value: str) -> None:
    assert TypeAdapter(DateString).validate_python(value) == value


@pytest.mark.parametrize(
    "value", ["2023-02-29", "2024-13-01", "0000-01-01", "2024-1-01", "2024-01-01\n", 20240101]
)
def test_invalid_dates_reject(value: object) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(DateString).validate_python(value)


@pytest.mark.parametrize(
    "value",
    ["0", "-0.00", "1.2300", "9" * 120 + "." + "7" * 120, "0." + "0" * 119 + "1"],
)
def test_decimal_wire_round_trips_exact_value_and_fractional_scale(value: str) -> None:
    result = wire(QuantitativeValue, quantitative(value))
    assert isinstance(result.normalized_value, Decimal)
    assert result.normalized_value == Decimal(value)
    assert json.loads(result.model_dump_json())["normalized_value"] == value
    assert result.model_dump()["normalized_value"] == Decimal(value)


@pytest.mark.parametrize(
    "value",
    [
        1,
        1.25,
        True,
        False,
        "1E+3",
        "1e-3",
        "NaN",
        "Infinity",
        "-Infinity",
        "+1.00",
        "00.1",
        "01",
        "-00.00",
        ".25",
        "1.",
        " 1.0",
        "1.0\n",
        "١.٢",
        "9" * 121,
        "0." + "1" * 121,
    ],
)
def test_decimal_wire_rejects_lossy_or_nonplain_inputs(value: object) -> None:
    with pytest.raises(ValidationError):
        wire(QuantitativeValue, quantitative(value))


@pytest.mark.parametrize(
    "value", [Decimal("NaN"), Decimal("Infinity"), Decimal("1E+120"), Decimal("1E-121")]
)
def test_internal_decimal_bounds_are_checked_before_serialization(value: Decimal) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(DecimalValue).validate_python(value)
    with pytest.raises(ValueError):
        decimal_to_wire(value)


def test_decimal_formatter_bounds_huge_exponents_before_allocating_output() -> None:
    with pytest.raises(ValueError):
        decimal_to_wire(Decimal("1E+1000000000"))
    with pytest.raises(ValueError):
        decimal_to_wire(Decimal("1E-1000000000"))
    assert decimal_to_wire(Decimal("1E+3")) == "1000"
    assert decimal_to_wire(Decimal("1.2300")) == "1.2300"


@pytest.mark.parametrize("raw", ["", "—", "-", " "])
def test_missing_raw_values_do_not_become_zero(raw: str) -> None:
    data = quantitative(None)
    data["raw_value"] = raw
    result = wire(QuantitativeValue, data)
    assert result.raw_value == raw
    assert result.normalized_value is None
    assert result.raw_basis_label == "basis unclear"
    assert result.denominator is None and result.ownership_date is None


@pytest.mark.parametrize(
    "payload",
    [
        period(),
        period(kind="INSTANT"),
        period(kind="INSTANT", instant_date="2024-03-31"),
        period(kind="DURATION", start_date="2023-04-01"),
        period(kind="DURATION", end_date="2024-03-31"),
        period(kind="DURATION", start_date="2024-03-31", end_date="2024-03-31"),
    ],
)
def test_period_preserves_explicit_missing_and_partial_dates(payload: dict[str, object]) -> None:
    result = wire(FinancialPeriod, payload)
    assert json.loads(result.model_dump_json()) == payload


@pytest.mark.parametrize(
    "payload",
    [
        period(kind="instant"),
        period(kind="INSTANT", start_date="2024-01-01"),
        period(kind="DURATION", instant_date="2024-01-01"),
        period(kind="DURATION", start_date="2024-04-01", end_date="2024-03-31"),
        period(start_date="2024-01-01"),
    ],
)
def test_period_rejects_kind_mismatch_and_reversed_dates(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        wire(FinancialPeriod, payload)


@pytest.mark.parametrize("value", [True, 1.5, "1", -1, MAX_SAFE_INTEGER])
def test_page_index_rejects_noninteger_or_unsafe_pdf_page_conversion(value: object) -> None:
    with pytest.raises(ValidationError):
        wire(EvidenceSource, source(value))


def test_max_page_index_remains_exact_after_one_based_conversion() -> None:
    result = wire(EvidenceSource, source(MAX_SAFE_INTEGER - 1))
    assert result.page_index + 1 == MAX_SAFE_INTEGER


def test_nonfinancial_indices_follow_json_integer_numeric_value_semantics() -> None:
    result = wire(EvidenceSource, source(1.0))
    assert result.page_index == 1 and type(result.page_index) is int
    rotation = wire(PageGeometry, geometry(rotation=90.0))
    assert rotation.rotation == 90 and type(rotation.rotation) is int


def test_text_span_uses_unicode_codepoints_and_retains_exact_quote() -> None:
    result = wire(TextSpan, span())
    assert result.quote == "A💰é"
    assert len(result.quote) == 4
    assert result.end - result.start == 4
    whitespace = wire(TextSpan, span(start=0, end=3, quote=" a\n"))
    assert whitespace.quote == " a\n"


@pytest.mark.parametrize(
    "payload", [span(end=15), span(end=10), span(start=-1), span(start=True), span(quote="")]
)
def test_text_span_rejects_invalid_offsets_or_quote_length(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        wire(TextSpan, payload)


def test_invalid_unicode_is_not_silently_replaced() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(RawText).validate_python("\ud800")


@pytest.mark.parametrize("message", ["\ud800", "\udfff"])
def test_internal_api_error_rejects_invalid_unicode_before_json_rendering(message: str) -> None:
    with pytest.raises(ValidationError):
        ApiError(code="INTERNAL_ERROR", message=message, details=())


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_geometry_retains_negative_crop_coordinates_and_single_rotation(rotation: int) -> None:
    result = wire(PageGeometry, geometry(rotation=rotation))
    assert result.crop_box.x0 == -5
    assert result.media_box.x0 == -10
    assert result.width == 612 and result.height == 792
    assert result.rotation == rotation
    assert result.coordinate_space == "UNROTATED_PDF_POINTS"
    assert result.origin == "BOTTOM_LEFT"


@pytest.mark.parametrize(
    "payload",
    [
        rectangle(x1=-10),
        rectangle(y1=-20),
        rectangle(x0=True),
        rectangle(x0=float("nan")),
        rectangle(x1=float("inf")),
        rectangle(x0=-1e308, x1=1e308),
    ],
)
def test_rectangles_reject_nonfinite_degenerate_or_overflow_extents(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        wire(PdfRectangle, payload)


@pytest.mark.parametrize(
    "payload",
    [
        geometry(width=0),
        geometry(width=613),
        geometry(rotation=45),
        geometry(rotation=False),
        geometry(rotation=90.5),
        geometry(coordinate_space="ROTATED_PIXELS"),
        geometry(origin="TOP_LEFT"),
    ],
)
def test_geometry_rejects_mismatched_dimensions_or_conventions(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        wire(PageGeometry, payload)


def test_geometry_dimension_tolerance_is_explicit_and_small() -> None:
    wire(PageGeometry, geometry(width=612 + 5e-10))
    with pytest.raises(ValidationError):
        wire(PageGeometry, geometry(width=612 + 2e-9))


def test_cell_reference_preserves_merged_spans_and_missing_context() -> None:
    result = wire(CellReference, cell())
    assert result.row_span == 2
    assert result.row_label_cell_ids == (ID3, ID4)
    assert result.period_column_cell_ids == (ID3,)
    assert result.unit_header_cell_ids == () and result.basis_header_cell_ids == ()


@pytest.mark.parametrize(
    "payload",
    [
        cell(row_span=0),
        cell(column_index=-1),
        cell(row_index=MAX_SAFE_INTEGER, row_span=1),
        cell(column_index=MAX_SAFE_INTEGER, column_span=1),
        cell(row_label_cell_ids=[ID3, ID3]),
    ],
)
def test_cell_reference_rejects_duplicate_context_and_unsafe_spans(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        wire(CellReference, payload)


def test_cross_page_support_is_separate_records_with_discriminated_evidence() -> None:
    payload: dict[str, object] = {"records": [text_evidence(), cell_evidence()]}
    result = wire(EvidenceSupport, payload)
    assert result.records[0].source.page_index == 0
    assert result.records[1].source.page_index == 1
    assert result.records[0].kind == "text" and result.records[1].kind == "table_cell"
    assert json.loads(result.model_dump_json()) == payload
    with pytest.raises(ValidationError):
        wire(EvidenceSupport, {"records": [text_evidence(), text_evidence(page_index=1)]})


def test_evidence_kind_requires_its_appropriate_shape() -> None:
    wrong = text_evidence()
    wrong["kind"] = "table_cell"
    with pytest.raises(ValidationError):
        wire(EvidenceSupport, {"records": [wrong]})
    missing_boxes = text_evidence()
    missing_boxes["boxes"] = []
    with pytest.raises(ValidationError):
        wire(EvidenceSupport, {"records": [missing_boxes]})


def test_relations_preserve_direction_and_required_missing_quantitative_context() -> None:
    result = wire(RelationReference, relation())
    assert result.subject_entity_id == ID2 and result.object_entity_id == ID3
    assert RELATION_DIRECTIONS[result.relation_type] == {
        "subject": "subsidiary",
        "object": "parent",
    }
    assert result.quantitative_context is None
    result_with_context = wire(RelationReference, relation(quantitative_context=quantitative()))
    assert result_with_context.quantitative_context is not None
    for changes in (
        {"relation_type": "RELATED_TO"},
        {"state": "PUBLISHED"},
        {"evidence_ids": [ID4, ID4]},
    ):
        with pytest.raises(ValidationError):
            wire(RelationReference, relation(**changes))


def test_lineage_keeps_named_distinct_filings_and_raw_explicit_type() -> None:
    for label in ("ADDENDUM_TO", "CORRIGENDUM_TO", "future-reviewed-type"):
        result = wire(
            FilingLineage,
            {"parent_filing_id": ID1, "child_filing_id": ID2, "lineage_type": label},
        )
        assert result.parent_filing_id == ID1 and result.child_filing_id == ID2
        assert result.lineage_type == label
    with pytest.raises(ValidationError):
        wire(FilingLineage, {"parent_filing_id": ID1, "child_filing_id": ID1, "lineage_type": "X"})


def test_effect_spelling_and_no_inferred_effective_date() -> None:
    result = wire(AmendmentEffect, effect())
    assert result.effect_type == "SUPERSEDE"
    assert result.effective_date is None and result.reviewed_decision_id is None
    # Empty sides preserve shape only; effect-specific authorization/resolution is later M1.
    wire(AmendmentEffect, effect(affected_observation_ids=[], new_observation_ids=[]))
    with pytest.raises(ValidationError):
        wire(AmendmentEffect, effect(effect_type="SUPERSEDES"))
    with pytest.raises(ValidationError):
        wire(AmendmentEffect, effect(affected_observation_ids=[ID2, ID2]))


def test_success_and_error_envelopes_keep_explicit_null_versions_and_safe_details() -> None:
    payload: dict[str, object] = {
        "data": {"id": ID2, "username": "learner-1", "role": "learner"},
        "meta": meta(),
    }
    user = wire(UserEnvelope, payload)
    assert isinstance(user, SuccessEnvelope)
    assert user.meta.versions.corpus_version_id is None
    assert json.loads(user.model_dump_json()) == payload
    error = wire(
        ErrorEnvelope,
        {
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed.",
                "details": [{"location": "body", "code": "INVALID_VALUE"}],
            },
            "meta": meta(),
        },
    )
    assert error.error.details[0].location == "body"
    with pytest.raises(ValidationError):
        wire(
            ApiError,
            {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed.",
                "details": [{"location": "body", "code": "INVALID_VALUE", "input": "secret"}],
            },
        )


def test_all_models_are_frozen_and_reject_unknown_fields() -> None:
    user = wire(UserIdentity, {"id": ID1, "username": "admin", "role": "admin"})
    with pytest.raises(ValidationError):
        user.role = "learner"
    payload = quantitative()
    payload["unknown"] = "must reject"
    with pytest.raises(ValidationError):
        wire(QuantitativeValue, payload)
    assert isinstance(wire(QuantitativeValue, quantitative()).evidence_ids, tuple)


def test_nullable_fields_are_required_and_not_defaulted() -> None:
    for model in PUBLIC_MODELS.values():
        assert all(field.is_required() for field in model.model_fields.values())
    missing_version = versions()
    del missing_version["corpus_version_id"]
    with pytest.raises(ValidationError):
        wire(VersionContext, missing_version)
    missing_context = relation()
    del missing_context["quantitative_context"]
    with pytest.raises(ValidationError):
        wire(RelationReference, missing_context)


def test_validation_and_serialization_schema_match_the_wire_contracts() -> None:
    assert len(PUBLIC_MODELS) == 20
    for model in PUBLIC_MODELS.values():
        validation = model.model_json_schema(mode="validation")
        assert validation == model.model_json_schema(mode="serialization")
        assert validation["additionalProperties"] is False
        assert set(validation["required"]) == set(validation["properties"])
    decimal_schema = QuantitativeValue.model_json_schema()["properties"]["normalized_value"]
    assert decimal_schema["anyOf"][0]["type"] == "string"
    assert decimal_schema["anyOf"][0]["pattern"] == DECIMAL_PATTERN
    assert UserIdentity.model_json_schema()["properties"]["id"]["pattern"] == ID_PATTERN
    date_schema = FinancialPeriod.model_json_schema()["properties"]["instant_date"]["anyOf"][0]
    assert date_schema["pattern"] == DATE_PATTERN and date_schema["format"] == "date"
    assert "discriminator" in EvidenceSupport.model_json_schema()["properties"]["records"]["items"]


def test_public_constants_encode_fixed_relations_and_approved_ownership() -> None:
    assert list(RELATION_DIRECTIONS) == [
        "OWNS",
        "PROMOTER_OF",
        "SUBSIDIARY_OF",
        "SUPPLIES_TO",
        "AUDITS",
        "LENDS_TO",
    ]
    assert RELATION_DIRECTIONS["OWNS"] == {"subject": "owner", "object": "owned"}
    assert MODULE_OWNERSHIP["company_search_backend"] == "M1"
    assert MODULE_OWNERSHIP["company_profile_experience"] == "M2"
    assert MODULE_OWNERSHIP["GET /v1/quotes"] == "M2"
    assert MODULE_OWNERSHIP["immutable_quote_snapshots"] == "M4"
    assert json.loads(json.dumps(MODULE_OWNERSHIP)) == MODULE_OWNERSHIP


def test_shape_contracts_do_not_enforce_source_containment_or_acceptance() -> None:
    payload = text_evidence()
    payload["boxes"] = [rectangle(x0=-100, y0=-100, x1=800, y1=900)]
    support = wire(EvidenceSupport, {"records": [payload]})
    assert support.records[0].boxes[0].x0 == -100
    duplicate_across_fields = copy.deepcopy(cell())
    duplicate_across_fields["row_label_cell_ids"] = [ID3]
    duplicate_across_fields["period_column_cell_ids"] = [ID3]
    wire(CellReference, duplicate_across_fields)
