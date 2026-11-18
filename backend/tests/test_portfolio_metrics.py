"""Exact snapshot ratios from authored ledgers, with no market-return claims."""

from datetime import timedelta
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest
from test_portfolio_analytics import history
from test_portfolio_engine import COMPANY, NOW, order, quote
from test_portfolio_valuation import partial, two_positions

from regintel.portfolio.analytics import MAX_ANALYTICS_ENTRIES, ledger_analytics
from regintel.portfolio.metrics import PortfolioSnapshotMetrics, snapshot_metrics
from regintel.portfolio.models import PortfolioAccount, PortfolioState
from regintel.portfolio.valuation import value_portfolio


def opening_value(cash="100000.00"):
    identity = str(uuid4())
    account = PortfolioAccount(
        account_id=identity,
        portfolio_version_id=identity,
        state=PortfolioState(cash=cash, holdings=()),
        committed_orders=0,
    )
    return value_portfolio(ledger_analytics(account, Decimal(cash), ()), {}, NOW)


def test_partial_sale_ratios_retain_exact_sources_and_unchanged_valuation_bytes():
    value = value_portfolio(partial(), {COMPANY: quote("25.00")}, NOW)
    before = value.model_dump_json()
    with localcontext() as ambient:
        ambient.prec = 2
        result = snapshot_metrics(value)
    body = result.model_dump(mode="json")
    assert result.valuation.model_dump_json() == value.model_dump_json() == before
    assert result.schema_version == "portfolio-snapshot-metrics-1"
    assert result.return_basis == "SELECTED_LEDGER_AT_VALUATION_TIME"
    assert result.rounding_mode == "ROUND_HALF_EVEN" and result.percentage_decimal_places == 6
    assert body["simple_return"] == {
        "state": "AVAILABLE",
        "numerator": "65.00",
        "denominator": "100000.00",
        "percentage": "0.065000",
    }
    assert body["allocation"] == {
        "state": "AVAILABLE",
        "denominator": "100065.00",
        "entries": [
            {
                "kind": "CASH",
                "company_id": None,
                "numerator": "100040.00",
                "percentage": "99.975016",
            },
            {
                "kind": "HOLDING",
                "company_id": COMPANY,
                "numerator": "25.00",
                "percentage": "0.024984",
            },
        ],
        "percentage_sum": "100.000000",
        "rounding_residual": "0.000000",
    }
    assert PortfolioSnapshotMetrics.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("closed", [False, True])
def test_cash_only_opening_and_closed_histories_need_no_prices(closed):
    value = opening_value()
    if closed:
        account, entries = history()
        value = value_portfolio(ledger_analytics(account, Decimal("100000.00"), entries), {}, NOW)
    result = snapshot_metrics(value)
    assert result.simple_return.percentage == Decimal("0.012000" if closed else "0.000000")
    assert len(result.allocation.entries) == 1
    assert result.allocation.entries[0].percentage == Decimal("100.000000")
    assert result.allocation.entries[0].numerator == value.total_value
    assert result.valuation.positions == result.valuation.quote_version_ids == ()


@pytest.mark.parametrize(
    ("sale", "expected"),
    [
        ("1.01", "0.000000"),
        ("0.99", "0.000000"),
        ("1.03", "0.000002"),
        ("1.05", "0.000002"),
        ("0.97", "-0.000002"),
    ],
)
def test_half_even_ties_and_negative_tiny_returns_have_canonical_unsigned_zero(sale, expected):
    account, entries = history(
        ("1.00", sale), (order(quantity=1), order("SELL", 1)), opening_cash="2000000.00"
    )
    value = value_portfolio(ledger_analytics(account, Decimal("2000000.00"), entries), {}, NOW)
    result = snapshot_metrics(value)
    assert result.model_dump(mode="json")["simple_return"]["percentage"] == expected


@pytest.mark.parametrize(
    ("components", "percentage", "total", "residual"),
    [
        (3, "33.333333", "99.999999", "0.000001"),
        (6, "16.666667", "100.000002", "-0.000002"),
    ],
)
def test_equal_components_expose_both_rounding_residual_signs_without_adjusted_weights(
    components, percentage, total, residual
):
    requests = tuple(
        order(quantity=1).model_copy(update={"company_id": str(uuid4())})
        for _ in range(components - 1)
    )
    cash = f"{components}.00"
    account, entries = history(("1.00",) * (components - 1), requests, opening_cash=cash)
    analytics = ledger_analytics(account, Decimal(cash), entries)
    sources = {
        request.company_id: quote("1.00", company_id=request.company_id) for request in requests
    }
    result = snapshot_metrics(value_portfolio(analytics, sources, NOW))
    allocation = result.model_dump(mode="json")["allocation"]
    assert [entry["percentage"] for entry in allocation["entries"]] == [percentage] * components
    assert allocation["percentage_sum"] == total and allocation["rounding_residual"] == residual
    assert [entry.company_id for entry in result.allocation.entries[1:]] == sorted(sources)
    assert result.simple_return.percentage == Decimal("0.000000")


@pytest.mark.parametrize(
    ("price", "expected"), [("50000.00", "-50.000000"), ("200000.00", "100.000000")]
)
def test_zero_cash_keeps_explicit_zero_weight_and_signed_total_return(price, expected):
    account, entries = history(("100000.00",), (order(quantity=1),))
    value = value_portfolio(
        ledger_analytics(account, Decimal("100000.00"), entries), {COMPANY: quote(price)}, NOW
    )
    result = snapshot_metrics(value)
    assert result.model_dump(mode="json")["simple_return"]["percentage"] == expected
    assert result.allocation.entries[0].numerator == 0
    assert result.allocation.entries[0].percentage == Decimal("0.000000")
    assert result.allocation.entries[1].percentage == Decimal("100.000000")


