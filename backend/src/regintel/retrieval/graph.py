"""Actual bounded Neo4j reads; provenance edges never become corporate paths."""

from dataclasses import dataclass
from typing import Literal, Protocol

from regintel.publication.graph import GraphUnavailable, Neo4jProjection
from regintel.publication.models import CorpusManifest
from regintel.reads.repository import ReadUnavailable


@dataclass(frozen=True)
class Neighbor:
    observation_id: str
    subject: str
    object: str
    hop: Literal[1, 2]


class GraphReader(Protocol):
    def expand(
        self,
        manifest: CorpusManifest,
        seeds: tuple[str, ...],
        allowed: tuple[str, ...],
        hops: Literal[1, 2],
    ) -> tuple[Neighbor, ...]: ...


class Neo4jExpansion:
    def __init__(self, projection: Neo4jProjection) -> None:
        self.projection = projection

    def expand(
        self,
        manifest: CorpusManifest,
        seeds: tuple[str, ...],
        allowed: tuple[str, ...],
        hops: Literal[1, 2],
    ) -> tuple[Neighbor, ...]:
        receipt = self.projection.verify(manifest)
        if receipt.corpus_version_id != manifest.id or receipt.manifest_sha256 != manifest.sha256:
            raise ReadUnavailable("The graph expansion version differs.")
        from neo4j import ManagedTransaction
        from neo4j.exceptions import DriverError, Neo4jError

        def read(tx: ManagedTransaction) -> tuple[Neighbor, ...]:
            frontier = set(seeds)
            visited = set(seeds)
            found: dict[str, Neighbor] = {}
            for hop in (1, 2):
                if hop > hops or not frontier:
                    break
                rows = tx.run(
                    "MATCH (a:RegIntelProjection:RegIntelEntity "
                    "{namespace:$namespace,corpus_version_id:$corpus})"
                    "-[r:OWNS|PROMOTER_OF|SUBSIDIARY_OF|SUPPLIES_TO|AUDITS|LENDS_TO]->"
                    "(b:RegIntelProjection:RegIntelEntity "
                    "{namespace:$namespace,corpus_version_id:$corpus}) "
                    "WHERE r.namespace=$namespace AND r.corpus_version_id=$corpus "
                    "AND r.id IN $allowed AND (a.id IN $frontier OR b.id IN $frontier) "
                    "RETURN r.id AS id,a.id AS subject,b.id AS object ORDER BY id LIMIT 1001",
                    namespace=receipt.namespace,
                    corpus=manifest.id,
                    allowed=list(allowed),
                    frontier=sorted(frontier),
                )
                reached: set[str] = set()
                count = 0
                for row in rows:
                    count += 1
                    identity, subject, target = (
                        str(row["id"]),
                        str(row["subject"]),
                        str(row["object"]),
                    )
                    found.setdefault(identity, Neighbor(identity, subject, target, hop))
                    reached.update((subject, target))
                if count > 1000 or len(found) > 1000:
                    raise ReadUnavailable("The graph expansion exceeds 1000 relations.")
                frontier = reached - visited
                visited.update(reached)
            return tuple(found[key] for key in sorted(found))

        try:
            with self.projection.driver.session(database="neo4j") as session:
                return session.execute_read(read)
        except (DriverError, Neo4jError):
            raise GraphUnavailable("The configured graph expansion is unavailable.") from None
