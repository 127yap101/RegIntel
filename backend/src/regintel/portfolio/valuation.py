"""Exact snapshot valuation of a replay-verified portfolio; no inferred prices."""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, localcontext
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, SafeInteger
from regintel.portfolio.analytics import (
    MAX_ANALYTICS_ENTRIES,
    CashFlowSummary,
    CentAmount,
    CompanyCashFlow,
    PortfolioAnalytics,
)
from regintel.portfolio.models import QuoteSnapshot

QuoteState = Literal[
    "AVAILABLE", "MISSING_QUOTE", "WRONG_QUOTE", "STALE_QUOTE", "CONFLICTING_QUOTE"
]
SourceIds = Annotated[
    tuple[CanonicalId, ...], Field(strict=False, max_length=MAX_ANALYTICS_ENTRIES)
]


def _quote_state(
    company_id: str, quote: QuoteSnapshot | None, at: datetime, conflicting: set[str]
) -> QuoteState:
    if quote is None:
        return "MISSING_QUOTE"
    if quote.id in conflicting:
        return "CONFLICTING_QUOTE"
    if quote.company_id != company_id or quote.currency != "INR":
        return "WRONG_QUOTE"
    if at < quote.observed_at or at >= quote.expires_at:
        return "STALE_QUOTE"
    return "AVAILABLE"


def _conflicting_ids(quotes: tuple[QuoteSnapshot | None, ...]) -> set[str]:
    seen: set[str] = set()
    conflicting: set[str] = set()
    for quote in quotes:
        if quote is not None:
            if quote.id in seen:
                conflicting.add(quote.id)
            seen.add(quote.id)
    return conflicting


class PositionValuation(ContractModel):
    cash_flow: CompanyCashFlow
    state: QuoteState
    quote: QuoteSnapshot | None
    market_value: CentAmount | None
    unrealized_result: CentAmount | None

    @model_validator(mode="after")
    def exact_position(self) -> Self:
        if self.cash_flow.position_state != "OPEN":
            raise ValueError("Snapshot valuation needs only remaining open holdings.")
        if self.state != "AVAILABLE":
            if self.market_value is not None or self.unrealized_result is not None:
                raise ValueError("Unavailable prices cannot produce position totals.")
            return self
        if self.quote is None or self.quote.company_id != self.cash_flow.company_id:
            raise ValueError("Position valuation requires its own exact quote snapshot.")
        with localcontext() as calculation:
            calculation.prec = 512
            value = self.quote.price * self.cash_flow.quantity
            if (
                self.market_value != value
                or self.unrealized_result != value - self.cash_flow.remaining_cost_basis
            ):
                raise ValueError("Position valuation must reconcile with its quote and FIFO cost.")
        return self


class PortfolioValuation(ContractModel):
    account_id: CanonicalId
    portfolio_version_id: CanonicalId
    evaluated_at: AwareDatetime
    currency: Literal["INR"] = "INR"
    state: Literal["AVAILABLE", "QUOTES_UNAVAILABLE", "LEDGER_BUDGET_EXCEEDED"]
    committed_orders: SafeInteger
    cost_basis_method: Literal["FIFO"] = "FIFO"
    input_entry_ids: SourceIds
    corpus_version_ids: SourceIds
    execution_quote_version_ids: SourceIds
    quote_version_ids: Annotated[tuple[CanonicalId, ...], Field(strict=False, max_length=100)]
    cash_flow: CashFlowSummary | None
    positions: Annotated[tuple[PositionValuation, ...], Field(strict=False, max_length=100)]
    market_value: CentAmount | None
    total_value: CentAmount | None
    unrealized_result: CentAmount | None
    total_result: CentAmount | None

    @model_validator(mode="after")
    def complete_valuation(self) -> Self:
        totals = (self.market_value, self.total_value, self.unrealized_result, self.total_result)
        if self.state == "LEDGER_BUDGET_EXCEEDED":
            if (
                self.cash_flow is not None
                or any(
                    (
                        self.input_entry_ids,
                        self.corpus_version_ids,
                        self.execution_quote_version_ids,
                        self.quote_version_ids,
                        self.positions,
                    )
                )
                or any(value is not None for value in totals)
            ):
                raise ValueError(
                    "Budget failure cannot present partial valuation inputs or totals."
                )
            return self
        if self.cash_flow is None or len(self.input_entry_ids) != self.committed_orders:
            raise ValueError("Valuation requires the complete selected ledger cash flow.")
        if len(set(self.input_entry_ids)) != len(self.input_entry_ids):
            raise ValueError("Valuation ledger input identities must be unique.")
        version = self.input_entry_ids[-1] if self.input_entry_ids else self.account_id
        if self.portfolio_version_id != version or (
            self.cash_flow.executed_orders + self.cash_flow.rejected_orders != self.committed_orders
        ):
            raise ValueError("Valuation must retain the exact selected portfolio version.")
        for identities in (
            self.corpus_version_ids,
            self.execution_quote_version_ids,
            self.quote_version_ids,
        ):
            if identities != tuple(sorted(set(identities))):
                raise ValueError("Valuation source versions must retain canonical membership.")
        companies = tuple(position.cash_flow.company_id for position in self.positions)
        if companies != tuple(sorted(set(companies))):
            raise ValueError("Valuation positions must retain canonical company membership.")
        quotes = tuple(position.quote for position in self.positions)
        conflicting = _conflicting_ids(quotes)
        if self.quote_version_ids != tuple(
            sorted({quote.quote_version_id for quote in quotes if quote is not None})
        ):
            raise ValueError("Valuation must identify its supplied quote versions separately.")
        for position in self.positions:
            if position.state != _quote_state(
                position.cash_flow.company_id, position.quote, self.evaluated_at, conflicting
            ):
                raise ValueError("Valuation quote status must retain identity and time validity.")
        available = all(position.state == "AVAILABLE" for position in self.positions)
        if (self.state == "AVAILABLE") != available:
            raise ValueError("Every open holding needs a valid quote for complete valuation.")
        with localcontext() as calculation:
            calculation.prec = 512
            remaining = sum(
                (position.cash_flow.remaining_cost_basis for position in self.positions),
                Decimal("0.00"),
            )
            if remaining != self.cash_flow.remaining_cost_basis:
                raise ValueError("Valuation must retain all remaining FIFO purchase costs.")
            if not available:
                if any(value is not None for value in totals):
                    raise ValueError("Missing prices cannot produce partial portfolio totals.")
                return self
            value = sum(
                (
                    position.market_value
                    for position in self.positions
                    if position.market_value is not None
                ),
                Decimal("0.00"),
            )
            total = self.cash_flow.cash + value
            unrealized = value - remaining
            if (
                self.market_value != value
                or self.total_value != total
                or self.unrealized_result != unrealized
                or self.total_result != total - self.cash_flow.opening_cash
                or self.total_result != unrealized + self.cash_flow.realized_result
            ):
                raise ValueError(
                    "Portfolio valuation must reconcile cash, quotes and FIFO results."
                )
        return self


