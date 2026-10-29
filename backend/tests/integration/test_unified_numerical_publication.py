"""Unified atomic M1 publication and M1–M4 readers over authored native evidence."""

import json
from pathlib import Path
from secrets import token_hex
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from pydantic import SecretStr

from backend.tests.integration import test_numerical_context_storage as contexts
from backend.tests.integration.test_numerical_acceptance_storage import (
    acceptance_case as acceptance_case,
)
from backend.tests.integration.test_numerical_binding_storage import binding as binding
from backend.tests.integration.test_numerical_candidate_storage import (
    candidate_case as candidate_case,
)
from backend.tests.integration.test_numerical_context_review_storage import (
    reviewed_case as reviewed_case,
)
from backend.tests.integration.test_numerical_context_review_storage import (
    supported_header as supported_header,
)
from backend.tests.integration.test_numerical_context_storage import inspection as inspection
from backend.tests.integration.test_numerical_context_storage import snapshot
from backend.tests.integration.test_numerical_publication_draft_storage import (
    draft_case as draft_case,
)
from backend.tests.integration.test_numerical_publication_draft_storage import (
    published_parent as published_parent,
)
from backend.tests.integration.test_publication_storage import configuration, prepared
from backend.tests.integration.test_publication_storage import publication as publication
from backend.tests.integration.test_validation_storage import validated as validated
from backend.tests.test_numerical_context import Options, authored
from regintel.analysis.models import ComparisonRequest
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
from regintel.publication.engine import PublicationConflict
from regintel.publication.models import (
    CandidateSelection,
    CorpusManifest,
    PublicationRequest,
    PublishedNumericalObservation,
)
from regintel.publication.repository import PublicationRepository
from regintel.reads.repository import ReadNotFound, ReadRepository
from regintel.reads.service import PublishedReadService
from regintel.validation.repository import ValidationAuthorizationError

pytestmark = pytest.mark.integration


@pytest.fixture
def native_header(supported_header, monkeypatch, request):
    label = getattr(request, "param", None)
    if label is not None:
        monkeypatch.setattr(
            contexts,
            "authored",
            lambda path: authored(
                path,
                Options(
                    unit=f"({label} in million)",
                    currency=(
                        f'All references to "{label}" are to Indian Rupees, '
                        "the official currency of the Republic of India.",
                    ),
                ),
            ),
        )
    return label


@pytest.fixture
def unified(native_header, draft_case):
    case, accepted, _, drafts = draft_case
    candidate = accepted.candidate.record
    request = PublicationRequest(
        idempotency_key=str(uuid4()),
        parent_corpus_version_id=None,
        selections=(
            CandidateSelection(
                candidate_run_id=candidate.request.gate_run_id,
                candidate_id=candidate.id,
                review_id=accepted.record.id,
            ),
        ),
    )
    repository = PublicationRepository(case.source.database, drafts.source)
    reads = PublishedReadService(
        repository,
        ReadRepository(case.source.database),
        EvidenceService(EvidenceRepository(case.source.database), drafts.source.storage),
        None,
    )
    return case, accepted, request, repository, reads


@pytest.mark.parametrize("native_header", ["₹", "Rs."], indirect=True)
def test_native_publication_preserves_source_currency_alias_and_normalized_currency(
    unified, native_header
):
    case, _, request, repository, reads = unified
    manifest = repository.build(request, configuration(), case.source.user)
    result = repository.finalize(
        manifest.id,
        configuration(),
        case.source.user,
        prepared(repository, case.source.user, manifest),
    )
    observation = result.observations[0]
    assert isinstance(observation, PublishedNumericalObservation)
    assert observation.quantity.raw_currency == native_header
    assert observation.quantity.currency == "INR"
    assert observation.quantity.raw_unit == f"({native_header} in million)"
    assert (
        reads.facts(reads.scope(result.id), observation.subject_entity_id, 0, 20)
        .facts[0]
        .observation
        == observation
    )


def test_native_publication_commits_complete_audit_decimal_and_head_together(unified):
    case, accepted, request, repository, reads = unified
    before = snapshot(case.source.database)
    manifest = repository.build(request, configuration(), case.source.user)
    assert isinstance(manifest.observations[0], PublishedNumericalObservation)
    assert len(manifest.observations[0].supports) > 16
    with pytest.raises(ReadNotFound):
        reads.scope(manifest.id)
    with connect_database(case.source.database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM regintel.native_publication_audits"
        ).fetchone() == (0,)
    receipt = prepared(repository, case.source.user, manifest)
    result = repository.finalize(manifest.id, configuration(), case.source.user, receipt)
    assert result == manifest == repository.published()
    assert CorpusManifest.model_validate_json(result.model_dump_json()) == result
    observation = result.observations[0]
    assert observation.native_acceptance_id == accepted.record.id
    assert observation.validation_run_id == accepted.record.id
    with connect_database(case.source.database) as connection:
        row = connection.execute(
            "SELECT o.normalized_value,n.acceptance_id,h.corpus_version_id "
            "FROM regintel.publication_observations o "
            "JOIN regintel.native_publication_audits n ON n.observation_id=o.id "
            "CROSS JOIN regintel.publication_head h"
        ).fetchone()
        assert row == (
            observation.quantity.normalized_value,
            UUID(accepted.record.id),
            UUID(result.id),
        )
    scope = reads.scope(result.id)
    facts = reads.facts(scope, observation.subject_entity_id, 0, 20)
    assert facts.facts[0].observation == observation
    for span in observation.supports:
        assert reads.published_evidence(scope, observation.id, span.evidence_id).supports == (span,)
    assert reads.source(scope, observation.id).sha256 == observation.proof.source_sha256
    after = snapshot(case.source.database)
    assert before != after
    assert repository.finalize(manifest.id, configuration(), case.source.user, receipt) == result
    assert snapshot(case.source.database) == after


