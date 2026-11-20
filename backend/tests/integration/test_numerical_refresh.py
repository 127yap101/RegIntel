"""Refresh authored source checks without transferring review/acceptance authority."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from secrets import token_hex
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.tests.integration.test_bound_numerical_gate_storage import run
from backend.tests.integration.test_numerical_applicability_storage import (
    applicability_case as applicability_case,
)
from backend.tests.integration.test_numerical_binding_storage import binding as binding
from backend.tests.integration.test_numerical_context_storage import inspection as inspection
from backend.tests.integration.test_numerical_context_storage import snapshot
from regintel.auth.config import AuthSettings
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.candidates.models import MetricDefinition
from regintel.candidates.repository import CandidateRepository
from regintel.config import Settings
from regintel.entities.models import canonical_bytes
from regintel.main import create_app
from regintel.numerical.gate_models import BoundGateInput
from regintel.numerical.gate_repository import BoundNumericalGateRepository
from regintel.numerical.refresh_models import NumericalRefreshRequest
from regintel.numerical.refresh_repository import NumericalRefreshRepository
from regintel.numerical.repository import NumericalAuthorizationError, NumericalSourceError
from regintel.numerical.resolved_gate_repository import ResolvedNumericalGateRepository
from regintel.numerical.review_repository import (
    NumericalContextReviewRepository,
    NumericalReviewConflict,
)
from regintel.validation.models import NumericMetricPolicy
from regintel.validation.repository import ValidationRepository

pytestmark = pytest.mark.integration


def request_for(gate):
    return NumericalRefreshRequest(
        gate_run_id=gate.result.id,
        gate_input_sha256=gate.result.input_sha256,
        gate_result_sha256=hashlib.sha256(canonical_bytes(gate.result)).hexdigest(),
    )


def register_policy(source):
    return ValidationRepository(source.database).register_policy(
        NumericMetricPolicy(
            id=str(uuid4()),
            metric_id=source.draft.metric_id,
            quantity_kind="MONEY",
            period_kind="DURATION",
            allowed_unit_labels=("million",),
            review_note="Authored test policy; not a real content approval.",
        ),
        source.user,
    )


def test_unchanged_refresh_replays_without_new_rows(binding):
    history, original = run(binding)
    source = binding.source
    repository = NumericalRefreshRepository(source.source)
    before = snapshot(source.database)
    refreshed = repository.refresh(request_for(original), source.user)
    assert refreshed.gate == original
    assert repository.refresh(request_for(original), source.user) == refreshed
    assert history.get(original.result.id, source.user) == original
    assert snapshot(source.database) == before


@pytest.mark.parametrize("inspection", ["no_metric", "no_policy"], indirect=True)
def test_fresh_approvals_create_new_context_and_gate_without_grafting_history(binding):
    history, original = run(binding)
    source = binding.source
    if original.source_input.context.source_input.metric is None:
        CandidateRepository(source.database).register_metric(
            MetricDefinition(
                id=source.draft.metric_id,
                key="authored_revenue",
                label="Authored revenue",
                kind="numeric_fact",
                cue_phrases=("Revenue from operations",),
            ),
            source.user,
        )
    register_policy(source)
    stale = history.run(binding.case.record.id, binding.case.artifact.id, source.user)
    assert next(c for c in stale.result.checks if c.code == "FRESH_CONTEXT").state == "REVIEW"
    before = snapshot(source.database)
    repository = NumericalRefreshRepository(source.source)
    refreshed = repository.refresh(request_for(original), source.user)
    gate = refreshed.gate
    assert gate.result.id != original.result.id
    assert gate.result.context_record_id != original.result.context_record_id
    assert (
        gate.source_input.context.source_input.draft
        == original.source_input.context.source_input.draft
    )
    assert gate.source_input.binding.phrases == original.source_input.binding.phrases
    assert gate.source_input.binding.cells == original.source_input.binding.cells
    assert gate.result.evidence_ids == original.result.evidence_ids
    assert all(
        c.state == "PASS"
        for c in gate.result.checks
        if c.code in {"METRIC", "UNIT", "FRESH_CONTEXT"}
    )
    assert not gate.result.acceptance_eligible
    assert gate.result.state == "REVIEW_REQUIRED"
    after = snapshot(source.database)
    assert {name for name in before if before[name] != after[name]} == {
        "numerical_context_records",
        "numerical_context_pages",
        "bound_numerical_gate_runs",
    }
    assert history.get(original.result.id, source.user) == original
    assert repository.refresh(request_for(original), source.user) == refreshed
    assert snapshot(source.database) == after


@pytest.mark.parametrize("inspection", ["no_policy"], indirect=True)
def test_context_and_gate_write_roll_back_together(binding, monkeypatch):
    _, original = run(binding)
    source = binding.source
    register_policy(source)
    before = snapshot(source.database)

    def fail(*args):
        raise NumericalSourceError("Authored post-context failure")

    monkeypatch.setattr(BoundNumericalGateRepository, "_run_in_transaction", fail)
    with pytest.raises(NumericalSourceError):
        NumericalRefreshRepository(source.source).refresh(request_for(original), source.user)
    assert snapshot(source.database) == before


@pytest.mark.parametrize("kind", ["learner", "forged", "stale", "input", "result", "source"])
def test_invalid_actor_selection_or_source_cannot_refresh(binding, kind):
    _, original = run(binding)
    source = binding.source
    user = (
        source.learner
        if kind == "learner"
        else replace(source.learner, role="admin")
        if kind == "forged"
        else replace(source.user, auth_version=2)
        if kind == "stale"
        else source.user
    )
    request = request_for(original)
    if kind in {"input", "result"}:
        request = request.model_copy(update={f"gate_{kind}_sha256": "0" * 64})
    if kind == "source":
        source.source_path.write_bytes(b"authored tampered source")
    before = snapshot(source.database)
    with pytest.raises(
        (NumericalAuthorizationError, NumericalReviewConflict, NumericalSourceError)
    ):
        NumericalRefreshRepository(source.source).refresh(request, user)
    assert snapshot(source.database) == before


def test_refresh_of_resolved_applicability_returns_base_checks_without_carrying_attestation(
    applicability_case,
):
    binding, base, request, reviews = applicability_case
    source = binding.source
    saved = reviews.save(request, source.user)
    resolved = ResolvedNumericalGateRepository(source.source).run(base.result.id, source.user)
    before = snapshot(source.database)
    fresh = NumericalRefreshRepository(source.source).refresh(request_for(resolved), source.user)
    assert type(fresh.gate.source_input) is BoundGateInput
    assert fresh.gate == base and fresh.gate.result.state == "REVIEW_REQUIRED"
    assert reviews.get(base.result.id, source.user) == saved
    assert snapshot(source.database) == before


@pytest.mark.parametrize("inspection", ["no_policy"], indirect=True)
def test_concurrent_identical_refreshes_retain_one_result(binding):
    _, original = run(binding)
    source = binding.source
    register_policy(source)
    repository = NumericalRefreshRepository(source.source)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(repository.refresh, request_for(original), source.user) for _ in range(2)
        ]
        results = [f.result(timeout=60) for f in futures]
    assert results[0] == results[1]
    before = snapshot(source.database)
    assert repository.refresh(request_for(original), source.user) == results[0]
    assert snapshot(source.database) == before


def test_refresh_http_contract_ownership_hash_binding_and_replay(binding):
    _, original = run(binding)
    source = binding.source
    auth_settings = AuthSettings(jwt_secret=SecretStr(token_hex(32)))
    auth = AuthService(PostgreSQLAuthRepository(source.database), auth_settings)
    app = create_app(
        Settings(environment="test"),
        auth_service=auth,
        numerical_review_repository=NumericalContextReviewRepository(source.source),
    )
    path = f"/v1/admin/numerical/gates/{original.result.id}/refresh"
    body = request_for(original).model_dump(mode="json")
    headers = {"Authorization": "Bearer " + issue_token(source.user, auth_settings)}
    before = snapshot(source.database)
    with TestClient(app) as client:
        assert client.post(path, json=body).status_code == 401
        assert (
            client.post(
                path,
                json=body,
                headers={"Authorization": "Bearer " + issue_token(source.learner, auth_settings)},
            ).status_code
            == 403
        )
        assert (
            client.post(
                path, json=body | {"gate_run_id": str(uuid4())}, headers=headers
            ).status_code
            == 409
        )
        assert (
            client.post(
                path, json=body | {"gate_result_sha256": "0" * 64}, headers=headers
            ).status_code
            == 409
        )
        assert client.post(path, json=body | {"approve": True}, headers=headers).status_code == 422
        response = client.post(path, json=body, headers=headers)
        assert response.status_code == 200
        result = response.json()
        assert result["data"]["request"] == body
        assert not result["data"]["context_changed"] and not result["data"]["gate_changed"]
        assert not result["data"]["publishes_fact"] and not result["data"]["acceptance_eligible"]
        assert result["data"]["packet"]["review"] is None
        assert all(value is None for value in result["meta"]["versions"].values())
        assert client.post(path, json=body, headers=headers).json()["data"] == result["data"]
    assert snapshot(source.database) == before
