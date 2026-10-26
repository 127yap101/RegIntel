"""Private review HTTP checks using authored M1 bindings, never real approvals."""

from secrets import token_hex
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.tests.integration.test_numerical_binding_storage import binding as binding
from backend.tests.integration.test_numerical_context_review_storage import (
    reviewed_case as reviewed_case,
)
from backend.tests.integration.test_numerical_context_review_storage import (
    supported_header as supported_header,
)
from backend.tests.integration.test_numerical_context_storage import inspection as inspection
from backend.tests.integration.test_numerical_context_storage import snapshot
from regintel.auth.config import AuthSettings
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.config import Settings
from regintel.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
def client_case(reviewed_case):
    case, gate, proposal, repository = reviewed_case
    settings = AuthSettings(jwt_secret=SecretStr(token_hex(32)))
    auth = AuthService(PostgreSQLAuthRepository(case.source.database), settings)
    app = create_app(
        Settings(environment="test"), auth_service=auth, numerical_review_repository=repository
    )
    with TestClient(app) as client:
        yield client, case, gate, proposal, repository, settings


def bearer(user, settings):
    return {"Authorization": "Bearer " + issue_token(user, settings)}


def test_exact_gate_binding_and_stored_review_survive_http_without_publication(client_case):
    client, case, gate, proposal, _, settings = client_case
    headers = bearer(case.source.user, settings)
    path = f"/v1/admin/numerical/gates/{gate.result.id}"
    before = snapshot(case.source.database)
    response = client.get(path, headers=headers)
    assert response.status_code == 200
    packet = response.json()
    assert packet["data"]["gate"] == gate.result.model_dump(mode="json")
    assert packet["data"]["binding"] == gate.source_input.binding.model_dump(mode="json")
    assert packet["data"]["review"] is None
    assert packet["meta"]["versions"]["corpus_version_id"] is None
    assert snapshot(case.source.database) == before
    saved = client.post(path + "/review", headers=headers, json=proposal.model_dump(mode="json"))
    assert saved.status_code == 200
    review = saved.json()["data"]
    assert not review["acceptance_eligible"] and not review["publishes_fact"]
    assert not review["mandatory_m1_validation_complete"]
    assert review["reviewed_by"] == str(case.source.user.id)
    assert (
        client.post(
            path + "/review", headers=headers, json=proposal.model_dump(mode="json")
        ).json()["data"]
        == review
    )
    assert client.get(path, headers=headers).json()["data"]["review"] == review
    after = snapshot(case.source.database)
    for table in ("fact_observations", "acceptance_audits", "corpus_versions"):
        assert after[table] == before[table]


@pytest.mark.parametrize("kind,status", [("anonymous", 401), ("learner", 403)])
def test_review_http_rejects_non_admin_without_read_or_write(client_case, kind, status):
    client, case, gate, proposal, _, settings = client_case
    headers = {} if kind == "anonymous" else bearer(case.source.learner, settings)
    path = f"/v1/admin/numerical/gates/{gate.result.id}"
    before = snapshot(case.source.database)
    assert client.get(path, headers=headers).status_code == status
    assert (
        client.post(
            path + "/review", headers=headers, json=proposal.model_dump(mode="json")
        ).status_code
        == status
    )
    assert snapshot(case.source.database) == before


@pytest.mark.parametrize("change,status", [("gate", 409), ("evidence", 409), ("actor", 422)])
def test_review_http_keeps_exact_gate_membership_and_server_actor(client_case, change, status):
    client, case, gate, proposal, _, settings = client_case
    body = proposal.model_dump(mode="json")
    if change == "gate":
        body["gate_run_id"] = str(uuid4())
    elif change == "evidence":
        body["evidence_ids"] = body["evidence_ids"][:-1]
    else:
        body["reviewed_by"] = str(case.source.learner.id)
    before = snapshot(case.source.database)
    response = client.post(
        f"/v1/admin/numerical/gates/{gate.result.id}/review",
        headers=bearer(case.source.user, settings),
        json=body,
    )
    assert response.status_code == status
    assert snapshot(case.source.database) == before


@pytest.mark.parametrize("supported_header", [False], indirect=True)
def test_review_http_cannot_confirm_unresolved_context_but_can_record_rejection(client_case):
    client, case, gate, proposal, _, settings = client_case
    path = f"/v1/admin/numerical/gates/{gate.result.id}/review"
    headers = bearer(case.source.user, settings)
    assert (
        client.post(path, headers=headers, json=proposal.model_dump(mode="json")).status_code == 409
    )
    body = proposal.model_dump(mode="json") | {"decision": "REJECT"}
    response = client.post(path, headers=headers, json=body)
    assert (
        response.status_code == 200 and response.json()["data"]["request"]["decision"] == "REJECT"
    )


def test_review_http_unknown_invalid_and_unconfigured_are_explicit(client_case):
    client, case, _, _, _, settings = client_case
    headers = bearer(case.source.user, settings)
    path = "/v1/admin/numerical/gates/"
    assert client.get(path + str(uuid4()), headers=headers).status_code == 404
    assert client.get(path + "invalid-id", headers=headers).status_code == 422
    auth = AuthService(PostgreSQLAuthRepository(case.source.database), settings)
    with TestClient(create_app(auth_service=auth)) as unavailable:
        assert unavailable.get(path + str(uuid4()), headers=headers).status_code == 503
