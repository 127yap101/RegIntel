"""Disposable real PostgreSQL/Neo4j checks; inputs are explicitly authored."""

from pathlib import Path
from uuid import uuid4

import pytest

from backend.tests.integration.test_publication_storage import (
    AuthoredEncoder,
    configuration,
    prepared,
)
from backend.tests.integration.test_publication_storage import publication as publication
from backend.tests.integration.test_published_reads_storage import service as read_service
from backend.tests.integration.test_validation_storage import validated as validated
from regintel.auth.types import User
from regintel.publication.graph import Neo4jProjection
from regintel.publication.models import PublicationRequest
from regintel.publication.repository import PublicationRepository
from regintel.reads.repository import ReadUnavailable
from regintel.retrieval.graph import Neo4jExpansion
from regintel.retrieval.models import Filters, NumericLookup, RetrievalRequest
from regintel.retrieval.repository import SearchRepository
from regintel.retrieval.service import RetrievalService

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "scenario", ["B0", "B1", "B2", "B3", "numeric", "unpublished", "wrong_manifest", "scope"]
)
def test_real_published_dense_hybrid_graph_and_numeric_reads(
    publication: tuple[PublicationRepository, User, PublicationRequest],
    tmp_path: Path,
    scenario: str,
) -> None:
    repository, user, request = publication
    manifest = repository.build(request, configuration(), user)
    search = SearchRepository(repository.database)
    if scenario == "unpublished":
        with pytest.raises(ReadUnavailable):
            search.search(
                manifest,
                tuple(item.id for item in manifest.observations),
                AuthoredEncoder().embed("question"),
            )
        return
    repository.finalize(manifest.id, configuration(), user, prepared(repository, user, manifest))
    reads = read_service(repository, tmp_path)
    if scenario == "wrong_manifest":
        wrong = manifest.model_copy(update={"request_sha256": "0" * 64})
        with pytest.raises(ReadUnavailable):
            search.search(wrong, (), AuthoredEncoder().embed("question"))
        return
    if scenario == "scope":
        with pytest.raises(ReadUnavailable):
            search.search(manifest, (str(uuid4()),), AuthoredEncoder().embed("question"))
        return
    graph = None
    try:
        if scenario == "B3":
            graph = Neo4jProjection.from_env(
                ROOT / ".env", namespace="regintel_test_" + uuid4().hex
            )
            graph.prepare(manifest)
        engine = RetrievalService(
            reads, search, Neo4jExpansion(graph) if graph else None, encoder=AuthoredEncoder()
        )
        if scenario == "numeric":
            item = next(item for item in manifest.observations if item.kind == "numeric_fact")
            assert item.quantity is not None
            quantity = item.quantity
            filters = Filters(
                company_id=item.subject_entity_id, period=quantity.period, basis=quantity.basis
            )
            numeric = NumericLookup(metric_id=item.metric_id, currency="INR", unit="crore")
            query = RetrievalRequest(
                question="Exact accepted revenue lookup",
                corpus_version_id=manifest.id,
                filters=filters,
                numeric=numeric,
            )
            result = engine.answer(query)
            assert result.state == "NUMERIC_VALUE" and len(result.claims) == 1
            assert (
                result.claims[0].quantity.model_dump(mode="json")["normalized_value"] == "1234.50"
            )
            assert result.claims[0].citations and result.retrieval.trace.provider_calls == 0
            wrong = engine.answer(
                query.model_copy(update={"numeric": numeric.model_copy(update={"unit": "lakh"})})
            )
            assert wrong.state == "NUMERIC_INCOMPATIBLE" and wrong.claims == ()
            missing = engine.answer(
                query.model_copy(
                    update={"numeric": numeric.model_copy(update={"metric_id": str(uuid4())})}
                )
            )
            assert missing.state == "NUMERIC_UNAVAILABLE"
            period = query.filters.period.model_copy(update={"start_date": None})
            incomplete = engine.answer(
                query.model_copy(update={"filters": filters.model_copy(update={"period": period})})
            )
            assert incomplete.state == "NUMERIC_CONTEXT_REQUIRED"
        else:
            query = RetrievalRequest.model_validate(
                {
                    "question": "Who supplies to Beta Solar?",
                    "corpus_version_id": manifest.id,
                    "arm": scenario,
                }
            )
            result = engine.search(query)
            assert result.view.corpus_version_id == manifest.id and result.hits
            assert result.trace.context_tokens <= query.context_budget
            assert all(hit.citations for hit in result.hits)
            assert {hit.observation.id for hit in result.hits}.issubset(
                item.id for item in manifest.observations
            )
            assert any(hit.lexical_rank is not None for hit in result.hits) == (
                scenario in ("B2", "B3")
            )
            if scenario == "B3":
                assert any(hit.graph_hop == 1 for hit in result.hits)
    finally:
        if graph is not None:
            graph.remove_test_namespace()
            graph.close()


def test_actual_neo4j_two_hops_cannot_cross_filtered_edges_or_corpus(
    publication: tuple[PublicationRepository, User, PublicationRequest],
) -> None:
    """Authored topology only; these extra edges are never accepted into PostgreSQL."""
    repository, user, request = publication
    original = repository.build(request, configuration(), user)
    template = next(item for item in original.observations if item.kind == "relation")
    a, b, c, d = (str(uuid4()) for _ in range(4))
    chain = tuple(
        template.model_copy(
            update={
                "id": str(uuid4()),
                "subject_entity_id": source,
                "object_entity_id": target,
            }
        )
        for source, target in ((a, b), (b, c), (c, d))
    )
    manifest = original.model_copy(
        update={
            "observations": tuple(sorted(chain, key=lambda item: item.id)),
            "active_observation_ids": tuple(sorted(item.id for item in chain)),
        }
    )
    graph = Neo4jProjection.from_env(ROOT / ".env", namespace="regintel_test_" + uuid4().hex)
    try:
        graph.prepare(manifest)
        # Another corpus in the same disposable namespace cannot become a path.
        graph.prepare(manifest.model_copy(update={"id": str(uuid4())}))
        reader = Neo4jExpansion(graph)
        allowed = tuple(item.id for item in chain)
        first = reader.expand(manifest, (a,), allowed, 1)
        second = reader.expand(manifest, (a,), allowed, 2)
        assert {item.observation_id for item in first} == {chain[0].id}
        assert {item.observation_id for item in second} == {chain[0].id, chain[1].id}
        assert next(item for item in second if item.observation_id == chain[1].id).hop == 2
        assert all((item.subject, item.object) in ((a, b), (b, c)) for item in second)
        filtered = reader.expand(manifest, (a,), (chain[0].id, chain[2].id), 2)
        assert {item.observation_id for item in filtered} == {chain[0].id}
    finally:
        graph.remove_test_namespace()
        graph.close()
