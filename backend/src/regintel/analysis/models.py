"""Explicit consumer selections and auditable deterministic comparison outputs."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from regintel.candidates.models import MetricDefinition
from regintel.contracts.models import ContractModel, FinancialPeriod, ReportingBasis
from regintel.contracts.primitives import CanonicalId, DateString, DecimalValue, Label
from regintel.reads.models import EntityLabel, PublishedFact, ViewInfo

CellState = Literal[
    "AVAILABLE",
    "MISSING",
    "INCOMPATIBLE",
    "CONFLICT",
    "CONTEXT_REQUIRED",
    "TEMPORAL_SUPPORT_UNAVAILABLE",
    "UNSUPPORTED_UNIT",
    "OUT_OF_RANGE",
]


class ComparisonRequest(ContractModel):
    corpus_version_id: CanonicalId
    company_ids: Annotated[tuple[CanonicalId, ...], Field(strict=False, min_length=2, max_length=4)]
    metric_ids: Annotated[tuple[CanonicalId, ...], Field(strict=False, min_length=1, max_length=12)]
    period: FinancialPeriod
    basis: ReportingBasis
    as_of_date: DateString | None = None

    @model_validator(mode="after")
    def distinct_selections(self) -> Self:
        if len(set(self.company_ids)) != len(self.company_ids):
            raise ValueError("Select distinct companies.")
        if len(set(self.metric_ids)) != len(self.metric_ids):
            raise ValueError("Select distinct metrics.")
        return self


class NormalizedAmount(ContractModel):
    value: DecimalValue
    unit: Label
    currency: Label | None
    multiplier: DecimalValue


class ComparisonCell(ContractModel):
    company_id: CanonicalId
    state: CellState
    explanation: Label
    inputs: Annotated[tuple[PublishedFact, ...], Field(strict=False, max_length=100)]
    normalized: NormalizedAmount | None

    @model_validator(mode="after")
    def available_input(self) -> Self:
        if (self.normalized is not None) != (self.state == "AVAILABLE"):
            raise ValueError("Only available cells carry a normalized value.")
        if self.state == "AVAILABLE" and len(self.inputs) != 1:
            raise ValueError("An available value has exactly one accepted input.")
        if any(item.observation.subject_entity_id != self.company_id for item in self.inputs):
            raise ValueError("Inputs must belong to the selected company.")
        return self


class PairDifference(ContractModel):
    baseline_company_id: CanonicalId
    company_id: CanonicalId
    state: Literal["AVAILABLE", "UNAVAILABLE", "INCOMPATIBLE", "OUT_OF_RANGE"]
    explanation: Label
    input_observation_ids: Annotated[tuple[CanonicalId, ...], Field(strict=False, max_length=2)]
    unit: Label | None
    currency: Label | None
    difference: DecimalValue | None
    percentage_state: Literal["AVAILABLE", "UNAVAILABLE", "NON_POSITIVE_BASELINE", "OUT_OF_RANGE"]
    percentage_difference: DecimalValue | None

    @model_validator(mode="after")
    def derived_outputs(self) -> Self:
        if (self.difference is not None) != (self.state == "AVAILABLE"):
            raise ValueError("Unavailable differences cannot carry a number.")
        if (self.percentage_difference is not None) != (self.percentage_state == "AVAILABLE"):
            raise ValueError("Unavailable percentages cannot carry a number.")
        if self.state == "AVAILABLE" and (len(self.input_observation_ids) != 2 or not self.unit):
            raise ValueError("A difference requires both exact inputs and a unit.")
        if self.state != "AVAILABLE" and self.percentage_state != "UNAVAILABLE":
            raise ValueError("Percentages require an available difference.")
        return self


class ComparisonRow(ContractModel):
    metric: MetricDefinition
    cells: Annotated[tuple[ComparisonCell, ...], Field(strict=False, min_length=2, max_length=4)]
    differences: Annotated[
        tuple[PairDifference, ...], Field(strict=False, min_length=1, max_length=3)
    ]


class CalculationPolicy(ContractModel):
    version: Literal["m2-comparison-1"]
    difference_formula: Literal["comparison - baseline"]
    percentage_formula: Literal["100 * (comparison - baseline) / baseline"]
    percentage_decimal_places: Literal[6]
    percentage_rounding: Literal["ROUND_HALF_EVEN"]
    positive_baseline_required: Literal[True]


CALCULATION_POLICY = CalculationPolicy(
    version="m2-comparison-1",
    difference_formula="comparison - baseline",
    percentage_formula="100 * (comparison - baseline) / baseline",
    percentage_decimal_places=6,
    percentage_rounding="ROUND_HALF_EVEN",
    positive_baseline_required=True,
)


class ComparisonResult(ContractModel):
    view: ViewInfo
    selection: ComparisonRequest
    companies: Annotated[tuple[EntityLabel, ...], Field(strict=False, min_length=2, max_length=4)]
    rows: Annotated[tuple[ComparisonRow, ...], Field(strict=False, min_length=1, max_length=12)]
    policy: CalculationPolicy
    warnings: Annotated[tuple[Label, ...], Field(strict=False, max_length=16)]

    @model_validator(mode="after")
    def selected_scope(self) -> Self:
        request = self.selection
        if (
            self.view.corpus_version_id != request.corpus_version_id
            or self.view.as_of_date != request.as_of_date
            or self.view.historical
            or tuple(item.id for item in self.companies) != request.company_ids
            or tuple(row.metric.id for row in self.rows) != request.metric_ids
        ):
            raise ValueError("Comparison output must retain its complete selected published scope.")
        for row in self.rows:
            if tuple(cell.company_id for cell in row.cells) != request.company_ids:
                raise ValueError("Every metric must retain the ordered company selections.")
            if any(
                item.metric.id != row.metric.id
                or item.observation.metric_id != row.metric.id
                or item.observation.kind != "numeric_fact"
                for cell in row.cells
                for item in cell.inputs
            ):
                raise ValueError("Inputs must retain the selected numeric metric.")
            if len(row.differences) != len(row.cells) - 1:
                raise ValueError("Each other company has one explicit baseline comparison.")
            for cell, pair in zip(row.cells[1:], row.differences, strict=True):
                if (
                    pair.baseline_company_id != request.company_ids[0]
                    or pair.company_id != cell.company_id
                ):
                    raise ValueError("Derived values must retain their baseline and company.")
                if pair.input_observation_ids and pair.input_observation_ids != tuple(
                    entry.inputs[0].observation.id
                    for entry in (row.cells[0], cell)
                    if entry.state == "AVAILABLE"
                ):
                    raise ValueError("Derived values must expose both exact accepted input IDs.")
        return self


class QuotesResult(ContractModel):
    state: Literal["UNAVAILABLE"]
    reason: Literal["NO_CONFIGURED_SOURCE"]
    explanation: Literal["No reviewed quote source is configured."]
    quotes: Annotated[tuple[CanonicalId, ...], Field(strict=False, max_length=0)]
    quote_version_id: None


QUOTES_UNAVAILABLE = QuotesResult(
    state="UNAVAILABLE",
    reason="NO_CONFIGURED_SOURCE",
    explanation="No reviewed quote source is configured.",
    quotes=(),
    quote_version_id=None,
)


class AnalysisWire(ContractModel):
    request: ComparisonRequest
    comparison: ComparisonResult
    quotes: QuotesResult
