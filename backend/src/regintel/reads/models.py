"""Consumer contracts preserve observation provenance and exact financial values."""

from typing import Literal

from regintel.candidates.models import MetricDefinition, SourceSpan
from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, DateString, SafeInteger, Sha256Hash
from regintel.entities.models import EntityKind, EntityName
from regintel.evidence.api import EvidenceData
from regintel.publication.models import PublishedObservation
from regintel.validation.models import ContextWitness


class ViewInfo(ContractModel):
    corpus_version_id: CanonicalId
    manifest_sha256: Sha256Hash
    state: Literal["AVAILABLE", "TEMPORAL_SUPPORT_UNAVAILABLE"]
    as_of_date: DateString | None
    historical: bool
    unresolved_parent_filing_version_ids: tuple[CanonicalId, ...]


class EntityLabel(ContractModel):
    id: CanonicalId
    kind: EntityKind
    name: EntityName


class CompanyPage(ContractModel):
    view: ViewInfo
    companies: tuple[EntityLabel, ...]
    total: SafeInteger
    offset: SafeInteger
    limit: SafeInteger


class PublishedFact(ContractModel):
    observation: PublishedObservation
    metric: MetricDefinition


class FactPage(ContractModel):
    view: ViewInfo
    company: EntityLabel
    facts: tuple[PublishedFact, ...]
    total: SafeInteger
    offset: SafeInteger
    limit: SafeInteger


class CompanyGraph(ContractModel):
    view: ViewInfo
    company: EntityLabel
    nodes: tuple[EntityLabel, ...]
    edges: tuple[PublishedObservation, ...]


class PublishedEvidence(ContractModel):
    view: ViewInfo
    observation_id: CanonicalId
    evidence: EvidenceData
    supports: tuple[SourceSpan, ...]
    context_supports: tuple[ContextWitness, ...]


class ReadWire(ContractModel):
    """Schema export root only; endpoints return the individual models in envelopes."""

    info: ViewInfo
    companies: CompanyPage
    facts: FactPage
    graph: CompanyGraph
    evidence: PublishedEvidence
