"""Actual PostgreSQL/HTTP preparation is read-only; fixtures are authored."""

from dataclasses import replace
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
from regintel.db.migrations import connect_database
from regintel.entities.models import EntityRegistration
from regintel.entities.repository import EntityRepository
from regintel.main import create_app
from regintel.numerical.publication_input_repository import NumericalPublicationInputRepository
from regintel.numerical.repository import NumericalAuthorizationError

pytestmark = pytest.mark.integration


def test_preparation_read_requires_confirmation_and_never_writes(client_case):
    client, case, gate, proposal, reviews, settings = client_case
    headers = bearer(case.source.user, settings)
    path = f"/v1/admin/numerical/gates/{gate.result.id}/publication-input"
    before = snapshot(case.source.database)
    result = client.get(path, headers=headers)
    assert result.status_code == 200
    assert result.json()["data"]["state"] == "BLOCKED"
    assert result.json()["data"]["proposed_input"] is None
    assert snapshot(case.source.database) == before
    saved = reviews.save(proposal, case.source.user)
    before = snapshot(case.source.database)
    first = client.get(path, headers=headers)
    assert first.status_code == 200
    packet = first.json()
    assert packet["meta"]["versions"]["corpus_version_id"] is None
    item = packet["data"]["proposed_input"]
    assert packet["data"]["state"] == "READY_FOR_ADAPTER" and len(packet["data"]["checks"]) == 16
    assert item["context_review"] == saved.model_dump(mode="json")
    assert item["proof"] == gate.source_input.binding.model_dump(mode="json")
    assert item["quantity"]["normalized_value"] == "2500.20"
    assert not item["acceptance_eligible"] and not item["publishes_fact"]
    assert not item["mandatory_m1_validation_complete"]
    assert client.get(path, headers=headers).json()["data"] == packet["data"]
    assert snapshot(case.source.database) == before


@pytest.mark.parametrize("actor,status", [("anonymous", 401), ("learner", 403)])
def test_private_preparation_rejects_non_administrators(client_case, actor, status):
    client, case, gate, _, _, settings = client_case
    headers = {} if actor == "anonymous" else bearer(case.source.learner, settings)
    before = snapshot(case.source.database)
    assert (
        client.get(
            f"/v1/admin/numerical/gates/{gate.result.id}/publication-input", headers=headers
        ).status_code
        == status
    )
    assert snapshot(case.source.database) == before


def test_current_admin_role_and_version_are_rechecked_inside_repository(reviewed_case):
    case, gate, _, reviews = reviewed_case
    repository = NumericalPublicationInputRepository(reviews.source)
    for user in (
        case.source.learner,
        replace(case.source.learner, role="admin"),
        replace(case.source.user, auth_version=2),
    ):
        with pytest.raises(NumericalAuthorizationError):
            repository.prepare(gate.result.id, user)
    with connect_database(case.source.database) as connection:
        connection.execute(
            "UPDATE regintel.users SET is_active=false WHERE id=%s", (case.source.user.id,)
        )
    before = snapshot(case.source.database)
    with pytest.raises(NumericalAuthorizationError):
        repository.prepare(gate.result.id, case.source.user)
    assert snapshot(case.source.database) == before


def test_a_historical_confirmation_cannot_bypass_changed_approval_state(client_case):
    client, case, gate, proposal, reviews, settings = client_case
    reviews.save(proposal, case.source.user)
    entity = gate.source_input.context.source_input.registry.entities[0]
    EntityRepository(case.source.database).register(
        EntityRegistration(
            id=str(uuid4()),
            kind="COMPANY",
            legal_name=entity.legal_name,
            legal_name_support=entity.legal_name_support,
            identifiers=(),
            aliases=(),
            review_note="Authored changed registry snapshot.",
        ),
        case.source.user,
    )
    before = snapshot(case.source.database)
    assert (
        client.get(
            f"/v1/admin/numerical/gates/{gate.result.id}/publication-input",
            headers=bearer(case.source.user, settings),
        ).status_code
        == 409
    )
    assert reviews.get(gate.result.id, case.source.user).request == proposal
    assert snapshot(case.source.database) == before


def test_original_bytes_are_rechecked_after_context_confirmation(client_case):
    client, case, gate, proposal, reviews, settings = client_case
    reviews.save(proposal, case.source.user)
    original = case.source.source_path.read_bytes()
    before = snapshot(case.source.database)
    try:
        case.source.source_path.write_bytes(original + b"authored tampering")
        assert (
            client.get(
                f"/v1/admin/numerical/gates/{gate.result.id}/publication-input",
                headers=bearer(case.source.user, settings),
            ).status_code
            == 409
        )
    finally:
        case.source.source_path.write_bytes(original)
    assert snapshot(case.source.database) == before


def test_rejected_context_stays_blocked_without_changing_its_review(client_case):
    client, case, gate, proposal, reviews, settings = client_case
    reviews.save(proposal.model_copy(update={"decision": "REJECT"}), case.source.user)
    before = snapshot(case.source.database)
    result = client.get(
        f"/v1/admin/numerical/gates/{gate.result.id}/publication-input",
        headers=bearer(case.source.user, settings),
    )
    assert result.status_code == 200
    assert result.json()["data"]["state"] == "BLOCKED"
    assert result.json()["data"]["checks"][-1]["state"] == "FAIL"
    assert snapshot(case.source.database) == before


@pytest.mark.parametrize("supported_header", [False], indirect=True)
def test_unresolved_source_context_cannot_be_prepared_by_reading(client_case):
    client, case, gate, _, _, settings = client_case
    before = snapshot(case.source.database)
    result = client.get(
        f"/v1/admin/numerical/gates/{gate.result.id}/publication-input",
        headers=bearer(case.source.user, settings),
    )
    assert result.status_code == 200 and result.json()["data"]["state"] == "BLOCKED"
    assert result.json()["data"]["proposed_input"] is None
    assert snapshot(case.source.database) == before


def test_unknown_invalid_and_unconfigured_preparation_are_explicit(client_case):
    client, case, _, _, _, settings = client_case
    headers = bearer(case.source.user, settings)
    before = snapshot(case.source.database)
    prefix = "/v1/admin/numerical/gates/"
    assert (
        client.get(prefix + str(uuid4()) + "/publication-input", headers=headers).status_code == 404
    )
    assert client.get(prefix + "invalid-id/publication-input", headers=headers).status_code == 422
    auth = AuthService(PostgreSQLAuthRepository(case.source.database), settings)
    with TestClient(create_app(auth_service=auth)) as unavailable:
        assert (
            unavailable.get(
                prefix + str(uuid4()) + "/publication-input", headers=headers
            ).status_code
            == 503
        )
    assert snapshot(case.source.database) == before
