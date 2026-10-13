"""Append-only audited entity registry and exact-source resolver storage."""

import hashlib
import json
from uuid import UUID

import psycopg
from pydantic import ValidationError

from regintel.auth.types import User
from regintel.contracts.models import TextEvidence
from regintel.db.config import DatabaseSettings
from regintel.db.migrations import DatabaseConnection, MigrationError, connect_database
from regintel.entities.models import (
    EntityRegistration,
    EntityReview,
    EntityRun,
    RegistrySnapshot,
    canonical_bytes,
)
from regintel.evidence.projection import MAX_ARTIFACT_BYTES, project_parse
from regintel.parsing.configuration import ParserRuntimeConfiguration
from regintel.parsing.models import ParseArtifact

REGISTRY_LOCK_ID = 5928237198818004551


class EntityConflict(ValueError):
    """An immutable identity or its previously stored payload conflicts."""


class EntityNotFound(ValueError):
    """A selected immutable source/run/mention is unavailable."""


class EntitySourceError(ValueError):
    """Source membership, storage or exact supporting text is invalid."""


class EntityRegistryChanged(ValueError):
    """The supplied run does not use the current registry snapshot."""


class EntityAuthorizationError(ValueError):
    """The actor is not a current active administrator."""


class EntityUnavailable(ValueError):
    """Database connectivity or migration prerequisites are unavailable."""


def _binary(value: object, maximum: int = MAX_ARTIFACT_BYTES) -> bytes:
    if not isinstance(value, (bytes, memoryview)):
        raise EntitySourceError("Entity storage is invalid.")
    result = bytes(value)
    if not 0 < len(result) <= maximum:
        raise EntitySourceError("Entity storage is invalid.")
    return result


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _checked(value: object, expected: object) -> bytes:
    contents = _binary(value)
    if _digest(contents) != expected:
        raise EntitySourceError("Entity storage fingerprint is invalid.")
    return contents


def _authorize(connection: DatabaseConnection, user: User) -> None:
    row = connection.execute(
        "SELECT role,is_active,auth_version FROM regintel.users WHERE id=%s FOR SHARE",
        (user.id,),
    ).fetchone()
    if row != ("admin", True, user.auth_version):
        raise EntityAuthorizationError("Entity writes require a current administrator.")


