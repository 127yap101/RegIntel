"""M4 virtual accounts and atomic immutable order outcomes; balances derive from the ledger."""

import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

import psycopg

from regintel.auth.types import User
from regintel.db.config import DatabaseSettings
from regintel.db.migrations import DatabaseConnection, MigrationError, connect_database
from regintel.entities.models import canonical_bytes
from regintel.portfolio.engine import evaluate_order
from regintel.portfolio.models import (
    Holding,
    LedgerEntry,
    LedgerPage,
    OrderReceipt,
    OrderRequest,
    PortfolioAccount,
    QuoteSnapshot,
)


class PortfolioError(ValueError):
    """Module-owned fixed diagnostics without submitted payloads or storage secrets."""


class PortfolioForbidden(PortfolioError):
    pass


class PortfolioConflict(PortfolioError):
    pass


class PortfolioNotFound(PortfolioError):
    pass


class PortfolioUnavailable(PortfolioError):
    pass


class QuoteProvider(Protocol):
    def snapshot(self, company_id: str, at: datetime) -> QuoteSnapshot | None: ...


class UnavailableQuotes:
    def snapshot(self, company_id: str, at: datetime) -> QuoteSnapshot | None:
        return None


def _now() -> datetime:
    return datetime.now(UTC)


def _checked(value: object, sha: object) -> bytes:
    if not isinstance(value, (bytes, memoryview)):
        raise PortfolioUnavailable("The virtual ledger payload is unavailable.")
    body = bytes(value)
    if not 0 < len(body) <= 32768 or hashlib.sha256(body).hexdigest() != sha:
        raise PortfolioUnavailable("The virtual ledger fingerprint differs.")
    return body


