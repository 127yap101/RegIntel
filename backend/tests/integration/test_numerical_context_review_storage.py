"""Actual M1 engineering bindings and immutable, non-publishing context reviews."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from pydantic import SecretStr

from backend.tests.integration import test_numerical_context_storage as contexts
from backend.tests.integration.test_numerical_binding_storage import binding as binding
from backend.tests.integration.test_numerical_context_storage import inspection as inspection
from backend.tests.integration.test_numerical_context_storage import snapshot
from backend.tests.test_numerical_context import Options
from regintel.auth.repository import PostgreSQLAuthRepository, seed_users
from regintel.auth.types import SeedAccount
from regintel.db.migrations import connect_database
from regintel.entities.models import EntityRegistration
from regintel.entities.repository import EntityRepository
from regintel.numerical import review_repository as review_module
from regintel.numerical.gate_repository import BoundNumericalGateRepository
from regintel.numerical.repository import NumericalAuthorizationError, NumericalNotFound
from regintel.numerical.review_models import NumericalContextReviewRequest
from regintel.numerical.review_repository import (
    NumericalContextReviewRepository,
    NumericalReviewConflict,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def supported_header(monkeypatch, request):
    if getattr(request, "param", True):
        original = contexts.authored
        monkeypatch.setattr(
            contexts,
            "authored",
            lambda path: original(path, Options(unit="(INR in million)", currency=())),
        )


@pytest.fixture
def reviewed_case(supported_header, binding):
    source = binding.source
    value = BoundNumericalGateRepository(source.source).run(
        binding.case.record.id, binding.case.artifact.id, source.user
    )
    proposal = NumericalContextReviewRequest(
        gate_run_id=value.result.id,
        decision="CONFIRM_CONTEXT",
        evidence_ids=value.result.evidence_ids,
        note="Authored engineering context decision, not real-filing human review.",
    )
    return binding, value, proposal, NumericalContextReviewRepository(source.source)


def test_confirmed_context_is_immutable_review_only_and_replay_has_no_writes(reviewed_case):
    binding, value, proposal, repository = reviewed_case
    assert value.result.state == "READY_FOR_REVIEW"
    first = repository.save(proposal, binding.source.user)
    before = snapshot(binding.source.database)
    assert repository.get(value.result.id, binding.source.user) == first
    assert repository.save(proposal, binding.source.user) == first
    assert snapshot(binding.source.database) == before
    assert (
        not first.acceptance_eligible
        and not first.mandatory_m1_validation_complete
        and not first.publishes_fact
    )
    with connect_database(binding.source.database) as connection:
        for table in ("fact_observations", "acceptance_audits", "corpus_versions"):
            assert connection.execute(f"SELECT count(*) FROM regintel.{table}").fetchone() == (0,)


@pytest.mark.parametrize("supported_header", [False], indirect=True)
def test_unresolved_real_shape_cannot_be_confirmed_or_overridden(reviewed_case):
    binding, value, proposal, repository = reviewed_case
    assert value.result.state == "REVIEW_REQUIRED"
    before = snapshot(binding.source.database)
    with pytest.raises(NumericalReviewConflict):
        repository.save(proposal, binding.source.user)
    assert snapshot(binding.source.database) == before
    rejected = repository.save(
        proposal.model_copy(update={"decision": "REJECT"}), binding.source.user
    )
    assert rejected.request.decision == "REJECT"


def test_concurrent_identical_reviews_retain_one_exact_original_decision(reviewed_case):
    binding, _, proposal, repository = reviewed_case
    with ThreadPoolExecutor(max_workers=2) as workers:
        calls = [workers.submit(repository.save, proposal, binding.source.user) for _ in range(2)]
        results = [call.result(timeout=60) for call in calls]
    assert results[0] == results[1]
    with connect_database(binding.source.database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM regintel.numerical_context_reviews"
        ).fetchone() == (1,)
    with pytest.raises(NumericalReviewConflict):
        repository.save(proposal.model_copy(update={"decision": "REJECT"}), binding.source.user)


def test_concurrent_admin_retries_preserve_one_original_actor(reviewed_case):
    binding, value, proposal, repository = reviewed_case
    database = binding.source.database
    seed_users(
        database,
        (SeedAccount("other-review-admin", SecretStr("Authored review administrator!"), "admin"),),
    )
    other = PostgreSQLAuthRepository(database).get_by_username("other-review-admin")
    assert other is not None
    barrier = Barrier(2)

    def submit(user):
        barrier.wait(timeout=30)
        return repository.save(proposal, user)

    before = snapshot(database)
    with ThreadPoolExecutor(max_workers=2) as workers:
        calls = [workers.submit(submit, user) for user in (binding.source.user, other)]
        results = [call.result(timeout=60) for call in calls]
    assert results[0] == results[1] == repository.get(value.result.id, other)
    assert results[0].reviewed_by in {str(binding.source.user.id), str(other.id)}
    assert not results[0].publishes_fact and not results[0].acceptance_eligible
    after = snapshot(database)
    for table in ("fact_observations", "acceptance_audits", "corpus_versions"):
        assert after[table] == before[table]
    with connect_database(database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM regintel.numerical_context_reviews"
        ).fetchone() == (1,)


def test_concurrent_conflicting_reviews_commit_only_one_decision(reviewed_case):
    binding, value, proposal, repository = reviewed_case
    barrier = Barrier(2)
    changed = proposal.model_copy(update={"decision": "REJECT"})

    def submit(request):
        barrier.wait(timeout=30)
        try:
            return repository.save(request, binding.source.user)
        except NumericalReviewConflict:
            return None

    before = snapshot(binding.source.database)
    with ThreadPoolExecutor(max_workers=2) as workers:
        calls = [workers.submit(submit, request) for request in (proposal, changed)]
        results = [call.result(timeout=60) for call in calls]
    retained = [result for result in results if result is not None]
    assert len(retained) == 1
    assert repository.get(value.result.id, binding.source.user) == retained[0]
    assert retained[0].request in (proposal, changed)
    assert repository.save(retained[0].request, binding.source.user) == retained[0]
    after = snapshot(binding.source.database)
    for table in ("fact_observations", "acceptance_audits", "corpus_versions"):
        assert after[table] == before[table]
    with connect_database(binding.source.database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM regintel.numerical_context_reviews"
        ).fetchone() == (1,)


def test_historical_review_replays_its_original_configuration(reviewed_case, monkeypatch):
    binding, value, proposal, repository = reviewed_case
    original = repository.save(proposal, binding.source.user)
    before = snapshot(binding.source.database)
    changed_configuration = "f" * 64 if original.configuration_sha256 != "f" * 64 else "e" * 64
    monkeypatch.setattr(review_module, "review_configuration_sha256", lambda: changed_configuration)
    assert repository.get(value.result.id, binding.source.user) == original
    assert repository.save(proposal, binding.source.user) == original
    assert snapshot(binding.source.database) == before


@pytest.mark.parametrize("actor", ["learner", "forged", "stale", "inactive"])
def test_current_administrator_is_required_for_review_and_history(reviewed_case, actor):
    binding, value, proposal, repository = reviewed_case
    source = binding.source
    user = (
        source.learner
        if actor == "learner"
        else replace(source.learner, role="admin")
        if actor == "forged"
        else replace(source.user, auth_version=2)
        if actor == "stale"
        else source.user
    )
    if actor == "inactive":
        with connect_database(source.database) as connection:
            connection.execute(
                "UPDATE regintel.users SET is_active=false WHERE id=%s", (source.user.id,)
            )
    before = snapshot(source.database)
    for action in (
        lambda: repository.save(proposal, user),
        lambda: repository.get(value.result.id, user),
    ):
        with pytest.raises(NumericalAuthorizationError):
            action()
    assert snapshot(source.database) == before


@pytest.mark.parametrize("action", ["UPDATE", "DELETE", "TRUNCATE"])
def test_review_rows_cannot_be_changed_or_discarded(reviewed_case, action):
    binding, _, proposal, repository = reviewed_case
    repository.save(proposal, binding.source.user)
    before = snapshot(binding.source.database)
    statement = (
        "UPDATE regintel.numerical_context_reviews SET id=id"
        if action == "UPDATE"
        else "DELETE FROM regintel.numerical_context_reviews"
        if action == "DELETE"
        else "TRUNCATE regintel.numerical_context_reviews CASCADE"
    )
    with pytest.raises(psycopg.Error), connect_database(binding.source.database) as connection:
        connection.execute(statement)
    assert snapshot(binding.source.database) == before


def test_changed_approved_registry_requires_new_context_instead_of_grafting_review(reviewed_case):
    binding, value, proposal, repository = reviewed_case
    entity = value.source_input.current_context.registry.entities[0]
    EntityRepository(binding.source.database).register(
        EntityRegistration(
            id=str(uuid4()),
            kind="COMPANY",
            legal_name=entity.legal_name,
            legal_name_support=entity.legal_name_support,
            identifiers=(),
            review_note="Separate authored same-name registration; no real entity claim.",
        ),
        binding.source.user,
    )
    before = snapshot(binding.source.database)
    with pytest.raises(NumericalReviewConflict, match="changed"):
        repository.save(proposal, binding.source.user)
    assert snapshot(binding.source.database) == before


def test_partial_evidence_and_unknown_history_are_not_accepted(reviewed_case):
    binding, _, proposal, repository = reviewed_case
    before = snapshot(binding.source.database)
    with pytest.raises(NumericalReviewConflict):
        repository.save(
            proposal.model_copy(update={"evidence_ids": proposal.evidence_ids[:-1]}),
            binding.source.user,
        )
    with pytest.raises(NumericalNotFound):
        repository.get(str(uuid4()), binding.source.user)
    assert snapshot(binding.source.database) == before


def test_changed_physical_source_and_configuration_block_new_reviews(reviewed_case, monkeypatch):
    binding, _, proposal, repository = reviewed_case
    source = binding.source
    before = snapshot(source.database)
    with monkeypatch.context() as patch:
        patch.setattr(review_module, "bound_gate_configuration_sha256", lambda: "f" * 64)
        with pytest.raises(NumericalReviewConflict, match="installed"):
            repository.save(proposal, source.user)
    original = source.source_path.read_bytes()
    try:
        source.source_path.write_bytes(original + b"authored source tampering")
        with pytest.raises(ValueError):
            repository.save(proposal, source.user)
    finally:
        source.source_path.write_bytes(original)
    assert snapshot(source.database) == before


def test_database_guard_rejects_injected_publication_flags_and_rolls_back(
    reviewed_case, monkeypatch
):
    binding, _, proposal, repository = reviewed_case
    original = review_module.ReviewedNumericalContext

    def invalid(**kwargs):
        return original(**kwargs).model_copy(update={"publishes_fact": True})

    monkeypatch.setattr(review_module, "ReviewedNumericalContext", invalid)
    before = snapshot(binding.source.database)
    with pytest.raises(NumericalReviewConflict):
        repository.save(proposal, binding.source.user)
    assert snapshot(binding.source.database) == before
