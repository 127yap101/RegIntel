"""Version-scoped Neo4j projection. PostgreSQL publication remains authoritative."""

import hashlib
import json
import re
from pathlib import Path
from typing import Literal, Protocol, cast

from dotenv import dotenv_values
from pydantic import Field

from regintel.candidates.records import stable_id
from regintel.contracts.models import ContractModel, RelationType
from regintel.contracts.primitives import CanonicalId, SafeInteger, Sha256Hash
from regintel.entities.models import canonical_bytes
from regintel.publication.engine import PublicationConflict
from regintel.publication.models import AuditedEffect, AuditedLineage, CorpusManifest

type NodeLabel = Literal["Corpus", "Entity", "Observation", "Evidence", "Decision"]
type EdgeLabel = RelationType | Literal["ASSERTS", "SUPPORTED_BY", "IN_CORPUS"]
NODE_LABELS = ("Corpus", "Entity", "Observation", "Evidence", "Decision")
EDGE_LABELS = (
    "OWNS",
    "PROMOTER_OF",
    "SUBSIDIARY_OF",
    "SUPPLIES_TO",
    "AUDITS",
    "LENDS_TO",
    "ASSERTS",
    "SUPPORTED_BY",
    "IN_CORPUS",
)


class GraphUnavailable(RuntimeError):
    """The configured local graph cannot prepare or verify a projection."""


class GraphNode(ContractModel):
    id: CanonicalId
    label: NodeLabel
    payload: str


class GraphEdge(ContractModel):
    id: CanonicalId
    source: CanonicalId
    target: CanonicalId
    label: EdgeLabel
    payload: str


class GraphData(ContractModel):
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


class GraphReceipt(ContractModel):
    corpus_version_id: CanonicalId
    manifest_sha256: Sha256Hash
    namespace: str = Field(pattern=r"^regintel(_test_[0-9a-f]{32})?$")
    graph_sha256: Sha256Hash
    node_count: SafeInteger
    edge_count: SafeInteger


