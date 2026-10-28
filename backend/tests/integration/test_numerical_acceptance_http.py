"""Private acceptance HTTP retains exact selected source and current administrator."""

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


@pytest.fixture
def acceptance_http_case(client_case):
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
    response = client.post(
        path + "/candidates",
        headers=headers,
        json={
            "gate_run_id": gate.result.id,
            "prepared_input_id": prepared["proposed_input"]["id"],
        },
    )
    assert response.status_code == 200
    candidate = response.json()["data"]
    identity = candidate["record"]["id"]
    body = {
        "candidate_id": identity,
        "decision": "ACCEPT",
        "evidence_ids": list(gate.result.evidence_ids),
        "note": "Authored explicit HTTP acceptance, not a real source approval.",
    }
    return (
        client,
        case,
        gate,
        candidate,
        settings,
        path + "/candidates/" + identity + "/acceptance",
        body,
    )


@pytest.mark.parametrize("decision", ["ACCEPT", "REJECT"])
def test_http_decision_keeps_unpublished_state_and_immutable_retry(acceptance_http_case, decision):
    client, case, gate, candidate, settings, path, body = acceptance_http_case
    headers = bearer(case.source.user, settings)
    body["decision"] = decision
    before = snapshot(case.source.database)
    response = client.post(path, headers=headers, json=body)
    assert response.status_code == 200
    result = response.json()["data"]
    assert response.json()["meta"]["versions"]["corpus_version_id"] is None
    assert result["candidate"] == candidate
    record = result["record"]
    assert record["request"] == body and record["reviewed_by"] == str(case.source.user.id)
    assert record["state"] == ("ACCEPTED_UNPUBLISHED" if decision == "ACCEPT" else "REJECTED")
    assert not record["publishes_fact"] and record["published_corpus_version_id"] is None
    after = snapshot(case.source.database)
    assert {name for name in before if before[name] != after[name]} == {"numerical_acceptances"}
    assert client.get(path, headers=headers).json()["data"] == result
    assert client.post(path, headers=headers, json=body).json()["data"] == result
    changed = body | {"decision": "REJECT" if decision == "ACCEPT" else "ACCEPT"}
    assert client.post(path, headers=headers, json=changed).status_code == 409
    wrong_gate = path.replace(gate.result.id, str(uuid4()))
    assert client.post(wrong_gate, headers=headers, json=body).status_code == 404
    assert client.get(wrong_gate, headers=headers).status_code == 404
    assert snapshot(case.source.database) == after


@pytest.mark.parametrize("actor,status", [("anonymous", 401), ("learner", 403)])
def test_acceptance_http_requires_current_administrator(acceptance_http_case, actor, status):
    client, case, _, _, settings, path, body = acceptance_http_case
    headers = {} if actor == "anonymous" else bearer(case.source.learner, settings)
    before = snapshot(case.source.database)
    assert client.post(path, headers=headers, json=body).status_code == status
    assert client.get(path, headers=headers).status_code == status
    assert snapshot(case.source.database) == before


@pytest.mark.parametrize("field", ["checks", "quantity", "reviewed_by", "publishes_fact"])
def test_acceptance_http_cannot_supply_values_or_authority(acceptance_http_case, field):
    client, case, _, _, settings, path, body = acceptance_http_case
    before = snapshot(case.source.database)
    assert (
        client.post(
            path, headers=bearer(case.source.user, settings), json=body | {field: "forged"}
        ).status_code
        == 422
    )
    assert snapshot(case.source.database) == before


def test_acceptance_http_missing_invalid_unconfigured_and_mixed_inputs(acceptance_http_case):
    client, case, gate, candidate, settings, path, body = acceptance_http_case
    headers = bearer(case.source.user, settings)
    before = snapshot(case.source.database)
    assert client.get(path, headers=headers).status_code == 404
    assert (
        client.post(path, headers=headers, json=body | {"candidate_id": str(uuid4())}).status_code
        == 409
    )
    assert (
        client.post(
            path, headers=headers, json=body | {"evidence_ids": body["evidence_ids"][:-1]}
        ).status_code
        == 409
    )
    invalid = path.replace(candidate["record"]["id"], "invalid-id")
    assert client.get(invalid, headers=headers).status_code == 422
    unknown = path.replace(candidate["record"]["id"], str(uuid4()))
    assert client.get(unknown, headers=headers).status_code == 404
    auth = AuthService(PostgreSQLAuthRepository(case.source.database), settings)
    with TestClient(create_app(auth_service=auth)) as unavailable:
        assert unavailable.post(path, headers=headers, json=body).status_code == 503
        assert unavailable.get(path, headers=headers).status_code == 503
    assert snapshot(case.source.database) == before
