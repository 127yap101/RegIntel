"""Published version, scope and exact evidence gates precede presentation."""

from dataclasses import dataclass
from typing import Protocol

from regintel.candidates.models import _exact_span
from regintel.evidence.api import EvidenceData, EvidenceService
from regintel.ingestion.models import SourceBlob
from regintel.publication.engine import PublicationConflict, corpus_view
from regintel.publication.graph import GraphProjection
from regintel.publication.models import CorpusManifest, CorpusView, PublishedObservation
from regintel.reads.models import (
    CompanyGraph,
    CompanyPage,
    EntityLabel,
    FactPage,
    PublishedEvidence,
    PublishedFact,
    ViewInfo,
)
from regintel.reads.repository import Catalog, CatalogReader, ReadNotFound, ReadUnavailable


class CorpusReader(Protocol):
    def published(self, corpus_id: str | None = None) -> CorpusManifest: ...


@dataclass(frozen=True)
class ReadScope:
    manifest: CorpusManifest
    view: CorpusView
    info: ViewInfo


def label(catalog: Catalog, entity_id: str) -> EntityLabel:
    found = next((item for item in catalog.entities if item.id == entity_id), None)
    if found is None:
        raise ReadUnavailable("A frozen published identity is unavailable.")
    return EntityLabel(id=found.id, kind=found.kind, name=found.legal_name)