def graph_data(manifest: CorpusManifest) -> GraphData:
    nodes = {
        manifest.id: GraphNode(
            id=manifest.id,
            label="Corpus",
            payload=json.dumps(
                {
                    "manifest_sha256": manifest.sha256,
                    "parent_corpus_version_id": manifest.parent_corpus_version_id,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    }
    edges: list[GraphEdge] = []
    for observation in manifest.observations:
        payload = json.dumps(
            {
                "corpus_version_id": manifest.id,
                "active": observation.id in manifest.active_observation_ids,
                "effect_ids": [
                    item.proposal.id
                    for item in manifest.effects
                    if observation.id
                    in (*item.proposal.affected_observation_ids, *item.new_observation_ids)
                ],
                "lineage_ids": [
                    item.proposal.id
                    for item in manifest.lineages
                    if observation.filing_version_id
                    in (
                        item.proposal.parent_filing_version_id,
                        item.proposal.child_filing_version_id,
                    )
                ],
                "observation": observation.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        nodes[observation.id] = GraphNode(
            id=observation.id,
            label="Observation",
            payload=payload,
        )
        for identity in (observation.subject_entity_id, observation.object_entity_id):
            if identity is not None:
                nodes[identity] = GraphNode(
                    id=identity, label="Entity", payload=json.dumps({"entity_id": identity})
                )
        edges.append(
            GraphEdge(
                id=stable_id("asserts:" + observation.id),
                source=observation.subject_entity_id,
                target=observation.id,
                label="ASSERTS",
                payload=payload,
            )
        )
        edges.append(
            GraphEdge(
                id=stable_id("member:" + observation.id),
                source=observation.id,
                target=manifest.id,
                label="IN_CORPUS",
                payload=payload,
            )
        )
        if observation.kind == "relation":
            assert (
                observation.object_entity_id is not None and observation.relation_type is not None
            )
            edges.append(
                GraphEdge(
                    id=observation.id,
                    source=observation.subject_entity_id,
                    target=observation.object_entity_id,
                    label=observation.relation_type,
                    payload=payload,
                )
            )
        for support in observation.supports:
            evidence_id = support.evidence_id
            nodes[evidence_id] = GraphNode(
                id=evidence_id, label="Evidence", payload=json.dumps({"evidence_id": evidence_id})
            )
            edges.append(
                GraphEdge(
                    id=stable_id(
                        "evidence:"
                        + observation.id
                        + ":"
                        + evidence_id
                        + f":{support.start}:{support.end}"
                    ),
                    source=observation.id,
                    target=evidence_id,
                    label="SUPPORTED_BY",
                    payload=canonical_bytes(support).decode(),
                )
            )
    decisions: tuple[AuditedLineage | AuditedEffect, ...] = (*manifest.lineages, *manifest.effects)
    for decision in decisions:
        identity = decision.proposal.id
        nodes[identity] = GraphNode(
            id=identity, label="Decision", payload=canonical_bytes(decision).decode()
        )
        edges.append(
            GraphEdge(
                id=stable_id("decision-member:" + identity),
                source=identity,
                target=manifest.id,
                label="IN_CORPUS",
                payload=canonical_bytes(decision).decode(),
            )
        )
    return GraphData(
        nodes=tuple(nodes[key] for key in sorted(nodes)),
        edges=tuple(sorted(edges, key=lambda item: item.id)),
    )


class GraphProjection(Protocol):
    def prepare(self, manifest: CorpusManifest) -> GraphReceipt: ...
    def verify(self, manifest: CorpusManifest) -> GraphReceipt: ...


class Neo4jProjection:
    def __init__(self, username: str, password: str, *, namespace: str = "regintel") -> None:
        if re.fullmatch(r"regintel(_test_[0-9a-f]{32})?", namespace) is None:
            raise ValueError("Graph namespace is invalid.")
        from neo4j import GraphDatabase

        self.namespace = namespace
        # No user-selected endpoint, custom resolver or credential-file fallback.
        self.driver = GraphDatabase.driver(
            "bolt://127.0.0.1:7687",
            auth=(username, password),
            connection_timeout=5,
            max_transaction_retry_time=5,
        )

    @classmethod
    def from_env(cls, path: Path, *, namespace: str = "regintel") -> "Neo4jProjection":
        values = dotenv_values(path, encoding="utf-8", interpolate=False)
        auth = values.get("NEO4J_AUTH")
        if not isinstance(auth, str) or not auth.startswith("neo4j/") or not auth[6:]:
            raise ValueError("Explicit project-local graph credentials are required.")
        return cls("neo4j", auth[6:], namespace=namespace)

    def close(self) -> None:
        self.driver.close()

    def _receipt(self, manifest: CorpusManifest) -> GraphReceipt:
        data = graph_data(manifest)
        return GraphReceipt(
            corpus_version_id=manifest.id,
            manifest_sha256=manifest.sha256,
            namespace=self.namespace,
            graph_sha256=data.sha256,
            node_count=len(data.nodes),
            edge_count=len(data.edges),
        )

    def prepare(self, manifest: CorpusManifest) -> GraphReceipt:
        from neo4j import ManagedTransaction

        data = graph_data(manifest)

        def write(tx: ManagedTransaction) -> None:
            # One managed transaction: readers see the prior complete projection
            # until this approved version is rebuilt. Only this namespace/version.
            tx.run(
                "MATCH (n:RegIntelProjection {namespace:$namespace,corpus_version_id:$corpus}) "
                "DETACH DELETE n",
                namespace=self.namespace,
                corpus=manifest.id,
            ).consume()
            for label in NODE_LABELS:
                rows = [item.model_dump(mode="json") for item in data.nodes if item.label == label]
                tx.run(
                    f"UNWIND $rows AS row CREATE (n:RegIntelProjection:RegIntel{label}) "
                    "SET "
                    "n.namespace=$namespace,n.corpus_version_id=$corpus,n.id=row.id,n.payload=row.payload",
                    rows=rows,
                    namespace=self.namespace,
                    corpus=manifest.id,
                ).consume()
            for label in EDGE_LABELS:
                rows = [item.model_dump(mode="json") for item in data.edges if item.label == label]
                tx.run(
                    "UNWIND $rows AS row MATCH (a:RegIntelProjection "
                    "{namespace:$namespace,corpus_version_id:$corpus,id:row.source}),"
                    "(b:RegIntelProjection "
                    "{namespace:$namespace,corpus_version_id:$corpus,id:row.target}) "
                    f"CREATE (a)-[r:{label}]->(b) SET r.id=row.id,r.payload=row.payload,"
                    "r.namespace=$namespace,r.corpus_version_id=$corpus",
                    rows=rows,
                    namespace=self.namespace,
                    corpus=manifest.id,
                ).consume()

        from neo4j.exceptions import DriverError, Neo4jError

        try:
            with self.driver.session(database="neo4j") as session:
                session.run(
                    "CREATE CONSTRAINT regintel_projection_key IF NOT EXISTS "
                    "FOR (n:RegIntelProjection) REQUIRE (n.namespace,n.corpus_version_id,n.id) IS "
                    "UNIQUE"
                ).consume()
                session.execute_write(write)
        except (DriverError, Neo4jError):
            raise GraphUnavailable("The configured graph is unavailable.") from None
        return self.verify(manifest)

    def verify(self, manifest: CorpusManifest) -> GraphReceipt:
        from neo4j import ManagedTransaction

        def read(tx: ManagedTransaction) -> GraphData:
            nodes = []
            for row in tx.run(
                "MATCH (n:RegIntelProjection {namespace:$namespace,corpus_version_id:$corpus}) "
                "RETURN n.id AS id,n.payload AS payload,labels(n) AS labels ORDER BY id",
                namespace=self.namespace,
                corpus=manifest.id,
            ):
                labels = cast(list[str], row["labels"])
                label = next((item for item in NODE_LABELS if "RegIntel" + item in labels), None)
                if label is None:
                    raise PublicationConflict("Graph labels differ from the approved projection.")
                nodes.append(
                    GraphNode.model_validate(
                        {"id": row["id"], "label": label, "payload": row["payload"]}
                    )
                )
            edges = []
            for row in tx.run(
                "MATCH (a:RegIntelProjection "
                "{namespace:$namespace,corpus_version_id:$corpus})-[r]->(b) "
                "RETURN r.id AS id,a.id AS source,b.id AS target,type(r) AS label,r.payload AS "
                "payload "
                "ORDER BY id",
                namespace=self.namespace,
                corpus=manifest.id,
            ):
                edges.append(GraphEdge.model_validate(dict(row)))
            return GraphData(nodes=tuple(nodes), edges=tuple(edges))

        from neo4j.exceptions import DriverError, Neo4jError

        try:
            with self.driver.session(database="neo4j") as session:
                actual = session.execute_read(read)
        except (DriverError, Neo4jError):
            raise GraphUnavailable("The configured graph is unavailable.") from None
        if actual != graph_data(manifest):
            raise PublicationConflict(
                "Graph projection content differs from the approved manifest."
            )
        return self._receipt(manifest)

    def remove_test_namespace(self) -> None:
        if not self.namespace.startswith("regintel_test_"):
            raise ValueError(
                "Only this explicitly selected disposable test namespace may be removed."
            )
        with self.driver.session(database="neo4j") as session:
            session.run(
                "MATCH (n:RegIntelProjection {namespace:$namespace}) DETACH DELETE n",
                namespace=self.namespace,
            ).consume()
