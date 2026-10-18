"""Independent authored acceptance oracles; no real-filing/gold result is asserted."""

import json
import runpy
import sys
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_analysis import comparison_fixture, period

from regintel.analysis.acceptance import (
    REQUIRED_CATEGORIES,
    AcceptanceCase,
    AcceptancePlan,
    Category,
    evaluate,
)
from regintel.analysis.models import ComparisonRequest, ComparisonResult, NormalizedAmount
from regintel.analysis.service import ComparisonService
from regintel.candidates.models import MetricDefinition
from regintel.reads.repository import Catalog
from regintel.reads.service import PublishedReadService

ROOT = Path(__file__).resolve().parents[2]


def authored_suite(tmp_path: Path) -> tuple[PublishedReadService, AcceptancePlan]:
    reads, request = comparison_fixture(tmp_path)
    memory = reads.corpus
    original = memory.manifest.observations
    alpha = next(item for item in original if item.subject_entity_id == request.company_ids[0])
    beta = next(item for item in original if item.subject_entity_id == request.company_ids[1])
    missing_metric = MetricDefinition.model_validate(
        memory.value.metrics[0].model_dump() | {"id": str(uuid4()), "key": "authored_missing"}
    )
    conflict_metric = MetricDefinition.model_validate(
        memory.value.metrics[0].model_dump() | {"id": str(uuid4()), "key": "authored_conflict"}
    )
    added = (
        alpha.model_copy(update={"id": str(uuid4()), "metric_id": missing_metric.id}),
        alpha.model_copy(update={"id": str(uuid4()), "metric_id": conflict_metric.id}),
        alpha.model_copy(update={"id": str(uuid4()), "metric_id": conflict_metric.id}),
        beta.model_copy(update={"id": str(uuid4()), "metric_id": conflict_metric.id}),
    )
    observations = tuple(sorted((*original, *added), key=lambda item: item.id))
    memory.manifest = memory.manifest.model_copy(
        update={
            "observations": observations,
            "active_observation_ids": tuple(item.id for item in observations),
        }
    )
    memory.value = Catalog(
        entities=memory.value.entities,
        metrics=(*memory.value.metrics, missing_metric, conflict_metric),
    )
    cases = []
    for category in REQUIRED_CATEGORIES:
        selected = request
        if category == "different_periods":
            selected = request.model_copy(
                update={"period": period(start_date="2024-04-01", end_date="2025-03-31")}
            )
        elif category == "standalone_vs_consolidated":
            selected = request.model_copy(update={"basis": "STANDALONE"})
        elif category == "missing_metric":
            selected = request.model_copy(update={"metric_ids": (missing_metric.id,)})
        elif category == "conflicting_observations":
            selected = request.model_copy(update={"metric_ids": (conflict_metric.id,)})
        cells = []
        for index, company in enumerate(request.company_ids):
            inputs = [
                item
                for item in observations
                if item.subject_entity_id == company and item.metric_id == selected.metric_ids[0]
            ]
            state = "AVAILABLE"
            if category in {"different_periods", "standalone_vs_consolidated"}:
                state = "INCOMPATIBLE"
            elif category == "missing_metric" and index == 1:
                state = "MISSING"
            elif category == "conflicting_observations" and index == 0:
                state = "CONFLICT"
            cells.append(
                {
                    "company_id": company,
                    "state": state,
                    "normalized": {
                        "value": "125000000" if index == 0 else "150000000",
                        "unit": "INR",
                        "currency": "INR",
                        "multiplier": "10000000" if index == 0 else "1000000",
                    }
                    if state == "AVAILABLE"
                    else None,
                    "input_observation_ids": tuple(item.id for item in inputs),
                    "input_evidence_ids": tuple(
                        sorted(
                            {support.evidence_id for item in inputs for support in item.supports}
                            | {
                                witness.span.evidence_id
                                for item in inputs
                                for witness in item.context_supports
                            }
                        )
                    ),
                }
            )
        positive = category in {"same_period_compatible", "different_units"}
        expected_pair = {
            "baseline_company_id": request.company_ids[0],
            "company_id": request.company_ids[1],
            "state": "AVAILABLE" if positive else "UNAVAILABLE",
            "input_observation_ids": (alpha.id, beta.id) if positive else (),
            "unit": "INR" if positive else None,
            "currency": "INR" if positive else None,
            "difference": "25000000" if positive else None,
            "percentage_state": "AVAILABLE" if positive else "UNAVAILABLE",
            "percentage_difference": "20.000000" if positive else None,
        }
        cases.append(
            AcceptanceCase.model_validate(
                {
                    "id": category,
                    "category": category,
                    "request": selected,
                    "expected": [
                        {
                            "metric_id": selected.metric_ids[0],
                            "cells": cells,
                            "differences": [expected_pair],
                        }
                    ],
                }
            )
        )
    scope = reads.scope(request.corpus_version_id, None, False)
    plan = AcceptancePlan(
        version="m2-acceptance-1",
        corpus_version_id=request.corpus_version_id,
        manifest_sha256=scope.info.manifest_sha256,
        calculation_policy_version="m2-comparison-1",
        declared_data_kind="AUTHORED",
        reviewed_by="Authored test reviewer assertion, not a real identity",
        reviewed_on="2026-10-18",
        cases=tuple(cases),
    )
    return reads, plan


