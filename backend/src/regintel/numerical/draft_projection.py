"""Pure unpublished graph/retrieval preparation over exact, complete word evidence."""

import hashlib
import json
import math
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from regintel.candidates.models import SourceSpan, _exact_span
from regintel.candidates.records import stable_id
from regintel.contracts.models import ContractModel, EvidenceSource
from regintel.contracts.primitives import CanonicalId, RawText, SafeInteger, Sha256Hash
from regintel.entities.models import canonical_bytes
from regintel.numerical.draft_models import MAX_DRAFT_BYTES, NumericalPublicationDraft
from regintel.numerical.evidence_binding_models import BoundNumericalPhrase, PhraseRole
from regintel.publication.embeddings import (
    SourceChunk,
    TextEncoder,
    lexical_counts,
    project_retrieval,
    split_support,
)
from regintel.publication.graph import GraphData, GraphEdge, GraphNode


class NumericalSourceChunk(ContractModel):
    id: CanonicalId
    observation_id: CanonicalId
    binding_id: CanonicalId
    role: PhraseRole
    phrase_ordinal: Annotated[SafeInteger, Field(le=3)]
    chunk_ordinal: SafeInteger
    source: EvidenceSource
    supports: Annotated[tuple[SourceSpan, ...], Field(strict=False, min_length=1, max_length=256)]
    cell_ids: Annotated[tuple[CanonicalId, ...], Field(strict=False, max_length=1)]
    text: Annotated[RawText, Field(min_length=1, max_length=64000)]
    token_count: Annotated[SafeInteger, Field(ge=3, le=450)]
    embedding: Annotated[tuple[float, ...], Field(strict=False, min_length=384, max_length=384)]
    term_counts: dict[str, Annotated[SafeInteger, Field(ge=1)]]

    @model_validator(mode="after")
    def reconstructed_text_and_vector(self) -> Self:
        if (
            self.text != " ".join(span.quote for span in self.supports)
            or not self.text.strip()
            or self.term_counts != lexical_counts(self.text)
            or not all(math.isfinite(value) for value in self.embedding)
            or abs(math.sqrt(sum(value * value for value in self.embedding)) - 1.0) > 1e-5
        ):
            raise ValueError(
                "Chunk text is reconstructed from exact supports with normalized vectors."
            )
        return self