def _registry_bytes(entities: tuple[EntityRegistration, ...]) -> bytes:
    return json.dumps(
        {"entities": [entity.model_dump(mode="json") for entity in entities]},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _snapshot(connection: DatabaseConnection) -> RegistrySnapshot:
    rows = connection.execute(
        "SELECT registration_bytes,registration_sha256 "
        "FROM regintel.entity_registrations ORDER BY id"
    ).fetchall()
    entities = tuple(
        EntityRegistration.model_validate_json(_checked(row[0], row[1])) for row in rows
    )
    return RegistrySnapshot(
        revision=len(entities), sha256=_digest(_registry_bytes(entities)), entities=entities
    )


def _run(connection: DatabaseConnection, run_id: str) -> EntityRun | None:
    row = connection.execute(
        "SELECT run_bytes,run_sha256 FROM regintel.entity_runs WHERE id=%s", (UUID(run_id),)
    ).fetchone()
    return EntityRun.model_validate_json(_checked(row[0], row[1])) if row is not None else None


class EntityRepository:
    def __init__(self, database: DatabaseSettings) -> None:
        self.database = database

    def register(self, registration: EntityRegistration, user: User) -> bool:
        """Atomically register one reviewed identity; identical replay is a no-op."""
        registration = EntityRegistration.model_validate(registration.model_dump(mode="python"))
        payload = canonical_bytes(registration)
        try:
            with connect_database(self.database) as connection, connection.transaction():
                _authorize(connection, user)
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (REGISTRY_LOCK_ID,))
                existing = connection.execute(
                    "SELECT registration_bytes,registration_sha256 "
                    "FROM regintel.entity_registrations WHERE id=%s",
                    (registration.id,),
                ).fetchone()
                if existing is not None:
                    if _checked(existing[0], existing[1]) != payload:
                        raise EntityConflict("Existing entity registration conflicts.")
                    return False
                connection.execute(
                    """INSERT INTO regintel.entity_registrations
                    (id,registration_bytes,registration_sha256,registered_by,auth_version)
                    VALUES(%s,%s,%s,%s,%s)""",
                    (registration.id, payload, _digest(payload), user.id, user.auth_version),
                )
                for item in registration.identifiers:
                    connection.execute(
                        "INSERT INTO regintel.entity_identifiers(entity_id,kind,value) "
                        "VALUES(%s,%s,%s)",
                        (registration.id, item.kind, item.value),
                    )
                return True
        except psycopg.errors.UniqueViolation:
            raise EntityConflict("An entity identifier is already registered.") from None
        except (psycopg.OperationalError, psycopg.InterfaceError, MigrationError):
            raise EntityUnavailable("Entity storage is unavailable.") from None
        except (psycopg.Error, ValidationError):
            raise EntitySourceError("Entity registration source or storage is invalid.") from None

    def snapshot(self) -> RegistrySnapshot:
        try:
            with connect_database(self.database) as connection:
                return _snapshot(connection)
        except (psycopg.OperationalError, psycopg.InterfaceError, MigrationError):
            raise EntityUnavailable("Entity storage is unavailable.") from None
        except (psycopg.Error, ValidationError):
            raise EntitySourceError("Entity registry storage is unavailable.") from None

    def evidence_for_parse(self, parse_id: str) -> tuple[tuple[TextEvidence, ...], str]:
        """Verify the sealed sidecar once and return only exact text projection."""
        try:
            with connect_database(self.database) as connection:
                row = connection.execute(
                    """SELECT a.artifact_bytes,a.configuration_bytes,p.artifact_sha256,
                    p.configuration_sha256 FROM regintel.parse_versions p
                    JOIN regintel.parse_artifacts a ON a.parse_version_id=p.id
                    JOIN regintel.filing_jobs j ON j.id=a.job_id AND j.state='PARSED'
                        AND j.parse_version_id=p.id WHERE p.id=%s""",
                    (UUID(parse_id),),
                ).fetchone()
                if row is None:
                    raise EntityNotFound("A sealed parsed filing is required.")
                artifact = ParseArtifact.model_validate_json(_checked(row[0], row[2]))
                configuration = ParserRuntimeConfiguration.model_validate_json(
                    _checked(row[1], row[3])
                )
                if artifact.id != parse_id:
                    raise EntitySourceError("Parse source identity is invalid.")
                projection = project_parse(artifact, configuration)
                actual = connection.execute(
                    "SELECT id,block_id,start_offset,end_offset,quote,page_id "
                    "FROM regintel.evidence WHERE parse_version_id=%s AND kind='text'",
                    (UUID(parse_id),),
                ).fetchall()
                expected = {
                    (
                        UUID(item.id),
                        UUID(item.span.block_id),
                        item.span.start,
                        item.span.end,
                        item.span.quote,
                        UUID(item.source.page_id),
                    )
                    for item in projection.evidence
                }
                if set(actual) != expected:
                    raise EntitySourceError("Exact evidence differs from the sealed artifact.")
            # Projection order is source page/block/span order, rather than database row order.
            return projection.evidence, projection.version.artifact_sha256
        except EntityNotFound:
            raise
        except (psycopg.OperationalError, psycopg.InterfaceError, MigrationError):
            raise EntityUnavailable("Entity storage is unavailable.") from None
        except (psycopg.Error, ValueError):
            raise EntitySourceError("Exact parse source or storage is invalid.") from None

    def save_run(self, run: EntityRun, user: User) -> EntityRun:
        """Seal all mentions atomically and return the original result on replay."""
        run = EntityRun.model_validate(run.model_dump(mode="python"))
        payload = canonical_bytes(run)
        try:
            with connect_database(self.database) as connection, connection.transaction():
                _authorize(connection, user)
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (REGISTRY_LOCK_ID,))
                snapshot = _snapshot(connection)
                if (snapshot.revision, snapshot.sha256) != (
                    run.registry_revision,
                    run.registry_sha256,
                ):
                    raise EntityRegistryChanged("Entity registry changed; resolve again.")
                existing = connection.execute(
                    """SELECT run_bytes,run_sha256 FROM regintel.entity_runs
                    WHERE parse_version_id=%s AND registry_revision=%s AND registry_sha256=%s
                        AND configuration_sha256=%s""",
                    (
                        run.parse_version_id,
                        run.registry_revision,
                        run.registry_sha256,
                        run.configuration.sha256,
                    ),
                ).fetchone()
                if existing is not None:
                    stored = EntityRun.model_validate_json(_checked(existing[0], existing[1]))
                    if canonical_bytes(stored) != payload:
                        raise EntityConflict("Existing entity run conflicts.")
                    return stored
                # Recompute from the complete authoritative source and frozen registry.
                # Caller-authored RESOLVED outcomes or omitted evidence are never trusted.
                from regintel.entities.resolution import EntityResolver

                evidence, artifact_sha256 = self.evidence_for_parse(run.parse_version_id)
                try:
                    expected = EntityResolver(snapshot, run.configuration).run(
                        evidence, artifact_sha256
                    )
                except ValueError:
                    raise EntitySourceError("Entity run configuration is invalid.") from None
                if canonical_bytes(expected) != payload:
                    raise EntitySourceError(
                        "Entity run differs from deterministic source resolution."
                    )
                connection.execute(
                    """INSERT INTO regintel.entity_runs
                    (id,parse_version_id,artifact_sha256,registry_revision,registry_sha256,
                     configuration_sha256,configuration_bytes,registry_bytes,run_bytes,run_sha256,
                     mention_count,submitted_by,auth_version)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        run.id,
                        run.parse_version_id,
                        run.artifact_sha256,
                        run.registry_revision,
                        run.registry_sha256,
                        run.configuration.sha256,
                        canonical_bytes(run.configuration),
                        _registry_bytes(snapshot.entities),
                        payload,
                        _digest(payload),
                        len(run.mentions),
                        user.id,
                        user.auth_version,
                    ),
                )
                for mention in run.mentions:
                    support = mention.support
                    connection.execute(
                        """INSERT INTO regintel.entity_mentions
                        (id,run_id,parse_version_id,evidence_id,start_offset,end_offset,quote,
                         kind,mention_bytes) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            mention.id,
                            run.id,
                            run.parse_version_id,
                            support.evidence_id,
                            support.start,
                            support.end,
                            support.quote,
                            mention.kind,
                            canonical_bytes(mention),
                        ),
                    )
                return run
        except psycopg.errors.UniqueViolation:
            raise EntityConflict("An immutable entity run identity conflicts.") from None
        except (psycopg.OperationalError, psycopg.InterfaceError, MigrationError):
            raise EntityUnavailable("Entity storage is unavailable.") from None
        except (psycopg.Error, ValidationError):
            raise EntitySourceError("Entity run source or storage is invalid.") from None

    def get_run(self, run_id: str) -> EntityRun | None:
        try:
            with connect_database(self.database) as connection:
                return _run(connection, run_id)
        except (psycopg.OperationalError, psycopg.InterfaceError, MigrationError):
            raise EntityUnavailable("Entity storage is unavailable.") from None
        except (psycopg.Error, ValidationError):
            raise EntitySourceError("Entity run storage is unavailable.") from None

    def review(self, decision: EntityReview, user: User) -> bool:
        """Store one final audited decision without mutating the original mention."""
        decision = EntityReview.model_validate(decision.model_dump(mode="python"))
        payload = canonical_bytes(decision)
        try:
            with connect_database(self.database) as connection, connection.transaction():
                _authorize(connection, user)
                # Serialize decisions for the same immutable mention; no registry mutation.
                lock_id = int.from_bytes(
                    hashlib.sha256(decision.mention_id.encode()).digest()[:8], "big", signed=True
                )
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (lock_id,))
                run = _run(connection, decision.run_id)
                if run is None:
                    raise EntityNotFound("Entity run does not exist.")
                mention = next((x for x in run.mentions if x.id == decision.mention_id), None)
                if mention is None:
                    raise EntityNotFound("Entity mention does not exist in this run.")
                if decision.decision == "RESOLVE" and decision.entity_id not in {
                    proposal.entity_id for proposal in mention.resolution.proposals
                }:
                    raise EntityConflict("Reviewed identity must be an existing run proposal.")
                existing = connection.execute(
                    "SELECT review_bytes,review_sha256 FROM regintel.entity_reviews "
                    "WHERE run_id=%s AND mention_id=%s",
                    (decision.run_id, decision.mention_id),
                ).fetchone()
                if existing is not None:
                    stored = EntityReview.model_validate_json(_checked(existing[0], existing[1]))
                    if canonical_bytes(stored) != payload:
                        raise EntityConflict("Existing entity review conflicts.")
                    return False
                connection.execute(
                    """INSERT INTO regintel.entity_reviews
                    (id,run_id,mention_id,decision,entity_id,review_bytes,review_sha256,
                     reviewed_by,auth_version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        decision.id,
                        decision.run_id,
                        decision.mention_id,
                        decision.decision,
                        decision.entity_id,
                        payload,
                        _digest(payload),
                        user.id,
                        user.auth_version,
                    ),
                )
                return True
        except psycopg.errors.UniqueViolation:
            raise EntityConflict("An immutable entity review identity conflicts.") from None
        except (psycopg.OperationalError, psycopg.InterfaceError, MigrationError):
            raise EntityUnavailable("Entity storage is unavailable.") from None
        except (psycopg.Error, ValidationError):
            raise EntitySourceError("Entity review source or storage is invalid.") from None

    def reviews(self, run_id: str) -> tuple[EntityReview, ...]:
        try:
            with connect_database(self.database) as connection:
                rows = connection.execute(
                    "SELECT review_bytes,review_sha256 FROM regintel.entity_reviews "
                    "WHERE run_id=%s ORDER BY mention_id,id",
                    (UUID(run_id),),
                ).fetchall()
            return tuple(EntityReview.model_validate_json(_checked(row[0], row[1])) for row in rows)
        except (psycopg.OperationalError, psycopg.InterfaceError, MigrationError):
            raise EntityUnavailable("Entity storage is unavailable.") from None
        except (psycopg.Error, ValidationError):
            raise EntitySourceError("Entity review storage is unavailable.") from None
