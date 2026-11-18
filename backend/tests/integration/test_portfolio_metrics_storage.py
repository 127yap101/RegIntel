"""Owned read-only snapshot metrics using disposable fixed-price ledger fixtures."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.tests.integration.test_numerical_context_storage import snapshot
from backend.tests.integration.test_portfolio_fifo_storage import fifo as fifo
from backend.tests.integration.test_portfolio_storage import NOW
from backend.tests.integration.test_portfolio_storage import portfolio as portfolio
from regintel.auth.config import AuthSettings
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.db.migrations import connect_database
from regintel.main import create_app
from regintel.portfolio.repository import (
    PortfolioForbidden,
    PortfolioNotFound,
    PortfolioRepository,
    PortfolioUnavailable,
)
from regintel.portfolio.service import PortfolioService

pytestmark = pytest.mark.integration


def test_owned_prefix_metrics_select_one_clock_and_quote_per_valuation_without_writes(fifo):
    database, repository, quotes, user, _, opening, receipts = fifo
    quotes.price, quotes.version = "25.00", str(uuid4())
    instants = []

    def clock():
        at = NOW + timedelta(seconds=len(instants))
        instants.append(at)
        return at

    repository.clock = clock
    before, calls = snapshot(database), quotes.calls
    for version, count, result, expected in (
        (opening.account_id, 0, "0.00", "0.000000"),
        (receipts[0].entry.id, 1, "30.00", "0.030000"),
        (receipts[1].entry.id, 2, "45.00", "0.045000"),
        (receipts[2].entry.id, 3, "65.00", "0.065000"),
        (receipts[3].entry.id, 4, "55.00", "0.055000"),
        (receipts[4].entry.id, 5, "91.00", "0.091000"),
    ):
        data = repository.snapshot_metrics(user, version=version)
        value = data.valuation
        assert value.portfolio_version_id == version and value.committed_orders == count
        assert len(instants) == count + 1 and value.evaluated_at == instants[-1]
        assert data.simple_return.numerator == Decimal(result)
        assert data.simple_return.denominator == Decimal("100000.00")
        assert data.simple_return.percentage == Decimal(expected)
        assert data.allocation.denominator == value.total_value
        assert data.allocation.entries[0].numerator == value.cash_flow.cash
        assert value.input_entry_ids == tuple(item.entry.id for item in receipts[:count])
        if value.positions:
            assert data.allocation.entries[1].numerator == value.positions[0].market_value
            assert value.positions[0].quote.observed_at == value.evaluated_at - timedelta(minutes=1)
            assert value.quote_version_ids == (quotes.version,)
    assert quotes.calls == calls + 4 and snapshot(database) == before


def test_changed_quote_revalues_both_metrics_at_same_owned_prefix(fifo):
    database, repository, quotes, user, _, _, receipts = fifo
    before = snapshot(database)
    version = receipts[2].entry.id
    quotes.price, quotes.version = "25.00", str(uuid4())
    first = repository.snapshot_metrics(user, version=version)
    quotes.price, quotes.version = "50.00", str(uuid4())
    second = repository.snapshot_metrics(user, version=version)
    assert first.simple_return.percentage == Decimal("0.065000")
    assert second.simple_return.percentage == Decimal("0.090000")
    assert second.allocation.denominator == Decimal("100090.00")
    assert second.allocation.entries[1].numerator == Decimal("50.00")
    assert second.allocation.entries[1].percentage == Decimal("0.049955")
    assert first.valuation.input_entry_ids == second.valuation.input_entry_ids
    assert (
        first.valuation.execution_quote_version_ids == second.valuation.execution_quote_version_ids
    )
    assert first.valuation.quote_version_ids != second.valuation.quote_version_ids
    assert snapshot(database) == before


def test_unavailable_provider_and_budget_failure_never_emit_partial_ratios(fifo, monkeypatch):
    database, _, quotes, user, _, opening, _ = fifo
    repository = PortfolioRepository(database, clock=lambda: NOW)
    before, calls = snapshot(database), quotes.calls
    data = repository.snapshot_metrics(user)
    assert data.valuation.cash_flow.cash == Decimal("100041.00")
    assert data.simple_return.state == data.allocation.state == "QUOTES_UNAVAILABLE"
    assert data.simple_return.percentage is data.allocation.denominator is None
    assert data.allocation.entries == ()
    assert (
        repository.snapshot_metrics(user, version=opening.account_id).simple_return.percentage == 0
    )
    monkeypatch.setattr("regintel.portfolio.repository.MAX_ANALYTICS_BYTES", 0)
    budget = repository.snapshot_metrics(user)
    assert budget.simple_return.state == budget.allocation.state == "LEDGER_BUDGET_EXCEEDED"
    assert budget.valuation.cash_flow is budget.simple_return.percentage is None
    assert budget.allocation.entries == ()
    assert snapshot(database) == before and quotes.calls == calls


def test_foreign_unknown_revoked_and_naive_clock_fail_before_quotes(fifo):
    database, repository, quotes, user, peer, _, receipts = fifo
    calls = quotes.calls
    for owner, version in ((peer, receipts[-1].entry.id), (user, str(uuid4()))):
        with pytest.raises(PortfolioNotFound):
            repository.snapshot_metrics(owner, version=version)
    with pytest.raises(PortfolioForbidden):
        repository.snapshot_metrics(replace(user, auth_version=user.auth_version + 1))
    repository.clock = lambda: NOW.replace(tzinfo=None)
    with pytest.raises(PortfolioUnavailable, match="timezone"):
        repository.snapshot_metrics(user)
    with connect_database(database) as connection:
        connection.execute("UPDATE regintel.users SET is_active=false WHERE id=%s", (user.id,))
    with pytest.raises(PortfolioForbidden):
        repository.snapshot_metrics(user)
    assert quotes.calls == calls


def test_metrics_http_is_versioned_owned_and_keeps_legacy_valuation_exact(fifo, monkeypatch):
    database, repository, quotes, user, peer, opening, receipts = fifo
    quotes.price, quotes.version, quotes.same_id = "25.00", str(uuid4()), str(uuid4())
    settings = AuthSettings(jwt_secret=SecretStr("bc" * 32))
    auth = AuthService(PostgreSQLAuthRepository(database), settings)
    before = snapshot(database)
    selected = []
    original = repository.valuation

    def valuation(owner, *, version=None):
        selected.append((owner.id, version))
        return original(owner, version=version)

    monkeypatch.setattr(repository, "valuation", valuation)
    with TestClient(
        create_app(auth_service=auth, portfolio_service=PortfolioService(repository, None))
    ) as client:
        headers = {"Authorization": "Bearer " + issue_token(user, settings)}
        foreign = {"Authorization": "Bearer " + issue_token(peer, settings)}
        suffix = "?portfolio_version_id=" + receipts[2].entry.id
        target = "/v1/portfolio/metrics" + suffix
        assert client.get(target).status_code == 401
        assert client.get(target, headers=foreign).status_code == 404
        calls, reads = quotes.calls, len(selected)
        response = client.get(target, headers=headers)
        assert response.status_code == 200
        assert quotes.calls == calls + 1 and len(selected) == reads + 1
        body = response.json()
        assert body["data"]["schema_version"] == "portfolio-snapshot-metrics-1"
        assert body["data"]["simple_return"]["percentage"] == "0.065000"
        assert body["data"]["simple_return"]["denominator"] == "100000.00"
        assert body["data"]["allocation"]["entries"][1]["percentage"] == "0.024984"
        assert body["meta"]["versions"]["portfolio_version_id"] == receipts[2].entry.id
        assert body["meta"]["versions"]["quote_version_id"] == quotes.version
        assert body["meta"]["versions"]["corpus_version_id"] is None
        legacy = client.get("/v1/portfolio/valuation" + suffix, headers=headers)
        assert legacy.status_code == 200 and legacy.json()["data"] == body["data"]["valuation"]
        cash = client.get(
            "/v1/portfolio/metrics?portfolio_version_id=" + opening.account_id, headers=headers
        )
        assert cash.status_code == 200
        assert cash.json()["data"]["simple_return"]["percentage"] == "0.000000"
        assert cash.json()["meta"]["versions"]["quote_version_id"] is None
        assert (
            client.get(
                "/v1/portfolio/metrics?portfolio_version_id=invalid", headers=headers
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/v1/portfolio/metrics?portfolio_version_id=" + str(uuid4()), headers=headers
            ).status_code
            == 404
        )
        quotes.failure = True
        failure = client.get(target, headers=headers)
        assert failure.status_code == 503 and "private diagnostic" not in failure.text
    assert snapshot(database) == before


def test_metrics_read_does_not_create_an_account(portfolio):
    database, repository, quotes, user, _ = portfolio
    before, calls = snapshot(database), quotes.calls
    with pytest.raises(PortfolioNotFound):
        repository.snapshot_metrics(user)
    assert snapshot(database) == before and quotes.calls == calls
