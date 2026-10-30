"""Owned authored numerical parent/child sources; never real filing annotations."""

from dataclasses import replace
from uuid import UUID, uuid4

from backend.tests.integration import test_numerical_context_storage as contexts
from backend.tests.integration.test_native_context_storage import prepare_native_context
from backend.tests.integration.test_publication_storage import configuration, prepared
from backend.tests.test_native_amendment_support import REFERENCE, STATEMENT, ordered_support
from backend.tests.test_numerical_context import ISSUER, Options, authored
from regintel.db.migrations import connect_database
from regintel.entities.repository import EntityRepository
from regintel.evidence.api import EvidenceService
from regintel.evidence.repository import EvidenceRepository
from regintel.ingestion.jobs import UploadMetadata
from regintel.numerical.acceptance_models import NumericalAcceptanceRequest
from regintel.numerical.acceptance_repository import NumericalAcceptanceRepository
from regintel.numerical.candidate_models import NumericalCandidateRequest
from regintel.numerical.candidate_repository import NumericalCandidateRepository
from regintel.numerical.gate_repository import BoundNumericalGateRepository
from regintel.numerical.publication_input_repository import NumericalPublicationInputRepository
from regintel.numerical.review_models import NumericalContextReviewRequest
from regintel.numerical.review_repository import NumericalContextReviewRepository
from regintel.parsing.native_repository import NativeM1Producer
from regintel.publication.models import (
    CandidateSelection,
    EffectProposal,
    LineageProposal,
    PublicationRequest,
)
from regintel.publication.repository import PublicationRepository
from regintel.publication.support import native_word_index
from regintel.reads.repository import ReadRepository
from regintel.reads.service import PublishedReadService


def accept_context(context, metadata):
    directory = context.source_path.parent / f"amendment-native-{context.draft.filing_version_id}"
    directory.mkdir()
    native = prepare_native_context(context, directory, metadata)
    job = NativeM1Producer(context.source).run(native.job.id, native.result, context.user)
    assert job.state == "PARSED" and job.parse_version_id == native.result.artifact.id
    assert native.result.artifact.provenance.adapter_name == "regintel-native-context"
    with connect_database(context.database) as connection:
        assert connection.execute(
            "SELECT format_version FROM regintel.parse_artifacts WHERE parse_version_id=%s",
            (UUID(job.parse_version_id),),
        ).fetchone() == ("1.1.0",)
    gate = BoundNumericalGateRepository(context.source).run(
        native.record.id, native.result.artifact.id, context.user
    )
    assert gate.result.state == "READY_FOR_REVIEW"
    NumericalContextReviewRepository(context.source).save(
        NumericalContextReviewRequest(
            gate_run_id=gate.result.id,
            decision="CONFIRM_CONTEXT",
            evidence_ids=gate.result.evidence_ids,
            note="Authored amendment fixture context, not real review.",
        ),
        context.user,
    )
    preparation = NumericalPublicationInputRepository(context.source).prepare(
        gate.result.id, context.user
    )
    assert preparation.proposed_input is not None
    candidate = NumericalCandidateRepository(context.source).save(
        NumericalCandidateRequest(
            gate_run_id=gate.result.id,
            prepared_input_id=preparation.proposed_input.id,
        ),
        context.user,
    )
    accepted = NumericalAcceptanceRepository(context.source).save(
        NumericalAcceptanceRequest(
            candidate_id=candidate.record.id,
            decision="ACCEPT",
            evidence_ids=gate.result.evidence_ids,
            note="Authored numerical amendment acceptance; no real source/content approval.",
        ),
        context.user,
    )
    return accepted


def select(accepted):
    return CandidateSelection(
        candidate_run_id=accepted.candidate.record.request.gate_run_id,
        candidate_id=accepted.candidate.record.id,
        review_id=accepted.record.id,
    )


