"""Private draft HTTP computes complete snapshots without creating a publication."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.tests.integration.test_numerical_acceptance_http import (
    acceptance_http_case as acceptance_http_case,
)
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
PATH = "/v1/admin/numerical/publication-drafts"


def test_http_draft_retains_accepted_proof_and_has_no_publication_side_effect(acceptance_http_case):
    client, case, _, candidate, settings, acceptance_path, decision = acceptance_http_case
    headers = bearer(case.source.user, settings)
    accepted = client.post(acceptance_path, headers=headers, json=decision)
    assert accepted.status_code == 200
    before = snapshot(case.source.database)
    body = {
        "idempotency_key": str(uuid4()),
        "parent_corpus_version_id": None,
        "candidate_ids": [candidate["record"]["id"]],
    }
    response = client.post(PATH, headers=headers, json=body)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["entries"][0]["acceptance"] == accepted.json()["data"]
    assert (
        data["state"] == "UNPUBLISHED_DRAFT"
        and not data["publishes_fact"]
        and not data["corpus_committed"]
    )
    assert response.json()["meta"]["versions"]["corpus_version_id"] is None
    assert client.post(PATH, headers=headers, json=body).json()["data"] == data
    assert snapshot(case.source.database) == before


@pytest.mark.parametrize("actor,status", [("anonymous", 401), ("learner", 403)])
def test_draft_http_requires_current_admin(acceptance_http_case, actor, status):
    client, case, _, candidate, settings, _, _ = acceptance_http_case
    headers = {} if actor == "anonymous" else bearer(case.source.learner, settings)
    before = snapshot(case.source.database)
    response = client.post(
        PATH,
        headers=headers,
        json={
            "idempotency_key": str(uuid4()),
            "parent_corpus_version_id": None,
            "candidate_ids": [candidate["record"]["id"]],
        },
    )
    assert response.status_code == status and snapshot(case.source.database) == before


@pytest.mark.parametrize("field", ["entries", "prepared_by", "quantity", "corpus_committed"])
def test_draft_http_rejects_caller_values_actor_and_publication(acceptance_http_case, field):
    client, case, _, candidate, settings, _, _ = acceptance_http_case
    before = snapshot(case.source.database)
    body = {
        "idempotency_key": str(uuid4()),
        "parent_corpus_version_id": None,
        "candidate_ids": [candidate["record"]["id"]],
        field: "forged",
    }
    assert (
        client.post(PATH, headers=bearer(case.source.user, settings), json=body).status_code == 422
    )
    assert snapshot(case.source.database) == before


def test_draft_http_missing_acceptance_parent_and_configuration_are_explicit(acceptance_http_case):
    client, case, _, candidate, settings, _, _ = acceptance_http_case
    headers = bearer(case.source.user, settings)
    body = {
        "idempotency_key": str(uuid4()),
        "parent_corpus_version_id": None,
        "candidate_ids": [candidate["record"]["id"]],
    }
    before = snapshot(case.source.database)
    assert client.post(PATH, headers=headers, json=body).status_code == 404
    assert (
        client.post(
            PATH, headers=headers, json=body | {"parent_corpus_version_id": str(uuid4())}
        ).status_code
        == 409
    )
    assert client.post(PATH, headers=headers, json=body | {"candidate_ids": []}).status_code == 422
    auth = AuthService(PostgreSQLAuthRepository(case.source.database), settings)
    with TestClient(create_app(auth_service=auth)) as unavailable:
        assert unavailable.post(PATH, headers=headers, json=body).status_code == 503
    assert snapshot(case.source.database) == before
