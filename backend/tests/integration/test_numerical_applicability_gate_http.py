"""Resolved applicability HTTP checks on authored sources in disposable databases."""

from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.tests.integration.test_numerical_applicability_http import bearer
from backend.tests.integration.test_numerical_applicability_http import client_case as client_case
from backend.tests.integration.test_numerical_applicability_storage import (
    applicability_case as applicability_case,
)
from backend.tests.integration.test_numerical_binding_storage import binding as binding
from backend.tests.integration.test_numerical_context_storage import inspection as inspection
from backend.tests.integration.test_numerical_context_storage import snapshot
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.auth.service import AuthService
from regintel.db.migrations import connect_database
from regintel.main import create_app
from regintel.numerical import gate_repository, review_repository

pytestmark = pytest.mark.integration
PREFIX = "/v1/admin/numerical/gates/"


def save_applicability(client_case):
    client, case, base, request, settings = client_case
    headers = bearer(case.source.user, settings)
    path = PREFIX + base.result.id + "/applicability"
    saved = client.post(path, headers=headers, json=request.model_dump(mode="json"))
    assert saved.status_code == 200
    return saved.json()["data"], headers, path


def test_http_applicability_resolution_keeps_separate_confirmation_and_immutable_history(
    client_case,
):
    client, case, base, _, _ = client_case
    review, headers, path = save_applicability(client_case)
    before = snapshot(case.source.database)
    response = client.post(path + "/gate", headers=headers)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    data = response.json()["data"]
    assert data["base_gate_run_id"] == base.result.id
    assert data["applicability_review_id"] == review["id"]
    packet = data["packet"]
    gate = packet["gate"]
    assert gate["id"] != base.result.id and gate["state"] == "READY_FOR_REVIEW"
    assert gate["quantity_proposal"] == base.result.model_dump(mode="json")["quantity_proposal"]
    assert gate["evidence_ids"] == list(base.result.evidence_ids)
    assert not gate["acceptance_eligible"] and not gate["mandatory_m1_validation_complete"]
    assert packet["binding"] == base.source_input.binding.model_dump(mode="json")
    assert packet["review"] is None
    selected = PREFIX + gate["id"]
    assert client.get(selected, headers=headers).json()["data"] == packet
    assert client.get(PREFIX + base.result.id, headers=headers).json()["data"]["gate"] == (
        base.result.model_dump(mode="json")
    )
    assert client.post(path + "/gate", headers=headers).json()["data"] == data
    prepared = client.get(selected + "/publication-input", headers=headers)
    assert prepared.status_code == 200 and prepared.json()["data"]["state"] == "BLOCKED"
    assert prepared.json()["data"]["proposed_input"] is None
    confirmed = client.post(
        selected + "/review",
        headers=headers,
        json={
            "gate_run_id": gate["id"],
            "decision": "CONFIRM_CONTEXT",
            "evidence_ids": gate["evidence_ids"],
            "note": "Authored HTTP context confirmation, separate from source applicability.",
        },
    )
    assert confirmed.status_code == 200
    prepared = client.get(selected + "/publication-input", headers=headers)
    assert prepared.status_code == 200
    preparation = prepared.json()["data"]
    assert preparation["state"] == "READY_FOR_ADAPTER"
    assert preparation["proposed_input"]["proof"] == packet["binding"]
    assert not preparation["publishes_fact"] and not preparation["acceptance_eligible"]
    rerun = client.post(path + "/gate", headers=headers)
    assert rerun.status_code == 200
    assert rerun.json()["data"]["packet"]["review"] == confirmed.json()["data"]
    after = snapshot(case.source.database)
    for table in before.keys() - {"bound_numerical_gate_runs", "numerical_context_reviews"}:
        assert before[table] == after[table], table
    assert client.post(selected + "/applicability/gate", headers=headers).status_code == 409
    assert snapshot(case.source.database) == after


@pytest.mark.parametrize(
    "actor,status", [("anonymous", 401), ("learner", 403), ("stale", 401), ("inactive", 401)]
)
def test_http_gate_resolution_requires_current_administrator(client_case, actor, status):
    client, case, gate, _, settings = client_case
    user = case.source.user
    if actor == "learner":
        user = case.source.learner
    elif actor == "stale":
        user = replace(user, auth_version=user.auth_version + 1)
    elif actor == "inactive":
        with connect_database(case.source.database) as connection:
            connection.execute("UPDATE regintel.users SET is_active=false WHERE id=%s", (user.id,))
    headers = {} if actor == "anonymous" else bearer(user, settings)
    before = snapshot(case.source.database)
    assert (
        client.post(PREFIX + gate.result.id + "/applicability/gate", headers=headers).status_code
        == status
    )
    assert snapshot(case.source.database) == before


def test_http_gate_requires_stored_review_and_configured_source(client_case):
    client, case, gate, _, settings = client_case
    headers = bearer(case.source.user, settings)
    before = snapshot(case.source.database)
    path = PREFIX + gate.result.id + "/applicability/gate"
    assert client.post(path, headers=headers).status_code == 404
    assert (
        client.post(PREFIX + str(uuid4()) + "/applicability/gate", headers=headers).status_code
        == 404
    )
    assert client.post(PREFIX + "invalid/applicability/gate", headers=headers).status_code == 422
    auth = AuthService(PostgreSQLAuthRepository(case.source.database), settings)
    with TestClient(create_app(auth_service=auth)) as unavailable:
        assert unavailable.post(path, headers=headers).status_code == 503
    assert snapshot(case.source.database) == before


def test_http_source_change_blocks_resolution_without_new_gate_or_authority(client_case):
    client, case, _, _, _ = client_case
    _, headers, path = save_applicability(client_case)
    before = snapshot(case.source.database)
    original = case.source.source_path.read_bytes()
    try:
        case.source.source_path.write_bytes(original + b"authored source change")
        assert client.post(path + "/gate", headers=headers).status_code == 409
        assert client.get(path, headers=headers).status_code == 200
        assert snapshot(case.source.database) == before
    finally:
        case.source.source_path.write_bytes(original)


def test_http_historical_gate_is_readable_but_cannot_prepare_after_policy_change(
    client_case, monkeypatch
):
    client, case, _, _, _ = client_case
    _, headers, path = save_applicability(client_case)
    response = client.post(path + "/gate", headers=headers)
    assert response.status_code == 200
    packet = response.json()["data"]["packet"]
    before = snapshot(case.source.database)
    monkeypatch.setattr(gate_repository, "configuration_for_input", lambda _: "f" * 64)
    monkeypatch.setattr(review_repository, "configuration_for_input", lambda _: "f" * 64)
    selected = PREFIX + packet["gate"]["id"]
    assert client.get(selected, headers=headers).json()["data"] == packet
    assert client.get(selected + "/publication-input", headers=headers).status_code == 409
    assert client.post(path + "/gate", headers=headers).status_code == 409
    assert snapshot(case.source.database) == before
