"""Read-only draft preparation from actual authored PostgreSQL acceptance records."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest

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
from backend.tests.integration.test_publication_storage import (
    AuthoredEncoder,
    configuration,
    prepared,
)
from backend.tests.integration.test_publication_storage import publication as publication
from backend.tests.integration.test_validation_storage import validated as validated
from regintel.db.migrations import connect_database
from regintel.entities.models import EntityRegistration
from regintel.entities.repository import EntityRepository
from regintel.ingestion.repository import JobRepository
from regintel.numerical import draft_repository as draft_module
from regintel.numerical.draft_models import NumericalPublicationDraftRequest
from regintel.numerical.draft_projection import prepare_numerical_graph, prepare_numerical_retrieval
from regintel.numerical.draft_repository import NumericalPublicationDraftRepository
from regintel.numerical.repository import NumericalAuthorizationError, NumericalNotFound
from regintel.numerical.review_repository import NumericalReviewConflict

pytestmark = pytest.mark.integration


@pytest.fixture
def draft_case(acceptance_case):
    case, candidate, decision, acceptances = acceptance_case
    accepted = acceptances.save(decision, case.source.user)
    request = NumericalPublicationDraftRequest(
        idempotency_key=str(uuid4()),
        parent_corpus_version_id=None,
        candidate_ids=(candidate.record.id,),
    )
    return case, accepted, request, NumericalPublicationDraftRepository(acceptances.source)


def test_draft_and_projection_preparation_change_no_authority_or_projection_rows(draft_case):
    case, accepted, request, repository = draft_case
    before = snapshot(case.source.database)
    draft = repository.prepare(request, case.source.user)
    assert draft.entries[0].acceptance == accepted
    assert (
        draft.state == "UNPUBLISHED_DRAFT"
        and not draft.corpus_committed
        and not draft.publishes_fact
    )
    proof = accepted.candidate.preparation.proposed_input.proof
    graph = prepare_numerical_graph(draft)
    retrieval = prepare_numerical_retrieval(draft, AuthoredEncoder(), "b" * 64)
    assert graph.draft_sha256 == draft.sha256
    assert {span.evidence_id for c in retrieval.numerical_chunks for span in c.supports} == {
        w.evidence.id for p in proof.phrases for w in p.words
    }
    assert repository.prepare(request, case.source.user) == draft
    with ThreadPoolExecutor(max_workers=2) as workers:
        values = list(
            workers.map(lambda _: repository.prepare(request, case.source.user), range(2))
        )
    assert values == [draft, draft]
    assert snapshot(case.source.database) == before


@pytest.mark.parametrize("actor", ["learner", "forged", "stale", "inactive", "demoted"])
def test_draft_requires_current_admin(draft_case, actor):
    case, _, request, repository = draft_case
    user = (
        case.source.learner
        if actor == "learner"
        else replace(case.source.learner, role="admin")
        if actor == "forged"
        else replace(case.source.user, auth_version=2)
        if actor == "stale"
        else case.source.user
    )
    if actor in {"inactive", "demoted"}:
        with connect_database(case.source.database) as connection:
            statement = (
                "UPDATE regintel.users SET is_active=false WHERE id=%s"
                if actor == "inactive"
                else "UPDATE regintel.users SET role='learner' WHERE id=%s"
            )
            connection.execute(statement, (user.id,))
    before = snapshot(case.source.database)
    with pytest.raises(NumericalAuthorizationError):
        repository.prepare(request, user)
    assert snapshot(case.source.database) == before


@pytest.mark.parametrize("decision", [None, "REJECT"])
def test_unaccepted_or_rejected_candidates_cannot_enter_drafts(acceptance_case, decision):
    case, candidate, proposal, acceptances = acceptance_case
    if decision:
        acceptances.save(proposal.model_copy(update={"decision": decision}), case.source.user)
    request = NumericalPublicationDraftRequest(
        idempotency_key=str(uuid4()),
        parent_corpus_version_id=None,
        candidate_ids=(candidate.record.id,),
    )
    before = snapshot(case.source.database)
    with pytest.raises(NumericalNotFound if decision is None else NumericalReviewConflict):
        NumericalPublicationDraftRepository(acceptances.source).prepare(request, case.source.user)
    assert snapshot(case.source.database) == before


def test_current_parent_is_explicit_and_never_substituted(draft_case):
    case, _, request, repository = draft_case
    before = snapshot(case.source.database)
    with pytest.raises(NumericalReviewConflict):
        repository.prepare(
            request.model_copy(update={"parent_corpus_version_id": str(uuid4())}), case.source.user
        )
    assert snapshot(case.source.database) == before


def test_changed_original_source_blocks_draft_after_acceptance(draft_case):
    case, _, request, repository = draft_case
    before = snapshot(case.source.database)
    original = case.source.source_path.read_bytes()
    try:
        case.source.source_path.write_bytes(original + b"authored changed source after acceptance")
        with pytest.raises(NumericalReviewConflict):
            repository.prepare(request, case.source.user)
    finally:
        case.source.source_path.write_bytes(original)
    assert snapshot(case.source.database) == before


def test_changed_registry_snapshot_blocks_draft(draft_case):
    case, accepted, request, repository = draft_case
    entity_id = accepted.candidate.preparation.proposed_input.subject_entity_id
    with connect_database(case.source.database) as connection:
        body = connection.execute(
            "SELECT registration_bytes FROM regintel.entity_registrations WHERE id=%s", (entity_id,)
        ).fetchone()[0]
    entity = EntityRegistration.model_validate_json(bytes(body))
    EntityRepository(case.source.database).register(
        entity.model_copy(update={"id": str(uuid4()), "identifiers": ()}), case.source.user
    )
    before = snapshot(case.source.database)
    with pytest.raises(NumericalReviewConflict):
        repository.prepare(request, case.source.user)
    assert snapshot(case.source.database) == before


def test_changed_acceptance_configuration_blocks_draft(draft_case, monkeypatch):
    case, _, request, repository = draft_case
    before = snapshot(case.source.database)
    monkeypatch.setattr(draft_module, "acceptance_configuration_sha256", lambda: "f" * 64)
    with pytest.raises(NumericalReviewConflict):
        repository.prepare(request, case.source.user)
    assert snapshot(case.source.database) == before


def test_unknown_candidates_cannot_create_a_partial_draft(draft_case):
    case, _, request, repository = draft_case
    before = snapshot(case.source.database)
    mixed = tuple(sorted((*request.candidate_ids, str(uuid4()))))
    with pytest.raises(NumericalNotFound):
        repository.prepare(request.model_copy(update={"candidate_ids": mixed}), case.source.user)
    assert snapshot(case.source.database) == before


def test_numeric_amendments_require_the_versioned_effect_adapter(monkeypatch, request):
    original = JobRepository.submit

    def submit(self, stored, metadata, *args, **kwargs):
        return original(
            self, stored, metadata.model_copy(update={"document_type": "ADDENDUM"}), *args, **kwargs
        )

    monkeypatch.setattr(JobRepository, "submit", submit)
    case, _, selection, repository = request.getfixturevalue("draft_case")
    before = snapshot(case.source.database)
    with pytest.raises(NumericalReviewConflict):
        repository.prepare(selection, case.source.user)
    assert snapshot(case.source.database) == before


@pytest.fixture
def published_parent(publication):
    repository, user, selection = publication
    manifest = repository.build(selection, configuration(), user)
    receipt = prepared(repository, user, manifest)
    return repository.finalize(manifest.id, configuration(), user, receipt)


def test_existing_published_parent_is_retained_without_rewriting_it(request):
    # Resolve the legacy parent first, then prepare numerical inputs against the
    # resulting current registry. Both fixtures share only this owned test DB.
    parent = request.getfixturevalue("published_parent")
    case, _, selection, repository = request.getfixturevalue("draft_case")
    selection = selection.model_copy(update={"parent_corpus_version_id": parent.id})
    before = snapshot(case.source.database)
    draft = repository.prepare(selection, case.source.user)
    assert draft.parent == parent and draft.request.parent_corpus_version_id == parent.id
    assert draft.parent.observations == parent.observations
    assert prepare_numerical_graph(draft).draft_sha256 == draft.sha256
    assert prepare_numerical_retrieval(draft, AuthoredEncoder(), "b" * 64).legacy_chunks
    assert snapshot(case.source.database) == before
