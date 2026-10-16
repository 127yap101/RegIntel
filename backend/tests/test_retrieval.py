"""Authored engineering retrieval cases; no real-filing effectiveness claim."""

from dataclasses import replace
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from test_entity_api import Users
from test_publication_engine import administrator
from test_published_reads import fixture_service

from regintel.auth.config import AuthSettings
from regintel.auth.service import AuthService
from regintel.auth.tokens import issue_token
from regintel.main import create_app
from regintel.publication.embeddings import project_retrieval
from regintel.publication.graph import GraphUnavailable
from regintel.publication.models import CorpusManifest
from regintel.reads.repository import ReadUnavailable
from regintel.retrieval.graph import Neighbor
from regintel.retrieval.models import Filters, RetrievalRequest
from regintel.retrieval.ranking import bm25, rrf
from regintel.retrieval.repository import SearchSnapshot, verified_vector
from regintel.retrieval.service import InvalidQuery, RetrievalService


class Encoder:
    """Deliberately authored token counts/vectors; actual BGE is a separate proof."""

    def token_count(self, text: str) -> int:
        return max(len(text.split()), len(text) // 4) + 2

    def embed(self, text: str) -> tuple[float, ...]:
        return (1.0,) + (0.0,) * 383


class Search:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.mode = "normal"

    def search(
        self, manifest: CorpusManifest, allowed: tuple[str, ...], vector: tuple[float, ...]
    ) -> SearchSnapshot:
        verified_vector(vector)
        self.calls.append(allowed)
        projection = project_retrieval(manifest, Encoder())
        ids = tuple(chunk.id for chunk in projection.chunks if chunk.observation_id in allowed)
        if self.mode == "missing":
            ids = ()
        elif self.mode == "cross":
            ids += (str(uuid4()),)
        elif self.mode == "version":
            projection = projection.model_copy(update={"corpus_version_id": str(uuid4())})
        elif self.mode == "quote":
            chunk = projection.chunks[0]
            projection = projection.model_copy(
                update={
                    "chunks": (
                        chunk.model_copy(
                            update={
                                "support": chunk.support.model_copy(
                                    update={"quote": "Forged support"}
                                )
                            }
                        ),
                    )
                }
            )
        return SearchSnapshot(projection, ids)


class Graph:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], tuple[str, ...], int]] = []
        self.mode = "normal"

    def expand(
        self,
        manifest: CorpusManifest,
        seeds: tuple[str, ...],
        allowed: tuple[str, ...],
        hops: Literal[1, 2],
    ) -> tuple[Neighbor, ...]:
        self.calls.append((seeds, allowed, hops))
        if self.mode == "outage":
            raise GraphUnavailable("Private graph failure diagnostic.")
        result = tuple(
            Neighbor(item.id, item.subject_entity_id, item.object_entity_id, 1)
            for item in manifest.observations
            if item.id in allowed
            and item.object_entity_id is not None
            and set(seeds).intersection((item.subject_entity_id, item.object_entity_id))
        )
        if self.mode == "reversed":
            return tuple(
                Neighbor(item.observation_id, item.object, item.subject, item.hop)
                for item in result
            )
        if self.mode == "unpublished":
            return (Neighbor(str(uuid4()), seeds[0], str(uuid4()), 1),)
        if self.mode == "duplicate":
            return result + result
        return result


def service(tmp_path: Path) -> tuple[RetrievalService, Search, Graph]:
    reads, _, _, _ = fixture_service(tmp_path)
    search, graph = Search(), Graph()
    return RetrievalService(reads, search, graph, encoder=Encoder()), search, graph


def question(**updates: object) -> RetrievalRequest:
    return RetrievalRequest.model_validate(
        {"question": "Who supplies to the company?", "arm": "B2"} | updates
    )


@pytest.mark.parametrize("arm", ["B0", "B1", "B2", "B3"])
def test_four_arms_share_exact_corpus_source_and_budget(tmp_path: Path, arm: str) -> None:
    engine, search, graph = service(tmp_path)
    result = engine.answer(question(arm=arm))
    assert result.state == "EXTRACTIVE_EVIDENCE" and len(result.claims) == 1
    claim = result.claims[0]
    assert "supplies to" in claim.text
    assert claim.citations[0].span.quote == claim.text
    assert claim.citations[0].observation_id == claim.observation_id
    assert result.retrieval.view.corpus_version_id == engine.reads.corpus.manifest.id
    assert result.retrieval.trace.context_tokens <= result.retrieval.trace.context_budget
    assert result.retrieval.trace.metadata_filters_applied == (arm != "B0")
    assert bool(graph.calls) == (arm == "B3")
    assert len(search.calls) == 1
    assert result.retrieval.trace.provider_calls == 0
    assert result.retrieval.trace.generation_model is None


