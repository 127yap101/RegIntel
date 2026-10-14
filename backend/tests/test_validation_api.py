"""Admin boundaries, staged review receipts and safe validation failures."""

from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Literal
from uuid import UUID

import httpx2
import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.tests.test_candidate_models import ALPHA, make_input, metric
from backend.tests.test_entity_api import Users
from regintel.auth.config import AuthSettings
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.auth.types import User
from regintel.candidates.extraction import current_configuration as extraction_configuration
from regintel.candidates.extraction import extract
from regintel.candidates.records import materialize
from regintel.config import Settings
from regintel.contracts.models import ErrorEnvelope
from regintel.fixtures.sources import fixture_id
from regintel.main import create_app
from regintel.validation.api import (
    PolicyEnvelope,
    ReviewEnvelope,
    ValidationEnvelope,
    ValidationService,
)
from regintel.validation.gate import validate
from regintel.validation.models import (
    NumericMetricPolicy,
    ReviewDecision,
    ValidationInput,
    ValidationRun,
)
from regintel.validation.repository import (
    ValidationAuthorizationError,
    ValidationConflict,
    ValidationNotFound,
    ValidationRepository,
    ValidationSourceError,
    ValidationUnavailable,
)

BASE = "/v1/admin/validation"
Endpoint = Literal["policy", "validate", "read", "review"]


def validation_source() -> ValidationInput:
    source = make_input(
        f"{ALPHA} business is manufacture of solar modules.",
        metrics=(metric(numeric=False, cue="business"),),
    )
    candidate = materialize(source, extraction_configuration(), extract(source))
    return ValidationInput(
        candidate_run=candidate, source=source, source_input_sha256=candidate.input_sha256
    )


class Memory(ValidationRepository):
    """HTTP-only bounded fake; real gates run but SQL has separate live checks."""

    def __init__(self) -> None:
        self.source = validation_source()
        self.policies: dict[str, NumericMetricPolicy] = {}
        self.runs: dict[str, ValidationRun] = {}
        self.decisions: dict[str, ReviewDecision] = {}
        self.calls: list[str] = []
        self.actors: list[User] = []
        self.failure: Exception | None = None

    def called(self, action: str, user: User | None = None) -> None:
        self.calls.append(action)
        if user is not None:
            self.actors.append(user)
        if self.failure is not None:
            raise self.failure

    def register_policy(self, policy: NumericMetricPolicy, user: User) -> bool:
        self.called("policy", user)
        previous = self.policies.get(policy.id)
        if previous is not None:
            if previous != policy:
                raise ValidationConflict("private policy conflict")
            return False
        self.policies[policy.id] = policy
        return True

    def validate(self, candidate_run_id: str, user: User) -> ValidationRun:
        self.called("validate", user)
        if candidate_run_id != self.source.candidate_run.id:
            raise ValidationNotFound("private missing candidate run")
        run = validate(self.source)
        self.runs[run.id] = run
        return run

    def get_run(self, run_id: str) -> ValidationRun | None:
        self.called("read")
        return self.runs.get(run_id)

    def reviews(self, run_id: str) -> tuple[ReviewDecision, ...]:
        self.called("reviews")
        return tuple(item for item in self.decisions.values() if item.validation_run_id == run_id)

    def review(self, decision: ReviewDecision, user: User) -> bool:
        self.called("review", user)
        previous = self.decisions.get(decision.candidate_id)
        if previous is not None:
            if previous != decision:
                raise ValidationConflict("private different audit")
            return False
        self.decisions[decision.candidate_id] = decision
        return True


@dataclass
class Boundary:
    client: TestClient
    user: User
    users: Users
    token: str
    memory: Memory

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def decision(self) -> ReviewDecision:
        run = next(iter(self.memory.runs.values()), validate(self.memory.source))
        draft = self.memory.source.candidate_run.bundle.narrative_facts[0]
        return ReviewDecision(
            id=fixture_id(500),
            validation_run_id=run.id,
            candidate_id=run.results[0].candidate_id,
            decision="APPROVE_FOR_PUBLICATION",
            supports=draft.supports,
            review_note="Synthetic exact narrative inspected; staged only.",
        )

    def request(self, endpoint: Endpoint, headers: dict[str, str] | None = None) -> httpx2.Response:
        headers = self.headers if headers is None else headers
        if endpoint == "policy":
            policy = NumericMetricPolicy(
                id=fixture_id(501),
                metric_id=fixture_id(502),
                quantity_kind="MONEY",
                period_kind="DURATION",
                allowed_unit_labels=("crore",),
                review_note="Synthetic metric policy.",
            )
            return self.client.post(
                BASE + "/policies", headers=headers, json=policy.model_dump(mode="json")
            )
        if endpoint == "validate":
            return self.client.post(
                BASE + "/runs",
                headers=headers,
                json={"candidate_run_id": self.memory.source.candidate_run.id},
            )
        if endpoint == "read":
            run_id = next(iter(self.memory.runs), fixture_id(999))
            return self.client.get(BASE + "/runs/" + run_id, headers=headers)
        return self.client.post(
            BASE + "/reviews", headers=headers, json=self.decision().model_dump(mode="json")
        )


@pytest.fixture
def boundary() -> Iterator[Boundary]:
    user = User(UUID(fixture_id(1)), "admin", SecretStr("unused fixture hash"), "admin", True, 1)
    users = Users(user)
    settings = AuthSettings(jwt_secret=SecretStr("ef" * 32))
    auth = AuthService(users, settings)
    memory = Memory()
    with TestClient(
        create_app(
            Settings(environment="test"),
            auth_service=auth,
            validation_service=ValidationService(memory),
        )
    ) as client:
        yield Boundary(client, user, users, issue_token(user, settings), memory)


