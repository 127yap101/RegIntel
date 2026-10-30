"""Explicit native numerical corrections preserve immutable history in owned databases."""

import base64
import json
from decimal import Decimal
from secrets import token_hex
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from pydantic import SecretStr

from backend.tests.integration.test_numerical_context_storage import snapshot
from backend.tests.integration.test_numerical_publication_draft_storage import (
    published_parent as published_parent,
)
from backend.tests.integration.test_publication_storage import configuration, prepared
from backend.tests.integration.test_publication_storage import publication as publication
from backend.tests.integration.test_validation_storage import validated as validated
from backend.tests.native_amendment_fixtures import numerical_amendment_pair
from regintel.auth.config import AuthSettings
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.db.migrations import connect_database
from regintel.evidence.api import EvidenceService
from regintel.evidence.repository import EvidenceRepository
from regintel.learning.repository import LearningRepository
from regintel.learning.service import LearningService
from regintel.main import create_app
from regintel.portfolio.repository import PortfolioRepository
from regintel.portfolio.service import PortfolioService
from regintel.publication.engine import PublicationConflict, corpus_view
from regintel.publication.models import PublishedNumericalObservation
from regintel.publication.repository import PublicationRepository
from regintel.publication.support import support_spans

pytestmark = pytest.mark.integration


@pytest.fixture
def pair(auth_database, tmp_path, monkeypatch, request):
    legacy = (
        request.getfixturevalue("published_parent") if getattr(request, "param", False) else None
    )
    return numerical_amendment_pair(auth_database, tmp_path, monkeypatch, legacy)


