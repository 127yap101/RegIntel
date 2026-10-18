"""M2 reads actual published PostgreSQL state using explicitly authored filings."""

from decimal import Decimal
from pathlib import Path

import pytest

from backend.tests.integration.test_publication_storage import configuration, counts, prepared
from backend.tests.integration.test_publication_storage import publication as publication
from backend.tests.integration.test_published_reads_storage import service
from backend.tests.integration.test_validation_storage import SOURCE
from backend.tests.integration.test_validation_storage import validated as validated
from regintel.analysis.acceptance import AcceptancePlan, evaluate
from regintel.analysis.models import ComparisonRequest
from regintel.analysis.service import ComparisonService
from regintel.auth.types import User
from regintel.publication.models import PublicationRequest
from regintel.publication.repository import PublicationRepository
from regintel.reads.repository import ReadNotFound

pytestmark = pytest.mark.integration

AUTHORED_SOURCE = SOURCE.replace("1,234.50", "1.00").replace(
    "Alpha Solar Limited business",
    "Beta Solar Limited revenue was INR 15.00 million on a consolidated basis "
    "from 1 April 2023 to 31 March 2024.\nAlpha Solar Limited business",
)


@pytest.mark.parametrize(
    "validated",
    [{"source": AUTHORED_SOURCE, "allowed_unit_labels": ("crore", "million")}],
    indirect=True,
)
@pytest.mark.parametrize(
    "scenario", ["positive", "unpublished", "temporal", "different_period", "acceptance"]
)
def test_comparison_over_frozen_postgresql_inputs(
    publication: tuple[PublicationRepository, User, PublicationRequest],
    tmp_path: Path,
    scenario: str,
) -> None:
    repository, user, publication_request = publication
    manifest = repository.build(publication_request, configuration(), user)
    reads = service(repository, tmp_path)
    numeric = [item for item in manifest.observations if item.kind == "numeric_fact"]
    assert len(numeric) == 2
    alpha = next(item for item in numeric if "Alpha Solar Limited revenue" in item.raw_text)
    beta = next(item for item in numeric if "Beta Solar Limited revenue" in item.raw_text)
    assert alpha.quantity is not None and alpha.metric_id is not None
    request = ComparisonRequest(
        corpus_version_id=manifest.id,
        company_ids=(alpha.subject_entity_id, beta.subject_entity_id),
        metric_ids=(alpha.metric_id,),
        period=alpha.quantity.period,
        basis="CONSOLIDATED",
    )
    if scenario == "unpublished":
        with pytest.raises(ReadNotFound):
            ComparisonService(reads).compare(request)
        assert counts(repository) == (0, 0, 0, 0)
        return
    repository.finalize(manifest.id, configuration(), user, prepared(repository, user, manifest))
    before = counts(repository)
    if scenario == "temporal":
        request = request.model_copy(update={"as_of_date": "2026-01-01"})
    elif scenario == "different_period":
        request = request.model_copy(
            update={
                "period": request.period.model_copy(
                    update={
                        "start_date": "2022-04-01",
                        "end_date": "2023-03-31",
                    }
                )
            }
        )
    result = ComparisonService(reads).compare(request)
    row = result.rows[0]
    if scenario in {"positive", "acceptance"}:
        assert all(cell.state == "AVAILABLE" for cell in row.cells)
        assert row.cells[0].normalized is not None and row.cells[1].normalized is not None
        assert row.cells[0].normalized.value == Decimal("10000000.00")
        assert row.cells[1].normalized.value == Decimal("15000000.00")
        assert row.differences[0].difference == Decimal("5000000.00")
        assert row.differences[0].percentage_difference == Decimal("50.000000")
        assert row.differences[0].input_observation_ids == (alpha.id, beta.id)
        assert row.cells[0].inputs[0].observation == alpha
        assert row.cells[1].inputs[0].observation == beta
    else:
        expected = "TEMPORAL_SUPPORT_UNAVAILABLE" if scenario == "temporal" else "INCOMPATIBLE"
        assert all(cell.state == expected and cell.normalized is None for cell in row.cells)
        assert row.differences[0].difference is None
    if scenario == "acceptance":
        plan = AcceptancePlan.model_validate(
            {
                "version": "m2-acceptance-1",
                "corpus_version_id": manifest.id,
                "manifest_sha256": manifest.sha256,
                "calculation_policy_version": "m2-comparison-1",
                "declared_data_kind": "AUTHORED",
                "reviewed_by": None,
                "reviewed_on": None,
                "cases": [
                    {
                        "id": "Authored PostgreSQL scaling",
                        "category": "different_units",
                        "request": request,
                        "expected": [
                            {
                                "metric_id": alpha.metric_id,
                                "cells": [
                                    {
                                        "company_id": item.subject_entity_id,
                                        "state": "AVAILABLE",
                                        "normalized": {
                                            "value": value,
                                            "unit": "INR",
                                            "currency": "INR",
                                            "multiplier": multiplier,
                                        },
                                        "input_observation_ids": [item.id],
                                        "input_evidence_ids": sorted(
                                            {support.evidence_id for support in item.supports}
                                            | {
                                                witness.span.evidence_id
                                                for witness in item.context_supports
                                            }
                                        ),
                                    }
                                    for item, value, multiplier in (
                                        (alpha, "10000000", "10000000"),
                                        (beta, "15000000", "1000000"),
                                    )
                                ],
                                "differences": [
                                    {
                                        "baseline_company_id": alpha.subject_entity_id,
                                        "company_id": beta.subject_entity_id,
                                        "state": "AVAILABLE",
                                        "input_observation_ids": [alpha.id, beta.id],
                                        "unit": "INR",
                                        "currency": "INR",
                                        "difference": "5000000",
                                        "percentage_state": "AVAILABLE",
                                        "percentage_difference": "50.000000",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )
        acceptance = evaluate(plan, result.view, ComparisonService(reads).compare)
        assert acceptance["status"] == "BLOCKED"  # Review and five categories remain pending.
        assert acceptance["passed_cases"] == 1 and acceptance["failed_cases"] == 0
        assert acceptance["covered_categories"] == ["different_units"]
    assert ComparisonService(reads).compare(request) == result
    assert counts(repository) == before
    assert repository.published(manifest.id).sha256 == manifest.sha256
