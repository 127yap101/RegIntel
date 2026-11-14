"""Applicability API authorization and exact membership on authored database sources."""

from secrets import token_hex
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.tests.integration.test_numerical_applicability_storage import (
    applicability_case as applicability_case,
)
from backend.tests.integration.test_numerical_binding_storage import binding as binding
from backend.tests.integration.test_numerical_context_storage import inspection as inspection
from backend.tests.integration.test_numerical_context_storage import snapshot
from regintel.auth.config import AuthSettings
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.config import Settings
from regintel.main import create_app
from regintel.numerical.review_repository import NumericalContextReviewRepository

pytestmark = pytest.mark.integration


@pytest.fixture
def client_case(applicability_case):
    case, gate, proposal, repository = applicability_case
    settings = AuthSettings(jwt_secret=SecretStr(token_hex(32)))
    auth = AuthService(PostgreSQLAuthRepository(case.source.database), settings)
    app = create_app(
        Settings(environment="test"),
        auth_service=auth,
        numerical_review_repository=NumericalContextReviewRepository(repository.source),
    )
    with TestClient(app) as client:
        yield client, case, gate, proposal, settings


def bearer(user, settings):
    return {"Authorization": "Bearer " + issue_token(user, settings)}


def test_authenticated_applicability_roundtrip_retains_gate_and_original_actor(client_case):
    client, case, gate, proposal, settings = client_case
    path = f"/v1/admin/numerical/gates/{gate.result.id}/applicability"
    headers = bearer(case.source.user, settings)
    before = snapshot(case.source.database)
    requirements = client.get(path + "/requirements", headers=headers)
    assert requirements.status_code == 200 and requirements.json()["data"]["eligible"]
    assert requirements.headers["cache-control"] == "no-store"
    assert client.get(path, headers=headers).status_code == 404
    assert snapshot(case.source.database) == before
    saved = client.post(path, headers=headers, json=proposal.model_dump(mode="json"))
    assert saved.status_code == 200
    result = saved.json()["data"]
    assert result["reviewed_by"] == str(case.source.user.id)
    assert not result["publishes_fact"] and not result["acceptance_eligible"]
    assert client.get(path, headers=headers).json()["data"] == result
    assert (
        client.post(path, headers=headers, json=proposal.model_dump(mode="json")).json()["data"]
        == result
    )
    after = snapshot(case.source.database)
    assert {
        table: after[table] for table in before if table != "numerical_applicability_reviews"
    } == {
        table: value
        for table, value in before.items()
        if table != "numerical_applicability_reviews"
    }
    packet = client.get(path.removesuffix("/applicability"), headers=headers).json()["data"]
    assert packet["gate"] == gate.result.model_dump(mode="json") and packet["review"] is None


@pytest.mark.parametrize("actor,status", [("anonymous", 401), ("learner", 403)])
def test_applicability_api_requires_administrator_for_all_operations(client_case, actor, status):
    client, case, gate, proposal, settings = client_case
    headers = {} if actor == "anonymous" else bearer(case.source.learner, settings)
    path = f"/v1/admin/numerical/gates/{gate.result.id}/applicability"
    before = snapshot(case.source.database)
    assert client.get(path + "/requirements", headers=headers).status_code == status
    assert client.get(path, headers=headers).status_code == status
    assert (
        client.post(path, headers=headers, json=proposal.model_dump(mode="json")).status_code
        == status
    )
    assert snapshot(case.source.database) == before


@pytest.mark.parametrize("change,status", [("gate", 409), ("words", 409), ("actor", 422)])
def test_applicability_api_rejects_changed_references_and_client_actor(client_case, change, status):
    client, case, gate, proposal, settings = client_case
    body = proposal.model_dump(mode="json")
    if change == "gate":
        body["gate_run_id"] = str(uuid4())
    elif change == "words":
        body["assertions"][0]["evidence_ids"][0] = str(uuid4())
    else:
        body["reviewed_by"] = str(case.source.learner.id)
    before = snapshot(case.source.database)
    response = client.post(
        f"/v1/admin/numerical/gates/{gate.result.id}/applicability",
        headers=bearer(case.source.user, settings),
        json=body,
    )
    assert response.status_code == status
    assert snapshot(case.source.database) == before


def test_applicability_api_explicit_unknown_invalid_unconfigured_and_conflict(client_case):
    client, case, gate, proposal, settings = client_case
    headers = bearer(case.source.user, settings)
    prefix = "/v1/admin/numerical/gates/"
    assert (
        client.get(
            prefix + str(uuid4()) + "/applicability/requirements", headers=headers
        ).status_code
        == 404
    )
    assert client.get(prefix + "bad-id/applicability", headers=headers).status_code == 422
    path = prefix + gate.result.id + "/applicability"
    assert (
        client.post(path, headers=headers, json=proposal.model_dump(mode="json")).status_code == 200
    )
    assert (
        client.post(
            path,
            headers=headers,
            json=proposal.model_dump(mode="json") | {"note": "Different decision explanation."},
        ).status_code
        == 409
    )
    auth = AuthService(PostgreSQLAuthRepository(case.source.database), settings)
    with TestClient(create_app(auth_service=auth)) as unavailable:
        assert unavailable.get(path, headers=headers).status_code == 503
