"""Actual owned PostgreSQL decisions over labelled authored numerical candidates."""

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
from backend.tests.integration.test_numerical_candidate_storage import (
    candidate_case as candidate_case,
)
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
from regintel.numerical import acceptance_repository as storage_module
from regintel.numerical.acceptance_models import NumericalAcceptanceRequest
from regintel.numerical.acceptance_repository import NumericalAcceptanceRepository
from regintel.numerical.repository import NumericalAuthorizationError, NumericalNotFound
from regintel.numerical.review_repository import NumericalReviewConflict

pytestmark = pytest.mark.integration


@pytest.fixture
def acceptance_case(candidate_case):
    case, gate, proposal, candidates = candidate_case
    candidate = candidates.save(proposal, case.source.user)
    request = NumericalAcceptanceRequest(
        candidate_id=candidate.record.id,
        decision="ACCEPT",
        evidence_ids=gate.result.evidence_ids,
        note="Authored numerical acceptance, not a real source review.",
    )
    return case, candidate, request, NumericalAcceptanceRepository(candidates.source)


@pytest.mark.parametrize("decision", ["ACCEPT", "REJECT"])
def test_decision_is_durable_and_creates_no_public_observation_or_corpus(acceptance_case, decision):
    case, candidate, request, repository = acceptance_case
    request = request.model_copy(update={"decision": decision})
    before = snapshot(case.source.database)
    stored = repository.save(request, case.source.user)
    assert stored.candidate == candidate
    assert stored.record.reviewed_by == str(case.source.user.id)
    assert stored.record.mandatory_m1_validation_complete == (decision == "ACCEPT")
    assert stored.record.checks == (candidate.preparation.checks if decision == "ACCEPT" else ())
    assert not stored.record.publishes_fact and stored.record.published_corpus_version_id is None
    after = snapshot(case.source.database)
    assert {name for name in before if before[name] != after[name]} == {"numerical_acceptances"}
    assert repository.get(candidate.record.id, case.source.user) == stored
    assert repository.save(request, case.source.user) == stored
    assert snapshot(case.source.database) == after


def test_simultaneous_identical_decisions_keep_one_record_and_original_actor(acceptance_case):
    case, candidate, request, repository = acceptance_case
    seed_users(
        case.source.database,
        (
            SeedAccount(
                "other-acceptance-admin", SecretStr("Authored acceptance administrator!"), "admin"
            ),
        ),
    )
    other = PostgreSQLAuthRepository(case.source.database).get_by_username("other-acceptance-admin")
    assert other is not None
    barrier = Barrier(2)

    def decide(user):
        barrier.wait(timeout=30)
        return repository.save(request, user)

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(decide, user) for user in (case.source.user, other)]
        values = [future.result(timeout=60) for future in futures]
    assert values[0] == values[1]
    assert values[0].record.reviewed_by in {str(case.source.user.id), str(other.id)}
    with connect_database(case.source.database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM regintel.numerical_acceptances"
        ).fetchone() == (1,)
    assert repository.get(candidate.record.id, case.source.user) == values[0]


def test_simultaneous_conflicting_decisions_commit_only_one(acceptance_case):
    case, _, request, repository = acceptance_case
    barrier = Barrier(2)

    def decide(decision):
        barrier.wait(timeout=30)
        try:
            return repository.save(
                request.model_copy(update={"decision": decision}), case.source.user
            )
        except NumericalReviewConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(decide, decision) for decision in ("ACCEPT", "REJECT")]
        values = [future.result(timeout=60) for future in futures]
    assert sum(value is not None for value in values) == 1
    stored = repository.get(request.candidate_id, case.source.user)
    assert stored in values


@pytest.mark.parametrize("change", ["decision", "note", "evidence"])
def test_existing_decision_cannot_be_overwritten_by_changed_request(acceptance_case, change):
    case, _, request, repository = acceptance_case
    stored = repository.save(request, case.source.user)
    updated = {"decision": "REJECT"} if change == "decision" else {"note": "Changed explanation."}
    if change == "evidence":
        updated = {"evidence_ids": request.evidence_ids[:-1]}
    before = snapshot(case.source.database)
    with pytest.raises(NumericalReviewConflict):
        repository.save(request.model_copy(update=updated), case.source.user)
    assert repository.get(request.candidate_id, case.source.user) == stored
    assert snapshot(case.source.database) == before


def test_historical_retry_keeps_original_configuration_after_source_changes(
    acceptance_case, monkeypatch
):
    case, _, request, repository = acceptance_case
    stored = repository.save(request, case.source.user)
    before = snapshot(case.source.database)
    monkeypatch.setattr(storage_module, "acceptance_configuration_sha256", lambda: "f" * 64)
    original = case.source.source_path.read_bytes()
    try:
        case.source.source_path.write_bytes(original + b"authored tampering after acceptance")
        assert repository.get(request.candidate_id, case.source.user) == stored
        assert repository.save(request, case.source.user) == stored
    finally:
        case.source.source_path.write_bytes(original)
    assert stored.record.configuration_sha256 != "f" * 64
    assert snapshot(case.source.database) == before


