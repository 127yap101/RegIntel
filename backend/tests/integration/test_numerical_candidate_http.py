"""Private candidate HTTP writes use authored current-admin fixtures only."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.tests.integration.test_numerical_binding_storage import binding as binding
from backend.tests.integration.test_numerical_context_review_storage import (
    reviewed_case as reviewed_case,
)
from backend.tests.integration.test_numerical_context_review_storage import (
    supported_header as supported_header,
)
from backend.tests.integration.test_numerical_context_storage import inspection as inspection
from backend.tests.integration.test_numerical_context_storage import snapshot
from backend.tests.integration.test_numerical_review_http import bearer
from backend.tests.integration.test_numerical_review_http import client_case as client_case
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.auth.service import AuthService
from regintel.main import create_app

pytestmark = pytest.mark.integration


def test_candidate_http_keeps_complete_snapshot_and_idempotent_actor(client_case):
    client, case, gate, proposal, _, settings = client_case
    headers = bearer(case.source.user, settings)
    path = f"/v1/admin/numerical/gates/{gate.result.id}"
    assert (
        client.post(
            path + "/review", headers=headers, json=proposal.model_dump(mode="json")
        ).status_code
        == 200
    )
    prepared = client.get(path + "/publication-input", headers=headers).json()["data"]
    body = {"gate_run_id": gate.result.id, "prepared_input_id": prepared["proposed_input"]["id"]}
    before = snapshot(case.source.database)
    response = client.post(path + "/candidates", headers=headers, json=body)
    assert response.status_code == 200
    data = response.json()["data"]
    assert response.json()["meta"]["versions"]["corpus_version_id"] is None
    assert data["record"]["request"] == body
    assert data["record"]["submitted_by"] == str(case.source.user.id)
    assert data["record"]["state"] == "CANDIDATE"
    assert not data["record"]["acceptance_eligible"] and not data["record"]["publishes_fact"]
    assert data["preparation"] == prepared
    after = snapshot(case.source.database)
    assert {name for name in before if before[name] != after[name]} == {"numerical_candidates"}
    assert client.post(path + "/candidates", headers=headers, json=body).json()["data"] == data
    identity = data["record"]["id"]
    assert client.get(path + "/candidates/" + identity, headers=headers).json()["data"] == data
    assert (
        client.get(
            f"/v1/admin/numerical/gates/{uuid4()}/candidates/{identity}", headers=headers
        ).status_code
        == 404
    )
    assert snapshot(case.source.database) == after


@pytest.mark.parametrize("actor,status", [("anonymous", 401), ("learner", 403)])
def test_candidate_endpoints_reject_non_administrators(client_case, actor, status):
    client, case, gate, _, _, settings = client_case
    headers = {} if actor == "anonymous" else bearer(case.source.learner, settings)
    path = f"/v1/admin/numerical/gates/{gate.result.id}/candidates"
    before = snapshot(case.source.database)
    assert (
        client.post(
            path,
            headers=headers,
            json={"gate_run_id": gate.result.id, "prepared_input_id": str(uuid4())},
        ).status_code
        == status
    )
    assert client.get(path + "/" + str(uuid4()), headers=headers).status_code == status
    assert snapshot(case.source.database) == before


@pytest.mark.parametrize("injection", ["quantity", "submitted_by", "acceptance_eligible"])
def test_candidate_http_does_not_accept_client_values_or_actor(client_case, injection):
    client, case, gate, _, _, settings = client_case
    before = snapshot(case.source.database)
    response = client.post(
        f"/v1/admin/numerical/gates/{gate.result.id}/candidates",
        headers=bearer(case.source.user, settings),
        json={
            "gate_run_id": gate.result.id,
            "prepared_input_id": str(uuid4()),
            injection: "forged",
        },
    )
    assert response.status_code == 422
    assert snapshot(case.source.database) == before


def test_candidate_http_cannot_create_without_actual_context_confirmation(client_case):
    client, case, gate, _, _, settings = client_case
    before = snapshot(case.source.database)
    response = client.post(
        f"/v1/admin/numerical/gates/{gate.result.id}/candidates",
        headers=bearer(case.source.user, settings),
        json={"gate_run_id": gate.result.id, "prepared_input_id": str(uuid4())},
    )
    assert response.status_code == 409
    assert snapshot(case.source.database) == before


def test_candidate_http_keeps_selected_gate_identity(client_case):
    client, case, gate, _, _, settings = client_case
    before = snapshot(case.source.database)
    response = client.post(
        f"/v1/admin/numerical/gates/{gate.result.id}/candidates",
        headers=bearer(case.source.user, settings),
        json={"gate_run_id": str(uuid4()), "prepared_input_id": str(uuid4())},
    )
    assert response.status_code == 409
    assert snapshot(case.source.database) == before


def test_candidate_http_missing_invalid_and_unconfigured_are_explicit(client_case):
    client, case, gate, _, _, settings = client_case
    headers = bearer(case.source.user, settings)
    path = f"/v1/admin/numerical/gates/{gate.result.id}/candidates"
    before = snapshot(case.source.database)
    assert client.get(path + "/" + str(uuid4()), headers=headers).status_code == 404
    assert client.get(path + "/invalid-id", headers=headers).status_code == 422
    auth = AuthService(PostgreSQLAuthRepository(case.source.database), settings)
    with TestClient(create_app(auth_service=auth)) as unavailable:
        assert (
            unavailable.post(
                path,
                headers=headers,
                json={"gate_run_id": gate.result.id, "prepared_input_id": str(uuid4())},
            ).status_code
            == 503
        )
    assert snapshot(case.source.database) == before
