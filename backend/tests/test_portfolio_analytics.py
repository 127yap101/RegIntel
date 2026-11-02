"""Independent fixed-price cash-flow oracles; never a market or return benchmark."""

from decimal import Decimal, localcontext
from uuid import uuid4

import pytest
from test_portfolio_engine import NOW, order, quote

from regintel.portfolio.analytics import MAX_ANALYTICS_ENTRIES, ledger_analytics
from regintel.portfolio.engine import evaluate_order
from regintel.portfolio.models import LedgerEntry, PortfolioAccount, PortfolioState


def history(prices=("10.00", "12.00", "15.00"), requests=None, opening_cash="100000.00"):
    state = PortfolioState(cash=opening_cash, holdings=())
    requests = requests or (order(quantity=3), order("SELL", 1), order("SELL", 2))
    entries = []
    for index, (request, price) in enumerate(zip(requests, prices, strict=True), 1):
        source = quote(price, company_id=request.company_id)
        outcome = evaluate_order(state, request, source, NOW)
        entries.append(
            LedgerEntry(
                id=str(uuid4()),
                sequence=index,
                request=request,
                quote=source,
                committed_at=NOW,
                evaluation=outcome,
            )
        )
        state = outcome.after
    identity = str(uuid4())
    account = PortfolioAccount(
        account_id=identity,
        portfolio_version_id=entries[-1].id if entries else identity,
        state=state,
        committed_orders=len(entries),
    )
    return account, tuple(entries)


def test_closed_position_cash_result_and_exact_sources():
    account, entries = history()
    with localcontext() as ambient:
        ambient.prec = 2
        result = ledger_analytics(account, Decimal("100000.00"), entries)
    assert result.summary.buy_spend == Decimal("30.00")
    assert result.summary.sale_proceeds == Decimal("42.00")
    assert result.summary.net_cash_flow == Decimal("12.00")
    assert result.summary.cash == Decimal("100012.00")
    assert (result.summary.executed_orders, result.summary.rejected_orders) == (3, 0)
    assert result.companies[0].closed_position_result == Decimal("12.00")
    assert result.input_entry_ids == tuple(entry.id for entry in entries)
    assert result.corpus_version_ids == tuple(
        sorted({e.request.corpus_version_id for e in entries})
    )
    assert result.quote_version_ids == tuple(sorted({e.quote.quote_version_id for e in entries}))
    assert result.model_dump(mode="json")["summary"]["cash"] == "100012.00"
    assert result.market_value is None and result.total_value is None


@pytest.mark.parametrize("reopened", [False, True])
def test_open_position_cash_flow_is_not_reported_as_profit(reopened):
    requests = (order(quantity=3), order("SELL", 1))
    prices = ("10.00", "12.00")
    if reopened:
        requests += (order("SELL", 2), order(quantity=1))
        prices += ("15.00", "8.00")
    account, entries = history(prices, requests)
    result = ledger_analytics(account, Decimal("100000.00"), entries)
    selected = result.companies[0]
    assert selected.position_state == "OPEN" and selected.closed_position_result is None
    assert selected.net_cash_flow == Decimal("4.00" if reopened else "-18.00")
    assert selected.quantity == (1 if reopened else 2)


def test_rejected_missing_quotes_are_audited_without_financial_movement():
    opening = PortfolioState(cash="100000.00", holdings=())
    request = order()
    entry = LedgerEntry(
        id=str(uuid4()),
        sequence=1,
        request=request,
        quote=None,
        committed_at=NOW,
        evaluation=evaluate_order(opening, request, None, NOW),
    )
    account = PortfolioAccount(
        account_id=str(uuid4()),
        portfolio_version_id=entry.id,
        state=opening,
        committed_orders=1,
    )
    result = ledger_analytics(account, Decimal("100000.00"), (entry,))
    assert result.summary.executed_orders == 0 and result.summary.rejected_orders == 1
    assert result.summary.net_cash_flow == 0 and result.companies == ()
    assert result.quote_version_ids == () and result.input_entry_ids == (entry.id,)


def test_empty_account_has_available_cash_flow_without_invented_positions():
    identity = str(uuid4())
    account = PortfolioAccount(
        account_id=identity,
        portfolio_version_id=identity,
        state=PortfolioState(cash="100000.00", holdings=()),
        committed_orders=0,
    )
    result = ledger_analytics(account, Decimal("100000.00"), ())
    assert result.state == "AVAILABLE" and result.summary.cash == Decimal("100000.00")
    assert result.companies == result.input_entry_ids == result.corpus_version_ids == ()


@pytest.mark.parametrize("change", ["partial", "state", "version", "duplicate_id"])
def test_analytics_rejects_partial_mixed_or_tampered_history(change):
    account, entries = history()
    if change == "partial":
        entries = entries[:-1]
    elif change == "state":
        account = account.model_copy(update={"state": PortfolioState(cash="1.00", holdings=())})
    elif change == "version":
        account = account.model_copy(update={"portfolio_version_id": str(uuid4())})
    else:
        entries = (entries[0], entries[1].model_copy(update={"id": entries[0].id}), entries[2])
    with pytest.raises(ValueError):
        ledger_analytics(account, Decimal("100000.00"), entries)


