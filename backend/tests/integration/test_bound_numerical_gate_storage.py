"""Actual M1 binding/gate history on authored PDFs in owned disposable PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import psycopg
import pytest

from backend.tests.integration.test_numerical_binding_storage import StoredBindingFixture
from backend.tests.integration.test_numerical_binding_storage import binding as binding
from backend.tests.integration.test_numerical_context_storage import inspection as inspection
from backend.tests.integration.test_numerical_context_storage import snapshot
from regintel.db.migrations import connect_database
from regintel.numerical.gate_repository import BoundNumericalGateRepository
from regintel.numerical.repository import NumericalAuthorizationError, NumericalNotFound

pytestmark = pytest.mark.integration


def run(binding: StoredBindingFixture):
    source = binding.source
    repository = BoundNumericalGateRepository(source.source)
    value = repository.run(binding.case.record.id, binding.case.artifact.id, source.user)
    return repository, value


def test_gate_history_uses_actual_m1_words_replays_and_creates_no_authority(binding):
    repository, value = run(binding)
    source = binding.source
    before = snapshot(source.database)
    assert repository.get(value.result.id, source.user) == value
    assert repository.run(binding.case.record.id, binding.case.artifact.id, source.user) == value
    assert snapshot(source.database) == before
    assert value.result.state == "REVIEW_REQUIRED"
    assert value.result.evidence_ids and value.result.quantity_proposal is not None
    assert (
        not value.result.acceptance_eligible and not value.result.mandatory_m1_validation_complete
    )
    with connect_database(source.database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM regintel.bound_numerical_gate_runs"
        ).fetchone() == (1,)
        for table in ("fact_observations", "acceptance_audits", "corpus_versions"):
            assert connection.execute(f"SELECT count(*) FROM regintel.{table}").fetchone() == (0,)


def test_concurrent_identical_gate_runs_commit_one_exact_history(binding):
    source = binding.source
    repository = BoundNumericalGateRepository(source.source)
    with ThreadPoolExecutor(max_workers=2) as workers:
        calls = [
            workers.submit(
                repository.run, binding.case.record.id, binding.case.artifact.id, source.user
            )
            for _ in range(2)
        ]
        results = [call.result(timeout=60) for call in calls]
    assert results[0] == results[1]
    with connect_database(source.database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM regintel.bound_numerical_gate_runs"
        ).fetchone() == (1,)


@pytest.mark.parametrize("actor", ["learner", "forged", "stale", "inactive"])
def test_gate_run_rechecks_current_administrator(binding, actor):
    source = binding.source
    candidate = (
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
    with pytest.raises(NumericalAuthorizationError):
        BoundNumericalGateRepository(source.source).run(
            binding.case.record.id, binding.case.artifact.id, candidate
        )
    assert snapshot(source.database) == before


@pytest.mark.parametrize("action", ["UPDATE", "DELETE", "TRUNCATE"])
def test_gate_history_is_immutable(binding, action):
    _, value = run(binding)
    source = binding.source
    before = snapshot(source.database)
    with pytest.raises(psycopg.Error), connect_database(source.database) as connection:
        statement = (
            "UPDATE regintel.bound_numerical_gate_runs SET id=id"
            if action == "UPDATE"
            else "DELETE FROM regintel.bound_numerical_gate_runs"
            if action == "DELETE"
            else "TRUNCATE regintel.bound_numerical_gate_runs CASCADE"
        )
        connection.execute(statement)
    assert snapshot(source.database) == before
    assert value.result.id


def test_gate_storage_failure_rolls_back_and_retains_original_context(binding, monkeypatch):
    source = binding.source
    before = snapshot(source.database)
    original = __import__(
        "regintel.numerical.gate_repository", fromlist=["validate_bound_numerical"]
    ).validate_bound_numerical

    def wrong(packet):
        return original(packet).model_copy(update={"source_sha256": "f" * 64})

    monkeypatch.setattr("regintel.numerical.gate_repository.validate_bound_numerical", wrong)
    from regintel.numerical.repository import NumericalSourceError

    with pytest.raises(NumericalSourceError):
        run(binding)
    assert snapshot(source.database) == before


def test_unknown_gate_is_not_visible_and_learner_cannot_read_history(binding):
    repository, value = run(binding)
    before = snapshot(binding.source.database)
    with pytest.raises(NumericalNotFound):
        repository.get(str(uuid4()), binding.source.user)
    with pytest.raises(NumericalAuthorizationError):
        repository.get(value.result.id, binding.source.learner)
    assert snapshot(binding.source.database) == before
