"""Labelled authored M2 engineering cases, never real financial or gold results."""

import json
from decimal import Decimal, getcontext, localcontext
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_candidate_models import ALPHA, BETA, make_input, metric
from test_publication_engine import configuration, filing, selected
from test_published_reads import client_for, fixture_service
from test_validation_models import money_policy, numeric_draft, validation_input

from regintel.analysis.arithmetic import NormalizationRangeError, normalize
from regintel.analysis.models import ComparisonRequest, ComparisonResult, QuotesResult
from regintel.analysis.service import ComparisonService
from regintel.candidates.models import CandidateBundle, ExtractionInput
from regintel.candidates.records import stable_id
from regintel.contracts.models import FinancialPeriod, QuantitativeValue
from regintel.fixtures.sources import fixture_id
from regintel.publication.engine import approve_candidate
from regintel.publication.models import PublishedObservation
from regintel.reads.repository import Catalog, ReadUnavailable
from regintel.reads.service import PublishedReadService


def period(**updates: object) -> FinancialPeriod:
    return FinancialPeriod.model_validate(
        {
            "kind": "DURATION",
            "start_date": "2025-04-01",
            "end_date": "2026-03-31",
            "instant_date": None,
            "raw_label": "Authored full year",
        }
        | updates
    )


def quantity(**updates: object) -> QuantitativeValue:
    return QuantitativeValue.model_validate(
        {
            "raw_value": "12.50",
            "normalized_value": "12.50",
            "raw_unit": "crore",
            "normalized_unit": "crore",
            "raw_currency": "INR",
            "currency": "INR",
            "period": period(),
            "basis": "CONSOLIDATED",
            "raw_basis_label": "consolidated",
            "denominator": None,
            "stake_kind": None,
            "ownership_date": None,
            "evidence_ids": (fixture_id(750),),
        }
        | updates
    )


def comparison_fixture(tmp_path: Path) -> tuple[PublishedReadService, ComparisonRequest]:
    reads, memory, _, _ = fixture_service(tmp_path)
    template = memory.manifest.observations[0]
    assert template.object_entity_id is not None
    definition = metric()
    observations = []
    for company, value, unit in (
        (template.subject_entity_id, "12.50", "crore"),
        (template.object_entity_id, "150", "million"),
    ):
        # Controlled consumer DTOs; publication-gate correctness has separate tests.
        # All values are explicitly authored, with source spans retained for M2 identity tests.
        support = template.supports[0]
        text = (
            f"Authored fixture: {company} revenue INR {value} {unit} "
            "from 1 April 2025 to 31 March 2026 consolidated."
        )
        support = support.model_copy(update={"start": 0, "end": len(text), "quote": text})
        observations.append(
            PublishedObservation.model_validate(
                template.model_dump()
                | {
                    "id": str(uuid4()),
                    "subject_entity_id": company,
                    "object_entity_id": None,
                    "relation_type": None,
                    "kind": "numeric_fact",
                    "metric_id": definition.id,
                    "raw_text": text,
                    "supports": (support,),
                    "quantity": quantity(
                        raw_value=value,
                        normalized_value=value,
                        raw_unit=unit,
                        normalized_unit=unit,
                        evidence_ids=(support.evidence_id,),
                    ),
                }
            )
        )
    memory.value = Catalog(entities=memory.value.entities, metrics=(definition,))
    memory.manifest = memory.manifest.model_copy(
        update={
            "observations": tuple(sorted(observations, key=lambda item: item.id)),
            "active_observation_ids": tuple(item.id for item in observations),
        }
    )
    request = ComparisonRequest(
        corpus_version_id=memory.manifest.id,
        company_ids=(template.subject_entity_id, template.object_entity_id),
        metric_ids=(definition.id,),
        period=period(),
        basis="CONSOLIDATED",
    )
    return reads, request


def change_input(reads: PublishedReadService, company: str, **updates: object) -> None:
    memory = reads.corpus
    changed = []
    for observation in memory.manifest.observations:
        if observation.subject_entity_id == company:
            assert observation.quantity is not None
            observation = observation.model_copy(
                update={
                    "quantity": QuantitativeValue.model_validate(
                        observation.quantity.model_dump() | updates
                    )
                }
            )
        changed.append(observation)
    memory.manifest = memory.manifest.model_copy(update={"observations": tuple(changed)})


