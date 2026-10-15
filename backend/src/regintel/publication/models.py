"""Immutable publication contracts; requests cannot supply accepted payloads."""

import hashlib
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from regintel.candidates.models import SourceSpan
from regintel.contracts.models import ContractModel, QuantitativeValue, RelationType
from regintel.contracts.primitives import CanonicalId, DateString, SafeInteger, Sha256Hash
from regintel.entities.models import canonical_bytes
from regintel.ingestion.models import CandidateKind, DocumentType, StoredText
from regintel.validation.models import ContextWitness, ReviewDecision, ValidationRun

type EffectType = Literal["ADD", "CORRECT", "SUPPLEMENT", "SUPERSEDE", "REMOVE"]
type LineageType = Literal["ADDENDUM_TO", "CORRIGENDUM_TO", "AMENDS"]
type Ids = Annotated[tuple[CanonicalId, ...], Field(strict=False, max_length=1000)]
type Spans = Annotated[tuple[SourceSpan, ...], Field(strict=False, min_length=1, max_length=16)]
type Note = Annotated[StoredText, Field(min_length=1, max_length=2000)]


class CandidateSelection(ContractModel):
    candidate_run_id: CanonicalId
    candidate_id: CanonicalId
    review_id: CanonicalId | None


class FilingSnapshot(ContractModel):
    filing_id: CanonicalId
    filing_version_id: CanonicalId
    parse_version_id: CanonicalId
    source_sha256: Sha256Hash
    document_type: DocumentType
    published_on: DateString | None


class ReviewedApproval(ContractModel):
    decision: ReviewDecision
    reviewed_by: CanonicalId
    auth_version: Annotated[SafeInteger, Field(ge=1)]


class LineageProposal(ContractModel):
    id: CanonicalId
    parent_filing_version_id: CanonicalId
    child_filing_version_id: CanonicalId
    lineage_type: LineageType
    issuer_entity_id: CanonicalId
    parent_identity: SourceSpan
    child_identity: SourceSpan
    parent_reference: SourceSpan
    review_note: Note

    @model_validator(mode="after")
    def distinct_sources(self) -> Self:
        if self.parent_filing_version_id == self.child_filing_version_id:
            raise ValueError("A lineage requires distinct original filing versions.")
        if not self.review_note.strip():
            raise ValueError("Lineage requires an audited explanation.")
        return self


class EffectProposal(ContractModel):
    id: CanonicalId
    lineage_id: CanonicalId
    effect_type: EffectType
    affected_observation_ids: Ids
    new_candidate_ids: Ids
    supports: Spans
    effective_date: DateString | None
    effective_date_support: SourceSpan | None
    review_note: Note

    @model_validator(mode="after")
    def scoped_effect(self) -> Self:
        for values in (self.affected_observation_ids, self.new_candidate_ids):
            if len(set(values)) != len(values):
                raise ValueError("Effect references must be distinct.")
        if self.effect_type == "ADD":
            valid = not self.affected_observation_ids and bool(self.new_candidate_ids)
        elif self.effect_type == "REMOVE":
            valid = bool(self.affected_observation_ids) and not self.new_candidate_ids
        else:
            valid = bool(self.affected_observation_ids) and bool(self.new_candidate_ids)
        if not valid or not self.review_note.strip():
            raise ValueError("An effect requires its explicit affected/new scope and review.")
        if (self.effective_date is None) != (self.effective_date_support is None):
            raise ValueError("An effective date requires exact source support.")
        return self


class PublicationRequest(ContractModel):
    idempotency_key: CanonicalId
    parent_corpus_version_id: CanonicalId | None
    selections: Annotated[tuple[CandidateSelection, ...], Field(strict=False, max_length=100)]
    lineages: Annotated[tuple[LineageProposal, ...], Field(strict=False, max_length=100)] = ()
    effects: Annotated[tuple[EffectProposal, ...], Field(strict=False, max_length=100)] = ()

    @model_validator(mode="after")
    def distinct_request(self) -> Self:
        for ids in (
            tuple(item.candidate_id for item in self.selections),
            tuple(item.id for item in self.lineages),
            tuple(item.id for item in self.effects),
        ):
            if len(set(ids)) != len(ids) or ids != tuple(sorted(ids)):
                raise ValueError("Publication entries must be distinct and sorted by canonical ID.")
        if not self.selections and not self.lineages and not self.effects:
            raise ValueError("A publication requires supported new content or amendment decisions.")
        return self


