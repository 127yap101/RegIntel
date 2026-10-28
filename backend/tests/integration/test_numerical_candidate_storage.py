"""Actual owned PostgreSQL candidate writes over labelled authored source fixtures."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
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
from regintel.auth.repository import PostgreSQLAuthRepository, seed_users
from regintel.auth.types import SeedAccount
from regintel.db.migrations import connect_database
from regintel.entities.models import EntityRegistration
from regintel.entities.repository import EntityRepository
from regintel.numerical import candidate_repository as storage_module
from regintel.numerical.candidate_models import NumericalCandidateRequest
from regintel.numerical.candidate_repository import NumericalCandidateRepository
from regintel.numerical.publication_input_repository import NumericalPublicationInputRepository
from regintel.numerical.repository import NumericalAuthorizationError
from regintel.numerical.review_repository import NumericalReviewConflict

pytestmark = pytest.mark.integration


@pytest.fixture
def candidate_case(reviewed_case):
    case, gate, proposal, reviews = reviewed_case
    reviews.save(proposal, case.source.user)
    prepared = NumericalPublicationInputRepository(reviews.source).prepare(
        gate.result.id, case.source.user
    )
    assert prepared.proposed_input is not None
    request = NumericalCandidateRequest(
        gate_run_id=gate.result.id, prepared_input_id=prepared.proposed_input.id
    )
    return case, gate, request, NumericalCandidateRepository(reviews.source)


def test_complete_candidate_is_durable_immutable_proposal_and_retry_is_read_only(candidate_case):
    case, gate, request, repository = candidate_case
    before = snapshot(case.source.database)
    first = repository.save(request, case.source.user)
    assert first.preparation.proposed_input.proof == gate.source_input.binding
    assert first.preparation.proposed_input.quantity.raw_value == "2,500.20"
    assert first.record.submitted_by == str(case.source.user.id)
    assert first.record.state == "CANDIDATE" and not first.record.publishes_fact
    after = snapshot(case.source.database)
    assert {name for name in before if before[name] != after[name]} == {"numerical_candidates"}
    assert (
        repository.save(request, case.source.user)
        == repository.get(first.record.id, case.source.user)
        == first
    )
    assert snapshot(case.source.database) == after


def test_concurrent_requests_retain_one_candidate_and_original_actor(candidate_case):
    case, _, request, repository = candidate_case
    database = case.source.database
    seed_users(
        database,
        (
            SeedAccount(
                "other-candidate-admin", SecretStr("Authored candidate administrator!"), "admin"
            ),
        ),
    )
    other = PostgreSQLAuthRepository(database).get_by_username("other-candidate-admin")
    assert other is not None
    barrier = Barrier(2)

    def submit(user):
        barrier.wait(timeout=30)
        return repository.save(request, user)

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(submit, user) for user in (case.source.user, other)]
        values = [future.result(timeout=60) for future in futures]
    assert values[0] == values[1]
    assert values[0].record.submitted_by in {str(case.source.user.id), str(other.id)}
    with connect_database(database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM regintel.numerical_candidates"
        ).fetchone() == (1,)


def test_changed_gate_cannot_reuse_a_prepared_input_even_after_creation(candidate_case):
    case, _, request, repository = candidate_case
    original = repository.save(request, case.source.user)
    before = snapshot(case.source.database)
    with pytest.raises(NumericalReviewConflict):
        repository.save(request.model_copy(update={"gate_run_id": str(uuid4())}), case.source.user)
    assert repository.get(original.record.id, case.source.user) == original
    assert snapshot(case.source.database) == before


def test_historical_retry_preserves_original_configuration_and_source(candidate_case, monkeypatch):
    case, _, request, repository = candidate_case
    original = repository.save(request, case.source.user)
    before = snapshot(case.source.database)
    monkeypatch.setattr(storage_module, "candidate_storage_configuration_sha256", lambda: "f" * 64)
    body = case.source.source_path.read_bytes()
    try:
        case.source.source_path.write_bytes(body + b"authored source tampering")
        assert repository.get(original.record.id, case.source.user) == original
        assert repository.save(request, case.source.user) == original
    finally:
        case.source.source_path.write_bytes(body)
    assert original.record.storage_configuration_sha256 != "f" * 64
    assert snapshot(case.source.database) == before


@pytest.mark.parametrize("actor", ["learner", "forged", "stale", "inactive"])
def test_current_admin_is_required_for_candidate_creation_and_history(candidate_case, actor):
    case, _, request, repository = candidate_case
    user = (
        case.source.learner
        if actor == "learner"
        else replace(case.source.learner, role="admin")
        if actor == "forged"
        else replace(case.source.user, auth_version=2)
        if actor == "stale"
        else case.source.user
    )
    if actor == "inactive":
        with connect_database(case.source.database) as connection:
            connection.execute("UPDATE regintel.users SET is_active=false WHERE id=%s", (user.id,))
    before = snapshot(case.source.database)
    with pytest.raises(NumericalAuthorizationError):
        repository.save(request, user)
    with pytest.raises(NumericalAuthorizationError):
        repository.get(str(uuid4()), user)
    assert snapshot(case.source.database) == before


def test_new_candidate_requires_fresh_approvals_and_exact_selected_input(candidate_case):
    case, gate, request, repository = candidate_case
    before = snapshot(case.source.database)
    with pytest.raises(NumericalReviewConflict):
        repository.save(
            request.model_copy(update={"prepared_input_id": str(uuid4())}), case.source.user
        )
    assert snapshot(case.source.database) == before
    entity = gate.source_input.context.source_input.registry.entities[0]
    EntityRepository(case.source.database).register(
        EntityRegistration(
            id=str(uuid4()),
            kind="COMPANY",
            legal_name=entity.legal_name,
            legal_name_support=entity.legal_name_support,
            identifiers=(),
            review_note="Authored changed registry.",
        ),
        case.source.user,
    )
    before = snapshot(case.source.database)
    with pytest.raises(NumericalReviewConflict):
        repository.save(request, case.source.user)
    assert snapshot(case.source.database) == before


@pytest.mark.parametrize("action", ["UPDATE", "DELETE", "TRUNCATE"])
def test_candidate_rows_cannot_be_changed_or_discarded(candidate_case, action):
    case, _, request, repository = candidate_case
    original = repository.save(request, case.source.user)
    before = snapshot(case.source.database)
    command = (
        "UPDATE regintel.numerical_candidates SET auth_version=auth_version+1"
        if action == "UPDATE"
        else action
        + " "
        + ("FROM " if action == "DELETE" else "")
        + "regintel.numerical_candidates"
    )
    with connect_database(case.source.database) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute(command)
        connection.rollback()
    assert repository.get(original.record.id, case.source.user) == original
    assert snapshot(case.source.database) == before


@pytest.mark.parametrize(
    "change",
    [
        "acceptance",
        "mandatory",
        "publish",
        "preparation_authority",
        "input_authority",
        "quantity",
        "proof",
        "review",
        "actor",
        "checks",
    ],
)
def test_database_guard_rejects_rehashed_candidate_injection(candidate_case, change):
    case, _, request, repository = candidate_case
    original = repository.save(request, case.source.user)
    # Insert the same correctly identified source into a rolled-back transaction;
    # the BEFORE INSERT guard must reject tampering before uniqueness is checked.
    value = original.preparation.model_dump(mode="json")
    record = original.record.model_dump(mode="json")
    if change in {"acceptance", "mandatory", "publish"}:
        record[
            {
                "acceptance": "acceptance_eligible",
                "mandatory": "mandatory_m1_validation_complete",
                "publish": "publishes_fact",
            }[change]
        ] = True
    elif change == "preparation_authority":
        value["acceptance_eligible"] = True
    elif change == "input_authority":
        value["proposed_input"]["mandatory_m1_validation_complete"] = True
    elif change == "quantity":
        value["proposed_input"]["quantity"]["normalized_value"] = "1"
    elif change == "proof":
        value["proposed_input"]["proof"]["phrases"][0]["words"].pop()
    elif change == "review":
        value["proposed_input"]["context_review"]["request"]["note"] = "Forged authored review."
    elif change == "actor":
        record["submitted_by"] = str(case.source.learner.id)
    else:
        value["checks"].pop()
    preparation = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    record["preparation_sha256"] = hashlib.sha256(preparation).hexdigest()
    body = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    before = snapshot(case.source.database)
    prepared = original.preparation.proposed_input
    with connect_database(case.source.database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO regintel.numerical_candidates "
                "(id,gate_run_id,prepared_input_id,parse_version_id,context_review_id,record_bytes,record_sha256,"
                "preparation_bytes,preparation_sha256,storage_configuration_sha256,"
                "submitted_by,auth_version) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    original.record.id,
                    request.gate_run_id,
                    request.prepared_input_id,
                    prepared.proof.parse_version_id,
                    prepared.context_review.id,
                    body,
                    hashlib.sha256(body).hexdigest(),
                    preparation,
                    hashlib.sha256(preparation).hexdigest(),
                    original.record.storage_configuration_sha256,
                    case.source.user.id,
                    case.source.user.auth_version,
                ),
            )
        connection.rollback()
    assert snapshot(case.source.database) == before


@pytest.mark.parametrize("decision", [None, "REJECT"])
def test_candidate_requires_an_actual_supported_context_confirmation(reviewed_case, decision):
    case, gate, proposal, reviews = reviewed_case
    if decision:
        reviews.save(proposal.model_copy(update={"decision": decision}), case.source.user)
    request = NumericalCandidateRequest(gate_run_id=gate.result.id, prepared_input_id=str(uuid4()))
    repository = NumericalCandidateRepository(reviews.source)
    before = snapshot(case.source.database)
    with pytest.raises(NumericalReviewConflict):
        repository.save(request, case.source.user)
    assert snapshot(case.source.database) == before


def test_new_candidate_cannot_use_changed_original_bytes(candidate_case):
    case, _, request, repository = candidate_case
    original = case.source.source_path.read_bytes()
    before = snapshot(case.source.database)
    try:
        case.source.source_path.write_bytes(original + b"authored tampering")
        with pytest.raises(NumericalReviewConflict):
            repository.save(request, case.source.user)
    finally:
        case.source.source_path.write_bytes(original)
    assert snapshot(case.source.database) == before
