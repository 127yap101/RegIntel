"""All four HTTP modules share actual authored PostgreSQL publication state.

Uses labelled authored sources/vectors/graph receipts from the existing M1
engineering fixture. This is not real-filing approval or a Neo4j/model benchmark.
"""

from dataclasses import dataclass, field
from secrets import token_hex
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.tests.integration.test_analysis_storage import AUTHORED_SOURCE
from backend.tests.integration.test_publication_storage import configuration, counts, prepared
from backend.tests.integration.test_publication_storage import publication as publication
from backend.tests.integration.test_published_reads_storage import service
from backend.tests.integration.test_validation_storage import validated as validated
from regintel.analysis.models import ComparisonRequest
from regintel.auth.config import AuthSettings
from regintel.auth.repository import PostgreSQLAuthRepository, seed_users
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.auth.types import SeedAccount
from regintel.db.migrations import connect_database
from regintel.learning.models import GlossaryVersion
from regintel.learning.repository import LearningRepository
from regintel.learning.service import LearningService
from regintel.main import create_app
from regintel.portfolio.repository import PortfolioRepository
from regintel.portfolio.service import PortfolioService
from regintel.publication.models import CorpusManifest, PublishedObservation
from regintel.publication.repository import PublicationRepository

pytestmark = [
    pytest.mark.integration,
    pytest.mark.parametrize(
        "validated",
        [{"source": AUTHORED_SOURCE, "allowed_unit_labels": ("crore", "million")}],
        indirect=True,
    ),
]


@dataclass
class SharedModules:
    repository: PublicationRepository
    first: CorpusManifest
    next: CorpusManifest
    client: TestClient
    comparison: ComparisonRequest
    observation: PublishedObservation
    glossary: GlossaryVersion
    account_id: str
    learner: dict[str, str] = field(repr=False)
    peer: dict[str, str] = field(repr=False)

    def context(self, corpus=None, observation=None):
        return {
            "glossary_version_id": self.glossary.glossary_version_id,
            "definition_id": self.glossary.definitions[0].definition.id,
            "corpus_version_id": corpus or self.first.id,
            "observation_id": observation or self.observation.id,
            "as_of_date": None,
        }

    def order(self, corpus=None):
        return {
            "request_id": str(uuid4()),
            "corpus_version_id": corpus or self.first.id,
            "company_id": self.observation.subject_entity_id,
            "side": "BUY",
            "quantity": 1,
        }


@pytest.fixture
def shared(publication, tmp_path):
    repository, admin, request = publication
    with connect_database(repository.database) as connection:
        rows = connection.execute(
            "SELECT id FROM regintel.candidates WHERE kind='numeric_fact' AND id=ANY(%s)",
            ([UUID(item.candidate_id) for item in request.selections],),
        ).fetchall()
    numeric = {str(row[0]) for row in rows}
    first_request = request.model_copy(
        update={"selections": tuple(s for s in request.selections if s.candidate_id in numeric)}
    )
    first = repository.build(first_request, configuration(), admin)
    repository.finalize(first.id, configuration(), admin, prepared(repository, admin, first))
    later_request = request.model_copy(
        update={
            "idempotency_key": str(uuid4()),
            "parent_corpus_version_id": first.id,
            "selections": tuple(s for s in request.selections if s.candidate_id not in numeric),
        }
    )
    later = repository.build(later_request, configuration(), admin)
    alpha = next(item for item in first.observations if "Alpha Solar" in item.raw_text)
    beta = next(item for item in first.observations if "Beta Solar" in item.raw_text)
    assert alpha.quantity is not None and alpha.metric_id is not None
    comparison = ComparisonRequest(
        corpus_version_id=first.id,
        company_ids=(alpha.subject_entity_id, beta.subject_entity_id),
        metric_ids=(alpha.metric_id,),
        period=alpha.quantity.period,
        basis="CONSOLIDATED",
    )
    seed_users(
        repository.database,
        (
            SeedAccount("joint.learner", SecretStr("Authored joint module learner!"), "learner"),
            SeedAccount("joint.peer", SecretStr("Authored joint module peer!"), "learner"),
        ),
    )
    accounts = PostgreSQLAuthRepository(repository.database)
    learner = accounts.get_by_username("joint.learner")
    peer = accounts.get_by_username("joint.peer")
    assert learner is not None and peer is not None
    settings = AuthSettings(jwt_secret=SecretStr(token_hex(32)))
    reader = service(repository, tmp_path)
    application = create_app(
        auth_service=AuthService(accounts, settings),
        read_service=reader,
        learning_service=LearningService(LearningRepository(repository.database), reader),
        portfolio_service=PortfolioService(PortfolioRepository(repository.database), reader),
    )
    with TestClient(application) as client:
        admin_headers = {"Authorization": "Bearer " + issue_token(admin, settings)}
        learner_headers = {"Authorization": "Bearer " + issue_token(learner, settings)}
        peer_headers = {"Authorization": "Bearer " + issue_token(peer, settings)}
        proposed = client.post(
            "/v1/learning/drafts",
            headers=admin_headers,
            json={
                "term": "Authored joint revenue definition",
                "definition": "Authored engineering content; not real reviewed financial guidance.",
                "sources": [{"title": "Authored source", "url": "https://example.test/joint"}],
                "metric_ids": [alpha.metric_id],
            },
        )
        assert proposed.status_code == 200
        identity = proposed.json()["data"]["id"]
        reviewed = client.post(
            f"/v1/learning/drafts/{identity}/review",
            headers=admin_headers,
            json={
                "decision": "APPROVE",
                "note": "Authored fixture review; no real approval claim.",
            },
        )
        assert reviewed.status_code == 200
        published = client.post(
            "/v1/learning/versions", headers=admin_headers, json={"definition_ids": [identity]}
        )
        assert published.status_code == 200
        glossary = GlossaryVersion.model_validate(published.json()["data"])
        account = client.post("/v1/portfolio/accounts", headers=learner_headers, json={})
        assert account.status_code == 200
        yield SharedModules(
            repository,
            first,
            later,
            client,
            comparison,
            alpha,
            glossary,
            account.json()["data"]["account_id"],
            learner_headers,
            peer_headers,
        )