class PublicationConfiguration(ContractModel):
    version: Literal["1.0.0"] = "1.0.0"
    code_sha256: Sha256Hash
    validator_configuration_sha256: Sha256Hash
    embedding_manifest_sha256: Sha256Hash
    embedding_model: Literal["BAAI/bge-small-en-v1.5"] = "BAAI/bge-small-en-v1.5"
    embedding_revision: Literal["5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"] = (
        "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
    )
    embedding_dimensions: Literal[384] = 384
    max_embedding_tokens: Literal[512] = 512
    chunk_target_tokens: Literal[450] = 450
    onnxruntime_version: Literal["1.30.0"] = "1.30.0"
    tokenizers_version: Literal["0.23.2"] = "0.23.2"
    neo4j_driver_version: Literal["6.4.0"] = "6.4.0"

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


class PublishedObservation(ContractModel):
    id: CanonicalId
    acceptance_audit_id: CanonicalId
    first_corpus_version_id: CanonicalId
    candidate_id: CanonicalId
    candidate_run_id: CanonicalId
    parse_version_id: CanonicalId
    filing_version_id: CanonicalId
    validation_run_id: CanonicalId
    validation_input_sha256: Sha256Hash
    validator_configuration_sha256: Sha256Hash
    review_id: CanonicalId | None
    kind: CandidateKind
    subject_entity_id: CanonicalId
    object_entity_id: CanonicalId | None
    relation_type: RelationType | None
    metric_id: CanonicalId | None
    raw_text: StoredText
    quantity: QuantitativeValue | None
    supports: Spans
    context_supports: Annotated[tuple[ContextWitness, ...], Field(strict=False, max_length=16)]
    source_published_on: DateString | None

    @model_validator(mode="after")
    def typed_observation(self) -> Self:
        if self.kind == "relation":
            if (
                self.object_entity_id is None
                or self.relation_type is None
                or self.metric_id is not None
            ):
                raise ValueError("Relations retain their directed typed endpoints.")
            if self.subject_entity_id == self.object_entity_id:
                raise ValueError("Relation endpoints must be distinct.")
        elif (
            self.metric_id is None
            or self.object_entity_id is not None
            or self.relation_type is not None
        ):
            raise ValueError("Facts retain a metric without relation endpoints.")
        if self.kind == "numeric_fact" and self.quantity is None:
            raise ValueError("Numeric observations require the validated exact quantity.")
        if self.kind == "narrative_fact" and self.quantity is not None:
            raise ValueError("Narrative observations do not acquire numeric values.")
        return self


class AcceptanceSnapshot(ContractModel):
    observation: PublishedObservation
    fresh_validation: ValidationRun
    original_review: ReviewedApproval | None


class AuditedLineage(ContractModel):
    proposal: LineageProposal
    approved_in_corpus_version_id: CanonicalId
    reviewed_by: CanonicalId
    auth_version: Annotated[SafeInteger, Field(ge=1)]


class AuditedEffect(ContractModel):
    proposal: EffectProposal
    new_observation_ids: Ids
    approved_in_corpus_version_id: CanonicalId
    reviewed_by: CanonicalId
    auth_version: Annotated[SafeInteger, Field(ge=1)]


class CorpusManifest(ContractModel):
    id: CanonicalId
    parent_corpus_version_id: CanonicalId | None
    request_sha256: Sha256Hash
    configuration: PublicationConfiguration
    approved_by: CanonicalId
    approved_auth_version: Annotated[SafeInteger, Field(ge=1)]
    filings: Annotated[tuple[FilingSnapshot, ...], Field(strict=False, max_length=1000)]
    observations: Annotated[tuple[PublishedObservation, ...], Field(strict=False, max_length=10000)]
    new_acceptances: Annotated[tuple[AcceptanceSnapshot, ...], Field(strict=False, max_length=100)]
    lineages: Annotated[tuple[AuditedLineage, ...], Field(strict=False, max_length=1000)]
    effects: Annotated[tuple[AuditedEffect, ...], Field(strict=False, max_length=1000)]
    active_observation_ids: Ids
    unresolved_parent_filing_version_ids: Ids

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @model_validator(mode="after")
    def complete_manifest(self) -> Self:
        ids = tuple(item.id for item in self.observations)
        if len(set(ids)) != len(ids) or ids != tuple(sorted(ids)):
            raise ValueError("Historical observations must be distinct and canonically ordered.")
        if not set(self.active_observation_ids).issubset(ids):
            raise ValueError("Active observations must belong to this approved historical corpus.")
        if len(set(self.active_observation_ids)) != len(self.active_observation_ids):
            raise ValueError("Active observation references must be distinct.")
        return self


class CorpusView(ContractModel):
    corpus_version_id: CanonicalId
    as_of_date: DateString | None
    state: Literal["AVAILABLE", "TEMPORAL_SUPPORT_UNAVAILABLE"]
    observations: tuple[PublishedObservation, ...]
    unresolved_parent_filing_version_ids: Ids
