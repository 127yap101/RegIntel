"""Exact chunk and projection invariants using bounded authored encoder doubles."""

import math

import pytest
from pydantic import ValidationError
from test_publication_engine import ALPHA, BETA, authored, create

from regintel.candidates.models import SourceSpan
from regintel.fixtures.sources import fixture_id
from regintel.publication.embeddings import (
    SourceChunk,
    lexical_counts,
    project_retrieval,
    split_support,
    verify_model_file,
)
from regintel.publication.graph import graph_data


class CountingEncoder:
    def token_count(self, text: str) -> int:
        return len(text) + 2

    def embed(self, text: str) -> tuple[float, ...]:
        assert self.token_count(text) <= 512
        return (1.0,) + (0.0,) * 383


@pytest.mark.parametrize(
    "text", ["Exact 😀 e\u0301 disclosure. " * 100, "印度" * 1000, "A" * 1600, "one two three"]
)
def test_chunks_preserve_every_unicode_character_and_bound_token_budget(text: str) -> None:
    span = SourceSpan(evidence_id=fixture_id(10), start=17, end=17 + len(text), quote=text)
    encoder = CountingEncoder()
    chunks = split_support(span, encoder.token_count)
    assert "".join(chunk.quote for chunk in chunks) == text
    assert chunks[0].start == 17 and chunks[-1].end == 17 + len(text)
    assert all(encoder.token_count(chunk.quote) <= 450 for chunk in chunks)
    for left, right in zip(chunks[:-1], chunks[1:], strict=True):
        assert left.end == right.start


def test_retrieval_and_graph_are_tied_to_the_same_approved_history() -> None:
    manifest = create(authored(f"{ALPHA} supplies to {BETA}."))
    projection = project_retrieval(manifest, CountingEncoder())
    assert (
        projection.corpus_version_id == manifest.id
        and projection.manifest_sha256 == manifest.sha256
    )
    assert projection.chunks[0].support == manifest.observations[0].supports[0]
    assert projection.chunks[0].term_counts == lexical_counts(projection.chunks[0].support.quote)
    graph = graph_data(manifest)
    edge = next(edge for edge in graph.edges if edge.label == "SUPPLIES_TO")
    assert edge.source == manifest.observations[0].subject_entity_id
    assert edge.target == manifest.observations[0].object_entity_id
    assert manifest.observations[0].id in edge.payload
    assert graph == graph_data(manifest) and graph.sha256 == graph_data(manifest).sha256


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 0.0, 2.0])
def test_invalid_vectors_cannot_enter_derived_storage(value: float) -> None:
    manifest = create(authored(f"{ALPHA} supplies to {BETA}."))
    chunk = project_retrieval(manifest, CountingEncoder()).chunks[0]
    with pytest.raises(ValidationError):
        SourceChunk.model_validate(
            chunk.model_dump(mode="python") | {"embedding": (value,) + (0.0,) * 383}
        )
    assert math.isfinite(chunk.embedding[0])


@pytest.mark.parametrize(
    "name", ["../model.onnx", "configuration.py", "onnx/model.onnx", "tokenizer.json"]
)
def test_unpinned_or_modified_model_artifacts_are_rejected(name: str) -> None:
    with pytest.raises(ValueError):
        verify_model_file(name, b"authored invalid artifact")
