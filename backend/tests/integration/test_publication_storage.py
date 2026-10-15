"""Disposable PostgreSQL publication checks using explicitly authored filing text."""

from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest

from backend.tests.integration.test_validation_storage import ValidationContext, decision
from backend.tests.integration.test_validation_storage import validated as validated
from regintel.auth.types import User
from regintel.db.migrations import connect_database
from regintel.publication.embeddings import RetrievalProjection, project_retrieval
from regintel.publication.engine import PublicationConflict
from regintel.publication.graph import GraphReceipt, graph_data
from regintel.publication.models import (
    CandidateSelection,
    CorpusManifest,
    PublicationConfiguration,
    PublicationRequest,
)
from regintel.publication.repository import PublicationRepository
from regintel.validation.gate import current_configuration
from regintel.validation.repository import ValidationAuthorizationError

pytestmark = pytest.mark.integration


class AuthoredEncoder:
    """Controlled deterministic vectors solely for storage tests; never model results."""

    def token_count(self, text: str) -> int:
        return len(text.split()) + 2

    def embed(self, text: str) -> tuple[float, ...]:
        return (1.0,) + (0.0,) * 383


def configuration() -> PublicationConfiguration:
    return PublicationConfiguration(
        code_sha256="a" * 64,
        validator_configuration_sha256=current_configuration().sha256,
        embedding_manifest_sha256="b" * 64,
    )


@pytest.fixture
def publication(
    validated: ValidationContext,
) -> tuple[PublicationRepository, User, PublicationRequest]:
    run = validated.repository.validate(validated.candidate_run_id, validated.user)
    review = decision(validated, run, "narrative_fact")
    validated.repository.review(review, validated.user)
    request = PublicationRequest(
        idempotency_key=str(uuid4()),
        parent_corpus_version_id=None,
        selections=tuple(
            sorted(
                (
                    CandidateSelection(
                        candidate_run_id=run.candidate_run_id,
                        candidate_id=item.candidate_id,
                        review_id=review.id if item.candidate_id == review.candidate_id else None,
                    )
                    for item in run.results
                ),
                key=lambda item: item.candidate_id,
            )
        ),
    )
    return PublicationRepository(validated.database), validated.user, request


def prepared(
    repository: PublicationRepository, user: User, manifest: CorpusManifest
) -> GraphReceipt:
    projection = project_retrieval(manifest, AuthoredEncoder())
    repository.save_retrieval(projection, user)
    data = graph_data(manifest)
    # A labelled authored graph receipt isolates database commit guards. The real
    # Neo4j adapter is verified separately, including reconstruction and outages.
    receipt = GraphReceipt(
        corpus_version_id=manifest.id,
        manifest_sha256=manifest.sha256,
        namespace="regintel_test_" + uuid4().hex,
        graph_sha256=data.sha256,
        node_count=len(data.nodes),
        edge_count=len(data.edges),
    )
    repository.save_graph(receipt, user)
    return receipt


def counts(repository: PublicationRepository) -> tuple[object, ...]:
    with connect_database(repository.database) as connection:
        row = connection.execute("""SELECT (SELECT count(*) FROM regintel.acceptance_audits),
            (SELECT count(*) FROM regintel.fact_observations),
            (SELECT count(*) FROM regintel.relation_observations),
            (SELECT count(*) FROM regintel.publication_commits)""").fetchone()
        assert row is not None
        return row


def test_approved_build_is_replayable_but_cannot_be_read_as_published(
    publication: tuple[PublicationRepository, User, PublicationRequest],
) -> None:
    repository, user, request = publication
    manifest = repository.build(request, configuration(), user)
    assert counts(repository) == (0, 0, 0, 0)
    assert repository.build(request, configuration(), user) == manifest
    with pytest.raises(PublicationConflict):
        repository.published(manifest.id)
    with pytest.raises(PublicationConflict):
        repository.finalize(
            manifest.id,
            configuration(),
            user,
            GraphReceipt(
                corpus_version_id=manifest.id,
                manifest_sha256=manifest.sha256,
                namespace="regintel",
                graph_sha256="d" * 64,
                node_count=0,
                edge_count=0,
            ),
        )