def numerical_amendment_pair(
    database, tmp_path, monkeypatch, legacy_parent=None, *, statement=STATEMENT
):
    monkeypatch.setattr(
        contexts,
        "authored",
        lambda path: authored(
            path,
            Options(
                unit="(INR in million)",
                currency=(),
                document_title="Authored numerical parent",
            ),
        ),
    )
    parent_metadata = UploadMetadata(
        company_name_raw=ISSUER, document_type="RHP", published_on="2025-12-01"
    )
    parent = contexts.prepare_inspection(
        database,
        tmp_path,
        metadata=parent_metadata,
    )
    accepted_parent = accept_context(parent, parent_metadata)
    original = accepted_parent.candidate.preparation.proposed_input
    repository = PublicationRepository(database, parent.source)
    first_request = PublicationRequest(
        idempotency_key=str(uuid4()),
        parent_corpus_version_id=legacy_parent.id if legacy_parent else None,
        selections=(select(accepted_parent),),
    )
    first = repository.build(first_request, configuration(), parent.user)
    repository.finalize(
        first.id, configuration(), parent.user, prepared(repository, parent.user, first)
    )

    def child_source(path):
        case = authored(
            path,
            Options(
                unit="(INR in million)",
                currency=(),
                value="2,600.20",
                document_title="Authored numerical addendum",
                amendment_reference=REFERENCE,
                amendment_statement=statement,
            ),
        )
        source = case.input.model_copy(
            update={
                "draft": case.input.draft.model_copy(
                    update={
                        "subject_entity_id": original.subject_entity_id,
                        "metric_id": original.metric.id,
                    }
                ),
                "metric": original.metric,
                "policy": original.policy,
            }
        )
        return replace(case, input=source)

    monkeypatch.setattr(contexts, "authored", child_source)
    child_metadata = UploadMetadata(
        company_name_raw=ISSUER,
        document_type="ADDENDUM",
        published_on="2026-01-01",
        declared_parent_filing_version_id=parent.draft.filing_version_id,
    )
    child = contexts.prepare_inspection(
        database,
        tmp_path,
        approvals="no_issuer",
        metadata=child_metadata,
    )
    accepted_child = accept_context(child, child_metadata)
    entities = EntityRepository(database)
    old = entities.sealed_evidence_for_parse(
        accepted_parent.candidate.preparation.proposed_input.proof.parse_version_id
    )
    new = entities.sealed_evidence_for_parse(
        accepted_child.candidate.preparation.proposed_input.proof.parse_version_id
    )
    old_index, new_index = (
        native_word_index(old.artifact, old.evidence),
        native_word_index(new.artifact, new.evidence),
    )
    lineage = LineageProposal(
        id=str(uuid4()),
        parent_filing_version_id=parent.draft.filing_version_id,
        child_filing_version_id=child.draft.filing_version_id,
        lineage_type="ADDENDUM_TO",
        issuer_entity_id=original.subject_entity_id,
        parent_identity=ordered_support(old_index, ISSUER),
        child_identity=ordered_support(new_index, ISSUER),
        parent_reference=ordered_support(new_index, REFERENCE),
        review_note="Authored same-issuer parent/child decision; not a real amendment annotation.",
    )
    effect = EffectProposal(
        id=str(uuid4()),
        lineage_id=lineage.id,
        effect_type="CORRECT",
        affected_observation_ids=tuple(
            item.id
            for item in first.observations
            if item.candidate_id == accepted_parent.candidate.record.id
        ),
        new_candidate_ids=(accepted_child.candidate.record.id,),
        supports=(ordered_support(new_index, statement),),
        effective_date="2026-01-01",
        effective_date_support=ordered_support(new_index, "1 January 2026."),
        review_note="Authored explicit correction; never latest timestamp wins.",
    )
    request = PublicationRequest(
        idempotency_key=str(uuid4()),
        parent_corpus_version_id=first.id,
        selections=(select(accepted_child),),
        lineages=(lineage,),
        effects=(effect,),
    )
    manifest = repository.build(request, configuration(), parent.user)
    reads = PublishedReadService(
        repository,
        ReadRepository(database),
        EvidenceService(EvidenceRepository(database), parent.source.storage),
        None,
    )
    return parent, child, accepted_child, repository, reads, first, request, manifest
