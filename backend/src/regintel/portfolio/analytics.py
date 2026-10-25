"""Read-only replay-verified cash-flow analytics; no inferred quotes or cost basis."""

from decimal import Decimal, localcontext
from typing import Annotated, Final, Literal, Self

from pydantic import Field, model_validator

from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, DecimalValue, SafeInteger
from regintel.portfolio.engine import replay_ledger
from regintel.portfolio.models import LedgerEntry, Money, PortfolioAccount, PortfolioState

MAX_ANALYTICS_ENTRIES: Final = 10000
MAX_ANALYTICS_COMPANIES: Final = 1000
MAX_ANALYTICS_BYTES: Final = 33554432


class CashFlowSummary(ContractModel):
    opening_cash: Money
    cash: Money
    executed_orders: SafeInteger
    rejected_orders: SafeInteger
    buy_spend: DecimalValue
    sale_proceeds: DecimalValue
    net_cash_flow: DecimalValue


class CompanyCashFlow(ContractModel):
    company_id: CanonicalId
    bought_quantity: SafeInteger
    sold_quantity: SafeInteger
    quantity: SafeInteger
    buy_spend: DecimalValue
    sale_proceeds: DecimalValue
    net_cash_flow: DecimalValue
    position_state: Literal["OPEN", "CLOSED"]
    closed_position_result: DecimalValue | None

    @model_validator(mode="after")
    def explicit_closed_result(self) -> Self:
        if (self.position_state == "CLOSED") != (self.quantity == 0):
            raise ValueError("A closed position has no remaining shares.")
        if (self.closed_position_result is not None) != (self.position_state == "CLOSED"):
            raise ValueError("Open-position cash flow is not a profit calculation.")
        return self


class PortfolioAnalytics(ContractModel):
    account_id: CanonicalId
    portfolio_version_id: CanonicalId
    state: Literal["AVAILABLE", "LEDGER_BUDGET_EXCEEDED"]
    committed_orders: SafeInteger
    entry_budget: Literal[10000] = MAX_ANALYTICS_ENTRIES
    company_budget: Literal[1000] = MAX_ANALYTICS_COMPANIES
    byte_budget: Literal[33554432] = MAX_ANALYTICS_BYTES
    input_entry_ids: Annotated[
        tuple[CanonicalId, ...], Field(strict=False, max_length=MAX_ANALYTICS_ENTRIES)
    ]
    corpus_version_ids: Annotated[
        tuple[CanonicalId, ...], Field(strict=False, max_length=MAX_ANALYTICS_ENTRIES)
    ]
    quote_version_ids: Annotated[
        tuple[CanonicalId, ...], Field(strict=False, max_length=MAX_ANALYTICS_ENTRIES)
    ]
    summary: CashFlowSummary | None
    companies: Annotated[
        tuple[CompanyCashFlow, ...], Field(strict=False, max_length=MAX_ANALYTICS_COMPANIES)
    ]
    valuation_state: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    market_value: None = None
    total_value: None = None

    @model_validator(mode="after")
    def complete_inputs(self) -> Self:
        if self.state == "LEDGER_BUDGET_EXCEEDED":
            if self.summary is not None or any(
                (
                    self.input_entry_ids,
                    self.corpus_version_ids,
                    self.quote_version_ids,
                    self.companies,
                )
            ):
                raise ValueError("Budget failure cannot present truncated financial totals.")
            return self
        if self.summary is None or len(self.input_entry_ids) != self.committed_orders:
            raise ValueError("Available analytics require the complete selected ledger.")
        if len(set(self.input_entry_ids)) != len(self.input_entry_ids):
            raise ValueError("An analytics input must identify each committed entry once.")
        version = self.input_entry_ids[-1] if self.input_entry_ids else self.account_id
        if self.portfolio_version_id != version:
            raise ValueError("Analytics must retain its selected portfolio version.")
        for identities in (self.corpus_version_ids, self.quote_version_ids):
            if identities != tuple(sorted(set(identities))):
                raise ValueError("Source versions must retain distinct canonical membership.")
        return self


def unavailable_analytics(account: PortfolioAccount) -> PortfolioAnalytics:
    return PortfolioAnalytics(
        account_id=account.account_id,
        portfolio_version_id=account.portfolio_version_id,
        state="LEDGER_BUDGET_EXCEEDED",
        committed_orders=account.committed_orders,
        input_entry_ids=(),
        corpus_version_ids=(),
        quote_version_ids=(),
        summary=None,
        companies=(),
    )


def ledger_analytics(
    account: PortfolioAccount, opening_cash: Decimal, entries: tuple[LedgerEntry, ...]
) -> PortfolioAnalytics:
    if account.committed_orders > MAX_ANALYTICS_ENTRIES:
        return unavailable_analytics(account)
    if len(entries) != account.committed_orders:
        raise ValueError("Analytics cannot use a partial or mixed-version ledger.")
    if sum(len(entry.model_dump_json().encode("utf-8")) for entry in entries) > MAX_ANALYTICS_BYTES:
        return unavailable_analytics(account)
    opening = PortfolioState(cash=opening_cash, holdings=())
    if replay_ledger(opening, entries) != account.state:
        raise ValueError("Portfolio state differs from exact immutable ledger replay.")
    executed = tuple(entry for entry in entries if entry.evaluation.state == "EXECUTED")
    companies = sorted({entry.request.company_id for entry in executed})
    if len(companies) > MAX_ANALYTICS_COMPANIES:
        return unavailable_analytics(account)
    results = []
    with localcontext() as context:
        context.prec = 512
        spend = proceeds = Decimal("0.00")
        for identity in companies:
            selected = tuple(entry for entry in executed if entry.request.company_id == identity)
            bought = sum(e.request.quantity for e in selected if e.request.side == "BUY")
            sold = sum(e.request.quantity for e in selected if e.request.side == "SELL")
            cost = -sum(
                (e.evaluation.cash_delta for e in selected if e.request.side == "BUY"),
                Decimal("0.00"),
            )
            sales = sum(
                (e.evaluation.cash_delta for e in selected if e.request.side == "SELL"),
                Decimal("0.00"),
            )
            spend += cost
            proceeds += sales
            results.append(
                CompanyCashFlow(
                    company_id=identity,
                    bought_quantity=bought,
                    sold_quantity=sold,
                    quantity=bought - sold,
                    buy_spend=cost,
                    sale_proceeds=sales,
                    net_cash_flow=sales - cost,
                    position_state="CLOSED" if bought == sold else "OPEN",
                    closed_position_result=sales - cost if bought == sold else None,
                )
            )
        summary = CashFlowSummary(
            opening_cash=opening_cash,
            cash=account.state.cash,
            executed_orders=len(executed),
            rejected_orders=len(entries) - len(executed),
            buy_spend=spend,
            sale_proceeds=proceeds,
            net_cash_flow=proceeds - spend,
        )
        if summary.opening_cash + summary.net_cash_flow != summary.cash:
            raise ValueError("Analytics cash flow differs from the complete virtual account.")
    return PortfolioAnalytics(
        account_id=account.account_id,
        portfolio_version_id=account.portfolio_version_id,
        state="AVAILABLE",
        committed_orders=account.committed_orders,
        input_entry_ids=tuple(entry.id for entry in entries),
        corpus_version_ids=tuple(sorted({entry.request.corpus_version_id for entry in entries})),
        quote_version_ids=tuple(
            sorted({entry.quote.quote_version_id for entry in entries if entry.quote})
        ),
        summary=summary,
        companies=tuple(results),
    )