def test_compatible_unit_scaling_exact_differences_and_source_ids(tmp_path: Path) -> None:
    reads, request = comparison_fixture(tmp_path)
    before = reads.corpus.manifest.model_dump_json()
    result = ComparisonService(reads).compare(request)
    row = result.rows[0]
    assert [cell.state for cell in row.cells] == ["AVAILABLE", "AVAILABLE"]
    assert [cell.normalized.value for cell in row.cells] == [
        Decimal("125000000.00"),
        Decimal("150000000"),
    ]
    delta = row.differences[0]
    assert delta.difference == Decimal("25000000.00")
    assert delta.percentage_difference == Decimal("20.000000")
    assert delta.input_observation_ids == tuple(cell.inputs[0].observation.id for cell in row.cells)
    assert all(cell.inputs[0].observation.supports for cell in row.cells)
    wire = result.model_dump_json()
    assert '"difference":"25000000.00"' in wire
    assert ComparisonResult.model_validate_json(wire) == result
    assert reads.corpus.manifest.model_dump_json() == before


@pytest.mark.parametrize(
    "unit,currency,value,expected,target",
    [
        ("INR", "INR", "0.10", "0.10", "INR"),
        ("crores", "INR", "1.23", "12300000.00", "INR"),
        ("lakhs", "USD", "2", "200000", "USD"),
        ("billion", "INR", "-1.2", "-1200000000.0", "INR"),
        ("GW", None, "1.25", "1250.00", "MW"),
        ("MW", None, "0", "0", "MW"),
        ("shares", None, "9007199254740993", "9007199254740993", "shares"),
        ("%", None, "12.500", "12.500", "%"),
    ],
)
def test_exact_supported_unit_table(
    unit: str, currency: str | None, value: str, expected: str, target: str
) -> None:
    result = normalize(quantity(normalized_unit=unit, currency=currency, normalized_value=value))
    assert format(result.value, "f") == expected and result.unit == target


@pytest.mark.parametrize(
    "unit,currency,value",
    [
        ("crore", None, "1"),
        ("USD", "INR", "1"),
        ("rupees", "USD", "1"),
        ("crore", "EUR", "1"),
        ("MW", "INR", "1"),
        ("shares", None, "1.5"),
        ("shares", None, "-1"),
        ("GW", None, "-1"),
        ("%", None, "101"),
        ("%", None, "-1"),
        ("kW", None, "1"),
    ],
)
def test_unsupported_or_contradictory_units_do_not_compute(
    unit: str, currency: str | None, value: str
) -> None:
    with pytest.raises(ValueError):
        normalize(quantity(normalized_unit=unit, currency=currency, normalized_value=value))


@pytest.mark.parametrize(
    "updates,state",
    [
        ({"period": period(start_date="2024-04-01", end_date="2025-03-31")}, "INCOMPATIBLE"),
        ({"period": period(start_date=None)}, "CONTEXT_REQUIRED"),
        ({"basis": "STANDALONE"}, "INCOMPATIBLE"),
        ({"basis": "UNKNOWN"}, "CONTEXT_REQUIRED"),
        ({"normalized_value": None}, "CONTEXT_REQUIRED"),
        ({"denominator": "issued equity share capital"}, "CONTEXT_REQUIRED"),
        ({"normalized_unit": "unknown"}, "UNSUPPORTED_UNIT"),
        ({"normalized_value": "9" * 120}, "OUT_OF_RANGE"),
    ],
)
def test_incompatible_and_missing_context_never_derive(
    tmp_path: Path, updates: dict[str, object], state: str
) -> None:
    reads, request = comparison_fixture(tmp_path)
    change_input(reads, request.company_ids[1], **updates)
    row = ComparisonService(reads).compare(request).rows[0]
    assert row.cells[1].state == state and row.cells[1].normalized is None
    assert (
        row.differences[0].difference is None and row.differences[0].percentage_difference is None
    )


@pytest.mark.parametrize("baseline", ["0", "-2"])
def test_nonpositive_baseline_has_exact_difference_without_percentage(
    tmp_path: Path, baseline: str
) -> None:
    reads, request = comparison_fixture(tmp_path)
    change_input(reads, request.company_ids[0], normalized_value=baseline, normalized_unit="INR")
    delta = ComparisonService(reads).compare(request).rows[0].differences[0]
    assert delta.state == "AVAILABLE" and delta.difference is not None
    assert delta.percentage_state == "NON_POSITIVE_BASELINE" and delta.percentage_difference is None