def test_atomic_publication_retains_exact_decimal_and_original_review(
    publication: tuple[PublicationRepository, User, PublicationRequest],
) -> None:
    repository, user, request = publication
    manifest = repository.build(request, configuration(), user)
    receipt = prepared(repository, user, manifest)
    assert repository.finalize(manifest.id, configuration(), user, receipt) == manifest
    assert repository.published() == manifest
    assert counts(repository) == (3, 2, 1, 1)
    assert repository.finalize(manifest.id, configuration(), user, receipt) == manifest
    assert counts(repository) == (3, 2, 1, 1)
    with connect_database(repository.database) as connection:
        row = connection.execute(
            "SELECT normalized_value FROM regintel.publication_observations "
            "WHERE normalized_value IS NOT NULL"
        ).fetchone()
        assert row == (Decimal("1234.50"),)
        assert (
            connection.execute(
                "SELECT normalized_value FROM regintel.quantitative_contexts "
                "WHERE normalized_value IS NOT NULL"
            ).fetchone()
            == row
        )
        assert connection.execute(
            "SELECT count(*) FROM regintel.candidates WHERE state='CANDIDATE'"
        ).fetchone() == (3,)


def test_new_head_conflicts_with_prepared_sibling_build(
    publication: tuple[PublicationRepository, User, PublicationRequest],
) -> None:
    repository, user, request = publication
    first = repository.build(request, configuration(), user)
    sibling = repository.build(
        request.model_copy(update={"idempotency_key": str(uuid4())}), configuration(), user
    )
    one = prepared(repository, user, first)
    two = prepared(repository, user, sibling)
    repository.finalize(first.id, configuration(), user, one)
    with pytest.raises(PublicationConflict):
        repository.finalize(sibling.id, configuration(), user, two)
    assert repository.published() == first
    assert counts(repository) == (3, 2, 1, 1)


