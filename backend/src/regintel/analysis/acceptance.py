"""Compare independently recorded expectations with read-only published M2 results.

This is an engineering acceptance runner, not a research scoring or fact-writing API.
Review/data-origin labels in a plan are operator assertions, not verified identities.
"""

from collections.abc import Callable
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from regintel.analysis.arithmetic import complete_period, period_key
from regintel.analysis.models import (
    CALCULATION_POLICY,
    CellState,
    ComparisonRequest,
    ComparisonResult,
    NormalizedAmount,
    PairDifference,
)
from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, DateString, DecimalValue, Label, Sha256Hash
from regintel.reads.models import ViewInfo

Category = Literal[
    "same_period_compatible",
    "different_periods",
    "standalone_vs_consolidated",
    "different_units",
    "missing_metric",
    "conflicting_observations",
]
REQUIRED_CATEGORIES: tuple[Category, ...] = (
    "same_period_compatible",
    "different_periods",
    "standalone_vs_consolidated",
    "different_units",
    "missing_metric",
    "conflicting_observations",
)
Ids = Annotated[tuple[CanonicalId, ...], Field(strict=False, max_length=100)]


class CellExpectation(ContractModel):
    company_id: CanonicalId
    state: CellState
    normalized: NormalizedAmount | None
    input_observation_ids: Ids
    input_evidence_ids: Ids


class DifferenceExpectation(ContractModel):
    baseline_company_id: CanonicalId
    company_id: CanonicalId
    state: Literal["AVAILABLE", "UNAVAILABLE", "INCOMPATIBLE", "OUT_OF_RANGE"]
    input_observation_ids: Ids
    unit: Label | None
    currency: Label | None
    difference: DecimalValue | None
    percentage_state: Literal["AVAILABLE", "UNAVAILABLE", "NON_POSITIVE_BASELINE", "OUT_OF_RANGE"]
    percentage_difference: DecimalValue | None


class RowExpectation(ContractModel):
    metric_id: CanonicalId
    cells: Annotated[tuple[CellExpectation, ...], Field(strict=False, min_length=2, max_length=4)]
    differences: Annotated[
        tuple[DifferenceExpectation, ...], Field(strict=False, min_length=1, max_length=3)
    ]


class AcceptanceCase(ContractModel):
    id: Label
    category: Category
    request: ComparisonRequest
    expected: Annotated[
        tuple[RowExpectation, ...], Field(strict=False, min_length=1, max_length=12)
    ]

    @model_validator(mode="after")
    def complete_expectation(self) -> Self:
        request = self.request
        if not complete_period(request.period) or request.basis == "UNKNOWN":
            raise ValueError("Acceptance selections require a complete period and known basis.")
        if tuple(row.metric_id for row in self.expected) != request.metric_ids:
            raise ValueError("Record expectations for every selected metric in order.")
        for row in self.expected:
            if tuple(cell.company_id for cell in row.cells) != request.company_ids:
                raise ValueError("Record expectations for every selected company in order.")
            if len(row.differences) != len(row.cells) - 1:
                raise ValueError("Record every selected baseline comparison.")
            for cell in row.cells:
                if len(set(cell.input_observation_ids)) != len(cell.input_observation_ids) or len(
                    set(cell.input_evidence_ids)
                ) != len(cell.input_evidence_ids):
                    raise ValueError("Expected observation/evidence IDs must be distinct.")
                if (cell.state == "AVAILABLE") != (cell.normalized is not None):
                    raise ValueError("Only available cells carry normalized amounts.")
                if cell.state == "AVAILABLE" and (
                    len(cell.input_observation_ids) != 1 or not cell.input_evidence_ids
                ):
                    raise ValueError("An available expectation requires its exact input/evidence.")
            for company, pair in zip(request.company_ids[1:], row.differences, strict=True):
                if (pair.baseline_company_id, pair.company_id) != (request.company_ids[0], company):
                    raise ValueError("Expected differences must retain their selected companies.")
                PairDifference.model_validate(pair.model_dump() | {"explanation": "Expected."})
        return self


class AcceptancePlan(ContractModel):
    version: Literal["m2-acceptance-1"]
    corpus_version_id: CanonicalId
    manifest_sha256: Sha256Hash
    calculation_policy_version: Literal["m2-comparison-1"]
    declared_data_kind: Literal["REAL_FILINGS", "AUTHORED"]
    reviewed_by: Label | None
    reviewed_on: DateString | None
    cases: Annotated[tuple[AcceptanceCase, ...], Field(strict=False, max_length=24)]

    @model_validator(mode="after")
    def pinned_scope(self) -> Self:
        if (self.reviewed_by is None) != (self.reviewed_on is None):
            raise ValueError("Record both reviewer and review date, or leave both pending.")
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("Acceptance case IDs must be distinct.")
        if any(case.request.corpus_version_id != self.corpus_version_id for case in self.cases):
            raise ValueError("All cases must use the pinned published corpus.")
        return self


