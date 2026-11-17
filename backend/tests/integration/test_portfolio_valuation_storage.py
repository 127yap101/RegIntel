"""Owned fixed-price valuation reads; no market dataset or runtime provider is enabled."""

from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.tests.integration.test_numerical_context_storage import snapshot
from backend.tests.integration.test_portfolio_fifo_storage import fifo as fifo
from backend.tests.integration.test_portfolio_storage import NOW, order
from backend.tests.integration.test_portfolio_storage import portfolio as portfolio
from regintel.auth.config import AuthSettings
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.db.migrations import connect_database
from regintel.main import create_app
from regintel.portfolio.repository import (
    PortfolioConflict,
    PortfolioForbidden,
    PortfolioNotFound,
    PortfolioRepository,
    PortfolioUnavailable,
)
from regintel.portfolio.service import PortfolioService

pytestmark = pytest.mark.integration


def test_each_owned_ledger_prefix_uses_current_snapshot_and_never_writes_ledger_or_quotes(fifo):
    database, repository, quotes, user, _, opening, receipts = fifo
    quotes.price, quotes.version = "25.00", str(uuid4())
    before, calls = snapshot(database), quotes.calls
    for version, count, cash, value, unrealized, result in (
        (opening.account_id, 0, "100000.00", "0.00", "0.00", "0.00"),
        (receipts[0].entry.id, 1, "99980.00", "50.00", "30.00", "30.00"),
        (receipts[1].entry.id, 2, "99920.00", "125.00", "45.00", "45.00"),
        (receipts[2].entry.id, 3, "100040.00", "25.00", "5.00", "65.00"),
        (receipts[3].entry.id, 4, "100055.00", "0.00", "0.00", "55.00"),
        (receipts[4].entry.id, 5, "100041.00", "50.00", "36.00", "91.00"),
    ):
        actual = repository.valuation(user, version=version)
        assert actual.state == "AVAILABLE" and actual.evaluated_at == NOW
        assert actual.portfolio_version_id == version and actual.committed_orders == count
        assert actual.cash_flow.cash == Decimal(cash)
        assert actual.market_value == Decimal(value)
        assert actual.total_value == Decimal(cash) + Decimal(value)
        assert actual.unrealized_result == Decimal(unrealized)
        assert actual.total_result == Decimal(result)
        assert actual.input_entry_ids == tuple(receipt.entry.id for receipt in receipts[:count])
        assert actual.quote_version_ids == ((quotes.version,) if actual.positions else ())
        assert quotes.version not in actual.execution_quote_version_ids
    assert quotes.calls == calls + 4
    assert snapshot(database) == before


def test_unavailable_provider_does_not_reuse_execution_prices_for_remaining_holdings(fifo):
    database, _, _, user, _, opening, receipts = fifo
    repository = PortfolioRepository(database, clock=lambda: NOW)
    before = snapshot(database)
    current = repository.valuation(user)
    assert current.state == "QUOTES_UNAVAILABLE" and current.total_value is None
    assert current.market_value is current.unrealized_result is current.total_result is None
    assert current.cash_flow.cash == Decimal("100041.00")
    assert current.cash_flow.realized_result == Decimal("55.00")
    assert current.positions[0].state == "MISSING_QUOTE"
    assert current.quote_version_ids == ()
    assert current.execution_quote_version_ids == (receipts[0].entry.quote.quote_version_id,)
    assert repository.valuation(user, version=opening.account_id).total_value == Decimal(
        "100000.00"
    )
    assert repository.valuation(user, version=receipts[3].entry.id).total_value == Decimal(
        "100055.00"
    )
    assert snapshot(database) == before


def test_foreign_unknown_and_revoked_account_reads_fail_before_selecting_prices(fifo):
    database, repository, quotes, user, peer, _, receipts = fifo
    calls = quotes.calls
    for owner, version in ((peer, receipts[-1].entry.id), (user, str(uuid4()))):
        with pytest.raises(PortfolioNotFound):
            repository.valuation(owner, version=version)
    with pytest.raises(PortfolioForbidden):
        repository.valuation(replace(user, auth_version=user.auth_version + 1))
    assert quotes.calls == calls
    with connect_database(database) as connection:
        connection.execute("UPDATE regintel.users SET is_active=false WHERE id=%s", (user.id,))
    with pytest.raises(PortfolioForbidden):
        repository.valuation(user)
    assert quotes.calls == calls


