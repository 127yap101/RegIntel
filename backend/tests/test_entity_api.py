"""HTTP authorization and exact-source entity contracts, using a bounded storage fake."""

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Literal
from uuid import UUID

import httpx2
import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from regintel.auth.config import AuthSettings
from regintel.auth.errors import AuthUnavailable
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.auth.types import User
from regintel.config import Settings
from regintel.contracts.models import ErrorEnvelope, EvidenceSource, TextEvidence, TextSpan
from regintel.entities.api import (
    EntityService,
    RegistrationEnvelope,
    ReviewEnvelope,
    RunEnvelope,
)
from regintel.entities.models import (
    ApprovedIdentifier,
    EntityRegistration,
    EntityReview,
    EntityRun,
    EvidenceAnchor,
    RegistrySnapshot,
)
from regintel.entities.repository import (
    EntityAuthorizationError,
    EntityConflict,
    EntityNotFound,
    EntityRegistryChanged,
    EntityRepository,
    EntitySourceError,
    EntityUnavailable,
)
from regintel.fixtures.sources import evidence_catalog
from regintel.main import create_app

USER_ID = "00000000-0000-4000-8000-000000000001"
ENTITY_ID = "00000000-0000-4000-8000-000000000002"
PARSE_ID = "00000000-0000-4000-8000-000000000003"
EVIDENCE_ID = "00000000-0000-4000-8000-000000000004"
PAGE_ID = "00000000-0000-4000-8000-000000000005"
BLOCK_ID = "00000000-0000-4000-8000-000000000006"
REVIEW_ID = "00000000-0000-4000-8000-000000000007"
MISSING_ID = "00000000-0000-4000-8000-000000000008"
BASE = "/v1/admin/entities"
NAME = "Alpha Energy Limited"
CIN = "U12345MH2020PLC123456"
SOURCE = f"{NAME}\n{CIN}\nAlhpa Energy Limited"
SOURCE_START = 17
ARTIFACT_SHA = "a" * 64
type Endpoint = Literal["register", "resolve", "read", "review"]


class Users:
    def __init__(self, user: User) -> None:
        self.user: User | None = user
        self.unavailable = False

    def get_by_username(self, username: str) -> User | None:
        return self.user if self.user and self.user.username == username else None

    def get_by_id(self, user_id: UUID) -> User | None:
        if self.unavailable:
            raise AuthUnavailable("private authentication diagnostic")
        return self.user if self.user and self.user.id == user_id else None


