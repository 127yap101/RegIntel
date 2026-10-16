"""Real read-only administrator adapters on disposable authored PostgreSQL state."""

from uuid import uuid4

import pytest

from backend.tests.integration.test_publication_storage import configuration, prepared
from backend.tests.integration.test_publication_storage import publication as publication
from backend.tests.integration.test_validation_storage import SOURCE, ValidationContext
from backend.tests.integration.test_validation_storage import validated as validated
from regintel.admin.repository import AdminRepository
from regintel.auth.types import User
from regintel.candidates.records import drafts
from regintel.db.migrations import connect_database
from regintel.publication.models import PublicationRequest
from regintel.publication.repository import PublicationRepository
from regintel.validation.models import ReviewDecision
from regintel.validation.repository import ValidationAuthorizationError, ValidationNotFound

pytestmark = pytest.mark.integration


def test_queues_and_exact_review_page_preserve_authority(validated: ValidationContext) -> None:
    context = validated
    run = context.repository.validate(context.candidate_run_id, context.user)
    store = AdminRepository(context.database)
    with connect_database(context.database) as connection:
        before = connection.execute(
            "SELECT (SELECT count(*) FROM regintel.acceptance_audits),"
            "(SELECT count(*) FROM regintel.fact_observations),"
            "(SELECT count(*) FROM regintel.corpus_versions)"
        ).fetchone()
    for kind in ("filings", "processing", "validations", "publications"):
        page = store.queue(kind, 0, 1, context.user)
        assert len(page.items) <= 1
        assert page.limit == 1
    assert store.metrics(context.user).items
    page = store.review_page(run.id, "ALL", 0, 25, context.user)
    assert page.approval_current
    assert {item.candidate.id for item in page.items} == {
        result.candidate_id for result in run.results
    }
    assert all(
        len(item.result.checks) == 16 and item.draft.raw_text == item.candidate.raw_text
        for item in page.items
    )
    assert all(item.accepted_observation_id is None for item in page.items)
    assert store.review_page(run.id, "PASS", 0, 25, context.user).items
    assert store.review_page(run.id, "ALL", 10000, 1, context.user).items == ()
    with connect_database(context.database) as connection:
        after = connection.execute(
            "SELECT (SELECT count(*) FROM regintel.acceptance_audits),"
            "(SELECT count(*) FROM regintel.fact_observations),"
            "(SELECT count(*) FROM regintel.corpus_versions)"
        ).fetchone()
    assert before == after


@pytest.mark.parametrize("validated", [{"no_policy": True}], indirect=True)
def test_historical_final_review_is_visible_in_fresh_gate(validated: ValidationContext) -> None:
    context = validated
    first = context.repository.validate(context.candidate_run_id, context.user)
    source = context.repository.input_for_run(context.candidate_run_id)
    pair = next(
        (record, draft)
        for record, draft in zip(
            source.candidate_run.candidates, drafts(source.candidate_run.bundle), strict=True
        )
        if record.kind == "narrative_fact"
    )
    decision = ReviewDecision(
        id=str(uuid4()),
        validation_run_id=first.id,
        candidate_id=pair[0].id,
        decision="APPROVE_FOR_PUBLICATION",
        supports=(pair[1].supports[0],),
        review_note="Authored original final review.",
    )
    context.repository.review(decision, context.user)
    context.repository.register_policy(context.policy, context.user)
    fresh = context.repository.validate(context.candidate_run_id, context.user)
    assert fresh.id != first.id
    store = AdminRepository(context.database)
    assert not store.review_page(first.id, "ALL", 0, 25, context.user).approval_current
    page = store.review_page(fresh.id, "ALL", 0, 25, context.user)
    assert page.approval_current
    assert (
        next(item for item in page.items if item.candidate.id == decision.candidate_id).review
        == decision
    )
    assert store.review_page(first.id, "REVIEW", 0, 25, context.user).items


def test_admin_repository_rechecks_current_account(validated: ValidationContext) -> None:
    context = validated
    with connect_database(context.database) as connection:
        connection.execute(
            "UPDATE regintel.users SET role='learner' WHERE id=%s", (context.user.id,)
        )
    with pytest.raises(ValidationAuthorizationError):
        AdminRepository(context.database).queue("filings", 0, 20, context.user)


def test_unknown_audit_remains_unavailable(validated: ValidationContext) -> None:
    with pytest.raises(ValidationNotFound):
        AdminRepository(validated.database).review_page(str(uuid4()), "ALL", 0, 20, validated.user)


@pytest.mark.parametrize(
    "validated",
    [
        {
            "source": SOURCE.replace("INR 1,234.50 crore", "USD 1,234.50 rupees"),
            "allowed_unit_labels": ("rupees",),
        }
    ],
    indirect=True,
)
def test_quarantined_currency_conflict_stays_ineligible(validated: ValidationContext) -> None:
    run = validated.repository.validate(validated.candidate_run_id, validated.user)
    page = AdminRepository(validated.database).review_page(
        run.id, "QUARANTINED", 0, 25, validated.user
    )
    assert page.items
    assert all(not item.result.reviewer_eligible for item in page.items)
    assert any(
        check.code == "CURRENCY" and check.state == "FAIL"
        for item in page.items
        for check in item.result.checks
    )


def test_published_queue_and_existing_acceptance_are_explicit(
    publication: tuple[PublicationRepository, User, PublicationRequest],
) -> None:
    repository, user, request = publication
    manifest = repository.build(request, configuration(), user)
    repository.finalize(manifest.id, configuration(), user, prepared(repository, user, manifest))
    store = AdminRepository(repository.database)
    queue = store.queue("publications", 0, 25, user)
    assert next(item for item in queue.items if item.id == manifest.id).state == "PUBLISHED"
    assert queue.published_corpus_id == manifest.id
    acceptance = manifest.new_acceptances[0]
    page = store.review_page(acceptance.fresh_validation.id, "ALL", 0, 25, user)
    assert (
        next(
            item for item in page.items if item.candidate.id == acceptance.observation.candidate_id
        ).accepted_observation_id
        == acceptance.observation.id
    )
