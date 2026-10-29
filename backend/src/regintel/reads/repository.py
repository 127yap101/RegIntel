"""Read frozen accepted inputs; the current global registry is never a catalog."""

from typing import Protocol
from uuid import UUID

from regintel.candidates.models import MetricDefinition
from regintel.contracts.models import ContractModel
from regintel.db.config import DatabaseSettings
from regintel.db.migrations import connect_database
from regintel.entities.models import EntityRegistration, RegistrySnapshot, canonical_bytes
from regintel.numerical.gate_repository import _read as read_native_gate
from regintel.publication.models import (
    CorpusManifest,
    NumericalAcceptanceSnapshot,
    PublishedNumericalObservation,
)
from regintel.publication.repository import body
from regintel.validation.models import ValidationInput


class ReadUnavailable(ValueError):
    """The requested published view cannot be verified."""


class ReadNotFound(ValueError):
    """No matching resource exists within the requested published view."""


class Catalog(ContractModel):
    entities: tuple[EntityRegistration, ...]
    metrics: tuple[MetricDefinition, ...]


class CatalogReader(Protocol):
    def catalog(self, manifest: CorpusManifest) -> Catalog: ...


class RegistryContents(ContractModel):
    entities: tuple[EntityRegistration, ...]


class ReadRepository:
    def __init__(self, database: DatabaseSettings) -> None:
        self.database = database

    def _legacy_catalog(self, manifest: CorpusManifest) -> Catalog:
        validations = {
            item.validation_run_id
            for item in manifest.observations
            if not isinstance(item, PublishedNumericalObservation)
        }
        if not validations:
            return Catalog(entities=(), metrics=())
        keys = [UUID(identity) for identity in sorted(validations)]
        with connect_database(self.database) as connection, connection.transaction():
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            selection = """FROM regintel.validation_runs v
                JOIN regintel.candidate_runs c ON c.id=v.candidate_run_id
                JOIN regintel.entity_runs e ON e.id=c.entity_run_id WHERE v.id=ANY(%s)"""
            sizes = connection.execute(
                "SELECT sum(octet_length(v.input_bytes)+octet_length(e.registry_bytes)),count(*) "
                + selection,
                (keys,),
            ).fetchone()
            if (
                sizes is None
                or sizes[1] != len(keys)
                or not isinstance(sizes[0], int)
                or sizes[0] > 128_000_000
            ):
                raise ReadUnavailable("The frozen read inputs are unavailable or exceed the bound.")
            rows = connection.execute(
                "SELECT v.id,v.input_bytes,v.input_sha256,e.registry_bytes,e.registry_sha256,"
                "e.registry_revision,e.id " + selection,
                (keys,),
            ).fetchall()
        entities: dict[str, EntityRegistration] = {}
        metrics: dict[str, MetricDefinition] = {}
        for row in rows:
            source = ValidationInput.model_validate_json(body(row[1], row[2], maximum=64_000_000))
            contents = RegistryContents.model_validate_json(
                body(row[3], row[4], maximum=64_000_000)
            )
            registry = RegistrySnapshot.model_validate(
                {
                    "revision": row[5],
                    "sha256": row[4],
                    "entities": contents.entities,
                }
            )
            observations = [
                item
                for item in manifest.observations
                if not isinstance(item, PublishedNumericalObservation)
                and item.validation_run_id == str(row[0])
            ]
            if (
                source.source.entity_run.id != str(row[6])
                or source.source.entity_run.registry_sha256 != registry.sha256
                or any(item.validation_input_sha256 != row[2] for item in observations)
                or any(item.candidate_run_id != source.candidate_run.id for item in observations)
            ):
                raise ReadUnavailable("Accepted inputs differ from their immutable source.")
            needed = {
                identity
                for item in observations
                for identity in (item.subject_entity_id, item.object_entity_id)
                if identity is not None
            }
            needed_metrics = {item.metric_id for item in observations if item.metric_id is not None}
            owned_entities = {item.id: item for item in registry.entities if item.id in needed}
            owned_metrics = {
                item.id: item for item in source.source.metrics if item.id in needed_metrics
            }
            if set(owned_entities) != needed or set(owned_metrics) != needed_metrics:
                raise ReadUnavailable(
                    "A published identity or metric is absent from its frozen input."
                )
            for identity, entity in owned_entities.items():
                if identity in entities and entities[identity] != entity:
                    raise ReadUnavailable("Frozen entity labels conflict.")
                entities[identity] = entity
            for identity, metric in owned_metrics.items():
                if identity in metrics and metrics[identity] != metric:
                    raise ReadUnavailable("Frozen metric labels conflict.")
                metrics[identity] = metric
        return Catalog(
            entities=tuple(entities[key] for key in sorted(entities)),
            metrics=tuple(metrics[key] for key in sorted(metrics)),
        )

    def catalog(self, manifest: CorpusManifest) -> Catalog:
        legacy = self._legacy_catalog(manifest)
        entities = {item.id: item for item in legacy.entities}
        metrics = {item.id: item for item in legacy.metrics}
        with connect_database(self.database) as connection, connection.transaction():
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            for observation in manifest.observations:
                if not isinstance(observation, PublishedNumericalObservation):
                    continue
                row = connection.execute(
                    "SELECT snapshot_bytes,snapshot_sha256 FROM regintel.native_publication_audits "
                    "WHERE observation_id=%s",
                    (UUID(observation.id),),
                ).fetchone()
                if row is None:
                    raise ReadUnavailable("Published native acceptance audit is unavailable.")
                payload = body(row[0], row[1], maximum=32_000_000)
                accepted = NumericalAcceptanceSnapshot.model_validate_json(payload)
                if canonical_bytes(accepted) != payload or accepted.observation != observation:
                    raise ReadUnavailable(
                        "Published native observation differs from its immutable audit."
                    )
                gate = read_native_gate(connection, observation.candidate_run_id)
                if (
                    gate.result.input_sha256 != observation.validation_input_sha256
                    or gate.source_input.binding != observation.proof
                ):
                    raise ReadUnavailable("Published native source membership differs.")
                retained = gate.source_input.context.source_input
                entity = next(
                    (
                        e
                        for e in retained.registry.entities
                        if e.id == observation.subject_entity_id
                    ),
                    None,
                )
                metric = retained.metric
                if entity is None or metric is None or metric.id != observation.metric_id:
                    raise ReadUnavailable("Published native catalog membership is unavailable.")
                if (
                    entity.id in entities
                    and entities[entity.id] != entity
                    or metric.id in metrics
                    and metrics[metric.id] != metric
                ):
                    raise ReadUnavailable("Frozen native and legacy catalog labels conflict.")
                entities[entity.id] = entity
                metrics[metric.id] = metric
        return Catalog(
            entities=tuple(entities[k] for k in sorted(entities)),
            metrics=tuple(metrics[k] for k in sorted(metrics)),
        )