@pytest.mark.parametrize("actor", ["learner", "forged", "stale", "inactive", "demoted"])
def test_current_admin_is_required_for_new_decisions_and_history(acceptance_case, actor):
    case, _, request, repository = acceptance_case
    repository.save(request, case.source.user)
    user = (
        case.source.learner
        if actor == "learner"
        else replace(case.source.learner, role="admin")
        if actor == "forged"
        else replace(case.source.user, auth_version=2)
        if actor == "stale"
        else case.source.user
    )
    if actor in {"inactive", "demoted"}:
        with connect_database(case.source.database) as connection:
            statement = (
                "UPDATE regintel.users SET is_active=false WHERE id=%s"
                if actor == "inactive"
                else "UPDATE regintel.users SET role='learner' WHERE id=%s"
            )
            connection.execute(statement, (user.id,))
    before = snapshot(case.source.database)
    with pytest.raises(NumericalAuthorizationError):
        repository.save(request, user)
    with pytest.raises(NumericalAuthorizationError):
        repository.get(request.candidate_id, user)
    assert snapshot(case.source.database) == before


def test_acceptance_requires_fresh_original_bytes_but_rejection_claims_no_recheck(acceptance_case):
    case, _, request, repository = acceptance_case
    original = case.source.source_path.read_bytes()
    before = snapshot(case.source.database)
    try:
        case.source.source_path.write_bytes(original + b"authored tampering before acceptance")
        with pytest.raises(NumericalReviewConflict):
            repository.save(request, case.source.user)
        assert snapshot(case.source.database) == before
        rejected = repository.save(
            request.model_copy(update={"decision": "REJECT"}), case.source.user
        )
        assert rejected.record.checks == () and not rejected.record.mandatory_m1_validation_complete
    finally:
        case.source.source_path.write_bytes(original)


def test_acceptance_refuses_changed_approval_snapshot(acceptance_case):
    case, candidate, request, repository = acceptance_case
    entity = candidate.preparation.proposed_input.subject_entity_id
    with connect_database(case.source.database) as connection:
        row = connection.execute(
            "SELECT registration_bytes FROM regintel.entity_registrations WHERE id=%s", (entity,)
        ).fetchone()
    retained = EntityRegistration.model_validate_json(bytes(row[0]))
    EntityRepository(case.source.database).register(
        retained.model_copy(update={"id": str(uuid4()), "identifiers": ()}), case.source.user
    )
    before = snapshot(case.source.database)
    with pytest.raises(NumericalReviewConflict):
        repository.save(request, case.source.user)
    assert snapshot(case.source.database) == before


def test_acceptance_refuses_old_candidate_storage_contract(acceptance_case, monkeypatch):
    case, _, request, repository = acceptance_case
    before = snapshot(case.source.database)
    monkeypatch.setattr(storage_module, "candidate_storage_configuration_sha256", lambda: "f" * 64)
    with pytest.raises(NumericalReviewConflict):
        repository.save(request, case.source.user)
    assert snapshot(case.source.database) == before


def test_unknown_candidate_and_incomplete_evidence_cannot_create_a_decision(acceptance_case):
    case, _, request, repository = acceptance_case
    before = snapshot(case.source.database)
    with pytest.raises(NumericalNotFound):
        repository.save(request.model_copy(update={"candidate_id": str(uuid4())}), case.source.user)
    with pytest.raises(NumericalNotFound):
        repository.get(request.candidate_id, case.source.user)
    with pytest.raises(NumericalReviewConflict):
        repository.save(
            request.model_copy(update={"evidence_ids": request.evidence_ids[:-1]}), case.source.user
        )
    assert snapshot(case.source.database) == before


@pytest.mark.parametrize("action", ["UPDATE", "DELETE", "TRUNCATE"])
def test_acceptance_rows_cannot_be_changed_or_discarded(acceptance_case, action):
    case, _, request, repository = acceptance_case
    stored = repository.save(request, case.source.user)
    before = snapshot(case.source.database)
    statement = (
        "UPDATE regintel.numerical_acceptances SET auth_version=auth_version+1"
        if action == "UPDATE"
        else action
        + " "
        + ("FROM " if action == "DELETE" else "")
        + "regintel.numerical_acceptances"
    )
    with connect_database(case.source.database) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute(statement)
        connection.rollback()
    assert repository.get(request.candidate_id, case.source.user) == stored
    assert snapshot(case.source.database) == before


@pytest.mark.parametrize(
    "change",
    ["actor", "checks", "evidence", "state", "mandatory", "publish", "corpus", "hash", "extra"],
)
def test_database_guard_rejects_rehashed_decision_injection(acceptance_case, change):
    case, _, request, repository = acceptance_case
    stored = repository.save(request, case.source.user)
    value = stored.record.model_dump(mode="json")
    if change == "actor":
        value["reviewed_by"] = str(case.source.learner.id)
    elif change == "checks":
        value["checks"].pop()
    elif change == "evidence":
        value["request"]["evidence_ids"].pop()
    elif change == "state":
        value["state"] = "REJECTED"
    elif change == "mandatory":
        value["mandatory_m1_validation_complete"] = False
    elif change == "publish":
        value["publishes_fact"] = True
    elif change == "corpus":
        value["published_corpus_version_id"] = str(uuid4())
    elif change == "hash":
        value["candidate_record_sha256"] = "f" * 64
    else:
        value["invented_authority"] = True
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    before = snapshot(case.source.database)
    with connect_database(case.source.database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO regintel.numerical_acceptances "
                "(id,candidate_id,candidate_record_sha256,candidate_preparation_sha256,configuration_sha256,"
                "decision,record_bytes,record_sha256,reviewed_by,auth_version) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    stored.record.id,
                    request.candidate_id,
                    stored.record.candidate_record_sha256,
                    stored.record.candidate_preparation_sha256,
                    stored.record.configuration_sha256,
                    "ACCEPT",
                    payload,
                    hashlib.sha256(payload).hexdigest(),
                    case.source.user.id,
                    case.source.user.auth_version,
                ),
            )
        connection.rollback()
    assert snapshot(case.source.database) == before
