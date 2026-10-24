"""Fixed-price virtual acceptance controls; prices are explicitly engineering fixtures."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest
from pydantic import ValidationError

from regintel.portfolio.engine import evaluate_order, replay_ledger
from regintel.portfolio.models import (
    Holding,
    LedgerEntry,
    OrderRequest,
    PortfolioState,
    QuoteSnapshot,
)

NOW = datetime(2026, 10, 23, 6, tzinfo=UTC)
COMPANY = str(uuid4())


def quote(price="10.10", **changes):
    values = dict(
        id=str(uuid4()),
        quote_version_id=str(uuid4()),
        company_id=COMPANY,
        price=price,
        observed_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=1),
        source="Authored fixed-price acceptance fixture",
        source_kind="ENGINEERING_FIXTURE",
    )
    values.update(changes)
    return QuoteSnapshot.model_validate(values)


def order(side="BUY", quantity=3):
    return OrderRequest(
        request_id=str(uuid4()),
        corpus_version_id=str(uuid4()),
        company_id=COMPANY,
        side=side,
        quantity=quantity,
    )


def test_fixed_buy_partial_sell_final_sell_and_ledger_replay():
    opening = state = PortfolioState(cash="100.00", holdings=())
    entries = []
    for index, request in enumerate((order(quantity=3), order("SELL", 1), order("SELL", 2)), 1):
        price = quote()
        with localcontext() as ambient:
            ambient.prec = 2
            result = evaluate_order(state, request, price, NOW)
        assert result.state == "EXECUTED"
        entries.append(
            LedgerEntry(
                id=str(uuid4()),
                sequence=index,
                request=request,
                quote=price,
                committed_at=NOW,
                evaluation=result,
            )
        )
        state = result.after
    assert entries[0].evaluation.after.cash == Decimal("69.70")
    assert entries[1].evaluation.after.cash == Decimal("79.80")
    assert entries[1].evaluation.after.holdings[0].quantity == 2
    assert state == opening and replay_ledger(opening, tuple(entries)) == state


@pytest.mark.parametrize(
    "reason",
    [
        "QUOTES_UNAVAILABLE",
        "WRONG_QUOTE",
        "STALE_QUOTE",
        "INSUFFICIENT_CASH",
        "INSUFFICIENT_HOLDINGS",
    ],
)
def test_rejected_orders_do_not_move_cash_or_holdings(reason):
    state = PortfolioState(cash="10.00", holdings=())
    request, price = order(), quote()
    if reason == "QUOTES_UNAVAILABLE":
        price = None
    elif reason == "WRONG_QUOTE":
        price = quote(company_id=str(uuid4()))
    elif reason == "STALE_QUOTE":
        price = quote(expires_at=NOW)
    elif reason == "INSUFFICIENT_HOLDINGS":
        request = order("SELL", 1)
    result = evaluate_order(state, request, price, NOW)
    assert result.reason == reason and result.after == result.before == state
    assert result.cash_delta == 0 and result.quantity_delta == 0


def test_future_quote_is_unavailable_and_expiry_boundary_is_exclusive():
    state = PortfolioState(cash="100.00", holdings=())
    assert (
        evaluate_order(state, order(), quote(observed_at=NOW + timedelta(seconds=1)), NOW).reason
        == "STALE_QUOTE"
    )
    assert evaluate_order(state, order(), quote(expires_at=NOW), NOW).reason == "STALE_QUOTE"


@pytest.mark.parametrize("quantity", [True, 1.0, "1", 0, -1, 1000001])
def test_order_quantity_is_a_bounded_positive_whole_share_count(quantity):
    with pytest.raises(ValidationError):
        order(quantity=quantity)


@pytest.mark.parametrize("price", [1.2, True, "1.001", "NaN", "0", "-1"])
def test_quote_prices_are_positive_decimal_cents(price):
    with pytest.raises(ValidationError):
        quote(price)


@pytest.mark.parametrize("change", ["duplicate", "gap", "cash"])
def test_ledger_replay_rejects_duplicate_gaps_and_modified_outcomes(change):
    opening = PortfolioState(cash="100.00", holdings=())
    request, price = order(), quote()
    result = evaluate_order(opening, request, price, NOW)
    entry = LedgerEntry(
        id=str(uuid4()),
        sequence=1,
        request=request,
        quote=price,
        committed_at=NOW,
        evaluation=result,
    )
    entries = (entry,)
    if change == "duplicate":
        entries = (entry, entry.model_copy(update={"sequence": 2}))
    elif change == "gap":
        entries = (entry.model_copy(update={"sequence": 2}),)
    else:
        entries = (
            entry.model_copy(
                update={
                    "evaluation": result.model_copy(
                        update={"after": PortfolioState(cash="1.00", holdings=())}
                    )
                }
            ),
        )
    with pytest.raises(ValueError):
        replay_ledger(opening, entries)


def test_holdings_limit_is_explicit_and_cash_range_failure_does_not_commit():
    state = PortfolioState(cash="0.00", holdings=(Holding(company_id=COMPANY, quantity=1000000),))
    assert (
        evaluate_order(state, order("SELL", 1000000), quote("99999999999999.99"), NOW).reason
        == "OUT_OF_RANGE"
    )
    state = state.model_copy(update={"cash": Decimal("100.00")})
    assert evaluate_order(state, order("BUY", 1), quote(), NOW).reason == "HOLDING_LIMIT"