def test_existing_quote_identity_cannot_be_redefined_by_a_valuation_read(fifo):
    database, repository, quotes, user, _, _, receipts = fifo
    quotes.same_id = receipts[-1].entry.quote.id
    quotes.price = "7.00"
    before = snapshot(database)
    assert repository.valuation(user).market_value == Decimal("14.00")
    quotes.price = "8.00"
    with pytest.raises(PortfolioConflict):
        repository.valuation(user)
    assert snapshot(database) == before


def test_budget_failure_does_not_read_prices_or_return_partial_values(fifo, monkeypatch):
    database, repository, quotes, user, _, _, _ = fifo
    monkeypatch.setattr("regintel.portfolio.repository.MAX_ANALYTICS_BYTES", 0)
    before, calls = snapshot(database), quotes.calls
    result = repository.valuation(user)
    assert result.state == "LEDGER_BUDGET_EXCEEDED"
    assert result.total_value is result.cash_flow is None
    assert result.positions == result.input_entry_ids == result.quote_version_ids == ()
    assert snapshot(database) == before and quotes.calls == calls


def test_provider_failure_is_sanitized_and_does_not_change_any_retained_state(fifo):
    database, repository, quotes, user, _, _, _ = fifo
    before = snapshot(database)
    quotes.failure = True
    with pytest.raises(PortfolioUnavailable, match="source is unavailable") as caught:
        repository.valuation(user)
    assert "private diagnostic" not in str(caught.value)
    assert snapshot(database) == before


def test_valuation_http_has_owned_version_decimal_strings_and_read_only_behavior(fifo):
    database, repository, quotes, user, peer, opening, receipts = fifo
    quotes.price, quotes.version = "25.00", str(uuid4())
    settings = AuthSettings(jwt_secret=SecretStr("be" * 32))
    auth = AuthService(PostgreSQLAuthRepository(database), settings)
    before = snapshot(database)
    with TestClient(
        create_app(auth_service=auth, portfolio_service=PortfolioService(repository, None))
    ) as client:
        headers = {"Authorization": "Bearer " + issue_token(user, settings)}
        foreign = {"Authorization": "Bearer " + issue_token(peer, settings)}
        target = "/v1/portfolio/valuation?portfolio_version_id=" + receipts[2].entry.id
        assert client.get(target).status_code == 401
        assert client.get(target, headers=foreign).status_code == 404
        response = client.get(target, headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["market_value"] == "25.00"
        assert body["data"]["total_value"] == "100065.00"
        assert body["data"]["unrealized_result"] == "5.00"
        assert body["data"]["total_result"] == "65.00"
        assert body["data"]["evaluated_at"] == "2026-10-23T06:00:00Z"
        assert body["data"]["positions"][0]["quote"]["source_kind"] == "ENGINEERING_FIXTURE"
        assert body["meta"]["versions"]["portfolio_version_id"] == receipts[2].entry.id
        assert body["meta"]["versions"]["quote_version_id"] == quotes.version
        assert body["meta"]["versions"]["corpus_version_id"] is None
        opening_response = client.get(
            "/v1/portfolio/valuation?portfolio_version_id=" + opening.account_id, headers=headers
        )
        assert opening_response.json()["data"]["total_value"] == "100000.00"
        assert opening_response.json()["meta"]["versions"]["quote_version_id"] is None
        assert (
            client.get(
                "/v1/portfolio/valuation?portfolio_version_id=invalid", headers=headers
            ).status_code
            == 422
        )
        quotes.failure = True
        failed = client.get(target, headers=headers)
        assert failed.status_code == 503 and "private diagnostic" not in failed.text
    assert snapshot(database) == before


def test_valuation_is_unavailable_until_account_creation_and_rejected_orders_keep_cash(portfolio):
    (
        database,
        _,
        _,
        user,
        _,
    ) = portfolio
    repository = PortfolioRepository(database, clock=lambda: NOW)
    with pytest.raises(PortfolioNotFound):
        repository.valuation(user)
    repository.create(user)
    receipt = repository.submit(order(), user)
    assert receipt.entry.evaluation.reason == "QUOTES_UNAVAILABLE"
    before = snapshot(database)
    value = repository.valuation(user)
    assert value.total_value == Decimal("100000.00") and value.total_result == Decimal("0.00")
    assert value.input_entry_ids == (receipt.entry.id,)
    assert value.cash_flow.rejected_orders == 1
    assert snapshot(database) == before
