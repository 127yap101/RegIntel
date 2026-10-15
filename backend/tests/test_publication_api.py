"""HTTP role/version/error contracts; storage and inference have separate proofs."""

from dataclasses import replace

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_entity_api import Users
from test_publication_engine import ALPHA, BETA, administrator, authored, create, selected

from regintel.auth.config import AuthSettings
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.auth.types import User
from regintel.main import create_app
from regintel.publication.engine import PublicationConflict
from regintel.publication.models import CorpusManifest, PublicationRequest
from regintel.publication.repository import PublicationRepository
from regintel.publication.service import PublicationService


class Memory(PublicationRepository):
    def __init__(self, manifest: CorpusManifest) -> None:
        self.manifest = manifest
        self.calls: list[str] = []

    def published(self, corpus_id: str | None = None) -> CorpusManifest:
        self.calls.append("view")
        return self.manifest

    def get_build(self, corpus_id: str, user: User) -> CorpusManifest:
        self.calls.append("read")
        return self.manifest


class Publisher(PublicationService):
    repository: Memory

    def __init__(self, memory: Memory) -> None:
        self.repository = memory
        self.failure: Exception | None = None

    def build(self, request: PublicationRequest, user: User) -> CorpusManifest:
        self.repository.calls.append("build")
        if self.failure:
            raise self.failure
        return self.repository.manifest

    def publish(self, corpus_id: str, user: User) -> CorpusManifest:
        self.repository.calls.append("publish")
        if self.failure:
            raise self.failure
        return self.repository.manifest

    def rebuild(self, corpus_id: str, user: User) -> CorpusManifest:
        return self.publish(corpus_id, user)


@pytest.mark.parametrize("role", ["anonymous", "learner", "admin"])
@pytest.mark.parametrize("endpoint", ["build", "read", "publish", "rebuild", "view"])
def test_roles_and_corpus_version_envelope(role: str, endpoint: str) -> None:
    source = authored(f"{ALPHA} supplies to {BETA}.")
    manifest = create(source)
    memory = Memory(manifest)
    publisher = Publisher(memory)
    user = administrator() if role != "learner" else replace(administrator(), role="learner")
    settings = AuthSettings(jwt_secret=SecretStr("ab" * 32))
    auth = AuthService(Users(user), settings)
    headers = (
        {} if role == "anonymous" else {"Authorization": "Bearer " + issue_token(user, settings)}
    )
    request = PublicationRequest(
        idempotency_key=manifest.id, parent_corpus_version_id=None, selections=(selected(source),)
    )
    with TestClient(create_app(auth_service=auth, publication_service=publisher)) as client:
        base = "/v1/admin/publication/builds"
        if endpoint == "build":
            response = client.post(base, headers=headers, json=request.model_dump(mode="json"))
        elif endpoint == "view":
            response = client.get("/v1/corpora/" + manifest.id, headers=headers)
        elif endpoint == "read":
            response = client.get(base + "/" + manifest.id, headers=headers)
        else:
            response = client.post(base + "/" + manifest.id + "/" + endpoint, headers=headers)
    expected = (
        401 if role == "anonymous" else 403 if role == "learner" and endpoint != "view" else 200
    )
    assert response.status_code == expected
    if expected == 200 and endpoint == "view":
        assert response.json()["meta"]["versions"]["corpus_version_id"] == manifest.id
        assert response.json()["data"]["observations"][0]["id"] == manifest.observations[0].id
    elif expected != 200:
        assert memory.calls == []


@pytest.mark.parametrize(
    "error,code",
    [
        (PublicationConflict("private conflict"), 409),
        (ValueError("private source"), 422),
        (psycopg.OperationalError("private endpoint"), 503),
    ],
)
def test_publication_errors_do_not_leak_payloads(error: Exception, code: int) -> None:
    source = authored(f"{ALPHA} supplies to {BETA}.")
    memory = Memory(create(source))
    publisher = Publisher(memory)
    publisher.failure = error
    user = administrator()
    settings = AuthSettings(jwt_secret=SecretStr("ab" * 32))
    with TestClient(
        create_app(auth_service=AuthService(Users(user), settings), publication_service=publisher)
    ) as client:
        response = client.post(
            "/v1/admin/publication/builds/" + memory.manifest.id + "/publish",
            headers={"Authorization": "Bearer " + issue_token(user, settings)},
        )
    assert response.status_code == code and "private" not in response.text
