"""Bounded graph topology, exact filter contexts and inert source-text behavior."""

from pathlib import Path
from uuid import uuid4

import pytest
from test_retrieval import Graph, question, service

from regintel.contracts.models import FinancialPeriod, QuantitativeValue
from regintel.publication.embeddings import SourceChunk, lexical_counts
from regintel.reads.repository import ReadUnavailable
from regintel.retrieval.graph import Neighbor
from regintel.retrieval.models import Filters
from regintel.retrieval.service import lexical_document, matches


def test_second_hop_requires_a_supported_first_hop_and_preserves_direction(tmp_path: Path) -> None:
    engine, _, _ = service(tmp_path)
    item = engine.reads.corpus.manifest.observations[0]
    neighbor = Neighbor(item.id, item.subject_entity_id, item.object_entity_id, 2)
    with pytest.raises(ReadUnavailable):
        engine._validate_neighbor(neighbor, {item.id: item}, set(), 2)
    with pytest.raises(ReadUnavailable):
        engine._validate_neighbor(neighbor, {item.id: item}, {item.subject_entity_id}, 1)
    engine._validate_neighbor(neighbor, {item.id: item}, {item.subject_entity_id}, 2)


def test_expansion_cannot_escape_company_or_period_filters(tmp_path: Path) -> None:
    engine, _, _ = service(tmp_path)
    manifest = engine.reads.corpus.manifest
    item = manifest.observations[0]

    class Rogue(Graph):
        def expand(self, manifest, seeds, allowed, hops):
            return (Neighbor(item.id, item.subject_entity_id, item.object_entity_id, 1),)

    engine.graph = Rogue()
    with pytest.raises(ReadUnavailable):
        engine.search(question(arm="B3", filters=Filters(company_id=str(uuid4()))))
    period = FinancialPeriod(
        kind="DURATION",
        start_date="2024-04-01",
        end_date="2025-03-31",
        instant_date=None,
        raw_label=None,
    )
    with pytest.raises(ReadUnavailable):
        engine.search(question(arm="B3", filters=Filters(period=period, basis="CONSOLIDATED")))


def test_graph_bound_failure_is_explicit_not_partial(tmp_path: Path) -> None:
    engine, _, _ = service(tmp_path)
    item = engine.reads.corpus.manifest.observations[0]

    class Oversize(Graph):
        def expand(self, manifest, seeds, allowed, hops):
            return tuple(
                Neighbor(str(uuid4()), item.subject_entity_id, item.object_entity_id, 1)
                for _ in range(1001)
            )

    engine.graph = Oversize()
    with pytest.raises(ReadUnavailable, match="bound"):
        engine.search(question(arm="B3"))


@pytest.mark.parametrize("difference", ["basis", "start", "end", "kind", "missing"])
def test_complete_financial_filters_require_exact_dates_and_basis(
    tmp_path: Path, difference: str
) -> None:
    engine, _, _ = service(tmp_path)
    item = engine.reads.corpus.manifest.observations[0]
    period = FinancialPeriod(
        kind="DURATION",
        start_date="2024-04-01",
        end_date="2025-03-31",
        instant_date=None,
        raw_label="Authored FY25",
    )
    quantity = QuantitativeValue.model_validate(
        {
            "raw_value": "12.00",
            "normalized_value": "12.00",
            "raw_unit": "crore",
            "normalized_unit": "crore",
            "raw_currency": "INR",
            "currency": "INR",
            "period": period,
            "basis": "CONSOLIDATED",
            "raw_basis_label": "consolidated",
            "denominator": None,
            "stake_kind": None,
            "ownership_date": None,
            "evidence_ids": (item.supports[0].evidence_id,),
        }
    )
    item = item.model_copy(update={"quantity": quantity})
    filters = Filters(period=period, basis="CONSOLIDATED")
    assert matches(item, filters)
    if difference == "basis":
        filters = filters.model_copy(update={"basis": "STANDALONE"})
    elif difference == "missing":
        filters = filters.model_copy(
            update={"period": period.model_copy(update={"start_date": None})}
        )
    elif difference == "kind":
        filters = filters.model_copy(
            update={
                "period": FinancialPeriod(
                    kind="INSTANT",
                    start_date=None,
                    end_date=None,
                    instant_date="2025-03-31",
                    raw_label=None,
                )
            }
        )
    else:
        filters = filters.model_copy(
            update={
                "period": period.model_copy(
                    update={
                        "start_date" if difference == "start" else "end_date": "2024-05-01"
                        if difference == "start"
                        else "2025-02-28"
                    }
                )
            }
        )
    assert not matches(item, filters)


def test_table_context_witnesses_are_local_and_repeated_with_the_chunk(tmp_path: Path) -> None:
    from regintel.validation.models import ContextWitness

    engine, _, _ = service(tmp_path)
    item = engine.reads.corpus.manifest.observations[0]
    span = item.supports[0]
    header = span.model_copy(
        update={
            "evidence_id": str(uuid4()),
            "quote": "Consolidated FY2025 crore",
            "start": 0,
            "end": len("Consolidated FY2025 crore"),
        }
    )
    item = item.model_copy(
        update={"context_supports": (ContextWitness(role="BASIS", span=header),)}
    )
    chunk = SourceChunk(
        id=str(uuid4()),
        observation_id=item.id,
        support=span,
        token_count=20,
        embedding=(1.0,) + (0.0,) * 383,
        term_counts=lexical_counts(span.quote),
    )
    terms = lexical_document(chunk, item)
    assert terms["consolidated"] == 1 and terms["fy2025"] == 1
    assert "unrelated" not in terms
