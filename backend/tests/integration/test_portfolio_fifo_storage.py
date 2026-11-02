"""Owned fixed-price FIFO acceptance; no market dataset or runtime provider is enabled."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.tests.integration.test_numerical_context_storage import snapshot
from backend.tests.integration.test_portfolio_storage import order
from backend.tests.integration.test_portfolio_storage import portfolio as portfolio
from regintel.auth.config import AuthSettings
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.main import create_app
from regintel.portfolio.repository import PortfolioNotFound, PortfolioRepository
from regintel.portfolio.service import PortfolioService

pytestmark = pytest.mark.integration


@pytest.fixture
def fifo(portfolio):
    database, repository, quotes, user, peer = portfolio
    opening = repository.create(user)
    receipts = []
    for request, price in (
        (order(quantity=2), "10.00"),
        (order(quantity=3), "20.00"),
        (order("SELL", 4), "30.00"),
        (order("SELL", 1), "15.00"),
        (order(quantity=2), "7.00"),
    ):
        quotes.price = price
        receipts.append(repository.submit(request, user))
    return database, repository, quotes, user, peer, opening, receipts


def selected_versions(opening, receipts):
    return (
        ("opening", opening.account_id, 0, "0.00", "0.00", "0.00"),
        ("buy", receipts[0].entry.id, 1, "0.00", "20.00", "0.00"),
        ("purchases", receipts[1].entry.id, 2, "0.00", "80.00", "0.00"),
        ("partial", receipts[2].entry.id, 3, "60.00", "20.00", "60.00"),
        ("closed", receipts[3].entry.id, 4, "80.00", "0.00", "55.00"),
        ("reopened", receipts[4].entry.id, 5, "80.00", "14.00", "55.00"),
    )


def test_fifo_costs_follow_exact_owned_prefixes_without_writing_or_selecting_new_quotes(fifo):
    database, repository, quotes, user, _, opening, receipts = fifo
    before, calls = snapshot(database), quotes.calls
    for _, version, count, allocated, remaining, realized in selected_versions(opening, receipts):
        value = repository.analytics(user, version=version)
        assert value.portfolio_version_id == version and value.committed_orders == count
        assert value.cost_basis_method == "FIFO"
        assert value.summary.realized_cost_basis == Decimal(allocated)
        assert value.summary.remaining_cost_basis == Decimal(remaining)
        assert value.summary.realized_result == Decimal(realized)
        assert value.input_entry_ids == tuple(receipt.entry.id for receipt in receipts[:count])
    assert quotes.calls == calls and snapshot(database) == before


def test_retry_does_not_add_a_second_purchase_lot_or_change_prior_fifo_results(fifo):
    database, repository, quotes, user, _, _, receipts = fifo
    before, calls = snapshot(database), quotes.calls
    selected = repository.analytics(user, version=receipts[2].entry.id)
    current = repository.analytics(user)
    assert repository.submit(receipts[0].entry.request, user) == receipts[0]
    assert repository.analytics(user, version=receipts[2].entry.id) == selected
    assert repository.analytics(user) == current
    assert quotes.calls == calls and snapshot(database) == before


def test_disabling_quotes_keeps_committed_costs_and_rejects_new_orders_without_movement(fifo):
    database, repository, _, user, _, _, _ = fifo
    before = repository.analytics(user)
    unpriced = PortfolioRepository(database, clock=lambda: datetime(2026, 10, 23, 6, tzinfo=UTC))
    receipt = unpriced.submit(order(), user)
    assert receipt.entry.evaluation.reason == "QUOTES_UNAVAILABLE"
    after = unpriced.analytics(user)
    assert after.summary.realized_result == before.summary.realized_result == Decimal("55.00")
    assert (
        after.summary.remaining_cost_basis
        == before.summary.remaining_cost_basis
        == Decimal("14.00")
    )
    assert after.summary.cash == before.summary.cash
    assert after.committed_orders == before.committed_orders + 1


def test_fifo_http_retains_exact_decimal_costs_source_membership_and_owner_boundaries(
    fifo, tmp_path
):
    database, repository, _, user, peer, opening, receipts = fifo
    settings = AuthSettings(jwt_secret=SecretStr("af" * 32))
    auth = AuthService(PostgreSQLAuthRepository(database), settings)
    before = snapshot(database)
    captures = {}
    with TestClient(
        create_app(auth_service=auth, portfolio_service=PortfolioService(repository, None))
    ) as client:
        headers = {"Authorization": "Bearer " + issue_token(user, settings)}
        foreign = {"Authorization": "Bearer " + issue_token(peer, settings)}
        for key, version, _, allocated, remaining, realized in selected_versions(opening, receipts):
            captures[key] = {}
            for name, path in (
                ("portfolio", "/v1/portfolio"),
                ("ledger", "/v1/portfolio/ledger"),
                ("analytics", "/v1/portfolio/analytics"),
            ):
                target = path + "?portfolio_version_id=" + version
                assert client.get(target).status_code == 401
                response = client.get(target, headers=headers)
                assert response.status_code == 200
                captures[key][name] = response.json()
                assert response.json()["meta"]["versions"]["portfolio_version_id"] == version
                if name == "analytics":
                    assert response.json()["data"]["summary"]["realized_cost_basis"] == allocated
                    assert response.json()["data"]["summary"]["remaining_cost_basis"] == remaining
                    assert response.json()["data"]["summary"]["realized_result"] == realized
                assert client.get(target, headers=foreign).status_code == 404
    assert snapshot(database) == before
    with pytest.raises(PortfolioNotFound):
        repository.analytics(peer, version=receipts[2].entry.id)
    (tmp_path / "portfolio-fifo-wire.json").write_bytes(
        (
            json.dumps(
                {
                    "fixture_notice": (
                        "Owned PostgreSQL/HTTP authored FIFO fixture; fixed engineering prices, "
                        "not market data or runtime quote configuration."
                    ),
                    "snapshots": captures,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
    )
