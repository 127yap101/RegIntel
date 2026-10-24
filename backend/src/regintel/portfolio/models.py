"""Exact virtual balances and server-selected immutable quote/order inputs."""

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, AwareDatetime, Field, model_validator

from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, DecimalValue, Label, SafeInteger


def _money(value: Decimal) -> Decimal:
    exponent = value.as_tuple().exponent
    if (
        value < 0
        or value > Decimal("99999999999999.99")
        or not isinstance(exponent, int)
        or exponent < -2
    ):
        raise ValueError(
            "Virtual INR money requires at most two decimal places and fourteen digits."
        )
    return value


Money = Annotated[DecimalValue, AfterValidator(_money)]
Quantity = Annotated[int, Field(strict=True, ge=1, le=1000000)]


class Holding(ContractModel):
    company_id: CanonicalId
    quantity: Quantity


class PortfolioState(ContractModel):
    cash: Money
    currency: Literal["INR"] = "INR"
    holdings: Annotated[tuple[Holding, ...], Field(strict=False, max_length=100)]

    @model_validator(mode="after")
    def ordered_holdings(self) -> Self:
        ids = tuple(item.company_id for item in self.holdings)
        if ids != tuple(sorted(set(ids))) or any(item.quantity == 0 for item in self.holdings):
            raise ValueError("Retain each positive holding once in canonical company order.")
        return self


class OrderRequest(ContractModel):
    request_id: CanonicalId
    corpus_version_id: CanonicalId
    company_id: CanonicalId
    side: Literal["BUY", "SELL"]
    quantity: Quantity


class QuoteSnapshot(ContractModel):
    id: CanonicalId
    quote_version_id: CanonicalId
    company_id: CanonicalId
    price: Money
    currency: Literal["INR"] = "INR"
    observed_at: AwareDatetime
    expires_at: AwareDatetime
    source: Label
    source_kind: Literal["REVIEWED_DATASET", "ENGINEERING_FIXTURE"]

    @model_validator(mode="after")
    def bounded_snapshot(self) -> Self:
        if self.price <= 0 or self.expires_at <= self.observed_at:
            raise ValueError("A quote needs a positive price and explicit validity interval.")
        return self


class OrderEvaluation(ContractModel):
    state: Literal["EXECUTED", "REJECTED"]
    reason: Literal[
        "FILLED",
        "QUOTES_UNAVAILABLE",
        "WRONG_QUOTE",
        "STALE_QUOTE",
        "INSUFFICIENT_CASH",
        "INSUFFICIENT_HOLDINGS",
        "HOLDING_LIMIT",
        "OUT_OF_RANGE",
    ]
    before: PortfolioState
    after: PortfolioState
    cash_delta: DecimalValue
    quantity_delta: Annotated[int, Field(strict=True, ge=-1000000, le=1000000)]

    @model_validator(mode="after")
    def rejected_orders_do_not_move_balances(self) -> Self:
        if self.state == "REJECTED" and (
            self.before != self.after or self.cash_delta != 0 or self.quantity_delta != 0
        ):
            raise ValueError("Rejected virtual orders cannot change cash or holdings.")
        if (self.reason == "FILLED") != (self.state == "EXECUTED"):
            raise ValueError("Only an executed order is filled.")
        return self


class LedgerEntry(ContractModel):
    id: CanonicalId
    sequence: Annotated[int, Field(strict=True, ge=1, le=1000000)]
    request: OrderRequest
    quote: QuoteSnapshot | None
    committed_at: AwareDatetime
    evaluation: OrderEvaluation


class PortfolioAccount(ContractModel):
    account_id: CanonicalId
    portfolio_version_id: CanonicalId
    state: PortfolioState
    committed_orders: SafeInteger
    valuation_state: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    market_value: None = None
    total_value: None = None


class OrderReceipt(ContractModel):
    account_id: CanonicalId
    portfolio_version_id: CanonicalId
    entry: LedgerEntry


class LedgerPage(ContractModel):
    account_id: CanonicalId
    portfolio_version_id: CanonicalId
    entries: Annotated[tuple[LedgerEntry, ...], Field(strict=False, max_length=100)]
    total: SafeInteger
    offset: SafeInteger