def test_currencies_are_not_converted(tmp_path: Path) -> None:
    reads, request = comparison_fixture(tmp_path)
    change_input(reads, request.company_ids[1], currency="USD")
    result = ComparisonService(reads).compare(request).rows[0]
    assert all(cell.state == "AVAILABLE" for cell in result.cells)
    assert result.differences[0].state == "INCOMPATIBLE"


def test_duplicate_accepted_values_remain_conflicts_even_if_equal(tmp_path: Path) -> None:
    reads, request = comparison_fixture(tmp_path)
    memory = reads.corpus
    original = memory.manifest.observations[0]
    duplicate = original.model_copy(
        update={"id": str(uuid4()), "source_published_on": "2026-01-01"}
    )
    memory.manifest = memory.manifest.model_copy(
        update={
            "observations": tuple(
                sorted((*memory.manifest.observations, duplicate), key=lambda item: item.id)
            ),
            "active_observation_ids": (*memory.manifest.active_observation_ids, duplicate.id),
        }
    )
    result = ComparisonService(reads).compare(request).rows[0]
    conflicted = next(
        cell for cell in result.cells if cell.company_id == original.subject_entity_id
    )
    assert conflicted.state == "CONFLICT" and len(conflicted.inputs) == 2
    assert result.differences[0].state == "UNAVAILABLE"


def test_context_request_and_unsupported_asof_are_explicit(tmp_path: Path) -> None:
    reads, request = comparison_fixture(tmp_path)
    result = ComparisonService(reads).compare(
        request.model_copy(update={"period": period(start_date=None)})
    )
    assert all(cell.state == "CONTEXT_REQUIRED" for cell in result.rows[0].cells)
    memory = reads.corpus
    memory.manifest = memory.manifest.model_copy(
        update={
            "filings": tuple(
                item.model_copy(update={"published_on": None}) for item in memory.manifest.filings
            )
        }
    )
    result = ComparisonService(reads).compare(
        request.model_copy(update={"as_of_date": "2026-01-01"})
    )
    assert result.view.state == "TEMPORAL_SUPPORT_UNAVAILABLE"
    assert all(
        cell.state == "TEMPORAL_SUPPORT_UNAVAILABLE" and not cell.inputs
        for cell in result.rows[0].cells
    )


@pytest.mark.parametrize(
    "baseline,comparison,expected",
    [
        ("3", "4", "33.333333"),
        ("3", "5", "66.666667"),
        ("200000000", "200000001", "0.000000"),
        ("200000000", "200000003", "0.000002"),
        ("9007199254740993.01", "9007199254740993.02", "0.000000"),
    ],
)
def test_formula_rounding_and_large_exact_values_ignore_global_context(
    tmp_path: Path, baseline: str, comparison: str, expected: str
) -> None:
    reads, request = comparison_fixture(tmp_path)
    change_input(reads, request.company_ids[0], normalized_value=baseline, normalized_unit="INR")
    change_input(reads, request.company_ids[1], normalized_value=comparison, normalized_unit="INR")
    before = getcontext().copy()
    with localcontext() as hostile:
        hostile.prec = 2
        delta = ComparisonService(reads).compare(request).rows[0].differences[0]
        assert delta.percentage_difference == Decimal(expected)
        assert hostile.prec == 2
    assert getcontext().prec == before.prec


def test_scale_overflow_is_not_rounded(tmp_path: Path) -> None:
    with pytest.raises(NormalizationRangeError):
        normalize(quantity(normalized_value="9" * 120))
    reads, request = comparison_fixture(tmp_path)
    change_input(
        reads,
        request.company_ids[0],
        normalized_value="0." + "0" * 119 + "1",
        normalized_unit="INR",
    )
    result = ComparisonService(reads).compare(request).rows[0].differences[0]
    assert result.state == "AVAILABLE" and result.percentage_state == "OUT_OF_RANGE"


@pytest.mark.parametrize(
    "changes",
    [
        {"company_ids": [fixture_id(101), fixture_id(101)]},
        {"metric_ids": [fixture_id(301), fixture_id(301)]},
        {"historical": True},
        {"basis": "consolidated"},
        {"corpus_version_id": "invalid"},
    ],
)
def test_invalid_selections_reject(tmp_path: Path, changes: dict[str, object]) -> None:
    _, request = comparison_fixture(tmp_path)
    with pytest.raises(ValidationError):
        ComparisonRequest.model_validate(request.model_dump() | changes)


