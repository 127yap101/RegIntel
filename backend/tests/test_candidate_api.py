"""HTTP authorization, metadata and safe failure mapping for raw proposals."""

from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Literal
from uuid import UUID

import httpx2
import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.tests.test_candidate_provider import source
from backend.tests.test_entity_api import Users
from regintel.auth.config import AuthSettings
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.auth.types import User
from regintel.candidates.api import CandidateEnvelope, CandidateService, MetricEnvelope
from regintel.candidates.extraction import current_configuration, extract
from regintel.candidates.models import ExtractionInput, MetricDefinition
from regintel.candidates.records import CandidateRun, materialize
from regintel.candidates.repository import (
    CandidateAuthorizationError,
    CandidateConflict,
    CandidateNotFound,
    CandidateRepository,
    CandidateSourceError,
    CandidateUnavailable,
)
from regintel.config import Settings
from regintel.contracts.models import ErrorEnvelope
from regintel.fixtures.sources import fixture_id
from regintel.main import create_app

BASE = "/v1/admin/candidates"
Endpoint = Literal["metric", "extract", "read"]


class Memory(CandidateRepository):
    """A bounded boundary fake; PostgreSQL gates have separate live tests."""

    def __init__(self, fixture: ExtractionInput) -> None:
        self.fixture = fixture
        self.definitions: dict[str, MetricDefinition] = {}
        self.runs: dict[str, CandidateRun] = {}
        self.calls: list[str] = []
        self.actors: list[User] = []
        self.failure: Exception | None = None

    def called(self, action: str, user: User | None = None) -> None:
        self.calls.append(action)
        if user is not None:
            self.actors.append(user)
        if self.failure is not None:
            raise self.failure

    def register_metric(self, metric: MetricDefinition, user: User) -> bool:
        self.called("metric", user)
        previous = self.definitions.get(metric.id)
        if previous is not None:
            if previous != metric:
                raise CandidateConflict("private conflict")
            return False
        self.definitions[metric.id] = metric
        return True

    def extract(self, entity_run_id: str, metric_ids: tuple[str, ...], user: User) -> CandidateRun:
        self.called("extract", user)
        if entity_run_id != self.fixture.entity_run.id:
            raise CandidateNotFound("private missing run")
        fixture = self.fixture.model_copy(
            update={
                "metrics": tuple(
                    metric for metric in self.fixture.metrics if metric.id in metric_ids
                )
            }
        )
        run = materialize(fixture, current_configuration(), extract(fixture))
        self.runs[run.id] = run
        return run

    def get_run(self, run_id: str) -> CandidateRun | None:
        self.called("read")
        return self.runs.get(run_id)


@dataclass
class Boundary:
    client: TestClient
    users: Users
    user: User
    token: str
    memory: Memory

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def request(self, endpoint: Endpoint, headers: dict[str, str] | None = None) -> httpx2.Response:
        headers = self.headers if headers is None else headers
        if endpoint == "metric":
            return self.client.post(
                BASE + "/metrics",
                headers=headers,
                json=self.memory.fixture.metrics[0].model_dump(mode="json"),
            )
        if endpoint == "extract":
            return self.client.post(
                BASE + "/runs",
                headers=headers,
                json={
                    "entity_run_id": self.memory.fixture.entity_run.id,
                    "metric_ids": [item.id for item in self.memory.fixture.metrics],
                },
            )
        run_id = next(iter(self.memory.runs), fixture_id(999))
        return self.client.get(BASE + "/runs/" + run_id, headers=headers)


@pytest.fixture
def boundary() -> Iterator[Boundary]:
    user = User(UUID(fixture_id(1)), "admin", SecretStr("unused fixture hash"), "admin", True, 1)
    users = Users(user)
    settings = AuthSettings(jwt_secret=SecretStr("cd" * 32))
    auth = AuthService(users, settings)
    memory = Memory(source())
    with TestClient(
        create_app(
            Settings(environment="test"),
            auth_service=auth,
            candidate_service=CandidateService(memory),
        )
    ) as client:
        yield Boundary(client, users, user, issue_token(user, settings), memory)


def assert_error(response: httpx2.Response, status: int) -> None:
    assert response.status_code == status
    result = ErrorEnvelope.model_validate_json(response.text)
    assert result.meta.request_id == response.headers["x-request-id"]
    assert result.meta.versions.corpus_version_id is None
    assert response.headers["cache-control"] == "no-store"
    assert "private" not in response.text
    assert "fixture hash" not in response.text


