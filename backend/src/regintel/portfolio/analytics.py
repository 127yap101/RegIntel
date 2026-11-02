"""Read-only replay-verified cash flow and FIFO purchase costs; no inferred quotes."""

from decimal import Decimal, localcontext
from typing import Annotated, Final, Literal, Self

from pydantic import AfterValidator, Field, model_validator

from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, DecimalValue, SafeInteger
from regintel.portfolio.cost_basis import fifo_positions
from regintel.portfolio.engine import replay_ledger
from regintel.portfolio.models import LedgerEntry, Money, PortfolioAccount, PortfolioState

MAX_ANALYTICS_ENTRIES: Final = 10000
MAX_ANALYTICS_COMPANIES: Final = 1000
MAX_ANALYTICS_BYTES: Final = 33554432


def _cent_amount(value: Decimal) -> Decimal:
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -2:
        raise ValueError("Virtual FIFO amounts require at most two decimal places.")
    return value


CentAmount = Annotated[DecimalValue, AfterValidator(_cent_amount)]


class CashFlowSummary(ContractModel):
    opening_cash: Money
    cash: Money
    executed_orders: SafeInteger
    rejected_orders: SafeInteger
    buy_spend: DecimalValue
    sale_proceeds: DecimalValue
    net_cash_flow: DecimalValue
    realized_cost_basis: CentAmount
    remaining_cost_basis: CentAmount
    realized_result: CentAmount

    @model_validator(mode="after")
    def exact_cost_allocation(self) -> Self:
        with localcontext() as calculation:
            calculation.prec = 512
            if (
                min(
                    self.buy_spend,
                    self.sale_proceeds,
                    self.realized_cost_basis,
                    self.remaining_cost_basis,
                )
                < 0
                or self.realized_cost_basis + self.remaining_cost_basis != self.buy_spend
                or self.sale_proceeds - self.realized_cost_basis != self.realized_result
                or self.sale_proceeds - self.buy_spend != self.net_cash_flow
                or self.opening_cash + self.net_cash_flow != self.cash
            ):
                raise ValueError("Cash flow and FIFO purchase-cost totals must reconcile exactly.")
        return self


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
    realized_cost_basis: CentAmount
    remaining_cost_basis: CentAmount
    realized_result: CentAmount

    @model_validator(mode="after")
    def explicit_closed_result(self) -> Self:
        if (self.position_state == "CLOSED") != (self.quantity == 0):
            raise ValueError("A closed position has no remaining shares.")
        if (self.closed_position_result is not None) != (self.position_state == "CLOSED"):
            raise ValueError("Open-position cash flow is not a profit calculation.")
        with localcontext() as calculation:
            calculation.prec = 512
            if (
                self.bought_quantity == 0
                or self.bought_quantity - self.sold_quantity != self.quantity
                or min(
                    self.buy_spend,
                    self.sale_proceeds,
                    self.realized_cost_basis,
                    self.remaining_cost_basis,
                )
                < 0
                or self.realized_cost_basis + self.remaining_cost_basis != self.buy_spend
                or self.sale_proceeds - self.realized_cost_basis != self.realized_result
                or self.sale_proceeds - self.buy_spend != self.net_cash_flow
                or (self.quantity == 0) != (self.remaining_cost_basis == 0)
                or self.closed_position_result is not None
                and (
                    self.closed_position_result != self.net_cash_flow
                    or self.closed_position_result != self.realized_result
                )
            ):
                raise ValueError("Company FIFO lots and cash flow must reconcile exactly.")
        return self


class PortfolioAnalytics(ContractModel):
    account_id: CanonicalId
    portfolio_version_id: CanonicalId
    state: Literal["AVAILABLE", "LEDGER_BUDGET_EXCEEDED"]
    committed_orders: SafeInteger
    cost_basis_method: Literal["FIFO"]
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
        company_ids = tuple(item.company_id for item in self.companies)
        if company_ids != tuple(sorted(set(company_ids))):
            raise ValueError("Analytics companies must have distinct canonical membership.")
        with localcontext() as calculation:
            calculation.prec = 512
            totals = (
                (
                    sum((item.buy_spend for item in self.companies), Decimal("0.00")),
                    self.summary.buy_spend,
                ),
                (
                    sum((item.sale_proceeds for item in self.companies), Decimal("0.00")),
                    self.summary.sale_proceeds,
                ),
                (
                    sum((item.net_cash_flow for item in self.companies), Decimal("0.00")),
                    self.summary.net_cash_flow,
                ),
                (
                    sum((item.realized_cost_basis for item in self.companies), Decimal("0.00")),
                    self.summary.realized_cost_basis,
                ),
                (
                    sum((item.remaining_cost_basis for item in self.companies), Decimal("0.00")),
                    self.summary.remaining_cost_basis,
                ),
                (
                    sum((item.realized_result for item in self.companies), Decimal("0.00")),
                    self.summary.realized_result,
                ),
            )
            for total, expected in totals:
                if total != expected:
                    raise ValueError("Company amounts must match complete portfolio totals.")
        if self.summary.executed_orders + self.summary.rejected_orders != self.committed_orders:
            raise ValueError("Analytics must count every committed order outcome.")
        return self


def unavailable_analytics(account: PortfolioAccount) -> PortfolioAnalytics:
    return PortfolioAnalytics(
        account_id=account.account_id,
        portfolio_version_id=account.portfolio_version_id,
        state="LEDGER_BUDGET_EXCEEDED",
        committed_orders=account.committed_orders,
        cost_basis_method="FIFO",
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
    costs = fifo_positions(entries)
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
            basis = costs[identity]
            if basis.quantity != bought - sold:
                raise ValueError("FIFO quantities differ from complete ledger replay.")
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
                    realized_cost_basis=basis.realized_cost_basis,
                    remaining_cost_basis=basis.remaining_cost_basis,
                    realized_result=sales - basis.realized_cost_basis,
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
            realized_cost_basis=sum(
                (item.realized_cost_basis for item in results), Decimal("0.00")
            ),
            remaining_cost_basis=sum(
                (item.remaining_cost_basis for item in results), Decimal("0.00")
            ),
            realized_result=sum((item.realized_result for item in results), Decimal("0.00")),
        )
        if summary.opening_cash + summary.net_cash_flow != summary.cash:
            raise ValueError("Analytics cash flow differs from the complete virtual account.")
    return PortfolioAnalytics(
        account_id=account.account_id,
        portfolio_version_id=account.portfolio_version_id,
        state="AVAILABLE",
        committed_orders=account.committed_orders,
        cost_basis_method="FIFO",
        input_entry_ids=tuple(entry.id for entry in entries),
        corpus_version_ids=tuple(sorted({entry.request.corpus_version_id for entry in entries})),
        quote_version_ids=tuple(
            sorted({entry.quote.quote_version_id for entry in entries if entry.quote})
        ),
        summary=summary,
        companies=tuple(results),
    )
