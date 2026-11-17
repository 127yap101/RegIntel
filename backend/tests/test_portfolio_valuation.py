"""Authored fixed-price valuation oracles; no market prices or financial recommendations."""

from datetime import timedelta
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest
from test_portfolio_analytics import history
from test_portfolio_engine import COMPANY, NOW, order, quote

from regintel.portfolio.analytics import MAX_ANALYTICS_ENTRIES, ledger_analytics
from regintel.portfolio.models import PortfolioAccount, PortfolioState
from regintel.portfolio.valuation import PortfolioValuation, value_portfolio


def partial():
    account, entries = history(
        ("10.00", "20.00", "30.00"),
        (order(quantity=2), order(quantity=3), order("SELL", 4)),
    )
    return ledger_analytics(account, Decimal("100000.00"), entries)


def test_current_price_valuation_reconciles_partial_sale_fifo_and_exact_source_versions():
    analytics = partial()
    source = quote("25.00")
    with localcontext() as ambient:
        ambient.prec = 2
        result = value_portfolio(analytics, {COMPANY: source}, NOW)
    assert result.state == "AVAILABLE"
    assert result.evaluated_at == NOW and result.currency == "INR"
    assert result.cash_flow.cash == Decimal("100040.00")
    assert result.market_value == Decimal("25.00")
    assert result.unrealized_result == Decimal("5.00")
    assert result.total_value == Decimal("100065.00")
    assert result.total_result == Decimal("65.00")
    assert result.cash_flow.realized_result == Decimal("60.00")
    assert result.positions[0].quote == source
    assert result.positions[0].cash_flow.quantity == 1
    assert result.input_entry_ids == analytics.input_entry_ids
    assert result.corpus_version_ids == analytics.corpus_version_ids
    assert result.execution_quote_version_ids == analytics.quote_version_ids
    assert result.quote_version_ids == (source.quote_version_id,)
    assert result.portfolio_version_id == analytics.portfolio_version_id
    body = result.model_dump(mode="json")
    assert body["market_value"] == "25.00" and body["total_result"] == "65.00"
    assert body["positions"][0]["quote"]["price"] == "25.00"
    assert PortfolioValuation.model_validate_json(result.model_dump_json()) == result


def test_falling_price_retains_negative_unrealized_result_and_exact_total():
    result = value_portfolio(partial(), {COMPANY: quote("0.01")}, NOW)
    assert result.unrealized_result == Decimal("-19.99")
    assert result.total_result == Decimal("40.01")
    assert result.total_value == Decimal("100040.01")


def test_closed_history_needs_no_quote_and_reports_only_cash_and_realized_result():
    account, entries = history()
    analytics = ledger_analytics(account, Decimal("100000.00"), entries)
    result = value_portfolio(analytics, {}, NOW)
    assert result.state == "AVAILABLE" and result.positions == ()
    assert result.market_value == result.unrealized_result == Decimal("0.00")
    assert result.total_value == Decimal("100012.00")
    assert result.total_result == Decimal("12.00")
    assert result.quote_version_ids == () and result.execution_quote_version_ids


def test_opening_account_is_cash_only_without_a_quote():
    identity = str(uuid4())
    account = PortfolioAccount(
        account_id=identity,
        portfolio_version_id=identity,
        state=PortfolioState(cash="100000.00", holdings=()),
        committed_orders=0,
    )
    result = value_portfolio(ledger_analytics(account, Decimal("100000.00"), ()), {}, NOW)
    assert result.state == "AVAILABLE" and result.total_value == Decimal("100000.00")
    assert result.total_result == Decimal("0.00")
    assert result.input_entry_ids == result.quote_version_ids == result.positions == ()


@pytest.mark.parametrize(
    ("source", "at", "state"),
    [
        (None, NOW, "MISSING_QUOTE"),
        (quote(company_id=str(uuid4())), NOW, "WRONG_QUOTE"),
        (quote(), NOW - timedelta(minutes=1, microseconds=1), "STALE_QUOTE"),
        (quote(), NOW + timedelta(minutes=1), "STALE_QUOTE"),
    ],
)
def test_missing_mismatched_future_or_expired_prices_never_produce_portfolio_totals(
    source, at, state
):
    analytics = partial()
    result = value_portfolio(analytics, {COMPANY: source}, at)
    assert result.state == "QUOTES_UNAVAILABLE" and result.positions[0].state == state
    assert result.cash_flow == analytics.summary
    assert result.market_value is result.total_value is result.unrealized_result is None
    assert result.total_result is None
    assert result.positions[0].market_value is result.positions[0].unrealized_result is None


