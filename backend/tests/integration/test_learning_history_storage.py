"""Published glossary history is exact, bounded, authenticated and read-only."""

import hashlib
from secrets import token_hex
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.tests.integration.test_learning_storage import approved
from backend.tests.integration.test_learning_storage import learning as learning
from backend.tests.integration.test_numerical_context_storage import snapshot
from regintel.auth.config import AuthSettings
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.entities.models import canonical_bytes
from regintel.learning.models import GlossaryVersion, LearningReview, PublishLearning
from regintel.learning.repository import LearningConflict, LearningNotFound
from regintel.learning.service import LearningService
from regintel.main import create_app

pytestmark = pytest.mark.integration


def publish(repository, admin, draft, parent=None):
    definition, _ = approved(repository, admin, draft)
    return repository.publish(
        PublishLearning(definition_ids=(definition.id,), parent_glossary_version_id=parent), admin
    )


def test_only_published_versions_are_listed_and_old_manifests_remain_stable(learning):
    database, repository, admin, learner, draft = learning
    assert repository.history(learner).total == 0
    pending = repository.propose(draft.model_copy(update={"term": "Pending authored term"}), admin)
    repository.review(
        pending.id, LearningReview(decision="REJECT", note="Authored rejection."), admin
    )
    assert repository.history(learner).items == ()
    first = publish(repository, admin, draft)
    second = publish(
        repository,
        admin,
        draft.model_copy(update={"definition": "Later authored definition."}),
        first.glossary_version_id,
    )
    before = snapshot(database)
    page = repository.history(learner, limit=1)
    assert page.total == 2 and page.head_glossary_version_id == second.glossary_version_id
    assert page.items[0].glossary_version_id == second.glossary_version_id
    assert page.items[0].parent_glossary_version_id == first.glossary_version_id
    older = repository.history(learner, offset=1, limit=1)
    assert older.items[0].glossary_version_id == first.glossary_version_id
    assert older.items[0].definition_count == 1
    assert repository.history(learner, offset=2, limit=1).items == ()
    assert repository.glossary(first.glossary_version_id, learner) == first
    assert snapshot(database) == before
    with pytest.raises(LearningNotFound):
        repository.glossary(pending.id, learner)


def test_history_follows_recorded_parents_when_timestamps_tie(learning):
    database, repository, admin, learner, draft = learning
    _, reviewed = approved(repository, admin, draft)
    first = GlossaryVersion(
        glossary_version_id="ffffffff-ffff-4fff-bfff-ffffffffffff", definitions=(reviewed,)
    )
    second = GlossaryVersion(
        glossary_version_id="00000000-0000-4000-8000-000000000001",
        parent_glossary_version_id=first.glossary_version_id,
        definitions=(reviewed,),
    )
    # Authored equal timestamps and random identities deliberately sort opposite
    # to the recorded parent lineage; retain ordinary insert/head guards.
    with repository.transaction(admin, admin=True) as connection:
        for version in (first, second):
            body = canonical_bytes(version)
            connection.execute(
                "INSERT INTO regintel.learning_versions "
                "(id,manifest,manifest_sha256,published_by,auth_version,created_at) "
                "VALUES (%s,%s,%s,%s,%s,TIMESTAMPTZ '2026-10-01 00:00:00+00')",
                (
                    UUID(version.glossary_version_id),
                    body,
                    hashlib.sha256(body).hexdigest(),
                    admin.id,
                    admin.auth_version,
                ),
            )
            connection.execute(
                "INSERT INTO regintel.learning_head(singleton,version_id) VALUES (true,%s) "
                "ON CONFLICT(singleton) DO UPDATE SET version_id=EXCLUDED.version_id",
                (UUID(version.glossary_version_id),),
            )
    before = snapshot(database)
    page = repository.history(learner)
    assert tuple(item.glossary_version_id for item in page.items) == (
        second.glossary_version_id,
        first.glossary_version_id,
    )
    assert repository.history(learner, offset=1, limit=1).items == page.items[1:]
    assert snapshot(database) == before


@pytest.mark.parametrize("offset,limit", [(-1, 20), (0, 21), (True, 1), (0, False), (1000001, 20)])
def test_history_rejects_unbounded_pages(learning, offset, limit):
    database, repository, _, learner, _ = learning
    before = snapshot(database)
    with pytest.raises(LearningConflict):
        repository.history(learner, offset=offset, limit=limit)
    assert snapshot(database) == before


def test_history_http_and_selected_manifest_keep_independent_versions(learning):
    database, repository, admin, learner, draft = learning
    first = publish(repository, admin, draft)
    second = publish(repository, admin, draft, first.glossary_version_id)
    settings = AuthSettings(jwt_secret=SecretStr(token_hex(32)))
    auth = AuthService(PostgreSQLAuthRepository(database), settings)
    with TestClient(
        create_app(auth_service=auth, learning_service=LearningService(repository, None))
    ) as client:
        path = "/v1/learning/versions"
        assert client.get(path).status_code == 401
        headers = {"Authorization": "Bearer " + issue_token(learner, settings)}
        before = snapshot(database)
        response = client.get(path, params={"offset": 1, "limit": 1}, headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["data"]["items"][0]["glossary_version_id"] == first.glossary_version_id
        assert payload["data"]["head_glossary_version_id"] == second.glossary_version_id
        assert payload["meta"]["versions"]["glossary_version_id"] is None
        selected = client.get(f"/v1/learning/glossary/{first.glossary_version_id}", headers=headers)
        assert selected.json()["data"] == first.model_dump(mode="json")
        assert (
            selected.json()["meta"]["versions"]["glossary_version_id"] == first.glossary_version_id
        )
        assert client.get(path, params={"limit": 21}, headers=headers).status_code == 422
        assert client.get(f"/v1/learning/glossary/{uuid4()}", headers=headers).status_code == 404
        assert snapshot(database) == before
