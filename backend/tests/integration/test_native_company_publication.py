"""Native-word identity through all four modules in an authored owned corpus."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.tests.integration.test_native_company_storage import company as company
from backend.tests.integration.test_numerical_publication_draft_storage import (
    published_parent as published_parent,
)
from backend.tests.integration.test_publication_storage import configuration, prepared
from backend.tests.integration.test_publication_storage import publication as publication
from backend.tests.integration.test_validation_storage import validated as validated
from regintel.analysis.models import ComparisonRequest
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.entities.models import NativeCompanyRegistration
from regintel.evidence.api import EvidenceService
from regintel.evidence.repository import EvidenceRepository
from regintel.learning.repository import LearningRepository
from regintel.learning.service import LearningService
from regintel.main import create_app
from regintel.numerical.acceptance_models import NumericalAcceptanceRequest
from regintel.numerical.acceptance_repository import NumericalAcceptanceRepository
from regintel.numerical.candidate_models import NumericalCandidateRequest
from regintel.numerical.candidate_repository import NumericalCandidateRepository
from regintel.numerical.context_storage import NumericalContextStorage
from regintel.numerical.gate_repository import BoundNumericalGateRepository
from regintel.numerical.publication_input_repository import NumericalPublicationInputRepository
from regintel.numerical.review_models import NumericalContextReviewRequest
from regintel.numerical.review_repository import NumericalContextReviewRepository
from regintel.portfolio.repository import PortfolioRepository
from regintel.portfolio.service import PortfolioService
from regintel.publication.models import CandidateSelection, PublicationRequest
from regintel.publication.repository import PublicationRepository
from regintel.reads.repository import ReadRepository
from regintel.reads.service import PublishedReadService

pytestmark = pytest.mark.integration


def test_native_company_identity_retains_frozen_history_and_flows_through_m1_m2_m3_m4(request):
    # Freeze the legacy parent first, so subsequent native registration never
    # becomes an identity in an earlier publication's catalog.
    parent = request.getfixturevalue("published_parent")
    fixture = request.getfixturevalue("company")
    source = fixture.native.source
    registry = fixture.registration
    assert fixture.repository.register(registry, source.user)
    context = NumericalContextStorage(source.source).save(
        fixture.native.record.source_input.draft, source.user
    )
    gate = BoundNumericalGateRepository(source.source).run(
        context.id, fixture.native.result.artifact.id, source.user
    )
    assert gate.result.state == "READY_FOR_REVIEW"
    NumericalContextReviewRepository(source.source).save(
        NumericalContextReviewRequest(
            gate_run_id=gate.result.id,
            decision="CONFIRM_CONTEXT",
            evidence_ids=gate.result.evidence_ids,
            note="Authored source context review only; no real filing/human approval.",
        ),
        source.user,
    )
    proposal = NumericalPublicationInputRepository(source.source).prepare(
        gate.result.id, source.user
    )
    assert proposal.proposed_input is not None
    candidate = NumericalCandidateRepository(source.source).save(
        NumericalCandidateRequest(
            gate_run_id=gate.result.id,
            prepared_input_id=proposal.proposed_input.id,
        ),
        source.user,
    )
    accepted = NumericalAcceptanceRepository(source.source).save(
        NumericalAcceptanceRequest(
            candidate_id=candidate.record.id,
            decision="ACCEPT",
            evidence_ids=gate.result.evidence_ids,
            note="Authored mandatory-check acceptance; no real content approval.",
        ),
        source.user,
    )
    assert accepted.record.state == "ACCEPTED_UNPUBLISHED"
    publication = PublicationRepository(source.database, source.source)
    selection = PublicationRequest(
        idempotency_key=str(uuid4()),
        parent_corpus_version_id=parent.id,
        selections=(
            CandidateSelection(
                candidate_run_id=gate.result.id,
                candidate_id=candidate.record.id,
                review_id=accepted.record.id,
            ),
        ),
    )
    manifest = publication.build(selection, configuration(), source.user)
    publication.finalize(
        manifest.id, configuration(), source.user, prepared(publication, source.user, manifest)
    )
    reads = PublishedReadService(
        publication,
        ReadRepository(source.database),
        EvidenceService(EvidenceRepository(source.database), source.source.storage),
        None,
    )
    catalog = ReadRepository(source.database)
    current = catalog.catalog(manifest)
    company = next(item for item in current.entities if item.id == registry.id)
    assert isinstance(company, NativeCompanyRegistration) and company == registry
    assert registry.id not in {item.id for item in catalog.catalog(parent).entities}
    assert publication.published(parent.id) == parent
    observation = next(
        item for item in manifest.observations if item.subject_entity_id == registry.id
    )
    app = create_app(
        auth_service=AuthService(PostgreSQLAuthRepository(source.database), fixture.settings),
        read_service=reads,
        learning_service=LearningService(LearningRepository(source.database), reads),
        portfolio_service=PortfolioService(PortfolioRepository(source.database), reads),
    )
    admin = {"Authorization": "Bearer " + issue_token(source.user, fixture.settings)}
    learner = {"Authorization": "Bearer " + issue_token(source.learner, fixture.settings)}
    with TestClient(app) as client:
        companies = client.get(
            "/v1/companies", headers=learner, params={"corpus_version_id": manifest.id}
        )
        assert companies.status_code == 200
        assert registry.id in {item["id"] for item in companies.json()["data"]["companies"]}
        facts = client.get(
            f"/v1/companies/{registry.id}/facts",
            headers=learner,
            params={"corpus_version_id": manifest.id},
        )
        assert facts.status_code == 200
        assert facts.json()["data"]["facts"][0]["observation"]["id"] == observation.id
        other = next(
            item.subject_entity_id
            for item in parent.observations
            if item.subject_entity_id != registry.id
        )
        comparison = ComparisonRequest(
            corpus_version_id=manifest.id,
            company_ids=(registry.id, other),
            metric_ids=(observation.metric_id,),
            period=observation.quantity.period,
            basis=observation.quantity.basis,
        )
        compared = client.post(
            "/v1/compare", headers=learner, json=comparison.model_dump(mode="json")
        )
        assert compared.status_code == 200
        assert compared.json()["data"]["rows"][0]["cells"][0]["state"] == "AVAILABLE"
        definition = client.post(
            "/v1/learning/drafts",
            headers=admin,
            json={
                "term": "Authored native-identity revenue",
                "definition": "Engineering content only.",
                "sources": [{"title": "Authored source", "url": "https://example.test/identity"}],
                "metric_ids": [observation.metric_id],
            },
        )
        assert definition.status_code == 200
        definition_id = definition.json()["data"]["id"]
        assert (
            client.post(
                f"/v1/learning/drafts/{definition_id}/review",
                headers=admin,
                json={"decision": "APPROVE", "note": "Authored fixture only."},
            ).status_code
            == 200
        )
        glossary = client.post(
            "/v1/learning/versions", headers=admin, json={"definition_ids": [definition_id]}
        ).json()["data"]
        explained = client.post(
            "/v1/learning/context",
            headers=learner,
            json={
                "glossary_version_id": glossary["glossary_version_id"],
                "definition_id": definition_id,
                "corpus_version_id": manifest.id,
                "observation_id": observation.id,
            },
        )
        assert explained.status_code == 200
        assert explained.json()["data"]["observation"]["id"] == observation.id
        assert len(explained.json()["data"]["evidence"]) == len(observation.supports)
        assert client.post("/v1/portfolio/accounts", headers=learner, json={}).status_code == 200
        order = client.post(
            "/v1/portfolio/orders",
            headers=learner,
            json={
                "request_id": str(uuid4()),
                "corpus_version_id": manifest.id,
                "company_id": registry.id,
                "side": "BUY",
                "quantity": 1,
            },
        )
        assert order.status_code == 200
        assert order.json()["data"]["entry"]["evaluation"]["reason"] == "QUOTES_UNAVAILABLE"
