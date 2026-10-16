"""Verify committed projection bytes and exact pgvector rows before ranking."""

import math
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from regintel.db.config import DatabaseSettings
from regintel.db.migrations import connect_database
from regintel.publication.embeddings import RetrievalProjection
from regintel.publication.models import CorpusManifest
from regintel.publication.repository import PublicationRepository, body
from regintel.reads.repository import ReadUnavailable


@dataclass(frozen=True)
class SearchSnapshot:
    projection: RetrievalProjection
    dense: tuple[str, ...]


class SearchReader(Protocol):
    def search(
        self, manifest: CorpusManifest, allowed: tuple[str, ...], vector: tuple[float, ...]
    ) -> SearchSnapshot: ...


def verified_projection(manifest: CorpusManifest, projection: RetrievalProjection) -> None:
    if (
        projection.corpus_version_id != manifest.id
        or projection.manifest_sha256 != manifest.sha256
        or projection.embedding_manifest_sha256 != manifest.configuration.embedding_manifest_sha256
    ):
        raise ReadUnavailable("The committed retrieval projection identity differs.")
    observations = {item.id: item for item in manifest.observations}
    ids: set[str] = set()
    for chunk in projection.chunks:
        observation = observations.get(chunk.observation_id)
        if observation is None or chunk.id in ids:
            raise ReadUnavailable("Retrieval chunk membership differs.")
        ids.add(chunk.id)
        spans = (*observation.supports, *(w.span for w in observation.context_supports))
        if not any(
            span.evidence_id == chunk.support.evidence_id
            and span.start <= chunk.support.start < chunk.support.end <= span.end
            and span.quote[chunk.support.start - span.start : chunk.support.end - span.start]
            == chunk.support.quote
            for span in spans
        ):
            raise ReadUnavailable("A retrieval chunk differs from its accepted exact support.")


def verified_vector(vector: tuple[float, ...]) -> str:
    if (
        len(vector) != 384
        or not all(math.isfinite(value) for value in vector)
        or abs(math.sqrt(sum(value * value for value in vector)) - 1.0) > 1e-5
    ):
        raise ReadUnavailable("The query embedding is invalid.")
    return "[" + ",".join(str(value) for value in vector) + "]"


class SearchRepository:
    def __init__(self, database: DatabaseSettings) -> None:
        self.database = database

    def search(
        self, manifest: CorpusManifest, allowed: tuple[str, ...], vector: tuple[float, ...]
    ) -> SearchSnapshot:
        encoded = verified_vector(vector)
        if not set(allowed).issubset(item.id for item in manifest.observations):
            raise ReadUnavailable("The search observation scope differs.")
        with connect_database(self.database) as connection, connection.transaction():
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            connection.execute("SET LOCAL statement_timeout='15s'")
            row = connection.execute(
                "SELECT r.projection_bytes,r.projection_sha256,c.retrieval_sha256,"
                "c.manifest_sha256,v.state FROM regintel.publication_retrieval r "
                "JOIN regintel.publication_commits c USING(corpus_version_id) "
                "JOIN regintel.corpus_versions v ON v.id=c.corpus_version_id "
                "WHERE r.corpus_version_id=%s",
                (UUID(manifest.id),),
            ).fetchone()
            if (
                row is None
                or row[1] != row[2]
                or row[3] != manifest.sha256
                or row[4] != "PUBLISHED"
            ):
                raise ReadUnavailable("A matching published retrieval commit is required.")
            projection = RetrievalProjection.model_validate_json(body(row[0], row[1]))
            if projection.sha256 != row[2]:
                raise ReadUnavailable("The canonical committed retrieval content differs.")
            verified_projection(manifest, projection)
            count = connection.execute(
                "SELECT count(*) FROM regintel.retrieval_chunks WHERE corpus_version_id=%s",
                (UUID(manifest.id),),
            ).fetchone()
            if count != (len(projection.chunks),):
                raise ReadUnavailable("The stored retrieval row count differs.")
            PublicationRepository._verify_chunks(connection, projection)
            ranked = connection.execute(
                "SELECT id,embedding <=> %s::public.vector AS distance "
                "FROM regintel.retrieval_chunks WHERE corpus_version_id=%s "
                "AND observation_id=ANY(%s) ORDER BY distance,id",
                (encoded, UUID(manifest.id), [UUID(value) for value in allowed]),
            ).fetchall()
        expected = {chunk.id for chunk in projection.chunks if chunk.observation_id in allowed}
        if (
            {str(row[0]) for row in ranked} != expected
            or len(ranked) != len(expected)
            or any(not isinstance(row[1], float) or not math.isfinite(row[1]) for row in ranked)
        ):
            raise ReadUnavailable("The scoped dense ranking is incomplete or invalid.")
        return SearchSnapshot(projection, tuple(str(row[0]) for row in ranked))
