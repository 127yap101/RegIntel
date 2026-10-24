"""Whole-share, zero-fee virtual execution/replay using exact Decimal cents only."""

from datetime import datetime
from decimal import Decimal, localcontext

from pydantic import ValidationError

from regintel.portfolio.models import (
    Holding,
    LedgerEntry,
    OrderEvaluation,
    OrderRequest,
    PortfolioState,
    QuoteSnapshot,
)


def evaluate_order(
    state: PortfolioState,
    request: OrderRequest,
    quote: QuoteSnapshot | None,
    at: datetime,
) -> OrderEvaluation:
    state = PortfolioState.model_validate(state.model_dump(mode="python"))
    request = OrderRequest.model_validate(request.model_dump(mode="python"))
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("Virtual execution requires an aware server timestamp.")

    def rejected(reason: str) -> OrderEvaluation:
        return OrderEvaluation.model_validate(
            {
                "state": "REJECTED",
                "reason": reason,
                "before": state,
                "after": state,
                "cash_delta": Decimal(0),
                "quantity_delta": 0,
            }
        )

    if quote is None:
        return rejected("QUOTES_UNAVAILABLE")
    quote = QuoteSnapshot.model_validate(quote.model_dump(mode="python"))
    if quote.company_id != request.company_id or quote.currency != state.currency:
        return rejected("WRONG_QUOTE")
    if at < quote.observed_at or at >= quote.expires_at:
        return rejected("STALE_QUOTE")
    positions = {holding.company_id: holding.quantity for holding in state.holdings}
    owned = positions.get(request.company_id, 0)
    if request.side == "SELL" and owned < request.quantity:
        return rejected("INSUFFICIENT_HOLDINGS")
    quantity_delta = request.quantity if request.side == "BUY" else -request.quantity
    quantity = owned + quantity_delta
    if quantity > 1000000 or (quantity > 0 and not owned and len(positions) == 100):
        return rejected("HOLDING_LIMIT")
    with localcontext() as context:
        context.prec = 64
        cost = quote.price * Decimal(request.quantity)
        cash_delta = -cost if request.side == "BUY" else cost
        cash = state.cash + cash_delta
    if cash < 0:
        return rejected("INSUFFICIENT_CASH")
    if quantity:
        positions[request.company_id] = quantity
    else:
        positions.pop(request.company_id, None)
    try:
        after = PortfolioState(
            cash=cash,
            holdings=tuple(
                Holding(company_id=key, quantity=value) for key, value in sorted(positions.items())
            ),
        )
    except ValidationError:
        return rejected("OUT_OF_RANGE")
    return OrderEvaluation(
        state="EXECUTED",
        reason="FILLED",
        before=state,
        after=after,
        cash_delta=cash_delta,
        quantity_delta=quantity_delta,
    )


def replay_ledger(opening: PortfolioState, entries: tuple[LedgerEntry, ...]) -> PortfolioState:
    current = PortfolioState.model_validate(opening.model_dump(mode="python"))
    requests = set()
    for sequence, entry in enumerate(entries, 1):
        entry = LedgerEntry.model_validate(entry.model_dump(mode="python"))
        if entry.sequence != sequence or entry.request.request_id in requests:
            raise ValueError("A virtual ledger needs contiguous immutable unique order outcomes.")
        expected = evaluate_order(current, entry.request, entry.quote, entry.committed_at)
        if entry.evaluation != expected:
            raise ValueError("Stored virtual outcome differs from deterministic ledger replay.")
        requests.add(entry.request.request_id)
        current = expected.after
    return current