class PublishedReadService:
    def __init__(
        self,
        corpus: CorpusReader,
        catalog: CatalogReader,
        evidence: EvidenceService,
        graph: GraphProjection | None,
    ) -> None:
        self.corpus = corpus
        self.catalog = catalog
        self.evidence = evidence
        self.graph = graph

    def scope(
        self,
        corpus_id: str | None,
        as_of_date: str | None = None,
        historical: bool = False,
    ) -> ReadScope:
        try:
            manifest = self.corpus.published(corpus_id)
        except PublicationConflict:
            raise ReadNotFound("A published corpus is required.") from None
        if corpus_id is not None and manifest.id != corpus_id:
            raise ReadUnavailable("The requested published corpus differs.")
        view = corpus_view(manifest, as_of_date, historical=historical)
        return ReadScope(
            manifest,
            view,
            ViewInfo(
                corpus_version_id=manifest.id,
                manifest_sha256=manifest.sha256,
                state=view.state,
                as_of_date=as_of_date,
                historical=historical,
                unresolved_parent_filing_version_ids=view.unresolved_parent_filing_version_ids,
            ),
        )

    def companies(self, scope: ReadScope, query: str, offset: int, limit: int) -> CompanyPage:
        catalog = (
            self.catalog.catalog(scope.manifest)
            if scope.view.observations
            else Catalog(entities=(), metrics=())
        )
        identities = {
            identity
            for item in scope.view.observations
            for identity in (item.subject_entity_id, item.object_entity_id)
            if identity is not None
        }
        query = query.strip().casefold()
        selected = sorted(
            (
                label(catalog, item.id)
                for item in catalog.entities
                if item.kind == "COMPANY"
                and item.id in identities
                and any(
                    query in term.casefold()
                    for term in (
                        item.legal_name,
                        *(alias.name for alias in item.aliases),
                        *(identifier.value for identifier in item.identifiers),
                    )
                )
            ),
            key=lambda item: (item.name.casefold(), item.id),
        )
        return CompanyPage(
            view=scope.info,
            companies=tuple(selected[offset : offset + limit]),
            total=len(selected),
            offset=offset,
            limit=limit,
        )

    def company(self, scope: ReadScope, catalog: Catalog, identity: str) -> EntityLabel:
        if not any(
            identity in (item.subject_entity_id, item.object_entity_id)
            for item in (
                scope.view.observations
                if scope.view.state == "AVAILABLE"
                else scope.manifest.observations
            )
        ):
            raise ReadNotFound("Company is absent from the published corpus.")
        result = label(catalog, identity)
        if result.kind != "COMPANY":
            raise ReadNotFound("A published company is required.")
        return result

    def facts(self, scope: ReadScope, identity: str, offset: int, limit: int) -> FactPage:
        catalog = self.catalog.catalog(scope.manifest)
        company = self.company(scope, catalog, identity)
        metrics = {item.id: item for item in catalog.metrics}
        observations = [
            item
            for item in scope.view.observations
            if item.subject_entity_id == identity and item.kind != "relation"
        ]
        try:
            facts = tuple(
                PublishedFact(observation=item, metric=metrics[item.metric_id])
                for item in observations[offset : offset + limit]
                if item.metric_id is not None
            )
        except KeyError:
            raise ReadUnavailable("A frozen metric is unavailable.") from None
        return FactPage(
            view=scope.info,
            company=company,
            facts=facts,
            total=len(observations),
            offset=offset,
            limit=limit,
        )

    def company_graph(self, scope: ReadScope, identity: str) -> CompanyGraph:
        catalog = self.catalog.catalog(scope.manifest)
        company = self.company(scope, catalog, identity)
        if scope.view.state != "AVAILABLE":
            return CompanyGraph(view=scope.info, company=company, nodes=(), edges=())
        if self.graph is None:
            raise ReadUnavailable("The published graph projection is unavailable.")
        receipt = self.graph.verify(scope.manifest)
        if (
            receipt.corpus_version_id != scope.manifest.id
            or receipt.manifest_sha256 != scope.manifest.sha256
        ):
            raise ReadUnavailable("The graph projection version differs.")
        edges = tuple(
            item
            for item in scope.view.observations
            if item.kind == "relation"
            and identity in (item.subject_entity_id, item.object_entity_id)
        )
        if len(edges) > 1000:
            raise ReadUnavailable(
                "The explicit graph bound of 1000 directed relations is exceeded."
            )
        identities = {identity}
        for edge in edges:
            identities.add(edge.subject_entity_id)
            if edge.object_entity_id is not None:
                identities.add(edge.object_entity_id)
        return CompanyGraph(
            view=scope.info,
            company=company,
            nodes=tuple(label(catalog, key) for key in sorted(identities)),
            edges=edges,
        )

    def observation(self, scope: ReadScope, identity: str) -> PublishedObservation:
        item = next((item for item in scope.view.observations if item.id == identity), None)
        if item is None:
            raise ReadNotFound("Observation is absent from this published view.")
        return item

    def published_evidence(
        self, scope: ReadScope, observation_id: str, evidence_id: str
    ) -> PublishedEvidence:
        observation = self.observation(scope, observation_id)
        supports = tuple(span for span in observation.supports if span.evidence_id == evidence_id)
        context = tuple(
            witness
            for witness in observation.context_supports
            if witness.span.evidence_id == evidence_id
        )
        if not supports and not context:
            raise ReadNotFound("Evidence is not support for the selected published observation.")
        result = self.evidence.repository.get_evidence(evidence_id)
        if result is None:
            raise ReadUnavailable("Published evidence is unavailable.")
        record, provenance, source_sha, processing_sha = result
        filing = next(
            (
                item
                for item in scope.manifest.filings
                if item.filing_version_id == observation.filing_version_id
            ),
            None,
        )
        if (
            filing is None
            or record.id != evidence_id
            or record.source.filing_version_id != filing.filing_version_id
            or record.source.parse_version_id != observation.parse_version_id
            or filing.parse_version_id != observation.parse_version_id
            or record.source.filing_id != filing.filing_id
            or source_sha != filing.source_sha256
            or not all(
                _exact_span(span, record) for span in (*supports, *(w.span for w in context))
            )
        ):
            raise ReadUnavailable("Published evidence differs from its exact approved support.")
        return PublishedEvidence(
            view=scope.info,
            observation_id=observation.id,
            evidence=EvidenceData(
                record=record,
                provenance=provenance,
                source_sha256=source_sha,
                processing_configuration_sha256=processing_sha,
            ),
            supports=supports,
            context_supports=context,
        )

    def source(self, scope: ReadScope, observation_id: str) -> SourceBlob:
        observation = self.observation(scope, observation_id)
        filing = next(
            (
                item
                for item in scope.manifest.filings
                if item.filing_version_id == observation.filing_version_id
            ),
            None,
        )
        blob = self.evidence.repository.get_source(observation.filing_version_id)
        if filing is None or blob is None or blob.sha256 != filing.source_sha256:
            raise ReadUnavailable("The published original source differs.")
        return blob