def run_suite(reads: PublishedReadService, plan: AcceptancePlan) -> dict[str, object]:
    return evaluate(
        plan,
        reads.scope(plan.corpus_version_id, None, False).info,
        ComparisonService(reads).compare,
    )


def test_complete_authored_suite_checks_six_categories_without_writes(tmp_path: Path) -> None:
    reads, plan = authored_suite(tmp_path)
    before = reads.corpus.manifest.model_dump_json()
    report = run_suite(reads, plan)
    assert report["status"] == "CASES_PASS", json.dumps(report, default=str)
    assert report["covered_categories"] == list(REQUIRED_CATEGORIES)
    assert report["executed_cases"] == report["passed_cases"] == 6
    assert report["failed_cases"] == 0
    assert report["declared_data_kind"] == "AUTHORED"
    assert reads.corpus.manifest.model_dump_json() == before
    assert "research effectiveness" in str(report["limitation"])


@pytest.mark.parametrize("kind", ["REAL_FILINGS", "AUTHORED"])
def test_empty_and_unreviewed_plans_never_pass(tmp_path: Path, kind: str) -> None:
    reads, plan = authored_suite(tmp_path)
    pending = AcceptancePlan.model_validate(
        plan.model_dump() | {"declared_data_kind": kind, "reviewed_by": None, "reviewed_on": None}
    )
    assert run_suite(reads, pending)["status"] == "BLOCKED"
    empty = pending.model_copy(update={"cases": ()})
    report = run_suite(reads, empty)
    assert report["status"] == "BLOCKED"
    assert report["passed_cases"] == report["executed_cases"] == 0
    assert report["missing_categories"] == list(REQUIRED_CATEGORIES)


@pytest.mark.parametrize("change", ["value", "evidence", "input", "unit"])
def test_wrong_independent_oracles_fail(tmp_path: Path, change: str) -> None:
    reads, plan = authored_suite(tmp_path)
    case = plan.cases[0]
    row = case.expected[0]
    cell = row.cells[0]
    assert cell.normalized is not None
    if change in {"value", "unit"}:
        amount = NormalizedAmount.model_validate(
            cell.normalized.model_dump()
            | ({"value": "124999999"} if change == "value" else {"unit": "USD"})
        )
        changed = cell.model_copy(update={"normalized": amount})
    else:
        key = "input_evidence_ids" if change == "evidence" else "input_observation_ids"
        changed = cell.model_copy(update={key: (str(uuid4()),)})
    row = row.model_copy(update={"cells": (changed, row.cells[1])})
    case = case.model_copy(update={"expected": (row,)})
    plan = plan.model_copy(update={"cases": (case, *plan.cases[1:])})
    report = run_suite(reads, plan)
    assert report["status"] == "FAIL"
    assert report["failed_cases"] == 1


