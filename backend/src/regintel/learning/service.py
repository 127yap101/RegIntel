"""Extractive learning context consumes an explicitly selected published M1 view."""

from typing import Literal

from regintel.auth.types import User
from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, DateString
from regintel.learning.models import ReviewedDefinition
from regintel.learning.repository import LearningConflict, LearningNotFound, LearningRepository
from regintel.publication.models import Observation
from regintel.reads.models import PublishedEvidence, ViewInfo
from regintel.reads.repository import ReadUnavailable
from regintel.reads.service import PublishedReadService


class LearningContextRequest(ContractModel):
    glossary_version_id: CanonicalId
    definition_id: CanonicalId
    corpus_version_id: CanonicalId
    observation_id: CanonicalId
    as_of_date: DateString | None = None


class LearningExplanation(ContractModel):
    glossary_version_id: CanonicalId
    definition: ReviewedDefinition
    view: ViewInfo
    observation: Observation
    evidence: tuple[PublishedEvidence, ...]
    generated: Literal[False] = False


class LearningService:
    def __init__(self, repository: LearningRepository, reads: PublishedReadService | None) -> None:
        self.repository, self.reads = repository, reads

    def explain(self, request: LearningContextRequest, user: User) -> LearningExplanation:
        version = self.repository.glossary(request.glossary_version_id, user)
        definition = next(
            (item for item in version.definitions if item.definition.id == request.definition_id),
            None,
        )
        if definition is None:
            raise LearningNotFound("The definition is absent from this reviewed glossary version.")
        if self.reads is None:
            raise ReadUnavailable("Published filing context is unavailable.")
        scope = self.reads.scope(request.corpus_version_id, request.as_of_date)
        if scope.view.state != "AVAILABLE":
            raise LearningConflict("The requested published date context is unavailable.")
        observation = self.reads.observation(scope, request.observation_id)
        if observation.metric_id not in definition.definition.draft.metric_ids:
            raise LearningConflict(
                "This definition has no approved link to the selected observation metric."
            )
        identities = dict.fromkeys(
            [span.evidence_id for span in observation.supports]
            + [support.span.evidence_id for support in observation.context_supports]
        )
        evidence = tuple(
            self.reads.published_evidence(scope, observation.id, identity)
            for identity in identities
        )
        return LearningExplanation(
            glossary_version_id=version.glossary_version_id,
            definition=definition,
            view=scope.info,
            observation=observation,
            evidence=evidence,
            generated=False,
        )
