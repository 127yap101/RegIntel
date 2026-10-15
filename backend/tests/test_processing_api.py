"""Workflow HTTP authorization, typed requests and safe failures; no SQL claims."""

from dataclasses import replace
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from backend.tests.test_entity_api import Users
from regintel.auth.config import AuthSettings
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.auth.types import User
from regintel.config import Settings
from regintel.contracts.models import ErrorEnvelope
from regintel.main import create_app
from regintel.processing.api import ProcessingEnvelope, ProcessingService
from regintel.processing.configuration import current_configuration
from regintel.processing.models import ProcessingEvent, ProcessingJob, ProcessingRequest
from regintel.processing.repository import (
    ProcessingConflict,
    ProcessingFailure,
    ProcessingNotFound,
    ProcessingRepository,
    ProcessingUnavailable,
)

BASE = "/v1/admin/processing/jobs"


class Memory(ProcessingRepository):
    def __init__(self, user):
        self.calls = []
        self.failure = None
        self.job = ProcessingJob(
            id=str(uuid4()),
            request=ProcessingRequest(
                idempotency_key=str(uuid4()), parse_version_id=str(uuid4()), metric_ids=()
            ),
            configuration=current_configuration(),
            submitted_by=str(user.id),
            submitted_auth_version=1,
            state="QUEUED",
            generation=0,
            failure_code=None,
            checkpoints=(),
            events=(),
        )

    def called(self, name):
        self.calls.append(name)
        if self.failure is not None:
            raise self.failure

    def submit(self, request, user):
        self.called("submit")
        assert request == self.job.request and str(user.id) == self.job.submitted_by
        return self.job

    def get(self, job_id):
        self.called("get")
        return self.job if job_id == self.job.id else None

    def dispatch(self, sender, *, job_id=None, limit=100, user=None):
        self.called("dispatch")
        assert job_id == self.job.id and user is not None
        sender(job_id)
        return 1


@pytest.fixture
def boundary():
    user = User(uuid4(), "admin", SecretStr("unused fixture hash"), "admin", True, 1)
    users = Users(user)
    settings = AuthSettings(jwt_secret=SecretStr("ef" * 32))
    memory = Memory(user)
    sent = []
    with TestClient(
        create_app(
            Settings(environment="test"),
            auth_service=AuthService(users, settings),
            processing_service=ProcessingService(memory, sent.append),
        )
    ) as client:
        yield (
            client,
            memory,
            users,
            user,
            {"Authorization": "Bearer " + issue_token(user, settings)},
            sent,
        )


def call(boundary, endpoint, headers=None):
    client, memory, _, _, own_headers, _ = boundary
    headers = own_headers if headers is None else headers
    if endpoint == "submit":
        return client.post(BASE, headers=headers, json=memory.job.request.model_dump(mode="json"))
    if endpoint == "read":
        return client.get(BASE + "/" + memory.job.id, headers=headers)
    return client.post(BASE + "/" + memory.job.id + "/dispatch", headers=headers)


def assert_error(response, status):
    assert response.status_code == status
    result = ErrorEnvelope.model_validate_json(response.text)
    assert result.meta.request_id == response.headers["x-request-id"]
    assert result.meta.versions.corpus_version_id is None
    assert response.headers["cache-control"] == "no-store"
    assert "private" not in response.text


def test_workflow_submission_read_and_explicit_dispatch(boundary):
    _, memory, _, _, _, sent = boundary
    created = call(boundary, "submit")
    assert created.status_code == 200
    result = ProcessingEnvelope.model_validate_json(created.text)
    assert result.data == memory.job
    assert result.meta.versions.parse_version_id == memory.job.request.parse_version_id
    assert result.meta.versions.corpus_version_id is None
    assert created.headers["cache-control"] == "no-store"
    assert call(boundary, "read").json()["data"] == result.data.model_dump(mode="json")
    assert call(boundary, "dispatch").json()["data"] == {"dispatched": True}
    assert sent == [memory.job.id, memory.job.id]


@pytest.mark.parametrize("endpoint", ("submit", "read", "dispatch"))
@pytest.mark.parametrize("mode", ("anonymous", "learner", "inactive", "revoked", "deleted"))
def test_permissions_precede_workflow_storage(boundary, endpoint, mode):
    _, memory, users, user, headers, _ = boundary
    status = 401
    if mode == "anonymous":
        headers = {}
    elif mode == "learner":
        users.user = replace(user, role="learner")
        status = 403
    elif mode == "inactive":
        users.user = replace(user, is_active=False)
    elif mode == "revoked":
        users.user = replace(user, auth_version=2)
    else:
        users.user = None
    assert_error(call(boundary, endpoint, headers), status)
    assert memory.calls == []


@pytest.mark.parametrize("endpoint", ("submit", "read", "dispatch"))
@pytest.mark.parametrize(
    "failure,status",
    (
        (ProcessingFailure("AUTHORIZATION_CHANGED"), 403),
        (ProcessingConflict("private conflict"), 409),
        (ProcessingNotFound("private missing"), 404),
        (ProcessingUnavailable("private outage"), 503),
        (psycopg.OperationalError("private database"), 503),
        (ValueError("private source"), 422),
        (RuntimeError("private bug"), 500),
    ),
)
def test_failures_are_sanitized(boundary, endpoint, failure, status):
    boundary[1].failure = failure
    assert_error(call(boundary, endpoint), status)


@pytest.mark.parametrize(
    "field,value",
    (
        ("idempotency_key", "bad"),
        ("parse_version_id", str(UUID(int=1))),
        ("metric_ids", ["bad"]),
        ("configuration", {}),
        ("state", "SUCCEEDED"),
        ("submitted_by", str(uuid4())),
        ("checkpoints", []),
        ("publish", True),
    ),
)
def test_client_cannot_supply_execution_or_authority(boundary, field, value):
    client, memory, _, _, headers, _ = boundary
    payload = memory.job.request.model_dump(mode="json") | {field: value}
    assert_error(client.post(BASE, headers=headers, json=payload), 422)
    assert memory.calls == []


@pytest.mark.parametrize("values", ((), (str(uuid4()), str(uuid4()))))
def test_metric_ids_require_distinct_canonical_order(values):
    if not values:
        values = (str(uuid4()),) * 2
    else:
        values = tuple(sorted(values, reverse=True))
    with pytest.raises(ValidationError):
        ProcessingRequest(
            idempotency_key=str(uuid4()), parse_version_id=str(uuid4()), metric_ids=values
        )


@pytest.mark.parametrize(
    "changes",
    (
        {"stage": "ENTITY"},
        {"failure_code": "SOURCE_INVALID"},
        {"generation": 0},
        {"kind": "RETRY", "failure_code": "SOURCE_INVALID"},
        {"kind": "FAILED", "failure_code": "STORAGE_UNAVAILABLE"},
    ),
)
def test_malformed_event_is_not_readable(changes):
    with pytest.raises(ValidationError):
        ProcessingEvent.model_validate(
            {
                "sequence": 1,
                "generation": 1,
                "kind": "STARTED",
                "stage": None,
                "failure_code": None,
            }
            | changes
        )
