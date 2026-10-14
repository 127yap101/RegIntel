"""Strict extraction contracts retaining raw source spans and reviewed entity bindings."""

import hashlib
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from regintel.contracts.models import ContractModel, RelationType, TextEvidence
from regintel.contracts.primitives import CanonicalId, Label, RawText, SafeInteger, Sha256Hash
from regintel.entities.models import EntityReview, EntityRun, canonical_bytes
from regintel.ingestion.models import CandidateKind


class SourceSpan(ContractModel):
    evidence_id: CanonicalId
    start: SafeInteger
    end: SafeInteger
    quote: Annotated[RawText, Field(min_length=1, max_length=20000)]

    @model_validator(mode="after")
    def exact_length(self) -> Self:
        if self.end <= self.start or self.end - self.start != len(self.quote):
            raise ValueError("Candidate support requires an exact Unicode subspan.")
        if "\x00" in self.quote:
            raise ValueError("Candidate support cannot contain a null code point.")
        return self


class MetricDefinition(ContractModel):
    """Extraction cues; this definition does not establish financial compatibility."""

    id: CanonicalId
    key: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    label: Label
    kind: Literal["numeric_fact", "narrative_fact"]
    cue_phrases: Annotated[
        tuple[Annotated[str, StringConstraints(min_length=1, max_length=128)], ...],
        Field(strict=False, min_length=1, max_length=16),
    ]

    @model_validator(mode="after")
    def bounded_literal_cues(self) -> Self:
        cues = list(self.cue_phrases)
        if len(set(cues)) != len(cues) or any(
            cue != cue.strip() or not any(char.isalnum() for char in cue) or "\x00" in cue
            for cue in self.cue_phrases
        ):
            raise ValueError("Metric cues must be unique bounded literal phrases.")
        if "\x00" in self.label:
            raise ValueError("Metric labels cannot contain a null code point.")
        return self


class RawQuantity(ContractModel):
    """All interpretation remains backend work; no model-computed values or dates."""

    value: SourceSpan
    unit: SourceSpan | None = None
    currency: SourceSpan | None = None
    period: SourceSpan | None = None
    basis: SourceSpan | None = None
    denominator: SourceSpan | None = None
    stake_kind: SourceSpan | None = None
    ownership_date: SourceSpan | None = None


class DraftCandidate(ContractModel):
    kind: CandidateKind
    subject_entity_id: CanonicalId
    subject_mention_id: CanonicalId
    object_entity_id: CanonicalId | None = None
    object_mention_id: CanonicalId | None = None
    metric_id: CanonicalId | None = None
    relation_type: RelationType | None = None
    supports: Annotated[tuple[SourceSpan, ...], Field(strict=False, min_length=1, max_length=16)]
    raw_text: Annotated[RawText, Field(min_length=1, max_length=20000)]
    raw_quantity: RawQuantity | None = None

    @model_validator(mode="after")
    def candidate_shape(self) -> Self:
        if "\x00" in self.raw_text:
            raise ValueError("Candidate text cannot contain a null code point.")
        keys = [(span.evidence_id, span.start, span.end) for span in self.supports]
        if len(set(keys)) != len(keys):
            raise ValueError("Candidate support spans must be unique.")
        if self.kind == "relation":
            if (
                self.object_entity_id is None
                or self.object_mention_id is None
                or self.relation_type is None
                or self.metric_id is not None
                or self.subject_entity_id == self.object_entity_id
                or self.subject_mention_id == self.object_mention_id
            ):
                raise ValueError("Relations require distinct directed endpoints and no metric.")
        elif (
            self.metric_id is None
            or self.object_entity_id is not None
            or self.object_mention_id is not None
            or self.relation_type is not None
        ):
            raise ValueError("Facts require a supplied metric and no relation endpoints.")
        if self.kind == "numeric_fact" and self.raw_quantity is None:
            raise ValueError("Numeric candidates require an exact raw-value span.")
        if self.kind == "narrative_fact" and self.raw_quantity is not None:
            raise ValueError("Narrative candidates cannot carry quantitative interpretations.")
        return self


