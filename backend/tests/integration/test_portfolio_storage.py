"""Fixed-price PostgreSQL virtual acceptance fixtures; no real quotes, money or trading."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import SecretStr

from backend.tests.integration.test_numerical_context_storage import snapshot
from backend.tests.test_published_reads import fixture_service
from regintel.auth.config import AuthSettings
from regintel.auth.repository import PostgreSQLAuthRepository, seed_users
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.auth.types import SeedAccount
from regintel.config import Settings
from regintel.db.migrations import connect_database
from regintel.main import create_app
from regintel.portfolio.engine import evaluate_order, replay_ledger
from regintel.portfolio.models import OrderRequest, QuoteSnapshot
from regintel.portfolio.repository import (
    PortfolioConflict,
    PortfolioForbidden,
    PortfolioRepository,
    PortfolioUnavailable,
)
from regintel.portfolio.service import PortfolioService

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 23, 6, tzinfo=UTC)
COMPANY, CORPUS = str(uuid4()), str(uuid4())


class FixedQuotes:
    def __init__(self):
        self.calls = 0
        self.failure = False
        self.price = "10.10"
        self.same_id = None
        self.version = str(uuid4())

    def snapshot(self, company_id, at):
        self.calls += 1
        if self.failure:
            raise RuntimeError("Authored provider outage; private diagnostic.")
        return QuoteSnapshot(
            id=self.same_id or str(uuid4()),
            quote_version_id=self.version,
            company_id=company_id,
            price=self.price,
            observed_at=at - timedelta(minutes=1),
            expires_at=at + timedelta(minutes=1),
            source="Fixed-price engineering acceptance fixture",
            source_kind="ENGINEERING_FIXTURE",
        )


@pytest.fixture
def portfolio(auth_database):
    seed_users(
        auth_database,
        (
            SeedAccount("learner", SecretStr("Authored virtual learner!"), "learner"),
            SeedAccount("peer", SecretStr("Authored virtual peer!"), "learner"),
        ),
    )
    accounts = PostgreSQLAuthRepository(auth_database)
    user, peer = accounts.get_by_username("learner"), accounts.get_by_username("peer")
    assert user is not None and peer is not None
    quotes = FixedQuotes()
    repository = PortfolioRepository(auth_database, quotes=quotes, clock=lambda: NOW)
    return auth_database, repository, quotes, user, peer


def order(side="BUY", quantity=3, **changes):
    values = dict(
        request_id=str(uuid4()),
        corpus_version_id=CORPUS,
        company_id=COMPANY,
        side=side,
        quantity=quantity,
    )
    values.update(changes)
    return OrderRequest.model_validate(values)


def test_virtual_opening_credit_is_once_per_owner_and_accounts_are_private(portfolio):
    database, repository, _, user, peer = portfolio
    first = repository.create(user)
    assert first == repository.create(user)
    assert first.state.cash == Decimal("100000.00") and first.committed_orders == 0
    assert first.portfolio_version_id == first.account_id
    other = repository.create(peer)
    assert first.account_id != other.account_id
    repository.submit(order(), user)
    assert repository.account(peer) == other and repository.ledger(peer).entries == ()
    with connect_database(database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM regintel.portfolio_accounts"
        ).fetchone() == (2,)


def test_buy_partial_sell_final_sell_replay_and_decimal_json(portfolio):
    _, repository, _, user, _ = portfolio
    opening = repository.create(user)
    receipts = [
        repository.submit(request, user)
        for request in (order(quantity=3), order("SELL", 1), order("SELL", 2))
    ]
    assert all(receipt.entry.evaluation.state == "EXECUTED" for receipt in receipts)
    assert receipts[0].entry.evaluation.after.cash == Decimal("99969.70")
    assert receipts[1].entry.evaluation.after.cash == Decimal("99979.80")
    assert repository.account(user).state == opening.state
    ledger = repository.ledger(user)
    assert replay_ledger(opening.state, ledger.entries) == opening.state
    assert ledger.portfolio_version_id == receipts[-1].entry.id
    assert receipts[0].model_dump(mode="json")["entry"]["evaluation"]["cash_delta"] == "-30.30"
    assert repository.ledger(user, offset=1, limit=1).entries == (ledger.entries[1],)
    before = snapshot(repository.database)
    analytics = repository.analytics(user)
    assert analytics.portfolio_version_id == ledger.portfolio_version_id
    assert analytics.summary.buy_spend == analytics.summary.sale_proceeds == Decimal("30.30")
    assert analytics.companies[0].closed_position_result == Decimal("0.00")
    assert analytics.input_entry_ids == tuple(entry.id for entry in ledger.entries)
    assert snapshot(repository.database) == before


@pytest.mark.parametrize(
    "side,quantity,reason",
    [("BUY", 10000, "INSUFFICIENT_CASH"), ("SELL", 1, "INSUFFICIENT_HOLDINGS")],
)
def test_insufficient_cash_and_oversell_have_one_immutable_rejected_outcome(
    portfolio, side, quantity, reason
):
    _, repository, quotes, user, _ = portfolio
    opening = repository.create(user)
    request = order(side, quantity)
    first = repository.submit(request, user)
    assert first.entry.evaluation.reason == reason and first.entry.evaluation.after == opening.state
    assert repository.submit(request, user) == first and quotes.calls == 1
    assert repository.account(user).committed_orders == 1


def test_missing_quotes_never_create_a_price_or_move_balances(portfolio):
    database, _, _, user, _ = portfolio
    repository = PortfolioRepository(database, clock=lambda: NOW)
    opening = repository.create(user)
    request = order()
    result = repository.submit(request, user)
    assert result.entry.quote is None and result.entry.evaluation.reason == "QUOTES_UNAVAILABLE"
    assert result.entry.evaluation.after == opening.state
    assert repository.submit(request, user) == result
    with connect_database(database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM regintel.portfolio_quote_snapshots"
        ).fetchone() == (0,)


def test_duplicate_key_and_conflicting_retry_do_not_execute_twice(portfolio):
    database, repository, quotes, user, _ = portfolio
    repository.create(user)
    request = order()
    first = repository.submit(request, user)
    before = snapshot(database)
    assert repository.submit(request, user) == first
    with pytest.raises(PortfolioConflict):
        repository.submit(request.model_copy(update={"quantity": 4}), user)
    assert snapshot(database) == before and quotes.calls == 1


def test_reusing_quote_identity_with_changed_price_rolls_back_order(portfolio):
    database, repository, quotes, user, _ = portfolio
    repository.create(user)
    quotes.same_id = str(uuid4())
    repository.submit(order(), user)
    before = snapshot(database)
    quotes.price = "20.20"
    with pytest.raises(PortfolioConflict):
        repository.submit(order(), user)
    assert snapshot(database) == before
    assert repository.account(user).committed_orders == 1


def test_concurrent_duplicate_request_commits_one_exact_result(portfolio):
    _, repository, quotes, user, _ = portfolio
    repository.create(user)
    request = order()
    with ThreadPoolExecutor(max_workers=2) as workers:
        calls = [workers.submit(repository.submit, request, user) for _ in range(2)]
        results = [call.result(timeout=30) for call in calls]
    assert results[0] == results[1] and quotes.calls == 1
    assert repository.account(user).committed_orders == 1


def test_concurrent_conflicting_spend_serializes_against_actual_cash(portfolio):
    _, repository, _, user, _ = portfolio
    opening = repository.create(user)
    with ThreadPoolExecutor(max_workers=2) as workers:
        calls = [workers.submit(repository.submit, order(quantity=6000), user) for _ in range(2)]
        results = [call.result(timeout=30) for call in calls]
    assert sorted(result.entry.evaluation.state for result in results) == ["EXECUTED", "REJECTED"]
    assert repository.account(user).state.cash == Decimal("39400.00")
    assert (
        replay_ledger(opening.state, repository.ledger(user).entries)
        == repository.account(user).state
    )


def test_provider_failure_rolls_back_and_retry_can_commit_once(portfolio):
    database, repository, quotes, user, _ = portfolio
    repository.create(user)
    request = order()
    quotes.failure = True
    before = snapshot(database)
    with pytest.raises(PortfolioUnavailable, match="snapshot source"):
        repository.submit(request, user)
    assert snapshot(database) == before
    quotes.failure = False
    first = repository.submit(request, user)
    assert (
        repository.submit(request, user) == first and repository.account(user).committed_orders == 1
    )


@pytest.mark.parametrize("change", ["cash", "quantity"])
def test_database_conservation_gate_rejects_corrupted_application_outcome(
    portfolio, monkeypatch, change
):
    database, repository, _, user, _ = portfolio
    repository.create(user)
    before = snapshot(database)

    def corrupted(*args):
        result = evaluate_order(*args)
        return (
            result.model_copy(update={"cash_delta": Decimal("0.00")})
            if change == "cash"
            else result.model_copy(update={"quantity_delta": 100})
        )

    monkeypatch.setattr("regintel.portfolio.repository.evaluate_order", corrupted)
    with pytest.raises(PortfolioConflict):
        repository.submit(order(), user)
    assert snapshot(database) == before


@pytest.mark.parametrize("change", ["forged", "stale", "inactive"])
def test_current_virtual_owner_is_rechecked(portfolio, change):
    database, repository, _, user, _ = portfolio
    repository.create(user)
    candidate = (
        replace(user, role="admin")
        if change == "forged"
        else replace(user, auth_version=2)
        if change == "stale"
        else user
    )
    if change == "inactive":
        with connect_database(database) as connection:
            connection.execute("UPDATE regintel.users SET is_active=false WHERE id=%s", (user.id,))
    before = snapshot(database)
    with pytest.raises(PortfolioForbidden):
        repository.submit(order(), candidate)
    assert snapshot(database) == before


@pytest.mark.parametrize(
    "table", ["portfolio_accounts", "portfolio_quote_snapshots", "portfolio_orders"]
)
@pytest.mark.parametrize("action", ["UPDATE", "DELETE", "TRUNCATE"])
def test_virtual_history_is_append_only(portfolio, table, action):
    database, repository, _, user, _ = portfolio
    repository.create(user)
    repository.submit(order(), user)
    before = snapshot(database)
    with pytest.raises(psycopg.Error), connect_database(database) as connection:
        statement = (
            sql.SQL("UPDATE regintel.{} SET id=id")
            if action == "UPDATE"
            else sql.SQL("DELETE FROM regintel.{}")
            if action == "DELETE"
            else sql.SQL("TRUNCATE regintel.{} CASCADE")
        )
        connection.execute(statement.format(sql.Identifier(table)))
    assert snapshot(database) == before


def test_virtual_http_uses_published_company_and_rejects_client_financial_fields(
    portfolio, tmp_path
):
    database, _, _, user, peer = portfolio
    repository = PortfolioRepository(database, clock=lambda: NOW)
    reads, memory, _, _ = fixture_service(tmp_path)
    company = memory.manifest.observations[0].subject_entity_id
    settings = AuthSettings(jwt_secret=SecretStr("ef" * 32))
    auth = AuthService(PostgreSQLAuthRepository(database), settings)
    with TestClient(
        create_app(
            Settings(environment="test"),
            auth_service=auth,
            portfolio_service=PortfolioService(repository, reads),
        )
    ) as client:
        headers = {"Authorization": "Bearer " + issue_token(user, settings)}
        assert client.get("/v1/portfolio").status_code == 401
        assert (
            client.post(
                "/v1/portfolio/accounts", json={"opening_cash": "9000000"}, headers=headers
            ).status_code
            == 422
        )
        account = client.post("/v1/portfolio/accounts", json={}, headers=headers)
        assert account.status_code == 200 and account.json()["data"]["state"]["cash"] == "100000.00"
        request = order(company_id=company, corpus_version_id=memory.manifest.id).model_dump(
            mode="json"
        )
        assert (
            client.post(
                "/v1/portfolio/orders", json=request | {"price": "0.01"}, headers=headers
            ).status_code
            == 422
        )
        receipt = client.post("/v1/portfolio/orders", json=request, headers=headers)
        assert (
            receipt.status_code == 200
            and receipt.json()["data"]["entry"]["evaluation"]["reason"] == "QUOTES_UNAVAILABLE"
        )
        assert receipt.json()["meta"]["versions"]["corpus_version_id"] == memory.manifest.id
        assert (
            receipt.json()["meta"]["versions"]["portfolio_version_id"]
            == receipt.json()["data"]["entry"]["id"]
        )
        assert (
            client.post("/v1/portfolio/orders", json=request, headers=headers).json()["data"]
            == receipt.json()["data"]
        )
        bad = request | {"request_id": str(uuid4()), "company_id": str(uuid4())}
        assert client.post("/v1/portfolio/orders", json=bad, headers=headers).status_code == 404
        assert client.get("/v1/quotes", headers=headers).json()["data"]["state"] == "UNAVAILABLE"
        assert client.get("/v1/portfolio/ledger", headers=headers).json()["data"]["total"] == 1
        before = snapshot(database)
        analytics = client.get("/v1/portfolio/analytics", headers=headers)
        assert analytics.status_code == 200
        assert analytics.json()["data"]["summary"]["rejected_orders"] == 1
        assert (
            analytics.json()["meta"]["versions"]["portfolio_version_id"]
            == receipt.json()["data"]["entry"]["id"]
        )
        assert client.get("/v1/portfolio/analytics").status_code == 401
        assert (
            client.get(
                "/v1/portfolio/analytics",
                headers={"Authorization": "Bearer " + issue_token(peer, settings)},
            ).status_code
            == 404
        )
        assert snapshot(database) == before
        assert (
            client.get(
                "/v1/portfolio", headers={"Authorization": "Bearer " + issue_token(peer, settings)}
            ).status_code
            == 404
        )
