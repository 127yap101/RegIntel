"""Per-owner immutable portfolio prefixes remain stable after later virtual orders."""

from decimal import Decimal
from uuid import uuid4

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
from regintel.config import Settings
from regintel.main import create_app
from regintel.portfolio.repository import PortfolioNotFound
from regintel.portfolio.service import PortfolioService

pytestmark = pytest.mark.integration


def test_opening_buy_and_closed_versions_retain_exact_account_ledger_and_analytics(portfolio):
    database, repository, _, user, _ = portfolio
    opening = repository.create(user)
    first = repository.submit(order(quantity=3), user)
    partial = repository.submit(order("SELL", 1), user)
    final = repository.submit(order("SELL", 2), user)
    before = snapshot(database)
    for version, count, cash, quantity in (
        (opening.account_id, 0, "100000.00", 0),
        (first.entry.id, 1, "99969.70", 3),
        (partial.entry.id, 2, "99979.80", 2),
        (final.entry.id, 3, "100000.00", 0),
    ):
        account = repository.account(user, version=version)
        ledger = repository.ledger(user, version=version)
        analytics = repository.analytics(user, version=version)
        assert (
            account.portfolio_version_id
            == ledger.portfolio_version_id
            == analytics.portfolio_version_id
            == version
        )
        assert account.committed_orders == ledger.total == len(ledger.entries) == count
        assert account.state.cash == analytics.summary.cash == Decimal(cash)
        assert sum(h.quantity for h in account.state.holdings) == quantity
        assert analytics.input_entry_ids == tuple(entry.id for entry in ledger.entries)
    assert snapshot(database) == before


def test_later_order_cannot_change_a_selected_page_or_its_financial_totals(portfolio):
    _, repository, _, user, _ = portfolio
    repository.create(user)
    first = repository.submit(order(quantity=3), user)
    selected = repository.account(user, version=first.entry.id)
    history = repository.ledger(user, version=selected.portfolio_version_id, limit=1)
    analytics = repository.analytics(user, version=selected.portfolio_version_id)
    repository.submit(order("SELL", 1), user)
    assert repository.account(user, version=first.entry.id) == selected
    assert repository.ledger(user, version=first.entry.id, limit=1) == history
    assert repository.ledger(user, version=first.entry.id, offset=1).entries == ()
    assert repository.analytics(user, version=first.entry.id) == analytics
    assert repository.account(user).committed_orders == 2


@pytest.mark.parametrize("selection", ["peer_account", "peer_order", "unknown"])
def test_other_account_and_unknown_versions_are_indistinguishably_unavailable(portfolio, selection):
    database, repository, _, user, peer = portfolio
    repository.create(user)
    other = repository.create(peer)
    receipt = repository.submit(order(), peer)
    version = (
        other.account_id
        if selection == "peer_account"
        else receipt.entry.id
        if selection == "peer_order"
        else str(uuid4())
    )
    before = snapshot(database)
    for read in (repository.account, repository.ledger, repository.analytics):
        with pytest.raises(PortfolioNotFound):
            read(user, version=version)
    assert snapshot(database) == before


def test_http_version_selection_retains_complete_prefix_and_rejects_foreign_versions(portfolio):
    database, repository, _, user, peer = portfolio
    opening = repository.create(user)
    repository.create(peer)
    first = repository.submit(order(quantity=3), user)
    repository.submit(order("SELL", 1), user)
    foreign = repository.submit(order(), peer)
    settings = AuthSettings(jwt_secret=SecretStr("ac" * 32))
    auth = AuthService(PostgreSQLAuthRepository(database), settings)
    before = snapshot(database)
    with TestClient(
        create_app(
            Settings(environment="test"),
            auth_service=auth,
            portfolio_service=PortfolioService(repository, None),
        )
    ) as client:
        headers = {"Authorization": "Bearer " + issue_token(user, settings)}
        for path in ("/v1/portfolio", "/v1/portfolio/ledger", "/v1/portfolio/analytics"):
            selected = path + "?portfolio_version_id=" + first.entry.id
            assert client.get(selected).status_code == 401
            response = client.get(selected, headers=headers)
            assert response.status_code == 200
            assert response.json()["meta"]["versions"]["portfolio_version_id"] == first.entry.id
            assert response.json()["data"]["portfolio_version_id"] == first.entry.id
            assert (
                client.get(
                    path + "?portfolio_version_id=" + foreign.entry.id, headers=headers
                ).status_code
                == 404
            )
            assert (
                client.get(path + "?portfolio_version_id=invalid", headers=headers).status_code
                == 422
            )
            initial = client.get(
                path + "?portfolio_version_id=" + opening.account_id, headers=headers
            )
            assert (
                initial.status_code == 200
                and initial.json()["data"]["portfolio_version_id"] == opening.account_id
            )
        history = client.get(
            "/v1/portfolio/ledger?portfolio_version_id=" + first.entry.id, headers=headers
        ).json()["data"]
        assert history["total"] == 1 and len(history["entries"]) == 1
    assert snapshot(database) == before
