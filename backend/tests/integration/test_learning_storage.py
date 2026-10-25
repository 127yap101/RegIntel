"""M3 real PostgreSQL/auth/HTTP engineering checks; no real reviewed content is seeded."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import SecretStr

from backend.tests.integration.test_numerical_context_storage import snapshot
from regintel.auth.config import AuthSettings
from regintel.auth.repository import PostgreSQLAuthRepository, seed_users
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.auth.types import SeedAccount
from regintel.config import Settings
from regintel.db.migrations import connect_database
from regintel.learning.models import (
    DefinitionDraft,
    ExampleInput,
    LearningReview,
    LearningSource,
    PublishLearning,
)
from regintel.learning.repository import LearningConflict, LearningForbidden, LearningRepository
from regintel.learning.service import LearningService
from regintel.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
def learning(auth_database):
    seed_users(
        auth_database,
        (
            SeedAccount("admin", SecretStr("Authored learning admin!"), "admin"),
            SeedAccount("learner", SecretStr("Authored learning learner!"), "learner"),
        ),
    )
    accounts = PostgreSQLAuthRepository(auth_database)
    admin, learner = accounts.get_by_username("admin"), accounts.get_by_username("learner")
    assert admin is not None and learner is not None
    repository = LearningRepository(auth_database)
    draft = DefinitionDraft(
        term="Authored arithmetic term",
        definition="Authored test definition; not reviewed financial content.",
        sources=(
            LearningSource(title="Authored source fixture", url="https://example.test/source"),
        ),
        example=ExampleInput(
            operation="ADD",
            left="0.10",
            right="0.20",
            unit="illustrative units",
            explanation="Authored example; no filing claim.",
        ),
    )
    return auth_database, repository, admin, learner, draft


def approved(repository, admin, draft):
    definition = repository.propose(draft, admin)
    reviewed = repository.review(
        definition.id,
        LearningReview(
            decision="APPROVE", note="Authored engineering decision; no real human-review claim."
        ),
        admin,
    )
    return definition, reviewed


def test_learning_draft_review_publication_and_explicit_history(learning):
    database, repository, admin, learner, draft = learning
    assert repository.overview(learner).state == "NO_PUBLISHED_GLOSSARY"
    definition = repository.propose(draft, admin)
    assert definition.calculation.result == Decimal("0.30")
    assert repository.draft(definition.id, admin) == definition
    before = snapshot(database)
    with pytest.raises(LearningConflict):
        repository.publish(PublishLearning(definition_ids=(definition.id,)), admin)
    assert snapshot(database) == before
    review = LearningReview(decision="APPROVE", note="Authored engineering review.")
    reviewed = repository.review(definition.id, review, admin)
    assert repository.review(definition.id, review, admin) == reviewed
    first = repository.publish(PublishLearning(definition_ids=(definition.id,)), admin)
    assert repository.glossary(first.glossary_version_id, learner) == first
    later, _ = approved(
        repository, admin, draft.model_copy(update={"definition": "Authored corrected definition."})
    )
    second = repository.publish(
        PublishLearning(
            definition_ids=(later.id,), parent_glossary_version_id=first.glossary_version_id
        ),
        admin,
    )
    assert repository.overview(learner).glossary_version_id == second.glossary_version_id
    assert repository.glossary(first.glossary_version_id, learner) == first
    with connect_database(database) as connection:
        assert connection.execute("SELECT count(*) FROM regintel.fact_observations").fetchone() == (
            0,
        )
        assert connection.execute("SELECT count(*) FROM regintel.corpus_versions").fetchone() == (
            0,
        )


def test_rejection_is_immutable_and_cannot_be_published(learning):
    _, repository, admin, _, draft = learning
    definition = repository.propose(draft, admin)
    repository.review(
        definition.id, LearningReview(decision="REJECT", note="Authored rejection."), admin
    )
    with pytest.raises(LearningConflict):
        repository.review(
            definition.id, LearningReview(decision="APPROVE", note="Changed review."), admin
        )
    with pytest.raises(LearningConflict):
        repository.publish(PublishLearning(definition_ids=(definition.id,)), admin)


@pytest.mark.parametrize("change", ["learner", "forged", "stale", "inactive"])
def test_learning_current_role_is_checked_in_write_transaction(learning, change):
    database, repository, admin, learner, draft = learning
    user = (
        learner
        if change == "learner"
        else replace(learner, role="admin")
        if change == "forged"
        else replace(admin, auth_version=2)
        if change == "stale"
        else admin
    )
    if change == "inactive":
        with connect_database(database) as connection:
            connection.execute("UPDATE regintel.users SET is_active=false WHERE id=%s", (admin.id,))
    before = snapshot(database)
    with pytest.raises(LearningForbidden):
        repository.propose(draft, user)
    assert snapshot(database) == before


def test_concurrent_identical_review_replays_one_decision(learning):
    database, repository, admin, _, draft = learning
    definition = repository.propose(draft, admin)
    review = LearningReview(decision="APPROVE", note="Authored concurrent review.")
    with ThreadPoolExecutor(max_workers=2) as workers:
        calls = [workers.submit(repository.review, definition.id, review, admin) for _ in range(2)]
        results = [call.result(timeout=30) for call in calls]
    assert results[0] == results[1]
    with connect_database(database) as connection:
        assert connection.execute("SELECT count(*) FROM regintel.learning_reviews").fetchone() == (
            1,
        )


def test_stale_glossary_parent_cannot_discard_a_concurrent_publication(learning):
    database, repository, admin, learner, draft = learning
    first, _ = approved(repository, admin, draft)
    version = repository.publish(PublishLearning(definition_ids=(first.id,)), admin)
    second, _ = approved(
        repository, admin, draft.model_copy(update={"term": "Authored second term"})
    )
    before = snapshot(database)
    with pytest.raises(LearningConflict):
        repository.publish(PublishLearning(definition_ids=(second.id,)), admin)
    assert snapshot(database) == before
    assert repository.overview(learner).glossary_version_id == version.glossary_version_id
    revised = repository.publish(
        PublishLearning(
            definition_ids=(first.id, second.id),
            parent_glossary_version_id=version.glossary_version_id,
        ),
        admin,
    )
    assert len(revised.definitions) == 2
    assert repository.glossary(version.glossary_version_id, learner) == version


def test_private_draft_queue_filters_pages_and_retains_actual_reviews(learning):
    database, repository, admin, learner, draft = learning
    pending = repository.propose(draft.model_copy(update={"term": "Revenue % literal"}), admin)
    accepted, review = approved(repository, admin, draft.model_copy(update={"term": "EPS"}))
    rejected = repository.propose(draft.model_copy(update={"term": "Rejected term"}), admin)
    repository.review(
        rejected.id, LearningReview(decision="REJECT", note="Authored rejection."), admin
    )
    before = snapshot(database)
    with pytest.raises(LearningForbidden):
        repository.queue(learner)
    page = repository.queue(admin, state="ALL", limit=2)
    assert page.total == 3 and [item.definition.id for item in page.items] == [
        pending.id,
        accepted.id,
    ]
    assert page.items[1].review == review and page.items[1].state == "APPROVED"
    assert repository.queue(admin, state="ALL", offset=2).items[0].definition == rejected
    assert repository.queue(admin, query="% literal").items[0].definition == pending
    assert repository.queue(admin, query="nonexistent").total == 0
    assert repository.queue(admin, state="APPROVED", query="eps").items[0].review == review
    assert repository.queue(admin, state="REJECTED").items[0].state == "REJECTED"
    assert snapshot(database) == before


@pytest.mark.parametrize("table", ["learning_definitions", "learning_reviews", "learning_versions"])
@pytest.mark.parametrize("action", ["UPDATE", "DELETE", "TRUNCATE"])
def test_learning_history_is_append_only(learning, table, action):
    database, repository, admin, _, draft = learning
    definition, _ = approved(repository, admin, draft)
    repository.publish(PublishLearning(definition_ids=(definition.id,)), admin)
    before = snapshot(database)
    with pytest.raises(psycopg.Error), connect_database(database) as connection:
        statement = (
            sql.SQL("UPDATE regintel.{} SET id=id")
            if action == "UPDATE"
            else sql.SQL("DELETE FROM regintel.{}")
            if action == "DELETE"
            else sql.SQL("TRUNCATE regintel.{} CASCADE")
        )
        connection.execute(statement.format(sql.Identifier(table)))
    assert snapshot(database) == before


def test_glossary_cannot_publish_conflicting_term_revisions_together(learning):
    database, repository, admin, _, draft = learning
    first, _ = approved(repository, admin, draft)
    second, _ = approved(
        repository,
        admin,
        draft.model_copy(update={"term": draft.term.upper(), "definition": "Authored conflict."}),
    )
    before = snapshot(database)
    with pytest.raises(LearningConflict):
        repository.publish(PublishLearning(definition_ids=(first.id, second.id)), admin)
    assert snapshot(database) == before


def test_learning_http_requires_review_and_echoes_independent_version(learning):
    _, repository, admin, learner, draft = learning
    settings = AuthSettings(jwt_secret=SecretStr("cd" * 32))
    auth = AuthService(PostgreSQLAuthRepository(repository.database), settings)
    with TestClient(
        create_app(
            Settings(environment="test"),
            auth_service=auth,
            learning_service=LearningService(repository, None),
        )
    ) as client:
        admin_headers = {"Authorization": "Bearer " + issue_token(admin, settings)}
        learner_headers = {"Authorization": "Bearer " + issue_token(learner, settings)}
        assert client.get("/v1/learning/status").status_code == 401
        assert client.get("/v1/learning/drafts", headers=learner_headers).status_code == 403
        assert client.get("/v1/learning/drafts?limit=21", headers=admin_headers).status_code == 422
        assert (
            client.post(
                "/v1/learning/drafts", json=draft.model_dump(mode="json"), headers=learner_headers
            ).status_code
            == 403
        )
        proposal = client.post(
            "/v1/learning/drafts", json=draft.model_dump(mode="json"), headers=admin_headers
        )
        assert proposal.status_code == 200
        identity = proposal.json()["data"]["id"]
        queue = client.get("/v1/learning/drafts", headers=admin_headers)
        assert (
            queue.status_code == 200
            and queue.json()["data"]["items"][0]["definition"]["id"] == identity
        )
        assert (
            client.get(f"/v1/learning/drafts/{identity}/review", headers=admin_headers).status_code
            == 404
        )
        request = {"definition_ids": [identity]}
        assert (
            client.post("/v1/learning/versions", json=request, headers=admin_headers).status_code
            == 409
        )
        review = client.post(
            f"/v1/learning/drafts/{identity}/review",
            json={"decision": "APPROVE", "note": "Authored API review."},
            headers=admin_headers,
        )
        assert review.status_code == 200
        recorded = client.get(f"/v1/learning/drafts/{identity}/review", headers=admin_headers)
        assert recorded.status_code == 200 and recorded.json()["data"] == review.json()["data"]
        assert (
            client.get(
                f"/v1/learning/drafts/{identity}/review", headers=learner_headers
            ).status_code
            == 403
        )
        response = client.post("/v1/learning/versions", json=request, headers=admin_headers)
        assert response.status_code == 200
        version = response.json()["data"]["glossary_version_id"]
        assert response.json()["meta"]["versions"]["glossary_version_id"] == version
        published = client.get(f"/v1/learning/glossary/{version}", headers=learner_headers)
        assert published.status_code == 200 and published.headers["cache-control"] == "no-store"
        assert (
            published.json()["data"]["definitions"][0]["definition"]["calculation"]["result"]
            == "0.30"
        )
        assert (
            client.get(f"/v1/learning/drafts/{identity}", headers=learner_headers).status_code
            == 403
        )
        assert (
            client.get(f"/v1/learning/glossary/{uuid4()}", headers=learner_headers).status_code
            == 404
        )