def test_metric_receipt_and_run_read_replay(boundary: Boundary) -> None:
    first = MetricEnvelope.model_validate_json(boundary.request("metric").text)
    second = MetricEnvelope.model_validate_json(boundary.request("metric").text)
    assert first.data.already_exists is False
    assert second.data.already_exists is True
    initial = boundary.request("extract")
    repeated = boundary.request("extract")
    read = boundary.request("read")
    assert initial.status_code == repeated.status_code == read.status_code == 200
    envelopes = [
        CandidateEnvelope.model_validate_json(item.text) for item in (initial, repeated, read)
    ]
    assert envelopes[0].data == envelopes[1].data == envelopes[2].data
    assert len({item.meta.request_id for item in envelopes}) == 3
    assert envelopes[0].meta.versions.parse_version_id == boundary.memory.fixture.parse_version_id
    assert envelopes[0].meta.versions.corpus_version_id is None
    assert envelopes[0].data.candidates[0].state == "CANDIDATE"
    assert len(boundary.memory.runs) == 1
    assert boundary.memory.actors == [boundary.user] * 4


@pytest.mark.parametrize("endpoint", ("metric", "extract", "read"))
@pytest.mark.parametrize("mode", ("anonymous", "learner", "inactive", "revoked", "deleted"))
def test_authorization_precedes_repository(
    boundary: Boundary, endpoint: Endpoint, mode: str
) -> None:
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


@pytest.mark.parametrize("endpoint", ("metric", "extract", "read"))
@pytest.mark.parametrize(
    "error,status",
    (
        (CandidateAuthorizationError("private permission"), 403),
        (CandidateUnavailable("private unavailable"), 503),
        (CandidateNotFound("private missing"), 404),
        (CandidateConflict("private conflict"), 409),
        (CandidateSourceError("private source"), 422),
        (ValueError("private value"), 422),
        (psycopg.OperationalError("private outage"), 503),
        (OSError("private I/O"), 503),
    ),
)
def test_safe_failure_mapping(
    boundary: Boundary, endpoint: Endpoint, error: Exception, status: int
) -> None:
    boundary.memory.failure = error
    assert_error(boundary.request(endpoint), status)


@pytest.mark.parametrize(
    "body",
    (
        {"entity_run_id": "invalid"},
        {"entity_run_id": fixture_id(90), "metric_ids": [fixture_id(95)] * 2},
        {"entity_run_id": fixture_id(90), "metric_ids": [fixture_id(95)] * 101},
        {"entity_run_id": fixture_id(90), "candidates": []},
        {"entity_run_id": fixture_id(90), "accept": True},
    ),
)
def test_extraction_request_cannot_submit_results(
    boundary: Boundary, body: dict[str, object]
) -> None:
    assert_error(boundary.client.post(BASE + "/runs", headers=boundary.headers, json=body), 422)
    assert boundary.memory.calls == []


def test_unconfigured_service_fails_after_auth(boundary: Boundary) -> None:
    auth = AuthService(boundary.users, AuthSettings(jwt_secret=SecretStr("cd" * 32)))
    with TestClient(create_app(Settings(environment="test"), auth_service=auth)) as client:
        assert_error(client.get(BASE + "/runs/" + fixture_id(999), headers=boundary.headers), 503)
        assert_error(client.get(BASE + "/runs/" + fixture_id(999)), 401)


def test_unhandled_error_is_sanitized(boundary: Boundary) -> None:
    boundary.memory.failure = RuntimeError("private unexpected exception")
    assert_error(boundary.request("extract"), 500)


def test_openapi_documents_typed_admin_proposals(boundary: Boundary) -> None:
    schema = boundary.client.get("/openapi.json").json()
    for path, method in (
        (BASE + "/metrics", "post"),
        (BASE + "/runs", "post"),
        (BASE + "/runs/{run_id}", "get"),
    ):
        operation = schema["paths"][path][method]
        assert operation["security"]
        assert "503" in operation["responses"]
    assert "CandidateEnvelope" in schema["components"]["schemas"]
    assert not any(
        "accept" in path or "publish" in path
        for path in schema["paths"]
        if path.startswith(BASE + "/")
    )
