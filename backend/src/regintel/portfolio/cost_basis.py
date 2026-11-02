"""FIFO purchase-cost allocation over already replay-verified virtual executions."""

from collections import deque
from dataclasses import dataclass
from decimal import Decimal, localcontext

from regintel.portfolio.models import LedgerEntry


@dataclass(frozen=True)
class FifoPosition:
    quantity: int
    realized_cost_basis: Decimal
    remaining_cost_basis: Decimal


def fifo_positions(entries: tuple[LedgerEntry, ...]) -> dict[str, FifoPosition]:
    """Consume oldest executed purchases, using committed prices without division."""
    lots: dict[str, deque[tuple[int, Decimal]]] = {}
    allocated: dict[str, Decimal] = {}
    with localcontext() as calculation:
        calculation.prec = 512
        for entry in entries:
            if entry.evaluation.state != "EXECUTED":
                continue
            if entry.quote is None:
                raise ValueError("Executed cost allocation requires its committed quote.")
            identity = entry.request.company_id
            queue = lots.setdefault(identity, deque())
            allocated.setdefault(identity, Decimal("0.00"))
            if entry.request.side == "BUY":
                queue.append((entry.request.quantity, entry.quote.price))
                continue
            remaining = entry.request.quantity
            while remaining:
                if not queue:
                    raise ValueError("An executed sale cannot exceed its purchased FIFO lots.")
                quantity, price = queue.popleft()
                consumed = min(remaining, quantity)
                allocated[identity] += price * Decimal(consumed)
                remaining -= consumed
                if quantity > consumed:
                    queue.appendleft((quantity - consumed, price))
        return {
            identity: FifoPosition(
                quantity=sum(quantity for quantity, _ in queue),
                realized_cost_basis=allocated[identity],
                remaining_cost_basis=sum(
                    (price * Decimal(quantity) for quantity, price in queue), Decimal("0.00")
                ),
            )
            for identity, queue in lots.items()
        }