def test_native_finalization_refuses_changed_source_without_partial_authority(unified):
    case, _, request, repository, _ = unified
    manifest = repository.build(request, configuration(), case.source.user)
    receipt = prepared(repository, case.source.user, manifest)
    before = snapshot(case.source.database)
    original = case.source.source_path.read_bytes()
    try:
        case.source.source_path.write_bytes(
            original + b"authored source modification before final commit"
        )
        with pytest.raises(PublicationConflict):
            repository.finalize(manifest.id, configuration(), case.source.user, receipt)
    finally:
        case.source.source_path.write_bytes(original)
    assert snapshot(case.source.database) == before


def test_late_native_audit_failure_rolls_back_publication_head_and_observation(
    unified, monkeypatch
):
    case, _, request, repository, _ = unified
    manifest = repository.build(request, configuration(), case.source.user)
    receipt = prepared(repository, case.source.user, manifest)
    before = snapshot(case.source.database)
    original = repository._observation

    def fail(connection, selected, observation, user):
        original(connection, selected, observation, user)
        raise RuntimeError("Authored failure after native authority insert.")

    monkeypatch.setattr(repository, "_observation", fail)
    with pytest.raises(RuntimeError):
        repository.finalize(manifest.id, configuration(), case.source.user, receipt)
    assert snapshot(case.source.database) == before