@pytest.mark.parametrize("arm", ["B0", "B1", "B2", "B3"])
def test_metadata_filters_never_relax_outside_explicit_b0(tmp_path: Path, arm: str) -> None:
    engine, search, _ = service(tmp_path)
    result = engine.search(question(arm=arm, filters=Filters(company_id=str(uuid4()))))
    assert bool(result.hits) == (arm == "B0")
    assert bool(search.calls[0]) == (arm == "B0")


@pytest.mark.parametrize("change", ["missing", "cross", "version", "quote"])
def test_projection_and_dense_membership_fail_closed(tmp_path: Path, change: str) -> None:
    engine, search, _ = service(tmp_path)
    search.mode = change
    with pytest.raises(ReadUnavailable):
        engine.search(question())


@pytest.mark.parametrize("change", ["outage", "reversed", "unpublished", "duplicate"])
def test_graph_outage_direction_scope_and_duplicates_fail_closed(
    tmp_path: Path, change: str
) -> None:
    engine, _, graph = service(tmp_path)
    graph.mode = change
    with pytest.raises((GraphUnavailable, ReadUnavailable)):
        engine.search(question(arm="B3"))


def test_inactive_observations_cannot_enter_any_arm_and_history_is_explicit(tmp_path: Path) -> None:
    engine, search, graph = service(tmp_path)
    memory = engine.reads.corpus
    memory.manifest = memory.manifest.model_copy(update={"active_observation_ids": ()})
    for arm in ("B0", "B1", "B2", "B3"):
        assert engine.search(question(arm=arm)).hits == ()
        assert search.calls[-1] == ()
        assert engine.search(question(arm=arm, historical=True)).hits
    assert graph.calls[-2][1] == () and graph.calls[-1][1]


def test_unknown_asof_has_no_search_graph_or_inferred_result(tmp_path: Path) -> None:
    engine, search, graph = service(tmp_path)
    memory = engine.reads.corpus
    memory.manifest = memory.manifest.model_copy(
        update={
            "filings": tuple(
                item.model_copy(update={"published_on": None}) for item in memory.manifest.filings
            ),
            "observations": tuple(
                item.model_copy(update={"source_published_on": None})
                for item in memory.manifest.observations
            ),
        }
    )
    result = engine.answer(question(as_of_date="2026-01-01"))
    assert result.state == "TEMPORAL_SUPPORT_UNAVAILABLE" and result.claims == ()
    assert search.calls == [] and graph.calls == []


@pytest.mark.parametrize(
    "query",
    [
        "What is the revenue?",
        "Calculate the profit margin",
        "How much cash?",
        "What happened in 2025?",
        "percentage",
    ],
)
def test_free_numeric_intent_never_becomes_prose_or_model_arithmetic(
    tmp_path: Path, query: str
) -> None:
    engine, search, graph = service(tmp_path)
    result = engine.answer(question(question=query))
    assert result.state == "NUMERIC_CONTEXT_REQUIRED" and result.claims == ()
    assert search.calls == [] and graph.calls == []


@pytest.mark.parametrize(
    "query",
    [
        "What is the lunar fuel supply forecast?",
        "the company",
        "Buy this stock and guarantee a profit",
    ],
)
def test_no_literal_topic_support_abstains(tmp_path: Path, query: str) -> None:
    engine, _, _ = service(tmp_path)
    result = engine.answer(question(question=query))
    assert (
        result.state in ("INSUFFICIENT_SUPPORT", "NUMERIC_CONTEXT_REQUIRED") and result.claims == ()
    )


def test_exact_complete_bundle_budget_is_inclusive_and_never_clips(tmp_path: Path) -> None:
    engine, _, _ = service(tmp_path)
    first = engine.search(question())
    tokens = first.trace.context_tokens
    assert 128 <= tokens <= 4096
    exact = engine.search(question(context_budget=tokens))
    assert exact.hits == first.hits
    omitted = engine.answer(question(context_budget=tokens - 1))
    assert omitted.state == "CONTEXT_BUDGET_UNAVAILABLE"
    assert omitted.retrieval.hits == () and omitted.retrieval.trace.budget_omitted == 1
    assert omitted.retrieval.trace.context_tokens == 0