def test_observation_boundary_is_inclusive_and_expiry_boundary_is_exclusive():
    source = quote()
    assert value_portfolio(partial(), {COMPANY: source}, source.observed_at).state == "AVAILABLE"
    assert (
        value_portfolio(partial(), {COMPANY: source}, source.expires_at).state
        == "QUOTES_UNAVAILABLE"
    )


def two_positions():
    other = str(uuid4())
    second = order(quantity=2).model_copy(update={"company_id": other})
    account, entries = history(("10.00", "20.00"), (order(quantity=3), second))
    return ledger_analytics(account, Decimal("100000.00"), entries), other


def test_one_missing_price_keeps_individually_supported_value_but_no_partial_portfolio_total():
    analytics, other = two_positions()
    result = value_portfolio(analytics, {COMPANY: quote("12.00"), other: None}, NOW)
    positions = {item.cash_flow.company_id: item for item in result.positions}
    assert positions[COMPANY].market_value == Decimal("36.00")
    assert positions[COMPANY].unrealized_result == Decimal("6.00")
    assert positions[other].market_value is None
    assert result.state == "QUOTES_UNAVAILABLE" and result.total_value is None
    assert result.market_value is result.unrealized_result is result.total_result is None


def test_snapshot_identity_reused_for_different_companies_is_explicitly_conflicting():
    analytics, other = two_positions()
    source = quote("12.00")
    result = value_portfolio(
        analytics,
        {COMPANY: source, other: quote("30.00", id=source.id, company_id=other)},
        NOW,
    )
    assert result.state == "QUOTES_UNAVAILABLE"
    assert all(item.state == "CONFLICTING_QUOTE" for item in result.positions)
    assert result.total_value is None


def test_multiple_quotes_reconcile_all_holdings_and_keep_distinct_quote_versions():
    analytics, other = two_positions()
    sources = {COMPANY: quote("12.00"), other: quote("30.00", company_id=other)}
    result = value_portfolio(analytics, sources, NOW)
    assert result.market_value == Decimal("96.00")
    assert result.total_value == Decimal("100026.00")
    assert result.unrealized_result == result.total_result == Decimal("26.00")
    assert result.quote_version_ids == tuple(
        sorted(source.quote_version_id for source in sources.values())
    )


@pytest.mark.parametrize("change", ["missing", "extra", "naive", "numeric_price", "partial_ledger"])
def test_valuation_rejects_incomplete_source_mapping_naive_time_or_tampered_inputs(change):
    analytics, sources, at = partial(), {COMPANY: quote()}, NOW
    if change == "missing":
        sources = {}
    elif change == "extra":
        sources[str(uuid4())] = quote()
    elif change == "naive":
        at = NOW.replace(tzinfo=None)
    elif change == "numeric_price":
        sources[COMPANY] = quote().model_copy(update={"price": 1.25})
    else:
        analytics = analytics.model_copy(update={"input_entry_ids": analytics.input_entry_ids[:-1]})
    with pytest.raises(ValueError):
        value_portfolio(analytics, sources, at)


def test_ledger_budget_failure_returns_no_partial_positions_totals_or_quote_versions():
    account, _ = history()
    account = account.model_copy(update={"committed_orders": MAX_ANALYTICS_ENTRIES + 1})
    analytics = ledger_analytics(account, Decimal("100000.00"), ())
    result = value_portfolio(analytics, {}, NOW)
    assert result.state == "LEDGER_BUDGET_EXCEEDED"
    assert result.cash_flow is result.market_value is result.total_value is None
    assert result.input_entry_ids == result.positions == result.quote_version_ids == ()


@pytest.mark.parametrize(
    "change", ["total", "status", "quote_versions", "expiry", "duplicate_entry"]
)
def test_wire_rejects_inconsistent_valuation_results(change):
    result = value_portfolio(partial(), {COMPANY: quote("25.00")}, NOW)
    body = result.model_dump(mode="python")
    if change == "total":
        body["total_value"] = Decimal("0.00")
    elif change == "status":
        body["positions"][0]["state"] = "MISSING_QUOTE"
    elif change == "quote_versions":
        body["quote_version_ids"] = ()
    elif change == "expiry":
        body["evaluated_at"] = NOW + timedelta(hours=1)
    else:
        body["input_entry_ids"] = (body["input_entry_ids"][0],) * 3
    with pytest.raises(ValueError):
        PortfolioValuation.model_validate(body)
