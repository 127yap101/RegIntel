"""Authored M3/M1 context controls; no real review or financial accuracy claim."""

from pathlib import Path
from uuid import uuid4

import pytest
from test_candidate_models import support
from test_publication_engine import ALPHA, administrator, authored, create, selected
from test_published_reads import fixture_service

from regintel.learning.models import (
    DefinitionDraft,
    GlossaryVersion,
    LearningReview,
    LearningSource,
    ReviewedDefinition,
    StoredDefinition,
)
from regintel.learning.repository import LearningConflict, LearningNotFound
from regintel.learning.service import LearningContextRequest, LearningService
from regintel.publication.models import ReviewedApproval
from regintel.reads.repository import Catalog, ReadNotFound, ReadUnavailable
from regintel.validation.models import ReviewDecision


def context_fixture(tmp_path: Path):
    reads, memory, evidence, _ = fixture_service(tmp_path)
    source = authored(f"{ALPHA} business is manufacture of solar modules.", narrative=True)
    approval = ReviewedApproval(
        decision=ReviewDecision(
            id=str(uuid4()),
            validation_run_id=str(uuid4()),
            candidate_id=selected(source).candidate_id,
            decision="APPROVE_FOR_PUBLICATION",
            supports=(support(source.source),),
            review_note="Authored engineering fixture; no actual reviewer decision.",
        ),
        reviewed_by=str(administrator().id),
        auth_version=1,
    )
    manifest = create(source, review=approval)
    assert evidence.blob is not None and evidence.result is not None
    manifest = manifest.model_copy(
        update={
            "filings": (
                manifest.filings[0].model_copy(update={"source_sha256": evidence.blob.sha256}),
            )
        }
    )
    memory.manifest = manifest
    memory.value = Catalog(entities=memory.value.entities, metrics=source.source.metrics)
    _, provenance, blob_hash, processing_hash = evidence.result
    evidence.result = (source.source.evidence[0], provenance, blob_hash, processing_hash)
    observation = manifest.observations[0]
    assert observation.metric_id is not None
    definition = ReviewedDefinition(
        definition=StoredDefinition(
            id=str(uuid4()),
            content_sha256="e" * 64,
            draft=DefinitionDraft(
                term="Authored business definition",
                definition="Authored learning content; filing text is retained separately.",
                sources=(LearningSource(title="Authored source", url="https://example.test"),),
                metric_ids=(observation.metric_id,),
            ),
            calculation=None,
            submitted_by=str(administrator().id),
        ),
        review_id=str(uuid4()),
        reviewed_by=str(administrator().id),
        review=LearningReview(decision="APPROVE", note="Authored test decision only."),
    )
    glossary = GlossaryVersion(glossary_version_id=str(uuid4()), definitions=(definition,))

    class AuthoredGlossary:
        def glossary(self, identity, user):
            assert user == administrator()
            if identity != glossary.glossary_version_id:
                raise LearningNotFound("Authored unknown version.")
            return glossary

    service = LearningService(AuthoredGlossary(), reads)
    request = LearningContextRequest(
        glossary_version_id=glossary.glossary_version_id,
        definition_id=definition.definition.id,
        corpus_version_id=manifest.id,
        observation_id=observation.id,
    )
    return service, request, memory, evidence, glossary


def test_reviewed_definition_retains_exact_published_text_and_evidence(tmp_path):
    service, request, memory, _, glossary = context_fixture(tmp_path)
    before = memory.manifest.model_dump_json()
    result = service.explain(request, administrator())
    assert result.glossary_version_id == glossary.glossary_version_id
    assert result.definition == glossary.definitions[0]
    assert result.observation == memory.manifest.observations[0]
    assert result.evidence[0].supports == result.observation.supports
    assert result.evidence[0].evidence.record.span.quote == result.observation.raw_text
    assert result.view.corpus_version_id == request.corpus_version_id
    assert result.generated is False and memory.manifest.model_dump_json() == before


@pytest.mark.parametrize(
    "field,error",
    [
        ("glossary_version_id", LearningNotFound),
        ("definition_id", LearningNotFound),
        ("corpus_version_id", ReadNotFound),
        ("observation_id", ReadNotFound),
    ],
)
def test_context_cannot_cross_selected_version_or_observation(tmp_path, field, error):
    service, request, _, _, _ = context_fixture(tmp_path)
    with pytest.raises(error):
        service.explain(request.model_copy(update={field: str(uuid4())}), administrator())


def test_context_rejects_unreviewed_metric_link(tmp_path):
    service, request, memory, _, _ = context_fixture(tmp_path)
    observation = memory.manifest.observations[0].model_copy(update={"metric_id": str(uuid4())})
    memory.manifest = memory.manifest.model_copy(update={"observations": (observation,)})
    with pytest.raises(LearningConflict, match="approved link"):
        service.explain(request, administrator())


def test_context_requires_evidence_from_the_selected_source_fingerprint(tmp_path):
    service, request, _, evidence, _ = context_fixture(tmp_path)
    assert evidence.result is not None
    record, provenance, _, processing_hash = evidence.result
    evidence.result = (record, provenance, "f" * 64, processing_hash)
    with pytest.raises(ReadUnavailable):
        service.explain(request, administrator())