@pytest.mark.parametrize(
    "change",
    [
        "value",
        "supports",
        "proof",
        "reviewer",
        "checks",
        "run",
        "currency",
        "raw_currency",
        "basis",
        "period",
        "date",
    ],
)
def test_sql_rejects_changed_native_snapshot_membership(unified, change):
    case, _, request, repository, _ = unified
    manifest = repository.build(request, configuration(), case.source.user)
    payload = manifest.new_acceptances[0].model_dump(mode="json")
    observation = payload["observation"]
    if change == "value":
        observation["quantity"]["normalized_value"] = "1"
    elif change == "supports":
        observation["supports"].pop()
    elif change == "proof":
        observation["proof"]["phrases"][0]["words"].pop()
    elif change == "reviewer":
        payload["accepted"]["record"]["reviewed_by"] = str(case.source.learner.id)
    elif change == "checks":
        payload["fresh_preparation"]["checks"][0]["state"] = "FAIL"
    elif change == "run":
        observation["validation_run_id"] = str(uuid4())
    elif change == "currency":
        observation["quantity"]["currency"] = "USD"
    elif change == "raw_currency":
        observation["quantity"]["raw_currency"] = "USD"
    elif change == "basis":
        observation["quantity"]["basis"] = "UNKNOWN"
    elif change == "period":
        observation["quantity"]["period"]["end_date"] = "2026-03-31"
    else:
        observation["source_published_on"] = "2026-10-01"
    before = snapshot(case.source.database)
    with connect_database(case.source.database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute("SELECT regintel.native_publication_snapshot(%s)", (Jsonb(payload),))
        connection.rollback()
    assert snapshot(case.source.database) == before


@pytest.mark.parametrize("action", ["UPDATE", "DELETE", "TRUNCATE"])
def test_native_audit_cannot_be_rewritten_or_discarded(unified, action):
    case, _, request, repository, _ = unified
    manifest = repository.build(request, configuration(), case.source.user)
    repository.finalize(
        manifest.id,
        configuration(),
        case.source.user,
        prepared(repository, case.source.user, manifest),
    )
    before = snapshot(case.source.database)
    command = (
        "UPDATE regintel.native_publication_audits SET auth_version=auth_version+1"
        if action == "UPDATE"
        else action
        + " "
        + ("FROM " if action == "DELETE" else "")
        + "regintel.native_publication_audits"
    )
    with connect_database(case.source.database) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute(command)
        connection.rollback()
    assert snapshot(case.source.database) == before


def test_learner_cannot_build_or_finalize_native_publication(unified):
    case, _, request, repository, _ = unified
    before = snapshot(case.source.database)
    with pytest.raises(ValidationAuthorizationError):
        repository.build(request, configuration(), case.source.learner)
    assert snapshot(case.source.database) == before
    manifest = repository.build(request, configuration(), case.source.user)
    receipt = prepared(repository, case.source.user, manifest)
    before = snapshot(case.source.database)
    with pytest.raises(ValidationAuthorizationError):
        repository.finalize(manifest.id, configuration(), case.source.learner, receipt)
    assert snapshot(case.source.database) == before


def test_native_parent_can_advance_with_legacy_content_without_replacing_history(request):
    _, _, legacy_selection = request.getfixturevalue("publication")
    case, _, native_selection, repository, reads = request.getfixturevalue("unified")
    first = repository.build(native_selection, configuration(), case.source.user)
    repository.finalize(
        first.id, configuration(), case.source.user, prepared(repository, case.source.user, first)
    )
    following = legacy_selection.model_copy(
        update={"idempotency_key": str(uuid4()), "parent_corpus_version_id": first.id}
    )
    second = repository.build(following, configuration(), case.source.user)
    repository.finalize(
        second.id, configuration(), case.source.user, prepared(repository, case.source.user, second)
    )
    assert repository.published().id == second.id
    assert repository.published(first.id) == first
    native = first.observations[0]
    assert native in second.observations and native.id in second.active_observation_ids
    assert (
        reads.facts(reads.scope(second.id), native.subject_entity_id, 0, 20).facts[0].observation
        == native
    )


def test_new_request_cannot_duplicate_an_existing_native_observation(unified):
    case, _, selection, repository, _ = unified
    first = repository.build(selection, configuration(), case.source.user)
    repository.finalize(
        first.id, configuration(), case.source.user, prepared(repository, case.source.user, first)
    )
    before = snapshot(case.source.database)
    duplicate = selection.model_copy(
        update={"idempotency_key": str(uuid4()), "parent_corpus_version_id": first.id}
    )
    with pytest.raises(PublicationConflict):
        repository.build(duplicate, configuration(), case.source.user)
    assert snapshot(case.source.database) == before


def test_public_native_observation_flows_through_all_four_http_modules(request):
    parent = request.getfixturevalue("published_parent")
    case, _, selection, repository, reads = request.getfixturevalue("unified")
    selection = selection.model_copy(update={"parent_corpus_version_id": parent.id})
    manifest = repository.build(selection, configuration(), case.source.user)
    repository.finalize(
        manifest.id,
        configuration(),
        case.source.user,
        prepared(repository, case.source.user, manifest),
    )
    observation = next(
        item for item in manifest.observations if isinstance(item, PublishedNumericalObservation)
    )
    settings = AuthSettings(jwt_secret=SecretStr(token_hex(32)))
    accounts = PostgreSQLAuthRepository(case.source.database)
    auth = AuthService(accounts, settings)
    app = create_app(
        auth_service=auth,
        read_service=reads,
        learning_service=LearningService(LearningRepository(case.source.database), reads),
        portfolio_service=PortfolioService(PortfolioRepository(case.source.database), reads),
    )
    admin = {"Authorization": "Bearer " + issue_token(case.source.user, settings)}
    learner = {"Authorization": "Bearer " + issue_token(case.source.learner, settings)}
    with TestClient(app) as client:
        company = client.get(
            "/v1/companies", headers=learner, params={"corpus_version_id": manifest.id}
        )
        assert company.status_code == 200 and observation.subject_entity_id in {
            item["id"] for item in company.json()["data"]["companies"]
        }
        facts = client.get(
            f"/v1/companies/{observation.subject_entity_id}/facts",
            headers=learner,
            params={"corpus_version_id": manifest.id},
        )
        assert facts.status_code == 200
        assert (
            facts.json()["data"]["facts"][0]["observation"]["schema_version"]
            == "native-numerical-observation-1"
        )
        other = next(
            item.subject_entity_id
            for item in parent.observations
            if item.subject_entity_id != observation.subject_entity_id
        )
        comparison = ComparisonRequest(
            corpus_version_id=manifest.id,
            company_ids=(observation.subject_entity_id, other),
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
                "term": "Authored native revenue",
                "definition": "Authored educational fixture; no real financial content approval.",
                "sources": [{"title": "Authored source", "url": "https://example.test/native"}],
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
        assert explained.status_code == 200 and len(explained.json()["data"]["evidence"]) == len(
            observation.supports
        )
        assert explained.json()["data"]["observation"]["proof"] == observation.proof.model_dump(
            mode="json"
        )
        account = client.post("/v1/portfolio/accounts", headers=learner, json={}).json()["data"]
        assert account["account_id"]
        order = client.post(
            "/v1/portfolio/orders",
            headers=learner,
            json={
                "request_id": str(uuid4()),
                "corpus_version_id": manifest.id,
                "company_id": observation.subject_entity_id,
                "side": "BUY",
                "quantity": 1,
            },
        )
        assert (
            order.status_code == 200
            and order.json()["data"]["entry"]["evaluation"]["reason"] == "QUOTES_UNAVAILABLE"
        )
        # Source-labelled authored wire fixture for the corresponding strict
        # browser-contract checks. No tokens, passwords or source PDFs are saved.
        wire = {
            "facts": facts.json(),
            "comparison": compared.json(),
            "request": comparison.model_dump(mode="json"),
            "context": explained.json(),
            "companies": company.json(),
            "order": order.json(),
        }
        (
            Path(__file__).resolve().parents[3]
            / ".cache/unified-native-wire-authored-20261028.json"
        ).write_text(
            json.dumps(wire, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