class PortfolioRepository:
    def __init__(
        self,
        database: DatabaseSettings,
        *,
        quotes: QuoteProvider | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.database, self.quotes, self.clock = database, quotes or UnavailableQuotes(), clock

    @contextmanager
    def transaction(self, user: User) -> Iterator[DatabaseConnection]:
        try:
            with connect_database(self.database) as connection, connection.transaction():
                row = connection.execute(
                    "SELECT role,is_active,auth_version FROM regintel.users WHERE id=%s FOR SHARE",
                    (user.id,),
                ).fetchone()
                if row != (user.role, True, user.auth_version):
                    raise PortfolioForbidden("A current virtual-account owner is required.")
                yield connection
        except PortfolioError:
            raise
        except (
            psycopg.OperationalError,
            psycopg.InterfaceError,
            MigrationError,
            psycopg.errors.UndefinedTable,
        ):
            raise PortfolioUnavailable("Virtual portfolio storage is unavailable.") from None
        except (psycopg.Error, ValueError, OSError):
            raise PortfolioConflict("The virtual order or ledger result conflicts.") from None

    def _account(self, connection: DatabaseConnection, user: User) -> str:
        row = connection.execute(
            "SELECT id FROM regintel.portfolio_accounts WHERE owner_id=%s FOR UPDATE",
            (user.id,),
        ).fetchone()
        if row is None:
            raise PortfolioNotFound("Create your virtual account before submitting an order.")
        return str(row[0])

    def _state(self, connection: DatabaseConnection, identity: str) -> PortfolioAccount:
        row = connection.execute(
            "SELECT a.opening_cash+coalesce(sum(o.cash_delta),0),count(o.id) "
            "FROM regintel.portfolio_accounts a "
            "LEFT JOIN regintel.portfolio_orders o ON o.account_id=a.id "
            "WHERE a.id=%s GROUP BY a.id,a.opening_cash",
            (UUID(identity),),
        ).fetchone()
        assert row is not None
        holdings = connection.execute(
            "SELECT company_id,sum(quantity_delta)::bigint FROM regintel.portfolio_orders "
            "WHERE account_id=%s GROUP BY company_id "
            "HAVING sum(quantity_delta)>0 ORDER BY company_id",
            (UUID(identity),),
        ).fetchall()
        last = connection.execute(
            "SELECT id FROM regintel.portfolio_orders WHERE account_id=%s "
            "ORDER BY sequence DESC LIMIT 1",
            (UUID(identity),),
        ).fetchone()
        return PortfolioAccount.model_validate(
            {
                "account_id": identity,
                "portfolio_version_id": str(last[0]) if last else identity,
                "state": {
                    "cash": row[0],
                    "holdings": [
                        Holding.model_validate({"company_id": str(h[0]), "quantity": h[1]})
                        for h in holdings
                    ],
                },
                "committed_orders": row[1],
            }
        )

    def create(self, user: User) -> PortfolioAccount:
        with self.transaction(user) as connection:
            connection.execute(
                "INSERT INTO regintel.portfolio_accounts(id,owner_id,opening_cash,auth_version) "
                "VALUES (%s,%s,100000.00,%s) ON CONFLICT(owner_id) DO NOTHING",
                (uuid4(), user.id, user.auth_version),
            )
            return self._state(connection, self._account(connection, user))

    def account(self, user: User) -> PortfolioAccount:
        with self.transaction(user) as connection:
            return self._state(connection, self._account(connection, user))

    def submit(self, request: OrderRequest, user: User) -> OrderReceipt:
        request = OrderRequest.model_validate(request.model_dump(mode="python"))
        request_bytes = canonical_bytes(request)
        with self.transaction(user) as connection:
            account_id = self._account(connection, user)
            existing = connection.execute(
                "SELECT request_bytes,request_sha256,entry_bytes,entry_sha256 "
                "FROM regintel.portfolio_orders WHERE account_id=%s AND request_id=%s",
                (UUID(account_id), UUID(request.request_id)),
            ).fetchone()
            if existing is not None:
                if _checked(existing[0], existing[1]) != request_bytes:
                    raise PortfolioConflict(
                        "The request key already belongs to another virtual order."
                    )
                entry = LedgerEntry.model_validate_json(_checked(existing[2], existing[3]))
                return OrderReceipt(
                    account_id=account_id, portfolio_version_id=entry.id, entry=entry
                )
            current = self._state(connection, account_id)
            if current.committed_orders >= 1000000:
                raise PortfolioConflict("The virtual pilot ledger is at its explicit order bound.")
            at = self.clock()
            try:
                quote = self.quotes.snapshot(request.company_id, at)
            except Exception:
                raise PortfolioUnavailable(
                    "The configured quote snapshot source is unavailable."
                ) from None
            evaluation = evaluate_order(current.state, request, quote, at)
            entry = LedgerEntry(
                id=str(uuid4()),
                sequence=current.committed_orders + 1,
                request=request,
                quote=quote,
                committed_at=at,
                evaluation=evaluation,
            )
            if quote is not None:
                body = canonical_bytes(quote)
                connection.execute(
                    "INSERT INTO regintel.portfolio_quote_snapshots "
                    "(id,quote_bytes,quote_sha256,price,company_id,stored_by,auth_version) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                    (
                        UUID(quote.id),
                        body,
                        hashlib.sha256(body).hexdigest(),
                        quote.price,
                        UUID(quote.company_id),
                        user.id,
                        user.auth_version,
                    ),
                )
                actual = connection.execute(
                    "SELECT quote_bytes,quote_sha256 "
                    "FROM regintel.portfolio_quote_snapshots WHERE id=%s",
                    (UUID(quote.id),),
                ).fetchone()
                if actual is None or _checked(actual[0], actual[1]) != body:
                    raise PortfolioConflict(
                        "The quote snapshot identity already belongs to other source bytes."
                    )
            payload = canonical_bytes(entry)
            connection.execute(
                "INSERT INTO regintel.portfolio_orders "
                "(id,account_id,sequence,request_id,company_id,request_bytes,request_sha256,"
                "entry_bytes,entry_sha256,"
                "quote_id,state,cash_delta,quantity_delta,cash_after,submitted_by,"
                "auth_version,committed_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    UUID(entry.id),
                    UUID(account_id),
                    entry.sequence,
                    UUID(request.request_id),
                    UUID(request.company_id),
                    request_bytes,
                    hashlib.sha256(request_bytes).hexdigest(),
                    payload,
                    hashlib.sha256(payload).hexdigest(),
                    UUID(quote.id) if quote else None,
                    evaluation.state,
                    evaluation.cash_delta,
                    evaluation.quantity_delta,
                    evaluation.after.cash,
                    user.id,
                    user.auth_version,
                    at,
                ),
            )
            return OrderReceipt(account_id=account_id, portfolio_version_id=entry.id, entry=entry)

    def ledger(self, user: User, *, offset: int = 0, limit: int = 50) -> LedgerPage:
        if (
            type(offset) is not int
            or type(limit) is not int
            or not 0 <= offset <= 1000000
            or not 1 <= limit <= 100
        ):
            raise PortfolioConflict("Select a bounded ledger page.")
        with self.transaction(user) as connection:
            identity = self._account(connection, user)
            account = self._state(connection, identity)
            rows = connection.execute(
                "SELECT entry_bytes,entry_sha256 FROM regintel.portfolio_orders "
                "WHERE account_id=%s "
                "ORDER BY sequence OFFSET %s LIMIT %s",
                (UUID(identity), offset, limit),
            ).fetchall()
            return LedgerPage(
                account_id=identity,
                portfolio_version_id=account.portfolio_version_id,
                entries=tuple(
                    LedgerEntry.model_validate_json(_checked(row[0], row[1])) for row in rows
                ),
                total=account.committed_orders,
                offset=offset,
            )
