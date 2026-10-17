"""Consume one published active view, preserving conflicts and exact input provenance."""

from decimal import DecimalException

from regintel.analysis.arithmetic import (
    NormalizationRangeError,
    complete_period,
    difference,
    normalize,
    ownership_key,
    period_key,
)
from regintel.analysis.models import (
    CALCULATION_POLICY,
    ComparisonCell,
    ComparisonRequest,
    ComparisonResult,
    ComparisonRow,
)
from regintel.contracts.models import QuantitativeValue
from regintel.reads.models import PublishedFact
from regintel.reads.repository import ReadNotFound, ReadUnavailable
from regintel.reads.service import PublishedReadService, ReadScope


class ComparisonService:
    def __init__(self, reads: PublishedReadService) -> None:
        self.reads = reads

    def compare(self, request: ComparisonRequest) -> ComparisonResult:
        scope = self.reads.scope(request.corpus_version_id, request.as_of_date, False)
        catalog = self.reads.catalog.catalog(scope.manifest)
        companies = tuple(
            self.reads.company(scope, catalog, identity) for identity in request.company_ids
        )
        metrics = {metric.id: metric for metric in catalog.metrics}
        if any(
            identity not in metrics or metrics[identity].kind != "numeric_fact"
            for identity in request.metric_ids
        ):
            raise ReadNotFound("A published numeric metric is required.")
        rows = []
        returned_inputs = 0
        for identity in request.metric_ids:
            metric = metrics[identity]
            cells = []
            for company in companies:
                inputs = tuple(
                    PublishedFact(observation=item, metric=metric)
                    for item in scope.view.observations
                    if item.kind == "numeric_fact"
                    and item.metric_id == identity
                    and item.subject_entity_id == company.id
                )
                if len(inputs) > 100:
                    raise ReadUnavailable("Comparison inputs exceed the explicit response bound.")
                cell = self._cell(scope, request, company.id, inputs)
                returned_inputs += len(cell.inputs)
                if returned_inputs > 100:
                    raise ReadUnavailable("Comparison exceeds the total accepted-input bound.")
                cells.append(cell)
            rows.append(
                ComparisonRow(
                    metric=metric,
                    cells=tuple(cells),
                    differences=tuple(difference(cells[0], cell) for cell in cells[1:]),
                )
            )
        warnings = []
        if scope.info.unresolved_parent_filing_version_ids:
            warnings.append(
                "Some amendment parents are unresolved; no automatic replacement was applied."
            )
        result = ComparisonResult(
            view=scope.info,
            selection=request,
            companies=companies,
            rows=tuple(rows),
            policy=CALCULATION_POLICY,
            warnings=tuple(warnings),
        )
        if len(result.model_dump_json().encode("utf-8")) > 4_000_000:
            raise ReadUnavailable("Comparison exceeds its serialized response limit.")
        return result

    @staticmethod
    def _cell(
        scope: ReadScope,
        request: ComparisonRequest,
        company: str,
        inputs: tuple[PublishedFact, ...],
    ) -> ComparisonCell:
        def unavailable(state: str, reason: str) -> ComparisonCell:
            return ComparisonCell.model_validate(
                {
                    "company_id": company,
                    "state": state,
                    "explanation": reason,
                    "inputs": inputs,
                    "normalized": None,
                }
            )

        if scope.info.state != "AVAILABLE":
            return unavailable(
                "TEMPORAL_SUPPORT_UNAVAILABLE",
                "Source or effect dates lack support for this as-of view.",
            )
        if not complete_period(request.period) or request.basis == "UNKNOWN":
            return unavailable(
                "CONTEXT_REQUIRED",
                "Select a complete supported period and a known reporting basis.",
            )
        if not inputs:
            return unavailable(
                "MISSING", "No accepted numeric metric exists for this company in the active view."
            )
        if any(
            item.observation.quantity is not None
            and _unresolved_context(item.observation.quantity, request)
            for item in inputs
        ):
            return unavailable(
                "CONTEXT_REQUIRED",
                "An active disclosure has unresolved period or basis for this selection.",
            )
        matches = tuple(
            item
            for item in inputs
            if item.observation.quantity is not None
            and period_key(item.observation.quantity.period) == period_key(request.period)
            and item.observation.quantity.basis == request.basis
        )
        if not matches:
            return unavailable(
                "INCOMPATIBLE",
                "Accepted inputs do not match the complete selected period and reporting basis.",
            )
        if len(matches) != 1:
            return unavailable(
                "CONFLICT", "Multiple accepted observations match; explicit resolution is required."
            )
        quantity = matches[0].observation.quantity
        assert quantity is not None
        if quantity.normalized_value is None or not _complete_ownership(quantity):
            return unavailable(
                "CONTEXT_REQUIRED",
                "The accepted value or applicable ownership context is incomplete.",
            )
        try:
            amount = normalize(quantity)
        except (DecimalException, NormalizationRangeError):
            return unavailable(
                "OUT_OF_RANGE", "Exact unit scaling exceeds supported Decimal limits."
            )
        except ValueError:
            return unavailable(
                "UNSUPPORTED_UNIT",
                "Exact unit scaling is unavailable for this unit, currency or value.",
            )
        return ComparisonCell(
            company_id=company,
            state="AVAILABLE",
            explanation="One accepted input matches the exact selected context.",
            inputs=matches,
            normalized=amount,
        )


def _complete_ownership(quantity: QuantitativeValue) -> bool:
    context = ownership_key(quantity)
    if not any(value is not None for value in context):
        return True
    return (
        all(value is not None for value in context)
        and quantity.normalized_unit == "%"
        and quantity.period.kind == "INSTANT"
        and quantity.ownership_date == quantity.period.instant_date
    )


def _unresolved_context(quantity: QuantitativeValue, request: ComparisonRequest) -> bool:
    """Unknown context cannot silently remove a potentially conflicting active input."""
    if quantity.basis not in {"UNKNOWN", request.basis}:
        return False
    if quantity.period.kind not in {"UNKNOWN", request.period.kind}:
        return False
    left, right = period_key(quantity.period), period_key(request.period)
    if any(
        a is not None and b is not None and a != b for a, b in zip(left[1:], right[1:], strict=True)
    ):
        return False
    return quantity.basis == "UNKNOWN" or not complete_period(quantity.period)
