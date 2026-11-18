"""Snapshot simple return and allocation from one exact server-valued ledger prefix."""

from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, model_validator

from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, DecimalValue
from regintel.portfolio.analytics import CentAmount
from regintel.portfolio.valuation import PortfolioValuation

_PERCENT_QUANTUM = Decimal("0.000001")
_HUNDRED = Decimal("100.000000")


def _six_places(value: Decimal) -> Decimal:
    if value.as_tuple().exponent != -6 or value.is_zero() and value.is_signed():
        raise ValueError("A snapshot percentage has six decimal places and unsigned zero.")
    return value


SnapshotPercentage = Annotated[DecimalValue, AfterValidator(_six_places)]


def _percentage(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator <= 0:
        raise ValueError("Snapshot percentages require a positive exact denominator.")
    with localcontext() as calculation:
        calculation.prec = 512
        value = (numerator * 100 / denominator).quantize(_PERCENT_QUANTUM, rounding=ROUND_HALF_EVEN)
        return value.copy_abs() if value.is_zero() else value


class SnapshotReturn(ContractModel):
    state: Literal["AVAILABLE", "ZERO_OPENING_CASH", "QUOTES_UNAVAILABLE", "LEDGER_BUDGET_EXCEEDED"]
    numerator: CentAmount | None
    denominator: CentAmount | None
    percentage: SnapshotPercentage | None

    @model_validator(mode="after")
    def supported_ratio(self) -> Self:
        if self.state == "AVAILABLE":
            if (
                self.numerator is None
                or self.denominator is None
                or (self.percentage != _percentage(self.numerator, self.denominator))
            ):
                raise ValueError("Simple return must use the exact total result and opening cash.")
        elif self.state == "ZERO_OPENING_CASH":
            if self.numerator is None or self.denominator != 0 or self.percentage is not None:
                raise ValueError("Zero opening cash cannot produce a simple-return percentage.")
        elif any(
            value is not None for value in (self.numerator, self.denominator, self.percentage)
        ):
            raise ValueError("Unavailable valuation cannot produce a return ratio.")
        return self


class SnapshotAllocationEntry(ContractModel):
    kind: Literal["CASH", "HOLDING"]
    company_id: CanonicalId | None
    numerator: CentAmount
    percentage: SnapshotPercentage

    @model_validator(mode="after")
    def exact_component(self) -> Self:
        if (
            (self.kind == "CASH") != (self.company_id is None)
            or self.numerator < 0
            or not 0 <= self.percentage <= 100
        ):
            raise ValueError("Allocation identifies nonnegative cash or one exact holding.")
        return self


class SnapshotAllocation(ContractModel):
    state: Literal["AVAILABLE", "ZERO_TOTAL_VALUE", "QUOTES_UNAVAILABLE", "LEDGER_BUDGET_EXCEEDED"]
    denominator: CentAmount | None
    entries: Annotated[tuple[SnapshotAllocationEntry, ...], Field(strict=False, max_length=101)]
    percentage_sum: SnapshotPercentage | None
    rounding_residual: SnapshotPercentage | None

    @model_validator(mode="after")
    def complete_allocation(self) -> Self:
        if self.state != "AVAILABLE":
            denominator = Decimal("0.00") if self.state == "ZERO_TOTAL_VALUE" else None
            if (
                self.denominator != denominator
                or self.entries
                or (self.percentage_sum is not None or self.rounding_residual is not None)
            ):
                raise ValueError("An unavailable allocation cannot present partial weights.")
            return self
        if self.denominator is None or self.denominator <= 0 or not self.entries:
            raise ValueError("Allocation needs a positive total value and its cash component.")
        companies = tuple(entry.company_id for entry in self.entries[1:])
        if (
            self.entries[0].kind != "CASH"
            or any(entry.kind != "HOLDING" for entry in self.entries[1:])
            or companies
            != tuple(sorted(set(company for company in companies if company is not None)))
        ):
            raise ValueError("Allocation retains cash first and every holding in canonical order.")
        with localcontext() as calculation:
            calculation.prec = 512
            if (
                sum((entry.numerator for entry in self.entries), Decimal("0.00"))
                != self.denominator
            ):
                raise ValueError("Allocation components must sum to the exact total value.")
            if any(
                entry.percentage != _percentage(entry.numerator, self.denominator)
                for entry in self.entries
            ):
                raise ValueError("Allocation percentages must retain their exact proportions.")
            total = sum((entry.percentage for entry in self.entries), Decimal("0.000000"))
            if self.percentage_sum != total or self.rounding_residual != _HUNDRED - total:
                raise ValueError("Rounded allocation totals and residual must be explicit.")
        return self


def _return(value: PortfolioValuation) -> SnapshotReturn:
    if value.state != "AVAILABLE":
        return SnapshotReturn(state=value.state, numerator=None, denominator=None, percentage=None)
    assert value.cash_flow is not None and value.total_result is not None
    opening = value.cash_flow.opening_cash
    return SnapshotReturn(
        state="AVAILABLE" if opening > 0 else "ZERO_OPENING_CASH",
        numerator=value.total_result,
        denominator=opening,
        percentage=_percentage(value.total_result, opening) if opening > 0 else None,
    )


def _allocation(value: PortfolioValuation) -> SnapshotAllocation:
    if value.state != "AVAILABLE":
        return SnapshotAllocation(
            state=value.state,
            denominator=None,
            entries=(),
            percentage_sum=None,
            rounding_residual=None,
        )
    assert value.total_value is not None and value.cash_flow is not None
    if value.total_value == 0:
        return SnapshotAllocation(
            state="ZERO_TOTAL_VALUE",
            denominator=value.total_value,
            entries=(),
            percentage_sum=None,
            rounding_residual=None,
        )
    entries = [
        SnapshotAllocationEntry(
            kind="CASH",
            company_id=None,
            numerator=value.cash_flow.cash,
            percentage=_percentage(value.cash_flow.cash, value.total_value),
        )
    ]
    for position in value.positions:
        assert position.market_value is not None
        entries.append(
            SnapshotAllocationEntry(
                kind="HOLDING",
                company_id=position.cash_flow.company_id,
                numerator=position.market_value,
                percentage=_percentage(position.market_value, value.total_value),
            )
        )
    with localcontext() as calculation:
        calculation.prec = 512
        total = sum((entry.percentage for entry in entries), Decimal("0.000000"))
        residual = _HUNDRED - total
        return SnapshotAllocation(
            state="AVAILABLE",
            denominator=value.total_value,
            entries=tuple(entries),
            percentage_sum=total,
            rounding_residual=residual.copy_abs() if residual.is_zero() else residual,
        )


class PortfolioSnapshotMetrics(ContractModel):
    schema_version: Literal["portfolio-snapshot-metrics-1"] = "portfolio-snapshot-metrics-1"
    valuation: PortfolioValuation
    percentage_decimal_places: Literal[6] = 6
    rounding_mode: Literal["ROUND_HALF_EVEN"] = "ROUND_HALF_EVEN"
    return_basis: Literal["SELECTED_LEDGER_AT_VALUATION_TIME"] = "SELECTED_LEDGER_AT_VALUATION_TIME"
    simple_return: SnapshotReturn
    allocation: SnapshotAllocation

    @model_validator(mode="after")
    def one_valuation(self) -> Self:
        if self.simple_return != _return(self.valuation) or self.allocation != _allocation(
            self.valuation
        ):
            raise ValueError("Return and allocation must derive from this one exact valuation.")
        return self


def snapshot_metrics(value: PortfolioValuation) -> PortfolioSnapshotMetrics:
    """Selected holdings at one valuation time; no annualization or inferred past prices."""
    value = PortfolioValuation.model_validate(value.model_dump(mode="python"))
    return PortfolioSnapshotMetrics(
        valuation=value, simple_return=_return(value), allocation=_allocation(value)
    )