def value_portfolio(
    analytics: PortfolioAnalytics,
    quotes: Mapping[str, QuoteSnapshot | None],
    at: datetime,
) -> PortfolioValuation:
    """Value selected ledger holdings at one explicit server time, never at trade prices."""
    analytics = PortfolioAnalytics.model_validate(analytics.model_dump(mode="python"))
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("Portfolio valuation requires an aware server timestamp.")
    positions = tuple(company for company in analytics.companies if company.quantity > 0)
    if set(quotes) != {company.company_id for company in positions}:
        raise ValueError("Valuation quotes must explicitly cover exactly the open holdings.")
    snapshots = {
        company_id: QuoteSnapshot.model_validate(quote.model_dump(mode="python"))
        if quote is not None
        else None
        for company_id, quote in quotes.items()
    }
    conflicting = _conflicting_ids(tuple(snapshots.values()))
    valued = []
    with localcontext() as calculation:
        calculation.prec = 512
        for company in positions:
            quote = snapshots[company.company_id]
            state = _quote_state(company.company_id, quote, at, conflicting)
            value = quote.price * company.quantity if quote and state == "AVAILABLE" else None
            valued.append(
                PositionValuation(
                    cash_flow=company,
                    state=state,
                    quote=quote,
                    market_value=value,
                    unrealized_result=value - company.remaining_cost_basis
                    if value is not None
                    else None,
                )
            )
        summary = analytics.summary
        available = summary is not None and all(item.state == "AVAILABLE" for item in valued)
        market_value = (
            sum(
                (item.market_value for item in valued if item.market_value is not None),
                Decimal("0.00"),
            )
            if available
            else None
        )
        total_value = summary.cash + market_value if summary and market_value is not None else None
        return PortfolioValuation(
            account_id=analytics.account_id,
            portfolio_version_id=analytics.portfolio_version_id,
            evaluated_at=at,
            state="LEDGER_BUDGET_EXCEEDED"
            if analytics.state == "LEDGER_BUDGET_EXCEEDED"
            else "AVAILABLE"
            if available
            else "QUOTES_UNAVAILABLE",
            committed_orders=analytics.committed_orders,
            input_entry_ids=analytics.input_entry_ids,
            corpus_version_ids=analytics.corpus_version_ids,
            execution_quote_version_ids=analytics.quote_version_ids,
            quote_version_ids=tuple(
                sorted(
                    {quote.quote_version_id for quote in snapshots.values() if quote is not None}
                )
            ),
            cash_flow=summary,
            positions=tuple(valued),
            market_value=market_value,
            total_value=total_value,
            unrealized_result=market_value - summary.remaining_cost_basis
            if summary and market_value is not None
            else None,
            total_result=total_value - summary.opening_cash
            if summary and total_value is not None
            else None,
        )