def chunk_identity(draft_id: str, chunk: NumericalSourceChunk) -> str:
    # Vector values and lexical/token outputs are still checked separately. The
    # source/role/ordinal identity does not acquire an encoder-dependent value.
    payload = chunk.model_dump(
        mode="json", exclude={"id", "embedding", "term_counts", "token_count"}
    )
    return stable_id(
        "numerical-chunk:"
        + draft_id
        + ":"
        + hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def _legacy_coverage(draft: NumericalPublicationDraft, chunks: tuple[SourceChunk, ...]) -> None:
    if draft.parent is None:
        if chunks:
            raise ValueError("A draft without a legacy parent cannot inherit chunks.")
        return
    for observation in draft.parent.observations:
        sources = list(observation.supports)
        for witness in observation.context_supports:
            if not any(
                s.evidence_id == witness.span.evidence_id
                and s.start <= witness.span.start < witness.span.end <= s.end
                for s in sources
            ):
                sources.append(witness.span)
        selected = tuple(c.support for c in chunks if c.observation_id == observation.id)
        for span in selected:
            if not any(
                s.evidence_id == span.evidence_id
                and s.start <= span.start < span.end <= s.end
                and span.quote == s.quote[span.start - s.start : span.end - s.start]
                for s in sources
            ):
                raise ValueError("Legacy chunk quotation must match retained exact source support.")
        for source in sources:
            intervals = sorted(
                (max(source.start, s.start), min(source.end, s.end))
                for s in selected
                if s.evidence_id == source.evidence_id
                and s.start < source.end
                and s.end > source.start
            )
            cursor = source.start
            for start, end in intervals:
                if (
                    start > cursor
                    and source.quote[cursor - source.start : start - source.start].strip()
                ):
                    raise ValueError("Inherited legacy evidence cannot be silently dropped.")
                cursor = max(cursor, end)
            if source.quote[cursor - source.start :].strip():
                raise ValueError("Inherited legacy evidence cannot be truncated.")


def _coverage(phrase: BoundNumericalPhrase, chunks: tuple[NumericalSourceChunk, ...]) -> None:
    if tuple(chunk.chunk_ordinal for chunk in chunks) != tuple(range(len(chunks))) or not chunks:
        raise ValueError("Every phrase requires contiguous distinct chunk ordinals.")
    word_index, offset = 0, 0
    for chunk in chunks:
        for span in chunk.supports:
            if word_index >= len(phrase.words):
                raise ValueError("Chunk support duplicates or exceeds the retained phrase.")
            evidence = phrase.words[word_index].evidence
            if (
                span.evidence_id != evidence.id
                or span.start != offset
                or not _exact_span(span, evidence)
            ):
                raise ValueError("Chunks must preserve complete ordered exact word coverage.")
            offset = span.end
            if offset == evidence.span.end:
                word_index, offset = word_index + 1, 0
    if word_index != len(phrase.words) or offset:
        raise ValueError("Chunk support cannot truncate a phrase or source word.")


class NumericalRetrievalPreparation(ContractModel):
    schema_version: Literal["numerical-retrieval-preparation-1"] = (
        "numerical-retrieval-preparation-1"
    )
    draft: NumericalPublicationDraft
    embedding_manifest_sha256: Sha256Hash
    legacy_chunks: Annotated[tuple[SourceChunk, ...], Field(strict=False, max_length=100000)]
    numerical_chunks: Annotated[
        tuple[NumericalSourceChunk, ...], Field(strict=False, max_length=100000)
    ]
    publishes_fact: Literal[False] = False

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @model_validator(mode="after")
    def complete_projection(self) -> Self:
        expected_legacy = (
            {item.id for item in self.draft.parent.observations} if self.draft.parent else set()
        )
        if (self.draft.parent is None and self.legacy_chunks) or (
            self.draft.parent is not None
            and self.draft.parent.configuration.embedding_manifest_sha256
            != self.embedding_manifest_sha256
        ):
            raise ValueError("Inherited chunks require the same pinned embedding manifest.")
        for legacy_chunk in self.legacy_chunks:
            if legacy_chunk.observation_id not in expected_legacy or legacy_chunk.id != stable_id(
                "chunk:"
                + self.draft.id
                + ":"
                + legacy_chunk.observation_id
                + ":"
                + legacy_chunk.support.evidence_id
                + f":{legacy_chunk.support.start}:{legacy_chunk.support.end}"
            ):
                raise ValueError(
                    "Inherited chunk must belong to this draft and original observation."
                )
        _legacy_coverage(self.draft, self.legacy_chunks)
        entries = {entry.id: entry for entry in self.draft.entries}
        groups: dict[tuple[str, str, int], list[NumericalSourceChunk]] = {}
        for chunk in self.numerical_chunks:
            if chunk.observation_id not in entries or chunk.id != chunk_identity(
                self.draft.id, chunk
            ):
                raise ValueError("Native chunk must belong to the selected draft observation.")
            entry = entries[chunk.observation_id]
            proposed = entry.acceptance.candidate.preparation.proposed_input
            assert proposed is not None
            proof = proposed.proof
            phrase = next(
                (
                    p
                    for p in proof.phrases
                    if (p.role, p.ordinal) == (chunk.role, chunk.phrase_ordinal)
                ),
                None,
            )
            cells = tuple(
                sorted(cell.artifact_cell_id for cell in proof.cells if cell.role == chunk.role)
            )
            if (
                phrase is None
                or chunk.binding_id != proof.id
                or chunk.source != phrase.words[0].evidence.source
                or chunk.cell_ids != cells
            ):
                raise ValueError("Chunk role/page/cell membership differs from complete proof.")
            groups.setdefault((entry.id, chunk.role, chunk.phrase_ordinal), []).append(chunk)
        for entry in self.draft.entries:
            proposed = entry.acceptance.candidate.preparation.proposed_input
            assert proposed is not None
            for phrase in proposed.proof.phrases:
                chunks = tuple(
                    sorted(
                        groups.get((entry.id, phrase.role, phrase.ordinal), ()),
                        key=lambda c: c.chunk_ordinal,
                    )
                )
                _coverage(phrase, chunks)
        identities = tuple(item.id for item in self.legacy_chunks) + tuple(
            item.id for item in self.numerical_chunks
        )
        if len(set(identities)) != len(identities) or len(canonical_bytes(self)) > MAX_DRAFT_BYTES:
            raise ValueError("Projection exceeds its distinct chunk or explicit byte budget.")
        return self


def _phrase_pieces(
    phrase: BoundNumericalPhrase, encoder: TextEncoder
) -> tuple[tuple[SourceSpan, ...], ...]:
    atoms: list[SourceSpan] = []
    for word in phrase.words:
        evidence = word.evidence
        span = SourceSpan(
            evidence_id=evidence.id, start=0, end=evidence.span.end, quote=evidence.span.quote
        )
        atoms.extend(split_support(span, encoder.token_count))
    result: list[tuple[SourceSpan, ...]] = []
    pending: list[SourceSpan] = []
    for span in atoms:
        text = " ".join(item.quote for item in (*pending, span))
        if encoder.token_count(text) > 450 and pending:
            result.append(tuple(pending))
            pending = []
        if not 3 <= encoder.token_count(span.quote) <= 450:
            raise ValueError("Exact source cannot fit the configured tokenizer without truncation.")
        pending.append(span)
    if pending:
        result.append(tuple(pending))
    return tuple(result)


def prepare_numerical_retrieval(
    draft: NumericalPublicationDraft, encoder: TextEncoder, embedding_manifest_sha256: str
) -> NumericalRetrievalPreparation:
    draft = NumericalPublicationDraft.model_validate(draft.model_dump(mode="python"))
    legacy: list[SourceChunk] = []
    if draft.parent is not None:
        if draft.parent.configuration.embedding_manifest_sha256 != embedding_manifest_sha256:
            raise ValueError("The inherited corpus requires its exact pinned embedding manifest.")
        for legacy_chunk in project_retrieval(draft.parent, encoder).chunks:
            legacy.append(
                SourceChunk.model_validate(
                    legacy_chunk.model_dump(mode="python")
                    | {
                        "id": stable_id(
                            "chunk:"
                            + draft.id
                            + ":"
                            + legacy_chunk.observation_id
                            + ":"
                            + legacy_chunk.support.evidence_id
                            + f":{legacy_chunk.support.start}:{legacy_chunk.support.end}"
                        )
                    }
                )
            )
    chunks: list[NumericalSourceChunk] = []
    for entry in draft.entries:
        proposed = entry.acceptance.candidate.preparation.proposed_input
        assert proposed is not None
        proof = proposed.proof
        for phrase in proof.phrases:
            for ordinal, supports in enumerate(_phrase_pieces(phrase, encoder)):
                text = " ".join(span.quote for span in supports)
                chunk = NumericalSourceChunk(
                    id=entry.id,
                    observation_id=entry.id,
                    binding_id=proof.id,
                    role=phrase.role,
                    phrase_ordinal=phrase.ordinal,
                    chunk_ordinal=ordinal,
                    source=phrase.words[0].evidence.source,
                    supports=supports,
                    cell_ids=tuple(
                        sorted(
                            cell.artifact_cell_id
                            for cell in proof.cells
                            if cell.role == phrase.role
                        )
                    ),
                    text=text,
                    token_count=encoder.token_count(text),
                    embedding=encoder.embed(text),
                    term_counts=lexical_counts(text),
                )
                chunks.append(chunk.model_copy(update={"id": chunk_identity(draft.id, chunk)}))
    return NumericalRetrievalPreparation(
        draft=draft,
        embedding_manifest_sha256=embedding_manifest_sha256,
        legacy_chunks=tuple(sorted(legacy, key=lambda c: c.id)),
        numerical_chunks=tuple(sorted(chunks, key=lambda c: c.id)),
    )


class NumericalGraphPreparation(ContractModel):
    draft_id: CanonicalId
    draft_sha256: Sha256Hash
    state: Literal["UNPUBLISHED_DRAFT"] = "UNPUBLISHED_DRAFT"
    data: GraphData
    publishes_fact: Literal[False] = False

    @model_validator(mode="after")
    def graph_membership(self) -> Self:
        nodes = {node.id: node for node in self.data.nodes}
        root = nodes.get(self.draft_id)
        payload = json.loads(root.payload) if root is not None else None
        if (
            root is None
            or root.label != "Corpus"
            or not isinstance(payload, dict)
            or set(payload) != {"state", "draft_sha256", "parent_corpus_version_id"}
            or payload["state"] != self.state
            or payload["draft_sha256"] != self.draft_sha256
            or len(nodes) != len(self.data.nodes)
            or len({edge.id for edge in self.data.edges}) != len(self.data.edges)
            or any(edge.source not in nodes or edge.target not in nodes for edge in self.data.edges)
        ):
            raise ValueError(
                "Prepared graph must retain its exact draft and complete edge membership."
            )
        if len(canonical_bytes(self)) > MAX_DRAFT_BYTES:
            raise ValueError("The complete graph exceeds its explicit byte budget.")
        return self


def _payload(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def prepare_numerical_graph(draft: NumericalPublicationDraft) -> NumericalGraphPreparation:
    draft = NumericalPublicationDraft.model_validate(draft.model_dump(mode="python"))
    nodes: dict[str, GraphNode] = {}
    edges: dict[str, GraphEdge] = {}

    def node(
        identity: str,
        label: Literal["Corpus", "Entity", "Observation", "Evidence", "Decision"],
        payload: str,
    ) -> None:
        value = GraphNode(id=identity, label=label, payload=payload)
        if identity in nodes:
            previous = nodes[identity]
            if previous.label != label or json.loads(previous.payload) != json.loads(payload):
                raise ValueError("Graph node identities cannot collide across typed records.")
            return
        nodes[identity] = value

    def edge(
        source: str,
        target: str,
        label: Literal["ASSERTS", "SUPPORTED_BY", "IN_CORPUS"],
        payload: str,
    ) -> None:
        identity = stable_id(
            "numerical-draft-edge:"
            + draft.id
            + ":"
            + source
            + ":"
            + target
            + ":"
            + label
            + ":"
            + payload
        )
        edges[identity] = GraphEdge(
            id=identity, source=source, target=target, label=label, payload=payload
        )

    node(
        draft.id,
        "Corpus",
        _payload(
            {
                "state": draft.state,
                "draft_sha256": draft.sha256,
                "parent_corpus_version_id": draft.request.parent_corpus_version_id,
            }
        ),
    )
    if draft.parent is not None:
        from regintel.publication.graph import graph_data

        previous = graph_data(draft.parent)
        # The original legacy graph is retained as its own parent-version snapshot;
        # its nodes/edges keep the original corpus payload and active/effect history.
        for previous_node in previous.nodes:
            node(previous_node.id, previous_node.label, previous_node.payload)
        for previous_edge in previous.edges:
            edges[previous_edge.id] = previous_edge
        edge(
            draft.parent.id,
            draft.id,
            "IN_CORPUS",
            _payload({"inherited_parent": True, "published": False}),
        )
    for entry in draft.entries:
        proposed = entry.acceptance.candidate.preparation.proposed_input
        assert proposed is not None
        node(entry.id, "Observation", canonical_bytes(entry).decode())
        node(
            proposed.subject_entity_id,
            "Entity",
            _payload({"entity_id": proposed.subject_entity_id}),
        )
        node(
            entry.acceptance.record.id,
            "Decision",
            canonical_bytes(entry.acceptance.record).decode(),
        )
        edge(proposed.subject_entity_id, entry.id, "ASSERTS", _payload({"draft_id": draft.id}))
        edge(entry.id, draft.id, "IN_CORPUS", _payload({"published": False}))
        edge(entry.acceptance.record.id, draft.id, "IN_CORPUS", _payload({"published": False}))
        for phrase in proposed.proof.phrases:
            for word in phrase.words:
                # One Evidence node identity can be shared by phrases/observations;
                # source geometry remains in the complete retained entry proof.
                node(word.evidence.id, "Evidence", _payload({"evidence_id": word.evidence.id}))
                edge(
                    entry.id,
                    word.evidence.id,
                    "SUPPORTED_BY",
                    _payload(
                        {
                            "binding_id": proposed.proof.id,
                            "role": phrase.role,
                            "ordinal": phrase.ordinal,
                            "word": word.model_dump(mode="json"),
                        }
                    ),
                )
    return NumericalGraphPreparation(
        draft_id=draft.id,
        draft_sha256=draft.sha256,
        data=GraphData(
            nodes=tuple(nodes[k] for k in sorted(nodes)),
            edges=tuple(edges[k] for k in sorted(edges)),
        ),
    )