def test_authenticated_api_envelope_and_empty_quotes(tmp_path: Path) -> None:
    reads, request = comparison_fixture(tmp_path)
    client, headers, users = client_for(reads)
    with client:
        assert client.post("/v1/compare", json=request.model_dump(mode="json")).status_code == 401
        response = client.post("/v1/compare", json=request.model_dump(mode="json"), headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["meta"]["versions"]["corpus_version_id"] == request.corpus_version_id
        result = ComparisonResult.model_validate_json(json.dumps(response.json()["data"]))
        assert result.rows[0].differences[0].percentage_difference == Decimal("20.000000")
        quotes = client.get("/v1/quotes", headers=headers)
        assert QuotesResult.model_validate(quotes.json()["data"]).quotes == ()
        assert quotes.json()["meta"]["versions"]["quote_version_id"] is None
        assert client.get("/v1/quotes").status_code == 401
        users.user = None
        assert (
            client.post(
                "/v1/compare", json=request.model_dump(mode="json"), headers=headers
            ).status_code
            == 401
        )
        assert client.get("/v1/quotes", headers=headers).status_code == 401


def test_unpublished_and_foreign_ids_are_never_read(tmp_path: Path) -> None:
    reads, request = comparison_fixture(tmp_path)
    client, headers, _ = client_for(reads)
    with client:
        for changed in (
            {"corpus_version_id": str(uuid4())},
            {"company_ids": [request.company_ids[0], str(uuid4())]},
            {"metric_ids": [str(uuid4())]},
        ):
            response = client.post(
                "/v1/compare", json=request.model_dump(mode="json") | changed, headers=headers
            )
            assert response.status_code == 404
            assert "Authored fixture" not in response.text


def test_comparison_consumes_quantities_accepted_by_real_m1_gates(tmp_path: Path) -> None:
    reads, request = comparison_fixture(tmp_path)
    accepted = []
    filings = []
    for index, (name, value) in enumerate(((ALPHA, "12.50"), (BETA, "15.00"))):
        source = make_input(
            f"{name} consolidated revenue INR {value} crore from 1 April 2025 to 31 March 2026.",
            metrics=(metric(),),
        )
        # Each authored source has distinct immutable document/parse/mention IDs.
        owned = {
            *source.entity_run.evidence_ids,
            source.entity_run.id,
            source.entity_run.parse_version_id,
            source.evidence[0].source.filing_id,
            source.evidence[0].source.filing_version_id,
            source.evidence[0].source.page_id,
            source.evidence[0].span.block_id,
            *(mention.id for mention in source.entity_run.mentions),
        }
        encoded = source.model_dump_json()
        for identity in sorted(owned):
            encoded = encoded.replace(identity, stable_id(f"m2-authored:{index}:{identity}"))
        source = ExtractionInput.model_validate_json(encoded)
        frozen = validation_input(
            source,
            bundle=CandidateBundle(numeric_facts=(numeric_draft(source, value),)),
            policies=(money_policy(),),
        )
        snapshot = filing(frozen)
        approval = approve_candidate(
            request.corpus_version_id, selected(frozen), frozen, snapshot, None, configuration()
        )
        assert approval.fresh_validation.results[0].state == "PASS"
        accepted.append(approval.observation)
        filings.append(snapshot)
    memory = reads.corpus
    memory.manifest = memory.manifest.model_copy(
        update={
            "observations": tuple(sorted(accepted, key=lambda item: item.id)),
            "active_observation_ids": tuple(item.id for item in accepted),
            "filings": tuple(filings),
        }
    )
    result = ComparisonService(reads).compare(request).rows[0]
    assert result.differences[0].difference == Decimal("25000000.00")
    assert result.differences[0].percentage_difference == Decimal("20.000000")
    assert all(len(cell.inputs[0].observation.context_supports) == 5 for cell in result.cells)


def test_missing_metric_and_inactive_observations_do_not_supply_inputs(tmp_path: Path) -> None:
    reads, request = comparison_fixture(tmp_path)
    memory = reads.corpus
    original = next(
        item
        for item in memory.manifest.observations
        if item.subject_entity_id == request.company_ids[1]
    )
    # Another published metric retains company membership; the requested metric is absent.
    different = original.model_copy(update={"id": str(uuid4()), "metric_id": str(uuid4())})
    memory.manifest = memory.manifest.model_copy(
        update={
            "observations": tuple(
                sorted((*memory.manifest.observations, different), key=lambda item: item.id)
            ),
            "active_observation_ids": tuple(
                item.id for item in memory.manifest.observations if item.id != original.id
            )
            + (different.id,),
        }
    )
    result = ComparisonService(reads).compare(request).rows[0]
    assert result.cells[1].state == "MISSING" and result.cells[1].inputs == ()
    assert result.differences[0].difference is None
    assert original in memory.manifest.observations


def test_excess_conflicts_fail_without_silently_truncating(tmp_path: Path) -> None:
    reads, request = comparison_fixture(tmp_path)
    memory = reads.corpus
    original = memory.manifest.observations[0]
    duplicates = tuple(original.model_copy(update={"id": str(uuid4())}) for _ in range(101))
    memory.manifest = memory.manifest.model_copy(
        update={
            "observations": tuple(
                sorted((*memory.manifest.observations, *duplicates), key=lambda item: item.id)
            ),
            "active_observation_ids": (
                *memory.manifest.active_observation_ids,
                *(item.id for item in duplicates),
            ),
        }
    )
    with pytest.raises(ReadUnavailable):
        ComparisonService(reads).compare(request)


@pytest.mark.parametrize("unknown", ["basis", "start", "period", "unrelated_period"])
def test_unresolved_active_context_cannot_be_silently_excluded(
    tmp_path: Path, unknown: str
) -> None:
    reads, request = comparison_fixture(tmp_path)
    memory = reads.corpus
    original = next(
        item
        for item in memory.manifest.observations
        if item.subject_entity_id == request.company_ids[0]
    )
    assert original.quantity is not None
    quantity = original.quantity
    if unknown == "basis":
        quantity = quantity.model_copy(update={"basis": "UNKNOWN"})
    elif unknown == "start":
        quantity = quantity.model_copy(update={"period": period(start_date=None)})
    elif unknown == "period":
        quantity = quantity.model_copy(
            update={"period": period(kind="UNKNOWN", start_date=None, end_date=None)}
        )
    else:
        quantity = quantity.model_copy(
            update={"period": period(start_date="2023-04-01", end_date="2024-03-31")}
        )
    ambiguous = original.model_copy(update={"id": str(uuid4()), "quantity": quantity})
    memory.manifest = memory.manifest.model_copy(
        update={
            "observations": tuple(
                sorted((*memory.manifest.observations, ambiguous), key=lambda item: item.id)
            ),
            "active_observation_ids": (*memory.manifest.active_observation_ids, ambiguous.id),
        }
    )
    row = ComparisonService(reads).compare(request).rows[0]
    if unknown == "unrelated_period":
        assert row.cells[0].state == "AVAILABLE"
        assert row.differences[0].percentage_difference == Decimal("20.000000")
    else:
        assert row.cells[0].state == "CONTEXT_REQUIRED" and len(row.cells[0].inputs) == 2
        assert row.differences[0].difference is None


def test_exact_difference_overflow_and_invalid_json_are_explicit(tmp_path: Path) -> None:
    reads, request = comparison_fixture(tmp_path)
    change_input(
        reads, request.company_ids[0], normalized_value="-" + "9" * 120, normalized_unit="INR"
    )
    change_input(reads, request.company_ids[1], normalized_value="9" * 120, normalized_unit="INR")
    pair = ComparisonService(reads).compare(request).rows[0].differences[0]
    assert pair.state == "OUT_OF_RANGE" and pair.difference is None
    client, headers, _ = client_for(reads)
    with client:
        response = client.post(
            "/v1/compare",
            json=request.model_dump(mode="json") | {"synthetic_private_field": 1.23},
            headers=headers,
        )
        assert response.status_code == 422
        assert "synthetic_private_field" not in response.text


def test_percentage_points_are_distinct_from_relative_percentage_difference(tmp_path: Path) -> None:
    reads, request = comparison_fixture(tmp_path)
    for company, value in zip(request.company_ids, ("12.00", "15.00"), strict=True):
        change_input(reads, company, normalized_value=value, normalized_unit="%", currency=None)
    row = ComparisonService(reads).compare(request).rows[0]
    assert all(cell.normalized.unit == "%" for cell in row.cells)
    pair = row.differences[0]
    assert pair.unit == "percentage points" and pair.difference == Decimal("3.00")
    assert pair.percentage_difference == Decimal("25.000000")