def test_ledger_budget_failure_never_returns_partial_totals():
    account, _ = history()
    account = account.model_copy(update={"committed_orders": MAX_ANALYTICS_ENTRIES + 1})
    result = ledger_analytics(account, Decimal("100000.00"), ())
    assert result.state == "LEDGER_BUDGET_EXCEEDED"
    assert result.summary is None and result.companies == result.input_entry_ids == ()


@pytest.mark.parametrize(
    ("prices", "requests", "quantity", "allocated", "remaining", "realized", "flow"),
    [
        (
            ("10.00", "20.00", "30.00"),
            (order(quantity=2), order(quantity=3), order("SELL", 4)),
            1,
            "60.00",
            "20.00",
            "60.00",
            "40.00",
        ),
        (
            ("10.00", "20.00", "30.00", "15.00"),
            (order(quantity=2), order(quantity=3), order("SELL", 4), order("SELL", 1)),
            0,
            "80.00",
            "0.00",
            "55.00",
            "55.00",
        ),
        (
            ("10.00", "20.00", "30.00", "15.00", "7.00"),
            (
                order(quantity=2),
                order(quantity=3),
                order("SELL", 4),
                order("SELL", 1),
                order(quantity=2),
            ),
            2,
            "80.00",
            "14.00",
            "55.00",
            "41.00",
        ),
        (
            ("20.00", "10.00", "5.00"),
            (order(quantity=2), order(quantity=1), order("SELL", 2)),
            1,
            "40.00",
            "10.00",
            "-30.00",
            "-40.00",
        ),
    ],
)
def test_fifo_allocates_original_lots_with_independent_partial_closed_reopened_and_loss_oracles(
    prices, requests, quantity, allocated, remaining, realized, flow
):
    account, entries = history(prices, requests)
    with localcontext() as ambient:
        ambient.prec = 2
        result = ledger_analytics(account, Decimal("100000.00"), entries)
    item = result.companies[0]
    assert result.cost_basis_method == "FIFO" and item.quantity == quantity
    assert item.realized_cost_basis == result.summary.realized_cost_basis == Decimal(allocated)
    assert item.remaining_cost_basis == result.summary.remaining_cost_basis == Decimal(remaining)
    assert item.realized_result == result.summary.realized_result == Decimal(realized)
    assert item.net_cash_flow == result.summary.net_cash_flow == Decimal(flow)
    assert item.closed_position_result == (Decimal(realized) if quantity == 0 else None)


def test_rejected_sales_and_buys_never_consume_or_create_fifo_lots():
    requests = (order(quantity=2), order("SELL", 3), order(quantity=100000), order("SELL", 1))
    account, entries = history(("10.00", "100.00", "100.00", "12.00"), requests)
    result = ledger_analytics(account, Decimal("100000.00"), entries)
    assert result.summary.rejected_orders == 2
    assert result.summary.realized_cost_basis == Decimal("10.00")
    assert result.summary.remaining_cost_basis == Decimal("10.00")
    assert result.summary.realized_result == Decimal("2.00")


def test_fifo_company_lots_are_independent_when_executions_are_interleaved():
    other = str(uuid4())
    requests = (
        order(quantity=2),
        order(quantity=3).model_copy(update={"company_id": other}),
        order("SELL", 1),
        order("SELL", 3).model_copy(update={"company_id": other}),
    )
    account, entries = history(("10.00", "20.00", "15.00", "18.00"), requests)
    result = ledger_analytics(account, Decimal("100000.00"), entries)
    assert result.summary.realized_cost_basis == Decimal("70.00")
    assert result.summary.remaining_cost_basis == Decimal("10.00")
    assert result.summary.realized_result == Decimal("-1.00")
    closed = next(item for item in result.companies if item.company_id == other)
    assert closed.closed_position_result == closed.realized_result == Decimal("-6.00")


def test_fifo_retains_one_cent_above_javascript_safe_integer_range():
    opening = "99999999999999.00"
    account, entries = history(
        ("90071992547409.93", "90071992547409.94"), (order(quantity=1), order("SELL", 1)), opening
    )
    result = ledger_analytics(account, Decimal(opening), entries)
    assert result.summary.realized_cost_basis == Decimal("90071992547409.93")
    assert result.summary.realized_result == Decimal("0.01")
    assert result.summary.cash == Decimal("99999999999999.01")


@pytest.mark.parametrize(
    "change",
    [
        "allocated",
        "negative",
        "subcent",
        "result",
        "quantity",
        "policy",
        "summary",
        "duplicate_company",
    ],
)
def test_fifo_wire_rejects_unreconciled_or_unsupported_financial_totals(change):
    account, entries = history(("10.00", "12.00"), (order(quantity=3), order("SELL", 1)))
    value = ledger_analytics(account, Decimal("100000.00"), entries).model_dump(mode="json")
    item = value["companies"][0]
    if change == "allocated":
        item["realized_cost_basis"] = "11.00"
    if change == "negative":
        item["remaining_cost_basis"] = "-1.00"
    if change == "subcent":
        item["realized_cost_basis"] = "10.001"
    if change == "result":
        item["realized_result"] = "3.00"
    if change == "quantity":
        item["quantity"] = 1
    if change == "policy":
        value["cost_basis_method"] = "UNKNOWN"
    if change == "summary":
        value["summary"]["realized_result"] = "3.00"
    if change == "duplicate_company":
        value["companies"].append(item)
    with pytest.raises(ValueError):
        type(ledger_analytics(account, Decimal("100000.00"), entries)).model_validate(value)