def test_category_labels_do_not_substitute_for_actual_input_context(tmp_path: Path) -> None:
    reads, plan = authored_suite(tmp_path)
    positive = plan.cases[0].model_copy(
        update={"category": cast(Category, "conflicting_observations")}
    )
    report = run_suite(reads, plan.model_copy(update={"cases": (positive,)}))
    assert report["status"] == "FAIL"
    assert report["covered_categories"] == []


def test_manifest_pin_rejects_changed_published_state(tmp_path: Path) -> None:
    reads, plan = authored_suite(tmp_path)
    with pytest.raises(ValueError, match="manifest"):
        run_suite(reads, plan.model_copy(update={"manifest_sha256": "0" * 64}))


@pytest.mark.parametrize("changed", ["selection", "manifest"])
def test_mixed_response_scope_fails_each_case(tmp_path: Path, changed: str) -> None:
    reads, plan = authored_suite(tmp_path)

    def mixed(request: ComparisonRequest) -> ComparisonResult:
        result = ComparisonService(reads).compare(request)
        if changed == "manifest":
            return result.model_copy(
                update={"view": result.view.model_copy(update={"manifest_sha256": "0" * 64})}
            )
        return result.model_copy(
            update={"selection": request.model_copy(update={"as_of_date": "2026-01-01"})}
        )

    report = evaluate(plan, reads.scope(plan.corpus_version_id, None, False).info, mixed)
    assert report["status"] == "FAIL" and report["failed_cases"] == 6


def test_sanitized_case_failure_does_not_expose_diagnostics(tmp_path: Path) -> None:
    reads, plan = authored_suite(tmp_path)

    def failed(request: ComparisonRequest) -> ComparisonResult:
        raise RuntimeError("credential=value filing text should not enter the report")

    report = evaluate(plan, reads.scope(plan.corpus_version_id, None, False).info, failed)
    assert report["status"] == "FAIL" and report["failed_cases"] == 6
    assert "credential=value" not in json.dumps(report)


@pytest.mark.parametrize(
    "change", ["duplicate", "foreign", "partial", "review", "unknown_period", "float"]
)
def test_invalid_plan_fails_before_execution(tmp_path: Path, change: str) -> None:
    _, plan = authored_suite(tmp_path)
    value = json.loads(plan.model_dump_json())
    if change == "duplicate":
        value["cases"].append(value["cases"][0])
    elif change == "foreign":
        value["cases"][0]["request"]["corpus_version_id"] = str(uuid4())
    elif change == "partial":
        value["cases"][0]["expected"][0]["cells"].pop()
    elif change == "review":
        value["reviewed_on"] = None
    elif change == "unknown_period":
        value["cases"][0]["request"]["period"]["start_date"] = None
    else:
        value["cases"][0]["expected"][0]["cells"][0]["normalized"]["value"] = 125000000.0
    with pytest.raises(ValidationError):
        AcceptancePlan.model_validate_json(json.dumps(value))


def test_cli_rejects_oversized_plan_before_loading_database(tmp_path: Path) -> None:
    helpers = runpy.run_path(str(ROOT / "scripts/evaluate-analysis.py"))
    path = tmp_path / "oversized.json"
    path.write_bytes(b" " * 1_000_001)
    with pytest.raises(ValueError, match="size bound"):
        helpers["run"](path, tmp_path / "no-configuration")


def test_plan_schema_is_available_without_local_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    helpers = runpy.run_path(str(ROOT / "scripts/evaluate-analysis.py"))
    monkeypatch.setattr(sys, "argv", ["evaluate-analysis.py", "--schema"])
    assert helpers["main"]() == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["title"] == "AcceptancePlan"
    assert "expected" in schema["$defs"]["AcceptanceCase"]["required"]
