"""Resolved gates over authored source fixtures in an owned disposable database."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest

from backend.tests.integration.test_numerical_applicability_storage import (
    applicability_case as applicability_case,
)
from backend.tests.integration.test_numerical_binding_storage import binding as binding
from backend.tests.integration.test_numerical_context_storage import inspection as inspection
from backend.tests.integration.test_numerical_context_storage import snapshot
from backend.tests.integration.test_publication_storage import configuration
from backend.tests.integration.test_publication_storage import prepared as prepare_projection
from regintel.db.migrations import connect_database
from regintel.entities.models import canonical_bytes
from regintel.numerical import resolved_gate as gate_module
from regintel.numerical.acceptance_models import NumericalAcceptanceRequest
from regintel.numerical.acceptance_repository import NumericalAcceptanceRepository
from regintel.numerical.candidate_models import NumericalCandidateRequest
from regintel.numerical.candidate_repository import NumericalCandidateRepository
from regintel.numerical.gate_models import gate_identity
from regintel.numerical.gate_repository import BoundNumericalGateRepository
from regintel.numerical.publication_input_repository import NumericalPublicationInputRepository
from regintel.numerical.repository import NumericalAuthorizationError, NumericalNotFound
from regintel.numerical.resolved_gate_repository import ResolvedNumericalGateRepository
from regintel.numerical.review_models import NumericalContextReviewRequest
from regintel.numerical.review_repository import (
    NumericalContextReviewRepository,
    NumericalReviewConflict,
)
from regintel.publication.models import CandidateSelection, PublicationRequest
from regintel.publication.repository import PublicationRepository

pytestmark = pytest.mark.integration


@pytest.fixture
def resolved_case(applicability_case):
    binding, base, request, reviews = applicability_case
    review = reviews.save(request, binding.source.user)
    repository = ResolvedNumericalGateRepository(reviews.source)
    return binding.source, base, review, repository


def test_resolution_preserves_base_and_requires_separate_confirmation_and_acceptance(resolved_case):
    source, base, review, repository = resolved_case
    before = snapshot(source.database)
    gate = repository.run(base.result.id, source.user)
    after = snapshot(source.database)
    assert {table for table in before if before[table] != after[table]} == {
        "bound_numerical_gate_runs"
    }
    assert gate.result.state == "READY_FOR_REVIEW" and gate.result.id != base.result.id
    assert gate.result.quantity_proposal == base.result.quantity_proposal
    assert gate.result.evidence_ids == base.result.evidence_ids
    assert gate.source_input.applicability == review
    assert gate.source_input.base_gate() == base
    assert not gate.result.acceptance_eligible and not gate.result.mandatory_m1_validation_complete
    history = BoundNumericalGateRepository(repository.source)
    assert history.get(base.result.id, source.user) == base
    assert history.get(gate.result.id, source.user) == repository.run(base.result.id, source.user)
    assert snapshot(source.database) == after
    preparer = NumericalPublicationInputRepository(repository.source)
    assert preparer.prepare(gate.result.id, source.user).state == "BLOCKED"
    context_reviews = NumericalContextReviewRepository(repository.source)
    with pytest.raises(NumericalReviewConflict):
        context_reviews.save(
            NumericalContextReviewRequest(
                gate_run_id=base.result.id,
                decision="CONFIRM_CONTEXT",
                evidence_ids=base.result.evidence_ids,
                note="Authored attempt to confirm original gate.",
            ),
            source.user,
        )
    confirmation = context_reviews.save(
        NumericalContextReviewRequest(
            gate_run_id=gate.result.id,
            decision="CONFIRM_CONTEXT",
            evidence_ids=gate.result.evidence_ids,
            note="Authored fixture confirmation; no real approval.",
        ),
        source.user,
    )
    prepared = preparer.prepare(gate.result.id, source.user)
    assert prepared.state == "READY_FOR_ADAPTER" and prepared.proposed_input is not None
    assert prepared.proposed_input.proof == base.source_input.binding
    assert prepared.proposed_input.context_review == confirmation
    candidate = NumericalCandidateRepository(repository.source).save(
        NumericalCandidateRequest(
            gate_run_id=gate.result.id, prepared_input_id=prepared.proposed_input.id
        ),
        source.user,
    )
    accepted = NumericalAcceptanceRepository(repository.source).save(
        NumericalAcceptanceRequest(
            candidate_id=candidate.record.id,
            decision="ACCEPT",
            evidence_ids=gate.result.evidence_ids,
            note="Authored engineering acceptance retains all original words and qualifiers.",
        ),
        source.user,
    )
    assert accepted.record.state == "ACCEPTED_UNPUBLISHED"
    assert accepted.candidate.preparation.proposed_input.proof == base.source_input.binding
    assert not accepted.record.publishes_fact
    final = snapshot(source.database)
    assert {table for table in after if after[table] != final[table]} == {
        "numerical_context_reviews",
        "numerical_candidates",
        "numerical_acceptances",
    }
    publication = PublicationRepository(source.database, repository.source)
    manifest = publication.build(
        PublicationRequest(
            idempotency_key=str(uuid4()),
            parent_corpus_version_id=None,
            selections=(
                CandidateSelection(
                    candidate_run_id=gate.result.id,
                    candidate_id=candidate.record.id,
                    review_id=accepted.record.id,
                ),
            ),
        ),
        configuration(),
        source.user,
    )
    published = publication.finalize(
        manifest.id,
        configuration(),
        source.user,
        prepare_projection(publication, source.user, manifest),
    )
    observation = published.observations[0]
    assert observation.quantity.raw_value == base.result.quantity_proposal.raw_value
    assert {span.evidence_id for span in observation.supports} == set(base.result.evidence_ids)
    assert BoundNumericalGateRepository(repository.source).get(base.result.id, source.user) == base


def test_unsaved_applicability_and_recursive_resolution_cannot_create_a_gate(applicability_case):
    binding, base, request, reviews = applicability_case
    source = binding.source
    repository = ResolvedNumericalGateRepository(reviews.source)
    before = snapshot(source.database)
    with pytest.raises(NumericalNotFound):
        repository.run(base.result.id, source.user)
    assert snapshot(source.database) == before
    reviews.save(request, source.user)
    gate = repository.run(base.result.id, source.user)
    after = snapshot(source.database)
    with pytest.raises(NumericalReviewConflict):
        repository.run(gate.result.id, source.user)
    assert snapshot(source.database) == after


@pytest.mark.parametrize("actor", ["learner", "forged", "stale", "inactive"])
def test_resolution_requires_current_admin_without_writes(resolved_case, actor):
    source, base, _, repository = resolved_case
    user = source.user
    if actor == "learner":
        user = source.learner
    elif actor == "forged":
        user = replace(source.learner, role="admin")
    elif actor == "stale":
        user = replace(user, auth_version=user.auth_version + 1)
    else:
        with connect_database(source.database) as connection:
            connection.execute("UPDATE regintel.users SET is_active=false WHERE id=%s", (user.id,))
    before = snapshot(source.database)
    with pytest.raises(NumericalAuthorizationError):
        repository.run(base.result.id, user)
    assert snapshot(source.database) == before


def test_concurrent_resolution_appends_one_gate(resolved_case):
    source, base, _, repository = resolved_case
    barrier = Barrier(2)

    def run():
        barrier.wait(timeout=30)
        return repository.run(base.result.id, source.user)

    with ThreadPoolExecutor(max_workers=2) as workers:
        calls = [workers.submit(run) for _ in range(2)]
        gates = [call.result(timeout=90) for call in calls]
    assert gates[0] == gates[1]
    with connect_database(source.database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM regintel.bound_numerical_gate_runs"
        ).fetchone() == (2,)


def test_changed_original_source_blocks_resolution_and_confirmation_but_history_replays(
    resolved_case,
):
    source, base, _, repository = resolved_case
    gate = repository.run(base.result.id, source.user)
    before = snapshot(source.database)
    original = source.source_path.read_bytes()
    try:
        source.source_path.write_bytes(original + b"authored tampering")
        with pytest.raises((NumericalReviewConflict, ValueError)):
            repository.run(base.result.id, source.user)
        with pytest.raises((NumericalReviewConflict, ValueError)):
            NumericalContextReviewRepository(repository.source).save(
                NumericalContextReviewRequest(
                    gate_run_id=gate.result.id,
                    decision="CONFIRM_CONTEXT",
                    evidence_ids=gate.result.evidence_ids,
                    note="Authored attempt after bytes changed.",
                ),
                source.user,
            )
        assert (
            BoundNumericalGateRepository(repository.source).get(gate.result.id, source.user) == gate
        )
    finally:
        source.source_path.write_bytes(original)
    assert snapshot(source.database) == before


def test_changed_resolver_configuration_preserves_history_but_blocks_confirmation(
    resolved_case, monkeypatch
):
    source, base, _, repository = resolved_case
    gate = repository.run(base.result.id, source.user)
    monkeypatch.setattr(gate_module, "resolved_gate_configuration_sha256", lambda: "f" * 64)
    before = snapshot(source.database)
    assert BoundNumericalGateRepository(repository.source).get(gate.result.id, source.user) == gate
    with pytest.raises(NumericalReviewConflict):
        NumericalContextReviewRepository(repository.source).save(
            NumericalContextReviewRequest(
                gate_run_id=gate.result.id,
                decision="CONFIRM_CONTEXT",
                evidence_ids=gate.result.evidence_ids,
                note="Authored stale configuration attempt.",
            ),
            source.user,
        )
    assert snapshot(source.database) == before


@pytest.mark.parametrize(
    "change",
    [
        "actor",
        "auth_version",
        "review_note",
        "base_result",
        "binding",
        "quantity",
        "evidence",
        "pass_check",
    ],
)
def test_database_guard_rejects_detached_or_rewritten_gate_inputs(resolved_case, change):
    source, base, _, repository = resolved_case
    gate = repository.run(base.result.id, source.user)
    packet, result = gate.source_input.model_dump(mode="json"), gate.result.model_dump(mode="json")
    if change == "actor":
        packet["base_submitted_by"] = str(source.learner.id)
    elif change == "auth_version":
        packet["base_auth_version"] += 1
    elif change == "review_note":
        packet["applicability"]["request"]["note"] = "Detached replacement decision."
    elif change == "base_result":
        packet["base_result"]["checks"][0]["message"] = "Rewritten base check."
    elif change == "binding":
        packet["binding"]["phrases"][0]["words"][0]["evidence"]["span"]["quote"] = "999"
    elif change == "quantity":
        result["quantity_proposal"]["raw_value"] = "999"
    elif change == "evidence":
        result["evidence_ids"] = result["evidence_ids"][1:]
    else:
        result["checks"][0]["message"] = "Rewritten previously passed check."
    body = json.dumps(packet, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    result["input_sha256"] = hashlib.sha256(body).hexdigest()
    result["configuration_sha256"] = "e" * 64
    result["id"] = gate_identity(result["input_sha256"], result["configuration_sha256"])
    output = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    before = snapshot(source.database)
    with pytest.raises(psycopg.errors.CheckViolation):
        with connect_database(source.database) as connection:
            connection.execute(
                "INSERT INTO regintel.bound_numerical_gate_runs "
                "(id,context_record_id,parse_version_id,input_bytes,input_sha256,result_bytes,"
                "result_sha256,configuration_sha256,state,submitted_by,auth_version) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    UUID(result["id"]),
                    UUID(result["context_record_id"]),
                    UUID(result["parse_version_id"]),
                    body,
                    result["input_sha256"],
                    output,
                    hashlib.sha256(output).hexdigest(),
                    result["configuration_sha256"],
                    result["state"],
                    source.user.id,
                    source.user.auth_version,
                ),
            )
    assert snapshot(source.database) == before
    assert canonical_bytes(
        BoundNumericalGateRepository(repository.source).get(base.result.id, source.user)
    ) == canonical_bytes(base)
