"""Published evidence retrieval, complete context budgets and deterministic routing."""

import hashlib
from collections import Counter
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Literal
from uuid import uuid4

from regintel.candidates.models import SourceSpan
from regintel.entities.models import canonical_bytes
from regintel.publication.embeddings import CpuBgeEncoder, SourceChunk, TextEncoder, lexical_counts
from regintel.publication.models import CorpusManifest, PublishedObservation
from regintel.reads.repository import ReadUnavailable
from regintel.reads.service import PublishedReadService, ReadScope
from regintel.retrieval.graph import GraphReader, Neighbor
from regintel.retrieval.models import (
    AnswerResult,
    Citation,
    ContextBundle,
    ExtractiveClaim,
    Filters,
    RetrievalConfiguration,
    RetrievalHit,
    RetrievalRequest,
    RetrievalResult,
    Trace,
)
from regintel.retrieval.ranking import bm25, rrf
from regintel.retrieval.repository import SearchReader, verified_projection

STOP_WORDS = frozenset(
    "a an and are as at be by can could describe did disclose disclosed does for from has have "
    "in is it its me of on or please regarding say says tell that the their this to was were "
    "what which who with would about company limited ltd statement filing filings".split()
)
NUMERIC_TERMS = frozenset(
    "amount average calculate cash crore difference earnings ebitda eps growth lakh margin "
    "million much many number percentage percent price profit ratio revenue sales assets "
    "liabilities debt dividend stake ownership total turnover value worth".split()
)


class InvalidQuery(RuntimeError):
    """An encoded query exceeds the explicit model input limit."""


def current_configuration() -> RetrievalConfiguration:
    identity = hashlib.sha256()
    for file in sorted(Path(__file__).resolve().parent.glob("*.py")):
        identity.update(file.name.encode() + b"\0" + file.read_bytes() + b"\0")
    return RetrievalConfiguration(code_sha256=identity.hexdigest())


def matches(item: PublishedObservation, filters: Filters) -> bool:
    if filters.company_id is not None and filters.company_id not in (
        item.subject_entity_id,
        item.object_entity_id,
    ):
        return False
    quantity = item.quantity
    if filters.period is not None:
        if quantity is None:
            return False
        # Raw labels do not decide period equality; only complete explicit dates do.
        period = filters.period
        actual = quantity.period
        if not complete_period(period) or not complete_period(actual):
            return False
        if (actual.kind, actual.start_date, actual.end_date, actual.instant_date) != (
            period.kind,
            period.start_date,
            period.end_date,
            period.instant_date,
        ):
            return False
    return filters.basis is None or quantity is not None and quantity.basis == filters.basis


def complete_period(period: object) -> bool:
    from regintel.contracts.models import FinancialPeriod

    return isinstance(period, FinancialPeriod) and (
        period.kind == "INSTANT"
        and period.instant_date is not None
        or period.kind == "DURATION"
        and period.start_date is not None
        and period.end_date is not None
    )


def lexical_document(chunk: SourceChunk, observation: PublishedObservation) -> dict[str, int]:
    terms = Counter(chunk.term_counts)
    # Repeated original-text headers stay with their accepted observation; no
    # page-wide or table-preview text is imported as support.
    for witness in observation.context_supports:
        if not (
            witness.span.evidence_id == chunk.support.evidence_id
            and chunk.support.start <= witness.span.start < witness.span.end <= chunk.support.end
        ):
            terms.update(lexical_counts(witness.span.quote))
    return dict(terms)