def test_zero_opening_and_zero_total_are_distinct_unavailable_denominators():
    result = snapshot_metrics(opening_value("0.00"))
    assert result.valuation.state == "AVAILABLE"
    assert result.simple_return.state == "ZERO_OPENING_CASH"
    assert result.simple_return.numerator == result.simple_return.denominator == 0
    assert result.simple_return.percentage is None
    assert result.allocation.state == "ZERO_TOTAL_VALUE" and result.allocation.denominator == 0
    assert result.allocation.entries == ()
    assert result.allocation.percentage_sum is result.allocation.rounding_residual is None


@pytest.mark.parametrize("reason", ["missing", "wrong", "expired", "future", "conflicting"])
def test_any_unavailable_position_prevents_partial_return_or_allocation(reason):
    analytics, other = two_positions()
    first, second, at = quote("12.00"), quote("30.00", company_id=other), NOW
    if reason == "missing":
        second = None
    elif reason == "wrong":
        second = quote("30.00", company_id=str(uuid4()))
    elif reason == "expired":
        second = quote("30.00", company_id=other, expires_at=NOW)
    elif reason == "future":
        second = quote("30.00", company_id=other, observed_at=NOW + timedelta(seconds=1))
    else:
        second = quote("30.00", company_id=other, id=first.id)
    result = snapshot_metrics(value_portfolio(analytics, {COMPANY: first, other: second}, at))
    assert result.simple_return.state == result.allocation.state == "QUOTES_UNAVAILABLE"
    assert result.simple_return.numerator is result.simple_return.denominator is None
    assert result.simple_return.percentage is result.allocation.denominator is None
    assert result.allocation.entries == ()
    assert result.allocation.percentage_sum is result.allocation.rounding_residual is None


def test_ledger_budget_failure_does_not_produce_partial_metrics():
    account, _ = history()
    account = account.model_copy(update={"committed_orders": MAX_ANALYTICS_ENTRIES + 1})
    result = snapshot_metrics(
        value_portfolio(ledger_analytics(account, Decimal("100000.00"), ()), {}, NOW)
    )
    assert result.simple_return.state == result.allocation.state == "LEDGER_BUDGET_EXCEEDED"
    assert result.simple_return.percentage is result.allocation.denominator is None
    assert result.allocation.entries == () and result.valuation.positions == ()


@pytest.mark.parametrize(
    "change",
    [
        "float",
        "integer",
        "scale",
        "negative_zero",
        "return_denominator",
        "allocation_numerator",
        "partial",
        "cash_identity",
        "order",
        "residual",
        "clock",
        "version",
        "quote_version",
        "quote_price",
        "return_state",
        "schema",
        "rounding",
        "places",
    ],
)
def test_wire_rejects_forged_ratios_sources_membership_metadata_and_numbers(change):
    result = snapshot_metrics(value_portfolio(partial(), {COMPANY: quote("25.00")}, NOW))
    body = result.model_dump(mode="python")
    if change in {"float", "integer", "scale", "negative_zero"}:
        body["simple_return"]["percentage"] = {
            "float": 0.065,
            "integer": 0,
            "scale": Decimal("0.065"),
            "negative_zero": Decimal("-0.000000"),
        }[change]
    elif change == "return_denominator":
        body["simple_return"].update(
            denominator=Decimal("10000.00"), percentage=Decimal("0.650000")
        )
    elif change == "allocation_numerator":
        body["allocation"]["entries"][0]["numerator"] = Decimal("100039.00")
    elif change == "partial":
        body["allocation"]["entries"] = body["allocation"]["entries"][:1]
    elif change == "cash_identity":
        body["allocation"]["entries"][0]["company_id"] = COMPANY
    elif change == "order":
        body["allocation"]["entries"] = tuple(reversed(body["allocation"]["entries"]))
    elif change == "residual":
        body["allocation"]["rounding_residual"] = Decimal("0.000001")
    elif change == "clock":
        body["valuation"]["evaluated_at"] = NOW.replace(tzinfo=None)
    elif change == "version":
        body["valuation"]["portfolio_version_id"] = str(uuid4())
    elif change == "quote_version":
        body["valuation"]["quote_version_ids"] = ()
    elif change == "quote_price":
        body["valuation"]["positions"][0]["quote"]["price"] = Decimal("26.00")
    elif change == "return_state":
        body["simple_return"].update(
            state="QUOTES_UNAVAILABLE", numerator=None, denominator=None, percentage=None
        )
    else:
        key = {
            "schema": "schema_version",
            "rounding": "rounding_mode",
            "places": "percentage_decimal_places",
        }[change]
        body[key] = {"schema": "future", "rounding": "ROUND_HALF_UP", "places": 5}[change]
    with pytest.raises(ValueError):
        PortfolioSnapshotMetrics.model_validate(body)


@pytest.mark.parametrize("change", ["clock", "version", "float"])
def test_builder_revalidates_model_copy_instead_of_trusting_existing_instances(change):
    value = value_portfolio(partial(), {COMPANY: quote("25.00")}, NOW)
    updates = {
        "clock": {"evaluated_at": NOW.replace(tzinfo=None)},
        "version": {"portfolio_version_id": str(uuid4())},
        "float": {"total_result": 65.0},
    }[change]
    with pytest.raises(ValueError):
        snapshot_metrics(value.model_copy(update=updates))
