"""Administrator work queues fail closed before storage and keep source identity."""

from collections.abc import Iterator
from dataclasses import dataclass, replace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.tests.test_entity_api import Users
from backend.tests.test_validation_api import validation_source
from regintel.admin.models import MetricPage, QueueKind, QueuePage, ReviewFilter, ReviewPage
from regintel.admin.repository import AdminRepository, bounded
from regintel.auth.config import AuthSettings
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.auth.types import User
from regintel.config import Settings
from regintel.contracts.models import ErrorEnvelope
from regintel.fixtures.sources import fixture_id
from regintel.main import create_app
from regintel.validation.gate import validate
from regintel.validation.repository import ValidationAuthorizationError, ValidationNotFound


class Memory(AdminRepository):
    def __init__(self) -> None:
        self.calls = 0
        self.failure: Exception | None = None
        self.run = validate(validation_source())

    def called(self) -> None:
        self.calls += 1
        if self.failure:
            raise self.failure

    def queue(self, kind: QueueKind, offset: int, limit: int, user: User) -> QueuePage:
        self.called()
        return QueuePage(
            kind=kind,
            items=(),
            offset=offset,
            limit=limit,
            has_more=False,
            published_corpus_id=None,
        )

    def metrics(self, user: User) -> MetricPage:
        self.called()
        return MetricPage(items=())

    def review_page(
        self, run_id: str, state: ReviewFilter, offset: int, limit: int, user: User
    ) -> ReviewPage:
        self.called()
        return ReviewPage(
            run_id=run_id,
            candidate_run_id=self.run.candidate_run_id,
            parse_version_id=self.run.parse_version_id,
            configuration_sha256=self.run.configuration.sha256,
            approval_current=True,
            state_filter=state,
            items=(),
            offset=offset,
            limit=limit,
            has_more=False,
        )


@dataclass
class Boundary:
    client: TestClient
    users: Users
    user: User
    memory: Memory
    token: str


@pytest.fixture
def boundary() -> Iterator[Boundary]:
    user = User(UUID(fixture_id(1)), "admin", SecretStr("unused fixture hash"), "admin", True, 1)
    users = Users(user)
    settings = AuthSettings(jwt_secret=SecretStr("ef" * 32))
    memory = Memory()
    with TestClient(
        create_app(
            Settings(environment="test"),
            auth_service=AuthService(users, settings),
            admin_repository=memory,
        )
    ) as client:
        yield Boundary(client, users, user, memory, issue_token(user, settings))


@pytest.mark.parametrize("path", ["queues/filings", "metrics", "reviews/" + fixture_id(800)])
@pytest.mark.parametrize("mode", ["anonymous", "learner", "inactive", "revoked", "deleted"])
def test_current_authorization_precedes_reads(boundary: Boundary, path: str, mode: str) -> None:
    headers = {"Authorization": "Bearer " + boundary.token}
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
    response = boundary.client.get("/v1/admin/workspace/" + path, headers=headers)
    assert response.status_code == status
    ErrorEnvelope.model_validate_json(response.text)
    assert response.headers["cache-control"] == "no-store"
    assert boundary.memory.calls == 0


@pytest.mark.parametrize(
    "suffix",
    [
        "queues/filings?limit=26",
        "queues/processing?offset=-1",
        "queues/unknown",
        "reviews/not-an-id",
        "reviews/" + fixture_id(800) + "?state=ACCEPTED",
    ],
)
def test_invalid_bounds_and_categories_do_not_read_storage(boundary: Boundary, suffix: str) -> None:
    response = boundary.client.get(
        "/v1/admin/workspace/" + suffix, headers={"Authorization": "Bearer " + boundary.token}
    )
    assert response.status_code == 422
    assert boundary.memory.calls == 0


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ValidationNotFound("private missing source"), 404),
        (ValidationAuthorizationError("private account change"), 403),
        (ValueError("private damaged source"), 503),
        (OSError("private path"), 503),
    ],
)
def test_failure_responses_are_sanitized(boundary: Boundary, error: Exception, status: int) -> None:
    boundary.memory.failure = error
    response = boundary.client.get(
        "/v1/admin/workspace/reviews/" + fixture_id(800),
        headers={"Authorization": "Bearer " + boundary.token},
    )
    assert response.status_code == status
    assert "private" not in response.text
    ErrorEnvelope.model_validate_json(response.text)


def test_empty_workspace_and_parse_bound_audit_are_readable(boundary: Boundary) -> None:
    headers = {"Authorization": "Bearer " + boundary.token}
    for kind in ("filings", "processing", "validations", "publications"):
        response = boundary.client.get("/v1/admin/workspace/queues/" + kind, headers=headers)
        assert response.status_code == 200
        assert response.json()["data"]["published_corpus_id"] is None
    response = boundary.client.get(
        "/v1/admin/workspace/reviews/" + fixture_id(800), headers=headers
    )
    assert response.status_code == 200
    assert (
        response.json()["meta"]["versions"]["parse_version_id"]
        == boundary.memory.run.parse_version_id
    )


@pytest.mark.parametrize(
    ("offset", "limit"), [(True, 20), (0, False), (-1, 20), (0, 26), (10001, 1)]
)
def test_repository_rejects_unsafe_bounds(offset: int, limit: int) -> None:
    with pytest.raises(ValueError):
        bounded(offset, limit)