class RetrievalService:
    def __init__(
        self,
        reads: PublishedReadService,
        repository: SearchReader,
        graph: GraphReader | None,
        *,
        encoder: TextEncoder | None = None,
        model_root: Path | None = None,
    ) -> None:
        self.reads = reads
        self.repository = repository
        self.graph = graph
        self.encoder = encoder
        self.model_root = model_root
        self.encoder_manifest: str | None = None
        self.encoder_lock = Lock()

    def _encoder(self, manifest: CorpusManifest) -> TextEncoder:
        expected = manifest.configuration.embedding_manifest_sha256
        with self.encoder_lock:
            if self.encoder is None:
                if self.model_root is None:
                    raise ReadUnavailable("The pinned local query encoder is unavailable.")
                self.encoder = CpuBgeEncoder(self.model_root, expected)
                self.encoder_manifest = expected
            if self.encoder_manifest not in (None, expected):
                raise ReadUnavailable("The requested corpus uses a different embedding identity.")
        return self.encoder

    def _citations(
        self, scope: ReadScope, observation: PublishedObservation
    ) -> tuple[Citation, ...]:
        citations: list[Citation] = []
        references: list[tuple[SourceSpan, str]] = [
            (span, "DISCLOSURE") for span in observation.supports
        ]
        references.extend((w.span, w.role) for w in observation.context_supports)
        for evidence_id in sorted(
            {span.evidence_id for span in observation.supports}
            | {w.span.evidence_id for w in observation.context_supports}
        ):
            verified = self.reads.published_evidence(scope, observation.id, evidence_id)
            record = verified.evidence.record
            for span, role in references:
                if span.evidence_id == evidence_id:
                    citations.append(
                        Citation.model_validate(
                            {
                                "observation_id": observation.id,
                                "filing_version_id": record.source.filing_version_id,
                                "parse_version_id": record.source.parse_version_id,
                                "source_sha256": verified.evidence.source_sha256,
                                "page_index": record.source.page_index,
                                "span": span,
                                "role": role,
                            }
                        )
                    )
        return tuple(citations)

    def _trace(
        self,
        request: RetrievalRequest,
        scope: ReadScope,
        started: float,
        tokens: int,
        omitted: int,
        query_tokens: int,
    ) -> Trace:
        return Trace(
            run_id=str(uuid4()),
            configuration_sha256=current_configuration().sha256,
            question_sha256=hashlib.sha256(request.question.encode()).hexdigest(),
            embedding_manifest_sha256=scope.manifest.configuration.embedding_manifest_sha256,
            arm=request.arm,
            metadata_filters_applied=request.arm != "B0" or request.numeric is not None,
            filters=request.filters,
            top_k=request.top_k,
            context_budget=request.context_budget,
            context_tokens=tokens,
            budget_omitted=omitted,
            query_tokens=query_tokens,
            graph_hops=request.graph_hops,
            duration_ms=(perf_counter() - started) * 1000,
        )

    def _result(
        self,
        request: RetrievalRequest,
        scope: ReadScope,
        started: float,
        hits: tuple[RetrievalHit, ...] = (),
        omitted: int = 0,
        query_tokens: int = 0,
    ) -> RetrievalResult:
        return RetrievalResult(
            view=scope.info,
            state=scope.info.state,
            hits=hits,
            trace=self._trace(
                request, scope, started, sum(h.context_tokens for h in hits), omitted, query_tokens
            ),
        )

    def _graph_channel(
        self,
        request: RetrievalRequest,
        scope: ReadScope,
        allowed: dict[str, PublishedObservation],
        chunks: dict[str, SourceChunk],
        base: list[str],
    ) -> tuple[list[str], dict[str, Literal[1, 2]]]:
        if self.graph is None:
            raise ReadUnavailable("The requested graph retrieval arm is unavailable.")
        seeds: set[str] = set()
        for key in base[: request.top_k]:
            item = allowed[chunks[key].observation_id]
            seeds.add(item.subject_entity_id)
            if item.object_entity_id is not None:
                seeds.add(item.object_entity_id)
        relation_ids = tuple(
            sorted(key for key, item in allowed.items() if item.kind == "relation")
        )
        neighbors = self.graph.expand(
            scope.manifest, tuple(sorted(seeds)), relation_ids, request.graph_hops
        )
        if len(neighbors) > 1000 or len({n.observation_id for n in neighbors}) != len(neighbors):
            raise ReadUnavailable("The graph expansion exceeds its distinct relation bound.")
        reached: dict[str, Literal[1, 2]] = {}
        frontier = set(seeds)
        for hop in (1, 2):
            layer = [neighbor for neighbor in neighbors if neighbor.hop == hop]
            next_frontier: set[str] = set()
            for neighbor in layer:
                self._validate_neighbor(neighbor, allowed, frontier, request.graph_hops)
                for identity in (neighbor.subject, neighbor.object):
                    reached.setdefault(identity, neighbor.hop)
                    next_frontier.add(identity)
            frontier = next_frontier
        ranks: dict[str, Literal[1, 2]] = {}
        for key, chunk in chunks.items():
            item = allowed[chunk.observation_id]
            # Reapply every filter; never promote an unfiltered neighbor fact.
            if not matches(item, request.filters):
                continue
            distance = [
                reached[key]
                for key in (item.subject_entity_id, item.object_entity_id)
                if key in reached
            ]
            if distance:
                ranks[key] = min(distance)
        channel = sorted(ranks, key=lambda key: (ranks[key], key))[:100]
        return channel, ranks

    @staticmethod
    def _validate_neighbor(
        neighbor: Neighbor,
        allowed: dict[str, PublishedObservation],
        frontier: set[str],
        hops: int,
    ) -> None:
        observation = allowed.get(neighbor.observation_id)
        if (
            observation is None
            or observation.kind != "relation"
            or neighbor.hop > hops
            or neighbor.hop not in (1, 2)
            or (neighbor.subject, neighbor.object)
            != (observation.subject_entity_id, observation.object_entity_id)
            or not frontier.intersection((neighbor.subject, neighbor.object))
        ):
            raise ReadUnavailable("The graph path differs from the filtered approved relations.")

    def search(self, request: RetrievalRequest) -> RetrievalResult:
        started = perf_counter()
        scope = self.reads.scope(request.corpus_version_id, request.as_of_date, request.historical)
        if scope.info.state != "AVAILABLE":
            return self._result(request, scope, started)
        encoder = self._encoder(scope.manifest)
        query = current_configuration().query_prefix + request.question
        query_tokens = encoder.token_count(query)
        if query_tokens > 512:
            raise InvalidQuery("The encoded question exceeds 512 tokens; no truncation is allowed.")
        allowed = {
            item.id: item
            for item in scope.view.observations
            if request.arm == "B0" or matches(item, request.filters)
        }
        snapshot = self.repository.search(
            scope.manifest, tuple(sorted(allowed)), encoder.embed(query)
        )
        verified_projection(scope.manifest, snapshot.projection)
        chunks = {
            chunk.id: chunk
            for chunk in snapshot.projection.chunks
            if chunk.observation_id in allowed
        }
        if len(snapshot.dense) != len(chunks) or set(snapshot.dense) != set(chunks):
            raise ReadUnavailable("The dense search contains missing or out-of-scope chunks.")
        dense = list(snapshot.dense[:100])
        lexical = (
            bm25(
                lexical_counts(request.question),
                {
                    key: lexical_document(chunk, allowed[chunk.observation_id])
                    for key, chunk in chunks.items()
                },
            )[:100]
            if request.arm in ("B2", "B3")
            else []
        )
        base = rrf((dense, lexical)) if lexical else dense
        graph_ranks: dict[str, Literal[1, 2]] = {}
        if request.arm == "B3":
            graph, graph_ranks = self._graph_channel(request, scope, allowed, chunks, base)
            ranked = rrf((dense, lexical, graph))
        else:
            ranked = base
        hits: list[RetrievalHit] = []
        seen: set[str] = set()
        used = omitted = 0
        for key in ranked:
            chunk = chunks[key]
            if chunk.observation_id in seen:
                continue
            seen.add(chunk.observation_id)
            item = allowed[chunk.observation_id]
            citations = self._citations(scope, item)
            context = canonical_bytes(ContextBundle(observation=item, citations=citations)).decode()
            count = encoder.token_count(context)
            if used + count > request.context_budget:
                omitted += 1
                continue
            hits.append(
                RetrievalHit(
                    chunk_id=key,
                    observation=item,
                    dense_rank=dense.index(key) + 1 if key in dense else None,
                    lexical_rank=lexical.index(key) + 1 if key in lexical else None,
                    graph_hop=graph_ranks.get(key),
                    citations=citations,
                    context_tokens=count,
                )
            )
            used += count
            if len(hits) == request.top_k:
                break
        return self._result(request, scope, started, tuple(hits), omitted, query_tokens)

    def answer(self, request: RetrievalRequest) -> AnswerResult:
        if request.numeric is not None:
            return self._numeric(request)
        terms = lexical_counts(request.question)
        if (
            any(term in NUMERIC_TERMS or term.isdecimal() for term in terms)
            or "%" in request.question
        ):
            started = perf_counter()
            scope = self.reads.scope(
                request.corpus_version_id, request.as_of_date, request.historical
            )
            result = self._result(request, scope, started)
            return AnswerResult(
                retrieval=result,
                state="NUMERIC_CONTEXT_REQUIRED"
                if result.state == "AVAILABLE"
                else "TEMPORAL_SUPPORT_UNAVAILABLE",
                claims=(),
                explanation=(
                    "Numeric questions require an explicit metric, company, complete period, "
                    "basis, unit and currency. Cross-fact calculations use the analysis module."
                ),
            )
        result = self.search(request)
        if result.state != "AVAILABLE":
            return AnswerResult(
                retrieval=result,
                state="TEMPORAL_SUPPORT_UNAVAILABLE",
                claims=(),
                explanation="The requested date lacks supported source/effect dates.",
            )
        catalog = self.reads.catalog.catalog(
            self.reads.scope(result.view.corpus_version_id).manifest
        )
        company_terms = {
            term for item in catalog.entities for term in lexical_counts(item.legal_name)
        }
        topics = set(terms) - STOP_WORDS - company_terms
        claims: list[ExtractiveClaim] = []
        for hit in result.hits:
            observation = hit.observation
            source_terms = set(lexical_counts(observation.raw_text))
            # This is a conservative literal-topic gate, not a semantic model or
            # calibrated support score. Excerpts retain all source qualifiers.
            if (
                not topics
                or len(topics & source_terms) * 2 < len(topics)
                or not any(observation.raw_text in span.quote for span in observation.supports)
                or observation.kind == "numeric_fact"
            ):
                continue
            claims.append(
                ExtractiveClaim(
                    text=observation.raw_text,
                    observation_id=observation.id,
                    citations=hit.citations,
                    quantity=observation.quantity,
                )
            )
        return AnswerResult(
            retrieval=result,
            state="EXTRACTIVE_EVIDENCE"
            if claims
            else "CONTEXT_BUDGET_UNAVAILABLE"
            if result.trace.budget_omitted and not result.hits
            else "INSUFFICIENT_SUPPORT",
            claims=tuple(claims),
            explanation="Verbatim published source excerpts; conflicts remain separate."
            if claims
            else "The published view lacks sufficient exact support within this context budget.",
        )

    def _numeric(self, request: RetrievalRequest) -> AnswerResult:
        started = perf_counter()
        scope = self.reads.scope(request.corpus_version_id, request.as_of_date, request.historical)
        result = self._result(request, scope, started)

        def unavailable(
            state: Literal[
                "TEMPORAL_SUPPORT_UNAVAILABLE",
                "NUMERIC_CONTEXT_REQUIRED",
                "NUMERIC_UNAVAILABLE",
                "NUMERIC_INCOMPATIBLE",
                "NUMERIC_CONFLICT",
                "CONTEXT_BUDGET_UNAVAILABLE",
            ],
            reason: str,
        ) -> AnswerResult:
            return AnswerResult(retrieval=result, state=state, claims=(), explanation=reason)

        if scope.info.state != "AVAILABLE":
            return unavailable(
                "TEMPORAL_SUPPORT_UNAVAILABLE",
                "The requested date lacks supported source/effect dates.",
            )
        numeric = request.numeric
        assert numeric is not None
        if (
            request.filters.company_id is None
            or not complete_period(request.filters.period)
            or request.filters.basis is None
        ):
            return unavailable(
                "NUMERIC_CONTEXT_REQUIRED",
                "Exact lookup requires company, complete period and reporting basis.",
            )
        candidates = [
            item
            for item in scope.view.observations
            if item.kind == "numeric_fact"
            and item.metric_id == numeric.metric_id
            and item.subject_entity_id == request.filters.company_id
        ]
        if not candidates:
            return unavailable(
                "NUMERIC_UNAVAILABLE",
                "No accepted metric value exists in the selected published view.",
            )
        compatible = [
            item
            for item in candidates
            if matches(item, request.filters)
            and item.quantity is not None
            and item.quantity.normalized_value is not None
            and (
                item.quantity.currency,
                item.quantity.normalized_unit,
                item.quantity.denominator,
                item.quantity.stake_kind,
                item.quantity.ownership_date,
            )
            == (
                numeric.currency,
                numeric.unit,
                numeric.denominator,
                numeric.stake_kind,
                numeric.ownership_date,
            )
        ]
        if not compatible:
            return unavailable(
                "NUMERIC_INCOMPATIBLE",
                "Accepted inputs differ in period, basis, unit, currency or ownership context.",
            )
        if len(compatible) != 1:
            return unavailable(
                "NUMERIC_CONFLICT",
                "Multiple accepted values require explicit resolution; none is selected by date.",
            )
        item = compatible[0]
        citations = self._citations(scope, item)
        encoder = self._encoder(scope.manifest)
        count = encoder.token_count(
            canonical_bytes(ContextBundle(observation=item, citations=citations)).decode()
        )
        if count > request.context_budget:
            return unavailable(
                "CONTEXT_BUDGET_UNAVAILABLE",
                "The complete exact input and its support exceed the selected context budget.",
            )
        result = result.model_copy(
            update={"trace": self._trace(request, scope, started, count, 0, 0)}
        )
        return AnswerResult(
            retrieval=result,
            state="NUMERIC_VALUE",
            claims=(
                ExtractiveClaim(
                    text=item.raw_text,
                    observation_id=item.id,
                    citations=citations,
                    quantity=item.quantity,
                ),
            ),
            explanation="Exact accepted Decimal value with complete context; no derived formula.",
        )