def test_native_correction_commits_separate_word_support_and_keeps_history(pair, tmp_path):
    source, _, accepted, repository, reads, parent, request, manifest = pair
    assert manifest.parent_corpus_version_id == parent.id
    assert manifest.unresolved_parent_filing_version_ids == ()
    assert len(manifest.observations) == 2 and len(manifest.active_observation_ids) == 1
    assert corpus_view(manifest, "2025-12-31").observations == parent.observations
    assert corpus_view(manifest, "2026-01-01").observations == (
        manifest.new_acceptances[0].observation,
    )
    assert {item.candidate_id for item in corpus_view(manifest, "2026-01-01").observations} == {
        accepted.candidate.record.id
    }
    assert len(corpus_view(manifest, historical=True).observations) == 2
    receipt = prepared(repository, source.user, manifest)
    assert repository.finalize(manifest.id, configuration(), source.user, receipt) == manifest
    assert repository.published(parent.id) == parent
    assert repository.build(request, configuration(), source.user) == manifest
    facts = reads.facts(
        reads.scope(manifest.id),
        accepted.candidate.preparation.proposed_input.subject_entity_id,
        0,
        20,
    )
    assert len(facts.facts) == 1 and facts.facts[
        0
    ].observation.quantity.normalized_value == Decimal("2600.20")
    with connect_database(source.database) as connection:
        rows = connection.execute(
            "SELECT normalized_value FROM regintel.publication_observations "
            "ORDER BY normalized_value"
        ).fetchall()
        assert rows == [(Decimal("2500.20"),), (Decimal("2600.20"),)]
    fixture = tmp_path / "native-amendment-wire.json"
    fixture.write_bytes(
        (
            json.dumps(
                {
                    "fixture_notice": (
                        "Authored owned-PostgreSQL amendment fixture, blank PDFs "
                        "and declared words; not real financial/research review."
                    ),
                    "request": request.model_dump(mode="json"),
                    "manifest": manifest.model_dump(mode="json"),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
    )


def test_sql_amendment_guard_refuses_gaps_disguised_cues_and_unowned_dates(pair):
    source, _, _, _, _, parent, request, manifest = pair
    original = request.model_dump(mode="json")
    before = snapshot(source.database)
    for change in (
        "gap",
        "isolated",
        "date-order",
        "issuer",
        "parent-reference",
        "unknown-version",
    ):
        payload = json.loads(json.dumps(original))
        if change == "gap":
            payload["effects"][0]["supports"][0]["spans"].pop(2)
        if change == "isolated":
            payload["effects"][0]["supports"] = [payload["effects"][0]["supports"][0]["spans"][4]]
        if change == "date-order":
            payload["effects"][0]["effective_date_support"]["spans"].reverse()
        if change == "issuer":
            payload["lineages"][0]["parent_identity"] = payload["lineages"][0]["child_identity"]
        if change == "parent-reference":
            payload["lineages"][0]["parent_reference"] = payload["lineages"][0]["child_identity"]
        if change == "unknown-version":
            payload["effects"][0]["supports"][0]["schema_version"] = "unknown"
        with connect_database(source.database) as connection:
            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(
                    "SELECT regintel.publication_amendments(%s,%s,%s)",
                    (
                        Jsonb(payload),
                        Jsonb(manifest.model_dump(mode="json")),
                        Jsonb(parent.model_dump(mode="json")),
                    ),
                )
            connection.rollback()
    assert snapshot(source.database) == before


def test_missing_native_effect_date_stays_explicitly_unavailable(pair):
    source, _, _, repository, _, _, request, _ = pair
    undated = request.model_copy(
        update={
            "idempotency_key": str(uuid4()),
            "effects": (
                request.effects[0].model_copy(
                    update={"effective_date": None, "effective_date_support": None}
                ),
            ),
        }
    )
    manifest = repository.build(undated, configuration(), source.user)
    assert corpus_view(manifest, "2026-01-01").state == "TEMPORAL_SUPPORT_UNAVAILABLE"
    assert len(corpus_view(manifest, historical=True).observations) == 2
    assert len(corpus_view(manifest).observations) == 1


def test_native_finalization_rechecks_original_bytes_before_any_effect_commit(pair):
    source, child, _, repository, _, parent, _, manifest = pair
    receipt = prepared(repository, source.user, manifest)
    blob = EvidenceRepository(source.database).get_source(child.draft.filing_version_id)
    assert blob is not None
    path = source.source.storage.root / blob.storage_key
    original = path.read_bytes()
    before = snapshot(source.database)
    try:
        path.write_bytes(original + b"\n% controlled owned-source tamper\n")
        with pytest.raises(PublicationConflict):
            repository.finalize(manifest.id, configuration(), source.user, receipt)
        assert snapshot(source.database) == before
        assert repository.published() == parent
    finally:
        path.write_bytes(original)


def test_a_negated_native_correction_cannot_advance_the_published_head(
    auth_database, tmp_path, monkeypatch
):
    with pytest.raises(PublicationConflict, match="Negated"):
        numerical_amendment_pair(
            auth_database,
            tmp_path,
            monkeypatch,
            statement="The earlier disclosure is not corrected effective 1 January 2026.",
        )
    parent = PublicationRepository(auth_database).published()
    assert parent is not None and len(parent.observations) == 1 and not parent.effects
    assert parent.observations[0].quantity.normalized_value == Decimal("2500.20")
    with connect_database(auth_database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM regintel.publication_commits"
        ).fetchone() == (1,)


@pytest.mark.parametrize("pair", [True], indirect=True)
def test_corrected_native_corpus_is_shared_by_all_four_http_modules(pair):
    source, _, accepted, repository, reads, parent, request, manifest = pair
    repository.finalize(
        manifest.id, configuration(), source.user, prepared(repository, source.user, manifest)
    )
    observed = manifest.new_acceptances[0].observation
    previous = next(
        item for item in parent.observations if isinstance(item, PublishedNumericalObservation)
    )
    other = next(
        item.subject_entity_id
        for item in parent.observations
        if item.subject_entity_id != observed.subject_entity_id
    )
    settings = AuthSettings(jwt_secret=SecretStr(token_hex(32)))
    evidence = EvidenceService(EvidenceRepository(source.database), source.source.storage)
    app = create_app(
        auth_service=AuthService(PostgreSQLAuthRepository(source.database), settings),
        evidence_service=evidence,
        read_service=reads,
        learning_service=LearningService(LearningRepository(source.database), reads),
        portfolio_service=PortfolioService(PortfolioRepository(source.database), reads),
    )
    admin = {"Authorization": "Bearer " + issue_token(source.user, settings)}
    learner = {"Authorization": "Bearer " + issue_token(source.learner, settings)}
    with TestClient(app) as client:
        facts = client.get(
            f"/v1/companies/{observed.subject_entity_id}/facts",
            headers=learner,
            params={"corpus_version_id": manifest.id},
        )
        assert facts.status_code == 200 and {
            item["observation"]["id"] for item in facts.json()["data"]["facts"]
        } == {observed.id}
        comparison = client.post(
            "/v1/compare",
            headers=learner,
            json={
                "corpus_version_id": manifest.id,
                "company_ids": [observed.subject_entity_id, other],
                "metric_ids": [observed.metric_id],
                "period": observed.quantity.period.model_dump(mode="json"),
                "basis": observed.quantity.basis,
                "as_of_date": None,
            },
        )
        assert comparison.status_code == 200
        cell = comparison.json()["data"]["rows"][0]["cells"][0]
        assert cell["state"] == "AVAILABLE" and cell["normalized"]["value"] == "2600200000.00"
        assert {item["observation"]["id"] for item in cell["inputs"]} == {observed.id}
        definition = client.post(
            "/v1/learning/drafts",
            headers=admin,
            json={
                "term": "Authored corrected revenue",
                "definition": "Authored engineering learning fixture; no real content approval.",
                "sources": [
                    {"title": "Authored source", "url": "https://example.test/native-amendment"}
                ],
                "metric_ids": [observed.metric_id],
            },
        ).json()["data"]
        assert (
            client.post(
                f"/v1/learning/drafts/{definition['id']}/review",
                headers=admin,
                json={"decision": "APPROVE", "note": "Authored content fixture only."},
            ).status_code
            == 200
        )
        glossary = client.post(
            "/v1/learning/versions", headers=admin, json={"definition_ids": [definition["id"]]}
        ).json()["data"]
        context = {
            "glossary_version_id": glossary["glossary_version_id"],
            "definition_id": definition["id"],
            "corpus_version_id": manifest.id,
            "observation_id": observed.id,
        }
        assert (
            client.post("/v1/learning/context", headers=learner, json=context).json()["data"][
                "observation"
            ]["id"]
            == observed.id
        )
        assert (
            client.post(
                "/v1/learning/context",
                headers=learner,
                json=context | {"observation_id": previous.id},
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/v1/learning/context",
                headers=learner,
                json=context | {"corpus_version_id": parent.id, "observation_id": previous.id},
            ).status_code
            == 200
        )
        account = client.post("/v1/portfolio/accounts", headers=learner, json={}).json()["data"]
        order = client.post(
            "/v1/portfolio/orders",
            headers=learner,
            json={
                "request_id": str(uuid4()),
                "corpus_version_id": manifest.id,
                "company_id": observed.subject_entity_id,
                "side": "BUY",
                "quantity": 1,
            },
        )
        assert (
            account["account_id"]
            and order.status_code == 200
            and order.json()["data"]["entry"]["evaluation"]["reason"] == "QUOTES_UNAVAILABLE"
        )
        evidence_words = {}
        for support in (
            request.lineages[0].parent_identity,
            request.lineages[0].child_identity,
            request.lineages[0].parent_reference,
            *request.effects[0].supports,
            request.effects[0].effective_date_support,
        ):
            assert support is not None
            for span in support_spans(support):
                response = client.get(f"/v1/evidence/{span.evidence_id}", headers=admin)
                assert response.status_code == 200
                evidence_words[span.evidence_id] = response.json()
        pdfs = {}
        for filing in manifest.filings:
            if filing.filing_version_id in {
                request.lineages[0].parent_filing_version_id,
                request.lineages[0].child_filing_version_id,
            }:
                pdfs[filing.filing_version_id] = base64.b64encode(
                    client.get(
                        f"/v1/filing-versions/{filing.filing_version_id}/source.pdf", headers=admin
                    ).content
                ).decode("ascii")
        artifact = {
            "fixture_notice": (
                "Actual owned-PostgreSQL native-context 1.1 authored correction; blank PDFs "
                "and declared word geometry; no real filing/content/research review."
            ),
            "request": request.model_dump(mode="json"),
            "manifest": manifest.model_dump(mode="json"),
            "evidence": evidence_words,
            "pdfs": pdfs,
            "accepted": accepted.model_dump(mode="json"),
            "meta": next(iter(evidence_words.values()))["meta"],
        }
        (source.source.storage.root.parent / "native-amendment-admin-wire.json").write_bytes(
            (json.dumps(artifact, sort_keys=True, separators=(",", ":")) + "\n").encode()
        )