def test_all_four_modules_retain_the_selected_published_corpus_after_the_head_advances(shared):
    repository, client = shared.repository, shared.client
    # The original M1 administrator owns both authored publication builds.
    actor = PostgreSQLAuthRepository(repository.database).get_by_username("admin")
    assert actor is not None
    repository.finalize(
        shared.next.id, configuration(), actor, prepared(repository, actor, shared.next)
    )
    before = counts(repository)
    assert (
        client.get("/v1/published-corpus", headers=shared.learner).json()["data"][
            "corpus_version_id"
        ]
        == shared.next.id
    )
    facts = client.get(
        f"/v1/companies/{shared.observation.subject_entity_id}/facts",
        params={"corpus_version_id": shared.first.id},
        headers=shared.learner,
    )
    assert facts.status_code == 200
    assert facts.json()["data"]["view"]["corpus_version_id"] == shared.first.id
    compared = client.post(
        "/v1/compare", json=shared.comparison.model_dump(mode="json"), headers=shared.learner
    )
    assert compared.status_code == 200
    assert compared.json()["meta"]["versions"]["corpus_version_id"] == shared.first.id
    difference = compared.json()["data"]["rows"][0]["differences"][0]
    assert difference["difference"] == "5000000.00"
    assert difference["percentage_difference"] == "50.000000"
    context = client.post("/v1/learning/context", json=shared.context(), headers=shared.learner)
    assert context.status_code == 200
    assert context.json()["meta"]["versions"]["corpus_version_id"] == shared.first.id
    assert (
        context.json()["meta"]["versions"]["glossary_version_id"]
        == shared.glossary.glossary_version_id
    )
    assert context.json()["data"]["observation"]["id"] == shared.observation.id
    assert context.json()["data"]["evidence"]
    order = shared.order()
    receipt = client.post("/v1/portfolio/orders", json=order, headers=shared.learner)
    assert receipt.status_code == 200
    result = receipt.json()
    assert result["data"]["account_id"] == shared.account_id
    assert result["meta"]["versions"]["corpus_version_id"] == shared.first.id
    assert result["data"]["entry"]["request"] == order
    assert result["data"]["entry"]["evaluation"]["reason"] == "QUOTES_UNAVAILABLE"
    assert result["data"]["entry"]["evaluation"]["after"]["cash"] == "100000.00"
    assert result["data"]["portfolio_version_id"] not in {
        shared.first.id,
        shared.next.id,
        shared.glossary.glossary_version_id,
    }
    assert counts(repository) == before
    assert repository.published(shared.first.id).sha256 == shared.first.sha256


def test_unpublished_context_never_falls_back_to_another_module_corpus(shared):
    client, corpus = shared.client, shared.next.id
    before = counts(shared.repository)
    compared = shared.comparison.model_copy(update={"corpus_version_id": corpus})
    assert (
        client.post(
            "/v1/compare", json=compared.model_dump(mode="json"), headers=shared.learner
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/v1/learning/context", json=shared.context(corpus), headers=shared.learner
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/v1/portfolio/orders", json=shared.order(corpus), headers=shared.learner
        ).status_code
        == 404
    )
    assert (
        client.get("/v1/portfolio", headers=shared.learner).json()["data"]["committed_orders"] == 0
    )
    assert counts(shared.repository) == before


def test_a_shared_published_corpus_does_not_share_private_portfolio_or_review_authority(shared):
    client = shared.client
    receipt = client.post("/v1/portfolio/orders", json=shared.order(), headers=shared.learner)
    assert receipt.status_code == 200
    assert client.post("/v1/portfolio/accounts", json={}, headers=shared.peer).status_code == 200
    version = receipt.json()["data"]["portfolio_version_id"]
    for path in ("/v1/portfolio", "/v1/portfolio/ledger", "/v1/portfolio/analytics"):
        assert (
            client.get(
                path, params={"portfolio_version_id": version}, headers=shared.peer
            ).status_code
            == 404
        )
    definition = shared.glossary.definitions[0].definition.id
    assert (
        client.post(
            f"/v1/learning/drafts/{definition}/review",
            headers=shared.learner,
            json={"decision": "REJECT", "note": "Unauthorized authored attempt."},
        ).status_code
        == 403
    )
    assert (
        client.post("/v1/learning/context", json=shared.context(), headers=shared.peer).status_code
        == 200
    )
    assert (
        client.post(
            "/v1/compare", json=shared.comparison.model_dump(mode="json"), headers=shared.peer
        ).status_code
        == 200
    )