def assert_error(response: httpx2.Response, status: int) -> None:
    assert response.status_code == status
    result = ErrorEnvelope.model_validate_json(response.text)
    assert result.meta.request_id == response.headers["x-request-id"]
    assert result.meta.versions.corpus_version_id is None
    assert response.headers["cache-control"] == "no-store"
    assert "private" not in response.text
    assert "fixture hash" not in response.text


def test_gate_run_and_staged_review_replay(boundary: Boundary) -> None:
    first = PolicyEnvelope.model_validate_json(boundary.request("policy").text)
    second = PolicyEnvelope.model_validate_json(boundary.request("policy").text)
    assert first.data.already_exists is False and second.data.already_exists is True
    created = boundary.request("validate")
    repeated = boundary.request("validate")
    assert created.status_code == repeated.status_code == 200
    initial = ValidationEnvelope.model_validate_json(created.text)
    replay = ValidationEnvelope.model_validate_json(repeated.text)
    assert initial.data.run == replay.data.run
    assert initial.meta.request_id != replay.meta.request_id
    assert initial.meta.versions.parse_version_id == boundary.memory.source.source.parse_version_id
    assert initial.meta.versions.corpus_version_id is None
    assert initial.data.run.results[0].state == "REVIEW"
    assert initial.data.run.results[0].reviewer_eligible is True
    approved = ReviewEnvelope.model_validate_json(boundary.request("review").text)
    decision_replay = ReviewEnvelope.model_validate_json(boundary.request("review").text)
    assert approved.data.already_exists is False and decision_replay.data.already_exists is True
    read = ValidationEnvelope.model_validate_json(boundary.request("read").text)
    assert read.data.reviews == (boundary.decision(),)
    assert read.data.run == initial.data.run
    assert boundary.memory.source.candidate_run.candidates[0].state == "CANDIDATE"


@pytest.mark.parametrize("endpoint", ("policy", "validate", "read", "review"))
@pytest.mark.parametrize("mode", ("anonymous", "learner", "inactive", "revoked", "deleted"))
def test_permissions_precede_storage(boundary: Boundary, endpoint: Endpoint, mode: str) -> None:
    headers = boundary.headers
    status = 401
    if mode == "anonymous":
        headers = {}
    elif mode == "learner":
        boundary.users.user = replace(boundary.user, role="learner")
        status = 403
    elif mode == "inactive":
        boundary.users.user = replace(boundary.user, is_active=False)
    elif mode == "revoked":
        boundary.users.user = replace(boundary.user, auth_version=2)
    else:
        boundary.users.user = None
    assert_error(boundary.request(endpoint, headers), status)
    assert boundary.memory.calls == []


@pytest.mark.parametrize("endpoint", ("policy", "validate", "read", "review"))
@pytest.mark.parametrize(
    "failure,status",
    (
        (ValidationAuthorizationError("private permission"), 403),
        (ValidationUnavailable("private outage"), 503),
        (ValidationNotFound("private missing"), 404),
        (ValidationConflict("private conflict"), 409),
        (ValidationSourceError("private support"), 422),
        (ValueError("private shape"), 422),
        (psycopg.OperationalError("private db"), 503),
        (OSError("private I/O"), 503),
        (RuntimeError("private unexpected"), 500),
    ),
)
def test_sanitized_failures(
    boundary: Boundary, endpoint: Endpoint, failure: Exception, status: int
) -> None:
    boundary.memory.failure = failure
    assert_error(boundary.request(endpoint), status)


@pytest.mark.parametrize(
    "body",
    (
        {"candidate_run_id": "invalid"},
        {"candidate_run_id": fixture_id(100), "checks": []},
        {"candidate_run_id": fixture_id(100), "state": "PASS"},
        {"candidate_run_id": fixture_id(100), "reviewer_eligible": True},
        {"candidate_run_id": fixture_id(100), "configuration": {}},
    ),
)
def test_clients_cannot_supply_gate_results(boundary: Boundary, body: dict[str, object]) -> None:
    assert_error(boundary.client.post(BASE + "/runs", headers=boundary.headers, json=body), 422)
    assert not boundary.memory.calls


def test_review_cannot_publish_or_accept_observations(boundary: Boundary) -> None:
    body = boundary.decision().model_dump(mode="json")
    for decision in ("ACCEPT", "ACCEPTED", "PUBLISH"):
        body["decision"] = decision
        assert_error(
            boundary.client.post(BASE + "/reviews", headers=boundary.headers, json=body), 422
        )
    assert not boundary.memory.calls
    schema = boundary.client.get("/openapi.json").json()
    assert all("publish" not in path and "accept" not in path for path in schema["paths"])
    for path, method in (
        (BASE + "/policies", "post"),
        (BASE + "/runs", "post"),
        (BASE + "/runs/{run_id}", "get"),
        (BASE + "/reviews", "post"),
    ):
        assert schema["paths"][path][method]["security"]


def test_unconfigured_service_reports_503_after_auth(boundary: Boundary) -> None:
    auth = AuthService(boundary.users, AuthSettings(jwt_secret=SecretStr("ef" * 32)))
    with TestClient(create_app(Settings(environment="test"), auth_service=auth)) as client:
        path = BASE + "/runs/" + fixture_id(999)
        assert_error(client.get(path, headers=boundary.headers), 503)
        assert_error(client.get(path), 401)