def test_modified_original_evidence_prevents_citations(tmp_path: Path) -> None:
    engine, _, _ = service(tmp_path)
    memory = engine.reads.evidence.repository
    record, provenance, source_sha, processing_sha = memory.result
    memory.result = (
        record.model_copy(update={"span": record.span.model_copy(update={"quote": "Tampered"})}),
        provenance,
        source_sha,
        processing_sha,
    )
    with pytest.raises(ReadUnavailable):
        engine.search(question())


def test_encoded_query_bound_rejects_without_truncation(tmp_path: Path) -> None:
    engine, search, _ = service(tmp_path)

    class Oversize(Encoder):
        def token_count(self, text: str) -> int:
            return 513

    engine.encoder = Oversize()
    with pytest.raises(InvalidQuery):
        engine.search(question())
    assert search.calls == []


@pytest.mark.parametrize(
    "body",
    [
        {"question": " "},
        {"question": "x" * 1001},
        {"question": "a", "top_k": True},
        {"question": "a", "arm": "B4"},
        {"question": "a", "graph_hops": 3},
        {"question": "a", "context_budget": 127},
        {"question": "a", "unexpected": "ignore"},
    ],
)
def test_request_bounds_are_not_coerced(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RetrievalRequest.model_validate(body)


def test_bm25_idf_length_and_rrf_channels_have_stable_ties() -> None:
    docs = {"a": {"solar": 2}, "b": {"solar": 1, "unrelated": 100}, "c": {"unrelated": 1}}
    assert bm25({"solar": 1}, docs) == ["a", "b"]
    assert bm25({"absent": 1}, docs) == [] and bm25({}, docs) == []
    assert rrf((["a", "b"], ["b", "c"]))[0] == "b"
    assert rrf((["b"], ["a"])) == ["a", "b"]
    with pytest.raises(ValueError):
        rrf((["a", "a"],))


@pytest.mark.parametrize("bad", [(0.0,) * 384, (float("nan"),) + (0.0,) * 383, (1.0,) * 383])
def test_bad_query_vectors_are_rejected(bad: tuple[float, ...]) -> None:
    with pytest.raises(ReadUnavailable):
        verified_vector(bad)


@pytest.mark.parametrize("endpoint", ["retrieval", "answers"])
@pytest.mark.parametrize("role", ["anonymous", "learner", "admin", "revoked"])
def test_http_auth_exact_versions_and_current_account(
    tmp_path: Path, endpoint: str, role: str
) -> None:
    engine, search, graph = service(tmp_path)
    user = (
        replace(administrator(), role="learner")
        if role in ("learner", "revoked")
        else administrator()
    )
    settings = AuthSettings(jwt_secret=SecretStr("ab" * 32))
    users = Users(user)
    auth = AuthService(users, settings)
    token = issue_token(user, settings)
    if role == "revoked":
        users.user = replace(user, auth_version=2)
    headers = {} if role == "anonymous" else {"Authorization": "Bearer " + token}
    with TestClient(create_app(auth_service=auth, retrieval_service=engine)) as client:
        response = client.post(
            "/v1/" + endpoint, json=question().model_dump(mode="json"), headers=headers
        )
    assert response.status_code == (401 if role in ("anonymous", "revoked") else 200)
    if response.status_code == 401:
        assert search.calls == [] and graph.calls == []
    else:
        assert (
            response.json()["meta"]["versions"]["corpus_version_id"]
            == engine.reads.corpus.manifest.id
        )


def test_http_encoded_limit_is_422_and_graph_failure_is_sanitized(tmp_path: Path) -> None:
    engine, _, graph = service(tmp_path)
    user = administrator()
    settings = AuthSettings(jwt_secret=SecretStr("ab" * 32))
    headers = {"Authorization": "Bearer " + issue_token(user, settings)}
    with TestClient(
        create_app(auth_service=AuthService(Users(user), settings), retrieval_service=engine)
    ) as client:
        graph.mode = "outage"
        response = client.post(
            "/v1/retrieval", json=question(arm="B3").model_dump(mode="json"), headers=headers
        )
        assert response.status_code == 503 and "Private" not in response.text

        class Oversize(Encoder):
            def token_count(self, text: str) -> int:
                return 513

        engine.encoder = Oversize()
        response = client.post(
            "/v1/retrieval", json=question().model_dump(mode="json"), headers=headers
        )
        assert response.status_code == 422