def result_rows(result: ComparisonResult) -> tuple[RowExpectation, ...]:
    """Capture values/states and exact support IDs, without interpreting financial labels."""
    return tuple(
        RowExpectation(
            metric_id=row.metric.id,
            cells=tuple(
                CellExpectation(
                    company_id=cell.company_id,
                    state=cell.state,
                    normalized=cell.normalized,
                    input_observation_ids=tuple(item.observation.id for item in cell.inputs),
                    input_evidence_ids=tuple(
                        sorted(
                            {
                                support.evidence_id
                                for item in cell.inputs
                                for support in item.observation.supports
                            }
                            | {
                                witness.span.evidence_id
                                for item in cell.inputs
                                for witness in item.observation.context_supports
                            }
                        )
                    ),
                )
                for cell in row.cells
            ),
            differences=tuple(
                DifferenceExpectation.model_validate(pair.model_dump(exclude={"explanation"}))
                for pair in row.differences
            ),
        )
        for row in result.rows
    )


def supports_category(category: Category, result: ComparisonResult) -> bool:
    """Require actual selected input context, not merely a case label, for coverage."""
    cells = [cell for row in result.rows for cell in row.cells]
    positive = any(pair.state == "AVAILABLE" for row in result.rows for pair in row.differences)
    if category == "same_period_compatible":
        return positive
    if category == "different_units":
        return any(
            pair.state == "AVAILABLE"
            and row.cells[0].normalized is not None
            and cell.normalized is not None
            and row.cells[0].normalized.multiplier != cell.normalized.multiplier
            and row.cells[0].inputs[0].observation.quantity is not None
            and cell.inputs[0].observation.quantity is not None
            and row.cells[0].inputs[0].observation.quantity.normalized_unit
            != cell.inputs[0].observation.quantity.normalized_unit
            for row in result.rows
            for cell, pair in zip(row.cells[1:], row.differences, strict=True)
        )
    if category == "missing_metric":
        return any(cell.state == "MISSING" and not cell.inputs for cell in cells) and any(
            cell.state == "AVAILABLE" for cell in cells
        )
    if category == "conflicting_observations":
        return any(
            cell.state == "CONFLICT"
            and sum(
                item.observation.quantity is not None
                and period_key(item.observation.quantity.period)
                == period_key(result.selection.period)
                and item.observation.quantity.basis == result.selection.basis
                for item in cell.inputs
            )
            >= 2
            for cell in cells
        )
    for cell in cells:
        if cell.state != "INCOMPATIBLE":
            continue
        for item in cell.inputs:
            quantity = item.observation.quantity
            if quantity is None or not complete_period(quantity.period):
                continue
            same_period = period_key(quantity.period) == period_key(result.selection.period)
            if (
                category == "different_periods"
                and not same_period
                and quantity.basis == result.selection.basis
            ):
                return True
            if (
                category == "standalone_vs_consolidated"
                and same_period
                and quantity.basis != "UNKNOWN"
                and quantity.basis != result.selection.basis
            ):
                return True
    return False


def evaluate(
    plan: AcceptancePlan,
    view: ViewInfo,
    compare: Callable[[ComparisonRequest], ComparisonResult],
) -> dict[str, object]:
    """Never derive expected numbers from production arithmetic or write accepted state."""
    if (
        view.corpus_version_id != plan.corpus_version_id
        or view.manifest_sha256 != plan.manifest_sha256
    ):
        raise ValueError("The published manifest does not match the pinned acceptance plan.")
    outcomes: list[dict[str, object]] = []
    covered: set[Category] = set()
    failed = 0
    for case in plan.cases:
        outcome: dict[str, object] = {"id": case.id, "category": case.category}
        try:
            result = compare(case.request)
            if (
                result.selection != case.request
                or result.view.manifest_sha256 != plan.manifest_sha256
                or result.policy != CALCULATION_POLICY
            ):
                raise ValueError("The returned selection, manifest or calculation policy differs.")
            actual = result_rows(result)
            matches = actual == case.expected
            category_supported = supports_category(case.category, result)
            passed = matches and category_supported
            outcome.update(
                status="PASS" if passed else "FAIL",
                expected_match=matches,
                category_supported=category_supported,
                actual=[row.model_dump(mode="json") for row in actual],
                expected=[row.model_dump(mode="json") for row in case.expected],
                warnings=list(result.warnings),
            )
            if passed:
                covered.add(case.category)
        except Exception:
            # Database/provider/validation exceptions can contain sensitive details.
            outcome.update(status="FAIL", error="Case unavailable or invalid; diagnostics omitted.")
        if outcome["status"] != "PASS":
            failed += 1
        outcomes.append(outcome)
    missing = [category for category in REQUIRED_CATEGORIES if category not in covered]
    review_pending = plan.reviewed_by is None
    state = "FAIL" if failed else "BLOCKED" if missing or review_pending else "CASES_PASS"
    return {
        "status": state,
        "declared_data_kind": plan.declared_data_kind,
        "corpus_version_id": plan.corpus_version_id,
        "manifest_sha256": plan.manifest_sha256,
        "calculation_policy_version": plan.calculation_policy_version,
        "review": {
            "reviewed_by": plan.reviewed_by,
            "reviewed_on": plan.reviewed_on,
            "pending": review_pending,
            "identity_independently_verified": False,
        },
        "required_categories": list(REQUIRED_CATEGORIES),
        "covered_categories": [category for category in REQUIRED_CATEGORIES if category in covered],
        "missing_categories": missing,
        "executed_cases": len(outcomes),
        "passed_cases": len(outcomes) - failed,
        "failed_cases": failed,
        "cases": outcomes,
        "limitation": (
            "Case outcomes test recorded expectations only. Data-origin/reviewer labels are "
            "operator assertions; this report does not establish research effectiveness or team "
            "acceptance."
        ),
    }