class ExtractionIssue(ContractModel):
    code: Literal[
        "UNRESOLVED_ENTITY", "MISSING_VALUE", "AMBIGUOUS_CONTEXT", "NO_SUPPORTED_CANDIDATE"
    ]
    evidence_ids: Annotated[tuple[CanonicalId, ...], Field(strict=False, max_length=16)] = ()
    message: Annotated[RawText, Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        if len(set(self.evidence_ids)) != len(self.evidence_ids) or "\x00" in self.message:
            raise ValueError("Issue evidence IDs must be unique and its text storable.")
        return self


Drafts = Annotated[tuple[DraftCandidate, ...], Field(strict=False, max_length=1000)]


class CandidateBundle(ContractModel):
    numeric_facts: Drafts = ()
    narrative_facts: Drafts = ()
    relations: Drafts = ()
    issues: Annotated[tuple[ExtractionIssue, ...], Field(strict=False, max_length=1000)] = ()

    @model_validator(mode="after")
    def matching_kinds(self) -> Self:
        groups: tuple[tuple[CandidateKind, tuple[DraftCandidate, ...]], ...] = (
            ("numeric_fact", self.numeric_facts),
            ("narrative_fact", self.narrative_facts),
            ("relation", self.relations),
        )
        if sum(len(group) for _, group in groups) > 1000:
            raise ValueError("A candidate bundle exceeds its explicit total limit.")
        if any(candidate.kind != kind for kind, group in groups for candidate in group):
            raise ValueError("Candidate kinds must match their output collection.")
        keys = [canonical_bytes(candidate) for _, group in groups for candidate in group]
        if len(set(keys)) != len(keys):
            raise ValueError("An extraction bundle must not repeat identical candidates.")
        return self


class EffectiveMention(ContractModel):
    entity_id: CanonicalId
    mention_id: CanonicalId
    support: SourceSpan
    review_id: CanonicalId | None = None


def _exact_span(span: SourceSpan, evidence: TextEvidence) -> bool:
    return (
        span.evidence_id == evidence.id
        and evidence.span.start <= span.start < span.end <= evidence.span.end
        and evidence.span.quote[span.start - evidence.span.start : span.end - evidence.span.start]
        == span.quote
    )


class ExtractionInput(ContractModel):
    parse_version_id: CanonicalId
    entity_run: EntityRun
    evidence: Annotated[
        tuple[TextEvidence, ...], Field(strict=False, min_length=1, max_length=10000)
    ]
    metrics: Annotated[tuple[MetricDefinition, ...], Field(strict=False, max_length=100)]
    reviews: Annotated[tuple[EntityReview, ...], Field(strict=False, max_length=25000)] = ()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @model_validator(mode="after")
    def exact_source_membership(self) -> Self:
        sources = {record.id: record for record in self.evidence}
        if (
            self.entity_run.parse_version_id != self.parse_version_id
            or len(sources) != len(self.evidence)
            or set(sources) != set(self.entity_run.evidence_ids)
            or any(
                record.source.parse_version_id != self.parse_version_id for record in self.evidence
            )
        ):
            raise ValueError("Extraction requires the complete exact evidence of one entity run.")
        if sum(len(record.span.quote) for record in self.evidence) > 2000000:
            raise ValueError("Extraction input exceeds its explicit source-text limit.")
        mentions = {mention.id: mention for mention in self.entity_run.mentions}
        for mention in mentions.values():
            anchor = SourceSpan.model_validate(mention.support.model_dump(mode="python"))
            if not _exact_span(anchor, sources[anchor.evidence_id]):
                raise ValueError("Entity mentions must retain exact source spans.")
        if len({metric.id for metric in self.metrics}) != len(self.metrics) or len(
            {metric.key for metric in self.metrics}
        ) != len(self.metrics):
            raise ValueError("Metric IDs and keys must be unique within the extraction input.")
        if len({review.id for review in self.reviews}) != len(self.reviews) or len(
            {review.mention_id for review in self.reviews}
        ) != len(self.reviews):
            raise ValueError("Entity review identities must be unique within the extraction input.")
        for review in self.reviews:
            reviewed_mention = mentions.get(review.mention_id)
            if (
                review.run_id != self.entity_run.id
                or reviewed_mention is None
                or not set(review.support_evidence_ids).issubset(sources)
                or (
                    review.decision == "RESOLVE"
                    and review.entity_id
                    not in {
                        proposal.entity_id for proposal in reviewed_mention.resolution.proposals
                    }
                )
            ):
                raise ValueError(
                    "Extraction entity reviews must match the frozen run and proposals."
                )
        return self


class ExtractionConfiguration(ContractModel):
    version: Literal["1.0.0"] = "1.0.0"
    code_sha256: Sha256Hash
    max_window_chars: Annotated[int, Field(ge=1, le=20000)] = 20000
    max_candidates: Annotated[int, Field(ge=1, le=1000)] = 1000
    max_input_chars: Annotated[int, Field(ge=1, le=2000000)] = 2000000

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


def effective_mentions(source: ExtractionInput) -> tuple[EffectiveMention, ...]:
    """A reviewed rejection suppresses even a previously exact-resolved mention."""
    reviews = {review.mention_id: review for review in source.reviews}
    result: list[EffectiveMention] = []
    for mention in source.entity_run.mentions:
        review = reviews.get(mention.id)
        entity_id = (
            review.entity_id
            if review is not None
            else mention.resolution.entity_id
            if mention.resolution.state == "RESOLVED"
            else None
        )
        if entity_id is not None:
            result.append(
                EffectiveMention(
                    entity_id=entity_id,
                    mention_id=mention.id,
                    support=SourceSpan.model_validate(mention.support.model_dump(mode="python")),
                    review_id=review.id if review is not None else None,
                )
            )
    return tuple(sorted(result, key=lambda mention: mention.mention_id))