class EntityMemory(EntityRepository):
    """Only the HTTP boundary uses this fake; it does not prove SQL/source gates."""

    def __init__(self, evidence: TextEvidence) -> None:
        self.evidence = (evidence,)
        self.entities: dict[str, EntityRegistration] = {}
        self.runs: dict[str, EntityRun] = {}
        self.decisions: dict[tuple[str, str], EntityReview] = {}
        self.calls: list[str] = []
        self.actors: list[User] = []
        self.failure: Exception | None = None
        self.fail_operation: str | None = None

    def called(self, operation: str, user: User | None = None) -> None:
        self.calls.append(operation)
        if user is not None:
            self.actors.append(user)
        if self.failure is not None and (
            self.fail_operation is None or self.fail_operation == operation
        ):
            raise self.failure

    def register(self, registration: EntityRegistration, user: User) -> bool:
        self.called("register", user)
        existing = self.entities.get(registration.id)
        if existing is not None:
            if existing != registration:
                raise EntityConflict("private registration conflict")
            return False
        assert len(self.entities) < 2
        self.entities[registration.id] = registration
        return True

    def snapshot(self) -> RegistrySnapshot:
        self.called("snapshot")
        entities = tuple(self.entities[key] for key in sorted(self.entities))
        contents = json.dumps(
            {"entities": [entity.model_dump(mode="json") for entity in entities]},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return RegistrySnapshot(
            revision=len(entities), sha256=hashlib.sha256(contents).hexdigest(), entities=entities
        )

    def evidence_for_parse(self, parse_id: str) -> tuple[tuple[TextEvidence, ...], str]:
        self.called("evidence_for_parse")
        if parse_id != PARSE_ID:
            raise EntityNotFound("private missing parse")
        return self.evidence, ARTIFACT_SHA

    def save_run(self, run: EntityRun, user: User) -> EntityRun:
        self.called("save_run", user)
        existing = self.runs.get(run.id)
        if existing is not None:
            if existing != run:
                raise EntityConflict("private run conflict")
            return existing
        assert len(self.runs) < 2
        self.runs[run.id] = run
        return run

    def get_run(self, run_id: str) -> EntityRun | None:
        self.called("get_run")
        return self.runs.get(run_id)

    def review(self, decision: EntityReview, user: User) -> bool:
        self.called("review", user)
        key = (decision.run_id, decision.mention_id)
        existing = self.decisions.get(key)
        if existing is not None:
            if existing != decision:
                raise EntityConflict("private review conflict")
            return False
        assert len(self.decisions) < 2
        self.decisions[key] = decision
        return True

    def reviews(self, run_id: str) -> tuple[EntityReview, ...]:
        self.called("reviews")
        return tuple(value for key, value in self.decisions.items() if key[0] == run_id)


@dataclass
class Boundary:
    client: TestClient
    users: Users
    user: User
    auth: AuthService
    token: str
    repository: EntityMemory
    registration: EntityRegistration

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    @property
    def run(self) -> EntityRun:
        return next(iter(self.repository.runs.values()))

    def review_body(self) -> EntityReview:
        if self.repository.runs:
            run = self.run
            mention = next(item for item in run.mentions if item.resolution.state == "REVIEW")
            run_id, mention_id = run.id, mention.id
        else:
            run_id, mention_id = MISSING_ID, BLOCK_ID
        return EntityReview(
            id=REVIEW_ID,
            run_id=run_id,
            mention_id=mention_id,
            decision="RESOLVE",
            entity_id=ENTITY_ID,
            support_evidence_ids=(EVIDENCE_ID,),
            review_note="Synthetic reviewer inspected the supplied exact source.",
        )

    def request(
        self, endpoint: Endpoint, *, headers: dict[str, str] | None = None
    ) -> httpx2.Response:
        selected_headers = self.headers if headers is None else headers
        if endpoint == "register":
            return self.client.post(
                BASE, headers=selected_headers, json=self.registration.model_dump(mode="json")
            )
        if endpoint == "resolve":
            return self.client.post(
                f"{BASE}/runs", headers=selected_headers, json={"parse_version_id": PARSE_ID}
            )
        if endpoint == "read":
            run_id = self.run.id if self.repository.runs else MISSING_ID
            return self.client.get(f"{BASE}/runs/{run_id}", headers=selected_headers)
        return self.client.post(
            f"{BASE}/reviews",
            headers=selected_headers,
            json=self.review_body().model_dump(mode="json"),
        )

    def create_run(self) -> EntityRun:
        assert self.request("register").status_code == 200
        response = self.request("resolve")
        assert response.status_code == 200
        return RunEnvelope.model_validate_json(response.text).data.run


@pytest.fixture
def boundary() -> Iterator[Boundary]:
    user = User(UUID(USER_ID), "admin", SecretStr("synthetic unused hash"), "admin", True, 1)
    users = Users(user)
    settings = AuthSettings(jwt_secret=SecretStr("ab" * 32))
    auth = AuthService(users, settings)
    example = next(iter(evidence_catalog().values()))
    assert isinstance(example, TextEvidence)
    record = TextEvidence(
        id=EVIDENCE_ID,
        kind="text",
        source=EvidenceSource(
            filing_id=USER_ID,
            filing_version_id=ENTITY_ID,
            parse_version_id=PARSE_ID,
            page_id=PAGE_ID,
            page_index=0,
        ),
        page_geometry=example.page_geometry,
        boxes=example.boxes,
        span=TextSpan(
            block_id=BLOCK_ID,
            start=SOURCE_START,
            end=SOURCE_START + len(SOURCE),
            quote=SOURCE,
        ),
    )
    name_support = EvidenceAnchor(
        evidence_id=EVIDENCE_ID,
        start=SOURCE_START,
        end=SOURCE_START + len(NAME),
        quote=NAME,
    )
    cin_start = SOURCE_START + SOURCE.index(CIN)
    registration = EntityRegistration(
        id=ENTITY_ID,
        kind="COMPANY",
        legal_name=NAME,
        legal_name_support=name_support,
        identifiers=(
            ApprovedIdentifier(
                kind="CIN",
                value=CIN,
                support=EvidenceAnchor(
                    evidence_id=EVIDENCE_ID, start=cin_start, end=cin_start + len(CIN), quote=CIN
                ),
            ),
        ),
        review_note="Synthetic approved registry identity; no real-filing claim.",
    )
    repository = EntityMemory(record)
    with TestClient(
        create_app(
            Settings(environment="test"),
            auth_service=auth,
            entity_service=EntityService(repository),
        )
    ) as client:
        yield Boundary(
            client, users, user, auth, issue_token(user, settings), repository, registration
        )


def assert_error(response: httpx2.Response, status: int, code: str) -> ErrorEnvelope:
    assert response.status_code == status
    envelope = ErrorEnvelope.model_validate_json(response.text)
    assert envelope.error.code == code
    assert envelope.meta.request_id == response.headers["x-request-id"]
    assert envelope.meta.versions.corpus_version_id is None
    assert response.headers["cache-control"] == "no-store"
    assert "private" not in response.text
    return envelope


def test_registration_receipt_distinguishes_creation_from_identical_replay(
    boundary: Boundary,
) -> None:
    first = boundary.request("register")
    repeated = boundary.request("register")
    assert first.status_code == repeated.status_code == 200
    created = RegistrationEnvelope.model_validate_json(first.text)
    replay = RegistrationEnvelope.model_validate_json(repeated.text)
    assert created.data.entity_id == replay.data.entity_id == ENTITY_ID
    assert created.data.already_exists is False
    assert replay.data.already_exists is True
    assert len(boundary.repository.entities) == 1
    assert boundary.repository.actors == [boundary.user, boundary.user]
    assert first.headers["cache-control"] == repeated.headers["cache-control"] == "no-store"
    assert created.meta.request_id != replay.meta.request_id


def test_actual_resolution_preserves_source_spans_and_leaves_fuzzy_proposal_for_review(
    boundary: Boundary,
) -> None:
    run = boundary.create_run()
    assert run.parse_version_id == PARSE_ID
    assert run.artifact_sha256 == ARTIFACT_SHA
    assert run.evidence_ids == (EVIDENCE_ID,)
    assert run.registry_revision == 1
    assert run.configuration.spacy_version == "3.8.16"
    assert run.configuration.rapidfuzz_version == "3.14.6"
    assert any(
        item.kind == "CIN"
        and item.resolution.entity_id == ENTITY_ID
        and item.resolution.method == "EXACT_CIN"
        for item in run.mentions
    )
    fuzzy = next(item for item in run.mentions if item.support.quote == "Alhpa Energy Limited")
    assert fuzzy.resolution.state == "REVIEW"
    assert fuzzy.resolution.entity_id is None
    assert fuzzy.resolution.method is None
    assert fuzzy.resolution.proposals[0].entity_id == ENTITY_ID
    assert fuzzy.resolution.proposals[0].method == "FUZZY"
    for mention in run.mentions:
        anchor = mention.support
        assert anchor.evidence_id == EVIDENCE_ID
        assert SOURCE[anchor.start - SOURCE_START : anchor.end - SOURCE_START] == anchor.quote
    assert boundary.repository.decisions == {}


def test_run_read_replay_and_metadata_are_unpublished_immutable_results(boundary: Boundary) -> None:
    original = boundary.create_run()
    read = boundary.request("read")
    repeat = boundary.request("resolve")
    assert read.status_code == repeat.status_code == 200
    for response in (read, repeat):
        envelope = RunEnvelope.model_validate_json(response.text)
        assert envelope.data.run == original
        assert envelope.data.reviews == ()
        assert envelope.meta.versions.parse_version_id == PARSE_ID
        assert envelope.meta.versions.corpus_version_id is None
        assert envelope.meta.request_id == response.headers["x-request-id"]
        assert response.headers["cache-control"] == "no-store"
    assert len(boundary.repository.runs) == 1


def test_review_receipts_replay_and_read_do_not_overwrite_original_mention(
    boundary: Boundary,
) -> None:
    original = boundary.create_run()
    first = boundary.request("review")
    repeated = boundary.request("review")
    assert first.status_code == repeated.status_code == 200
    assert ReviewEnvelope.model_validate_json(first.text).data.already_exists is False
    assert ReviewEnvelope.model_validate_json(repeated.text).data.already_exists is True
    assert ReviewEnvelope.model_validate_json(first.text).data.review_id == REVIEW_ID
    assert first.headers["cache-control"] == repeated.headers["cache-control"] == "no-store"
    read = boundary.request("read")
    envelope = RunEnvelope.model_validate_json(read.text)
    assert envelope.data.run == original
    assert envelope.data.reviews == (boundary.review_body(),)
    reviewed = next(
        item for item in envelope.data.run.mentions if item.resolution.state == "REVIEW"
    )
    assert reviewed.resolution.entity_id is None
    assert envelope.meta.versions.corpus_version_id is None
    assert boundary.repository.actors[-2:] == [boundary.user, boundary.user]


def test_review_replay_with_new_identity_is_rejected_without_changing_the_stored_review(
    boundary: Boundary,
) -> None:
    original = boundary.create_run()
    assert boundary.request("review").status_code == 200
    decision = boundary.review_body()
    replay = decision.model_copy(update={"id": MISSING_ID})
    response = boundary.client.post(
        f"{BASE}/reviews", headers=boundary.headers, json=replay.model_dump(mode="json")
    )
    assert_error(response, 409, "CONFLICT")
    assert boundary.repository.reviews(original.id) == (decision,)
    assert boundary.repository.runs[original.id] == original


@pytest.mark.parametrize("endpoint", ["register", "resolve", "read", "review"])
@pytest.mark.parametrize(
    "state", ["missing", "invalid", "learner", "revoked", "inactive", "deleted", "outage"]
)
def test_current_admin_authorization_precedes_repository_access(
    boundary: Boundary, endpoint: Endpoint, state: str
) -> None:
    headers = boundary.headers
    expected, code = 401, "UNAUTHENTICATED"
    if state == "missing":
        headers = {}
    elif state == "invalid":
        headers["Authorization"] = "Bearer invalid"
    elif state == "learner":
        boundary.users.user = replace(boundary.user, role="learner")
        expected, code = 403, "FORBIDDEN"
    elif state == "revoked":
        boundary.users.user = replace(boundary.user, auth_version=2)
    elif state == "inactive":
        boundary.users.user = replace(boundary.user, is_active=False)
    elif state == "deleted":
        boundary.users.user = None
    else:
        boundary.users.unavailable = True
        expected, code = 503, "SERVICE_UNAVAILABLE"
    response = boundary.request(endpoint, headers=headers)
    assert_error(response, expected, code)
    if expected == 401:
        assert response.headers["www-authenticate"] == "Bearer"
    assert boundary.repository.calls == []
    assert boundary.repository.actors == []
    assert not boundary.repository.entities and not boundary.repository.runs


@pytest.mark.parametrize("component", ["authentication", "entities"])
def test_explicit_unconfigured_services_fail_closed(boundary: Boundary, component: str) -> None:
    with TestClient(
        create_app(
            Settings(environment="test"),
            auth_service=boundary.auth if component == "entities" else None,
            entity_service=EntityService(boundary.repository)
            if component == "authentication"
            else None,
        )
    ) as client:
        response = client.post(
            f"{BASE}/runs", headers=boundary.headers, json={"parse_version_id": PARSE_ID}
        )
    assert_error(response, 503, "SERVICE_UNAVAILABLE")
    assert boundary.repository.calls == []


@pytest.mark.parametrize(
    "error_type,status,code",
    [
        (EntityAuthorizationError, 403, "FORBIDDEN"),
        (EntityNotFound, 404, "NOT_FOUND"),
        (EntityConflict, 409, "CONFLICT"),
        (EntityRegistryChanged, 409, "CONFLICT"),
        (EntitySourceError, 422, "VALIDATION_ERROR"),
        (ValueError, 422, "VALIDATION_ERROR"),
        (EntityUnavailable, 503, "SERVICE_UNAVAILABLE"),
        (ImportError, 503, "SERVICE_UNAVAILABLE"),
        (psycopg.OperationalError, 503, "SERVICE_UNAVAILABLE"),
        (OSError, 503, "SERVICE_UNAVAILABLE"),
        (RuntimeError, 500, "INTERNAL_ERROR"),
    ],
)
@pytest.mark.parametrize("endpoint", ["register", "resolve", "read", "review"])
def test_repository_failures_are_sanitized_json_envelopes(
    boundary: Boundary,
    endpoint: Endpoint,
    error_type: type[Exception],
    status: int,
    code: str,
) -> None:
    boundary.repository.failure = error_type("private SQL credential or filing text")
    response = boundary.request(endpoint)
    envelope = assert_error(response, status, code)
    assert envelope.error.details == ()
    assert len(boundary.repository.calls) == 1


@pytest.mark.parametrize("operation", ["evidence_for_parse", "save_run", "reviews"])
def test_late_resolution_failures_do_not_return_partial_success(
    boundary: Boundary, operation: str
) -> None:
    assert boundary.request("register").status_code == 200
    boundary.repository.failure = EntityRegistryChanged("private race diagnostic")
    boundary.repository.fail_operation = operation
    response = boundary.request("resolve")
    assert_error(response, 409, "CONFLICT")
    assert "data" not in response.json()


def test_unknown_parse_and_run_return_not_found(boundary: Boundary) -> None:
    absent_parse = boundary.client.post(
        f"{BASE}/runs", headers=boundary.headers, json={"parse_version_id": MISSING_ID}
    )
    absent_run = boundary.request("read")
    assert_error(absent_parse, 404, "NOT_FOUND")
    assert_error(absent_run, 404, "NOT_FOUND")
    assert boundary.repository.runs == {}


def test_conflicting_registration_and_review_replay_are_not_accepted(boundary: Boundary) -> None:
    boundary.create_run()
    changed_registration = boundary.registration.model_copy(
        update={"review_note": "Different audit"}
    )
    conflict = boundary.client.post(
        BASE, headers=boundary.headers, json=changed_registration.model_dump(mode="json")
    )
    assert_error(conflict, 409, "CONFLICT")
    assert boundary.repository.entities[ENTITY_ID] == boundary.registration
    assert boundary.request("review").status_code == 200
    original = boundary.review_body()
    changed_review = original.model_copy(update={"decision": "REJECT", "entity_id": None})
    conflict = boundary.client.post(
        f"{BASE}/reviews", headers=boundary.headers, json=changed_review.model_dump(mode="json")
    )
    assert_error(conflict, 409, "CONFLICT")
    assert boundary.repository.decisions[(original.run_id, original.mention_id)] == original


@pytest.mark.parametrize("endpoint", ["register", "resolve", "review"])
@pytest.mark.parametrize("invalid", ["unknown-field", "bad-id", "malformed-json"])
def test_invalid_bodies_are_rejected_without_echoing_input_or_storage_access(
    boundary: Boundary, endpoint: Endpoint, invalid: str
) -> None:
    if endpoint == "register":
        path, body = BASE, boundary.registration.model_dump(mode="json")
        identity = "id"
    elif endpoint == "review":
        path, body = f"{BASE}/reviews", boundary.review_body().model_dump(mode="json")
        identity = "run_id"
    else:
        path, body = f"{BASE}/runs", {"parse_version_id": PARSE_ID}
        identity = "parse_version_id"
    secret = "private submitted source or credential"
    if invalid == "malformed-json":
        response = boundary.client.post(
            path,
            headers={**boundary.headers, "Content-Type": "application/json"},
            content='{"private": "unterminated',
        )
    else:
        body["unexpected" if invalid == "unknown-field" else identity] = secret
        response = boundary.client.post(path, headers=boundary.headers, json=body)
    envelope = assert_error(response, 422, "VALIDATION_ERROR")
    assert [(item.location, item.code) for item in envelope.error.details] == [
        ("body", "INVALID_VALUE")
    ]
    assert secret not in response.text
    assert boundary.repository.calls == []


def test_invalid_support_and_review_decision_are_rejected_at_http_contract(
    boundary: Boundary,
) -> None:
    unsupported = boundary.registration.model_copy(
        update={"legal_name": "private unsupported name"}
    )
    response = boundary.client.post(
        BASE, headers=boundary.headers, json=unsupported.model_dump(mode="json")
    )
    assert_error(response, 422, "VALIDATION_ERROR")
    decision = boundary.review_body().model_copy(update={"entity_id": None})
    response = boundary.client.post(
        f"{BASE}/reviews", headers=boundary.headers, json=decision.model_dump(mode="json")
    )
    assert_error(response, 422, "VALIDATION_ERROR")
    assert boundary.repository.calls == []


def test_invalid_path_identity_is_sanitized_before_run_lookup(boundary: Boundary) -> None:
    response = boundary.client.get(f"{BASE}/runs/private-invalid-id", headers=boundary.headers)
    envelope = assert_error(response, 422, "VALIDATION_ERROR")
    assert [(item.location, item.code) for item in envelope.error.details] == [
        ("path", "INVALID_VALUE")
    ]
    assert boundary.repository.calls == []