def test_final_transaction_rolls_back_every_authority_write(
    publication: tuple[PublicationRepository, User, PublicationRequest],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, user, request = publication
    manifest = repository.build(request, configuration(), user)
    receipt = prepared(repository, user, manifest)
    original = repository._observation

    def interrupted(*args: object) -> None:
        original(*args)  # type: ignore[arg-type]
        raise RuntimeError("Authored interruption inside the publication transaction.")

    monkeypatch.setattr(repository, "_observation", interrupted)
    with pytest.raises(RuntimeError):
        repository.finalize(manifest.id, configuration(), user, receipt)
    assert counts(repository) == (0, 0, 0, 0)
    monkeypatch.setattr(repository, "_observation", original)
    assert repository.finalize(manifest.id, configuration(), user, receipt) == manifest


def test_current_administrator_is_checked_again_before_final_commit(
    publication: tuple[PublicationRepository, User, PublicationRequest],
) -> None:
    repository, user, request = publication
    manifest = repository.build(request, configuration(), user)
    receipt = prepared(repository, user, manifest)
    with pytest.raises(ValidationAuthorizationError):
        repository.finalize(
            manifest.id, configuration(), replace(user, auth_version=user.auth_version + 1), receipt
        )
    assert counts(repository) == (0, 0, 0, 0)


def test_later_rejection_cannot_be_ignored_at_publication(
    publication: tuple[PublicationRepository, User, PublicationRequest],
    validated: ValidationContext,
) -> None:
    repository, user, request = publication
    manifest = repository.build(request, configuration(), user)
    receipt = prepared(repository, user, manifest)
    run = validated.repository.validate(validated.candidate_run_id, user)
    validated.repository.review(decision(validated, run, "relation", "REJECT"), user)
    with pytest.raises(PublicationConflict):
        repository.finalize(manifest.id, configuration(), user, receipt)
    assert counts(repository) == (0, 0, 0, 0)


@pytest.mark.parametrize("field", ["raw_text", "quantity", "supports", "review_id"])
def test_sql_rejects_self_consistent_but_forged_acceptance_payload(
    publication: tuple[PublicationRepository, User, PublicationRequest], field: str
) -> None:
    repository, user, request = publication
    manifest = repository.build(request, configuration(), user)
    payload = manifest.model_dump(mode="json")
    numeric = next(
        item for item in payload["new_acceptances"] if item["observation"]["kind"] == "numeric_fact"
    )
    if field == "raw_text":
        numeric["observation"][field] = "Invented disclosure."
    elif field == "quantity":
        numeric["observation"][field]["normalized_value"] = "99999"
    elif field == "supports":
        numeric["observation"][field][0]["quote"] = "Invented support."
    else:
        numeric["observation"][field] = str(uuid4())
    # Call the same database boundary used for build insertion, independent of Python models.
    from psycopg.types.json import Jsonb

    with connect_database(repository.database) as connection, pytest.raises(psycopg.Error):
        connection.execute(
            "SELECT regintel.publication_snapshot(%s,%s)",
            (Jsonb(numeric), Jsonb(payload["configuration"])),
        )


@pytest.mark.parametrize(
    "table",
    [
        "publication_builds",
        "publication_retrieval",
        "retrieval_chunks",
        "publication_graph_receipts",
        "publication_commits",
        "publication_observations",
    ],
)
def test_publication_history_is_immutable(
    publication: tuple[PublicationRepository, User, PublicationRequest], table: str
) -> None:
    from psycopg import sql

    repository, user, request = publication
    manifest = repository.build(request, configuration(), user)
    receipt = prepared(repository, user, manifest)
    repository.finalize(manifest.id, configuration(), user, receipt)
    with (
        connect_database(repository.database) as connection,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        connection.execute(sql.SQL("DELETE FROM regintel.{}").format(sql.Identifier(table)))


def test_audited_retrieval_rebuild_preserves_authority_and_approved_content(publication):
    repository, user, request = publication
    manifest = repository.build(request, configuration(), user)
    receipt = prepared(repository, user, manifest)
    repository.finalize(manifest.id, configuration(), user, receipt)
    before = counts(repository)
    projection = repository.retrieval(manifest.id, user)
    repository.rebuild_retrieval(manifest.id, user)
    assert counts(repository) == before
    assert repository.retrieval(manifest.id, user) == projection
    assert repository.published() == manifest
    with connect_database(repository.database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM regintel.retrieval_rebuilds"
        ).fetchone() == (1,)


@pytest.mark.parametrize("validated", [{"published_on": "2025-01-01"}], indirect=True)
@pytest.mark.parametrize("operation", ["SUPERSEDE", "SUPPLEMENT", "REMOVE"])
def test_two_filing_scoped_amendment_retains_history_and_other_disclosures(
    publication, validated, operation
):
    from backend.tests.evidence_fixtures import synthetic_artifact
    from backend.tests.integration.test_evidence_storage import context, parsed, persist
    from regintel.candidates.models import SourceSpan
    from regintel.candidates.repository import CandidateRepository
    from regintel.entities.repository import EntityRepository
    from regintel.entities.resolution import (
        EntityResolver,
    )
    from regintel.entities.resolution import (
        current_configuration as resolver_configuration,
    )
    from regintel.publication.engine import corpus_view
    from regintel.publication.models import EffectProposal, LineageProposal

    repository, user, request = publication
    parent = repository.build(request, configuration(), user)
    repository.finalize(parent.id, configuration(), user, prepared(repository, user, parent))
    source_text = (
        "Alpha Solar Limited supplies to Beta Solar Limited.\nRed Herring Prospectus.\n"
        "The earlier supplies to disclosure is "
        + {"SUPERSEDE": "superseded", "SUPPLEMENT": "supplemented", "REMOVE": "removed"}[operation]
        + " effective 1 January 2026."
    )
    fixture = context(repository.database, document_type="ADDENDUM", published_on="2026-01-01")
    artifact = synthetic_artifact(
        configuration=fixture.configuration,
        blob=fixture.blob,
        parse_id=fixture.artifact.id,
        filing_id=fixture.artifact.filing_id,
        filing_version_id=fixture.artifact.filing_version_id,
        original=source_text,
    )
    artifact = artifact.model_validate(artifact.model_dump(mode="python") | {"tables": ()})
    fixture = replace(fixture, artifact=artifact)
    with connect_database(repository.database) as connection, connection.transaction():
        persist(connection, fixture)
        parsed(connection, fixture)
    entities = EntityRepository(repository.database)
    records, artifact_sha = entities.evidence_for_parse(artifact.id)
    entity_run = EntityResolver(entities.snapshot(), resolver_configuration()).run(
        records, artifact_sha
    )
    entities.save_run(entity_run, user)
    candidate_run = CandidateRepository(repository.database).extract(entity_run.id, (), user)
    parent_source = validated.repository.input_for_run(validated.candidate_run_id).source.evidence[
        0
    ]
    child_source = records[0]

    def anchor(record, quote):
        start = record.span.start + record.span.quote.index(quote)
        return SourceSpan(evidence_id=record.id, start=start, end=start + len(quote), quote=quote)

    old = next(item for item in parent.observations if item.kind == "relation")
    lineage = LineageProposal(
        id=str(uuid4()),
        parent_filing_version_id=old.filing_version_id,
        child_filing_version_id=artifact.filing_version_id,
        lineage_type="ADDENDUM_TO",
        issuer_entity_id=old.subject_entity_id,
        parent_identity=anchor(parent_source, "Alpha Solar Limited"),
        child_identity=anchor(child_source, "Alpha Solar Limited"),
        parent_reference=anchor(child_source, "Red Herring Prospectus"),
        review_note="Authored reviewed filing pair.",
    )
    selections = (
        ()
        if operation == "REMOVE"
        else (
            CandidateSelection(
                candidate_run_id=candidate_run.id,
                candidate_id=candidate_run.candidates[0].id,
                review_id=None,
            ),
        )
    )
    effect = EffectProposal(
        id=str(uuid4()),
        lineage_id=lineage.id,
        effect_type=operation,
        affected_observation_ids=(old.id,),
        new_candidate_ids=tuple(item.candidate_id for item in selections),
        supports=(anchor(child_source, source_text.splitlines()[-1]),),
        effective_date="2026-01-01",
        effective_date_support=anchor(child_source, "1 January 2026"),
        review_note="Authored explicit scoped effect.",
    )
    child_request = PublicationRequest(
        idempotency_key=str(uuid4()),
        parent_corpus_version_id=parent.id,
        selections=selections,
        lineages=(lineage,),
        effects=(effect,),
    )
    manifest = repository.build(child_request, configuration(), user)
    receipt = prepared(repository, user, manifest)
    repository.finalize(manifest.id, configuration(), user, receipt)
    assert repository.published(parent.id) == parent
    assert all(item in manifest.observations for item in parent.observations)
    assert len(corpus_view(manifest, historical=True).observations) == (
        3 if operation == "REMOVE" else 4
    )
    assert (
        len(corpus_view(manifest).observations)
        == {"REMOVE": 2, "SUPERSEDE": 3, "SUPPLEMENT": 4}[operation]
    )
    assert corpus_view(manifest, "2025-12-31").observations == parent.observations
    assert (
        old.id not in manifest.active_observation_ids
        if operation != "SUPPLEMENT"
        else old.id in manifest.active_observation_ids
    )
    assert not manifest.unresolved_parent_filing_version_ids


def test_real_neo4j_rebuild_verification_and_recoverable_outage(publication):
    from pathlib import Path

    from regintel.publication.graph import Neo4jProjection
    from regintel.publication.service import PublicationService

    repository, user, request = publication
    graph = Neo4jProjection.from_env(
        Path(__file__).resolve().parents[3] / ".env", namespace="regintel_test_" + uuid4().hex
    )
    service = PublicationService(repository, graph, configuration(), encoder=AuthoredEncoder())
    try:
        manifest = service.build(request, user)
        assert service.publish(manifest.id, user) == manifest
        first = graph.verify(manifest)
        assert service.rebuild(manifest.id, user) == manifest
        assert graph.verify(manifest) == first
        assert repository.published() == manifest
        with graph.driver.session(database="neo4j") as session:
            session.run(
                "MATCH (n:RegIntelProjection {namespace:$namespace,corpus_version_id:$corpus}) "
                "WHERE n.id=$id SET n.payload=$payload",
                namespace=graph.namespace,
                corpus=manifest.id,
                id=manifest.observations[0].id,
                payload="Authored damage inside this disposable namespace.",
            ).consume()
        with pytest.raises(PublicationConflict):
            graph.verify(manifest)
        service.rebuild(manifest.id, user)
        assert graph.verify(manifest) == first
    finally:
        graph.remove_test_namespace()
        graph.close()


def test_empty_projection_cannot_publish_an_approved_observation(publication):
    repository, user, request = publication
    manifest = repository.build(request, configuration(), user)
    empty = RetrievalProjection(
        corpus_version_id=manifest.id,
        manifest_sha256=manifest.sha256,
        embedding_manifest_sha256=manifest.configuration.embedding_manifest_sha256,
        chunks=(),
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        repository.save_retrieval(empty, user)
    assert repository.retrieval(manifest.id, user) is None
    assert counts(repository) == (0, 0, 0, 0)


def test_graph_outage_keeps_build_recoverable_and_head_unchanged(publication):
    from regintel.publication.graph import GraphUnavailable
    from regintel.publication.service import PublicationService

    class OfflineGraph:
        def prepare(self, manifest):
            raise GraphUnavailable("Authored unavailable projection.")

        def verify(self, manifest):
            raise GraphUnavailable("Authored unavailable projection.")

    repository, user, request = publication
    service = PublicationService(
        repository, OfflineGraph(), configuration(), encoder=AuthoredEncoder()
    )
    manifest = service.build(request, user)
    with pytest.raises(GraphUnavailable):
        service.publish(manifest.id, user)
    assert repository.retrieval(manifest.id, user) is not None
    assert counts(repository) == (0, 0, 0, 0)
    assert not repository.is_published(manifest.id)
    receipt = prepared(repository, user, manifest)
    repository.finalize(manifest.id, configuration(), user, receipt)
    assert repository.published() == manifest


def test_actual_revocation_after_approval_prevents_publication(publication):
    repository, user, request = publication
    manifest = repository.build(request, configuration(), user)
    receipt = prepared(repository, user, manifest)
    with connect_database(repository.database) as connection:
        connection.execute(
            "UPDATE regintel.users SET auth_version=auth_version+1 WHERE id=%s", (user.id,)
        )
    with pytest.raises(ValidationAuthorizationError):
        repository.finalize(manifest.id, configuration(), user, receipt)
    assert counts(repository) == (0, 0, 0, 0)


def test_historical_publication_replay_does_not_reaccept_after_configuration_change(publication):
    repository, user, request = publication
    manifest = repository.build(request, configuration(), user)
    receipt = prepared(repository, user, manifest)
    repository.finalize(manifest.id, configuration(), user, receipt)
    changed = configuration().model_copy(update={"code_sha256": "f" * 64})
    assert repository.finalize(manifest.id, changed, user, receipt) == manifest
    assert counts(repository) == (3, 2, 1, 1)
