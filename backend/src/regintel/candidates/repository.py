"""Audited immutable proposal storage using sealed evidence and entity decisions."""

import hashlib
from uuid import UUID

import psycopg

from regintel.auth.types import User
from regintel.candidates.models import (
    CandidateBundle,
    ExtractionConfiguration,
    ExtractionInput,
    MetricDefinition,
)
from regintel.candidates.records import CandidateRun, drafts, materialize
from regintel.db.config import DatabaseSettings
from regintel.db.migrations import DatabaseConnection, MigrationError, connect_database
from regintel.entities.models import EntityReview, EntityRun, canonical_bytes
from regintel.entities.repository import (
    EntityAuthorizationError,
    EntityNotFound,
    EntityRepository,
    EntitySourceError,
    EntityUnavailable,
)
from regintel.ingestion.models import CandidateRecord, QuantitativeContextRecord

METRIC_LOCK_ID = 5928237198818004552
UNAVAILABLE_STORAGE = (
    psycopg.OperationalError,
    psycopg.InterfaceError,
    psycopg.errors.UndefinedTable,
    psycopg.errors.UndefinedColumn,
    MigrationError,
    EntityUnavailable,
)


class CandidateConflict(ValueError):
    """An immutable identity or supplied snapshot conflicts with stored state."""


class CandidateNotFound(ValueError):
    """A requested source, metric or run does not exist."""


class CandidateSourceError(ValueError):
    """A source, proposal or stored payload fails the extraction contract."""


class CandidateAuthorizationError(ValueError):
    """The actor is no longer an active administrator."""


class CandidateUnavailable(ValueError):
    """Storage or its migration prerequisites are unavailable."""


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def checked(value: object, sha: object) -> bytes:
    if not isinstance(value, (bytes, memoryview)):
        raise CandidateSourceError("Stored extraction payload is invalid.")
    contents = bytes(value)
    if not 0 < len(contents) <= 32_000_000 or digest(contents) != sha:
        raise CandidateSourceError("Stored extraction fingerprint is invalid.")
    return contents


def authorize(connection: DatabaseConnection, user: User) -> None:
    row = connection.execute(
        "SELECT role,is_active,auth_version FROM regintel.users WHERE id=%s FOR SHARE",
        (user.id,),
    ).fetchone()
    if row != ("admin", True, user.auth_version):
        raise CandidateAuthorizationError("Proposal writes require a current administrator.")


def load_metrics(
    connection: DatabaseConnection, metric_ids: tuple[str, ...]
) -> tuple[MetricDefinition, ...]:
    if len(metric_ids) > 100 or len(set(metric_ids)) != len(metric_ids):
        raise CandidateSourceError("Metric references must be bounded and distinct.")
    result: list[MetricDefinition] = []
    for metric_id in sorted(metric_ids):
        row = connection.execute(
            "SELECT definition_bytes,definition_sha256 FROM regintel.metric_definitions "
            "WHERE id=%s",
            (UUID(metric_id),),
        ).fetchone()
        if row is None:
            raise CandidateNotFound("A requested metric definition does not exist.")
        result.append(MetricDefinition.model_validate_json(checked(row[0], row[1])))
    return tuple(result)


class CandidateRepository:
    def __init__(self, database: DatabaseSettings) -> None:
        self.database = database
        self.entities = EntityRepository(database)

    def register_metric(self, metric: MetricDefinition, user: User) -> bool:
        """Register an extraction label/cues, never a company financial observation."""
        metric = MetricDefinition.model_validate(metric.model_dump(mode="python"))
        payload = canonical_bytes(metric)
        try:
            with connect_database(self.database) as connection, connection.transaction():
                authorize(connection, user)
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (METRIC_LOCK_ID,))
                existing = connection.execute(
                    "SELECT definition_bytes,definition_sha256 "
                    "FROM regintel.metric_definitions WHERE id=%s",
                    (metric.id,),
                ).fetchone()
                if existing is not None:
                    if checked(existing[0], existing[1]) != payload:
                        raise CandidateConflict("Existing metric definition conflicts.")
                    return False
                connection.execute(
                    """INSERT INTO regintel.metric_definitions
                    (id,metric_key,definition_bytes,definition_sha256,registered_by,auth_version)
                    VALUES(%s,%s,%s,%s,%s,%s)""",
                    (metric.id, metric.key, payload, digest(payload), user.id, user.auth_version),
                )
                return True
        except psycopg.errors.UniqueViolation:
            raise CandidateConflict("An immutable metric ID or key conflicts.") from None
        except UNAVAILABLE_STORAGE:
            raise CandidateUnavailable("Proposal storage is unavailable.") from None
        except psycopg.Error:
            raise CandidateSourceError("Metric storage is invalid.") from None

    def metrics(self, metric_ids: tuple[str, ...]) -> tuple[MetricDefinition, ...]:
        try:
            with connect_database(self.database) as connection:
                return load_metrics(connection, metric_ids)
        except UNAVAILABLE_STORAGE:
            raise CandidateUnavailable("Proposal storage is unavailable.") from None
        except psycopg.Error:
            raise CandidateSourceError("Metric storage is invalid.") from None

    def _input(
        self, connection: DatabaseConnection, entity_run_id: str, metric_ids: tuple[str, ...]
    ) -> ExtractionInput:
        row = connection.execute(
            "SELECT run_bytes,run_sha256 FROM regintel.entity_runs WHERE id=%s",
            (UUID(entity_run_id),),
        ).fetchone()
        if row is None:
            raise CandidateNotFound("A sealed entity run is required.")
        run = EntityRun.model_validate_json(checked(row[0], row[1]))
        rows = connection.execute(
            "SELECT review_bytes,review_sha256 FROM regintel.entity_reviews "
            "WHERE run_id=%s ORDER BY mention_id,id",
            (run.id,),
        ).fetchall()
        reviews = tuple(EntityReview.model_validate_json(checked(r[0], r[1])) for r in rows)
        evidence, artifact_sha = self.entities.evidence_for_parse(run.parse_version_id)
        if artifact_sha != run.artifact_sha256:
            raise CandidateSourceError("Entity run artifact differs from its sealed source.")
        return ExtractionInput(
            parse_version_id=run.parse_version_id,
            entity_run=run,
            reviews=reviews,
            evidence=evidence,
            metrics=load_metrics(connection, metric_ids),
        )

    def input_for_run(self, entity_run_id: str, metric_ids: tuple[str, ...]) -> ExtractionInput:
        try:
            with connect_database(self.database) as connection, connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                return self._input(connection, entity_run_id, metric_ids)
        except UNAVAILABLE_STORAGE:
            raise CandidateUnavailable("Proposal storage is unavailable.") from None
        except EntityNotFound:
            raise CandidateNotFound("Sealed parsed evidence is unavailable.") from None
        except (psycopg.Error, EntitySourceError):
            raise CandidateSourceError("Extraction input storage is invalid.") from None

    def extract(self, entity_run_id: str, metric_ids: tuple[str, ...], user: User) -> CandidateRun:
        """One atomic rule-baseline run; no model/provider or acceptance side effects."""
        from regintel.candidates.extraction import current_configuration, extract

        try:
            with connect_database(self.database) as connection, connection.transaction():
                authorize(connection, user)
                # Freeze reviewed mention decisions until this proposal snapshot is sealed.
                # A later review produces a different input hash and a separate run.
                connection.execute("LOCK TABLE regintel.entity_reviews IN SHARE MODE")
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (METRIC_LOCK_ID,))
                source = self._input(connection, entity_run_id, metric_ids)
                configuration = current_configuration()
                bundle = extract(source)
                run = materialize(source, configuration, bundle)
                existing = connection.execute(
                    "SELECT input_sha256,configuration_sha256,bundle_bytes,bundle_sha256 "
                    "FROM regintel.candidate_runs WHERE id=%s",
                    (run.id,),
                ).fetchone()
                if existing is not None:
                    if existing[:2] != (source.sha256, configuration.sha256) or checked(
                        existing[2], existing[3]
                    ) != canonical_bytes(bundle):
                        raise CandidateConflict("Existing extraction run conflicts.")
                    return self._get_run(connection, run.id)
                source_bytes = canonical_bytes(source)
                config_bytes = canonical_bytes(configuration)
                bundle_bytes = canonical_bytes(bundle)
                connection.execute(
                    """INSERT INTO regintel.candidate_runs
                    (id,entity_run_id,parse_version_id,input_bytes,input_sha256,
                     configuration_bytes,configuration_sha256,bundle_bytes,bundle_sha256,
                     candidate_count,submitted_by,auth_version)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        run.id,
                        run.entity_run_id,
                        run.parse_version_id,
                        source_bytes,
                        source.sha256,
                        config_bytes,
                        configuration.sha256,
                        bundle_bytes,
                        digest(bundle_bytes),
                        len(run.candidates),
                        user.id,
                        user.auth_version,
                    ),
                )
                for context in run.quantities:
                    self._quantity(connection, context)
                for record, draft in zip(run.candidates, drafts(bundle), strict=True):
                    self._candidate(connection, record)
                    connection.execute(
                        """INSERT INTO regintel.candidate_run_items
                        (run_id,candidate_id,parse_version_id,draft_bytes) VALUES(%s,%s,%s,%s)""",
                        (run.id, record.id, run.parse_version_id, canonical_bytes(draft)),
                    )
                return run
        except psycopg.errors.UniqueViolation:
            raise CandidateConflict("An immutable extraction identity conflicts.") from None
        except UNAVAILABLE_STORAGE:
            raise CandidateUnavailable("Proposal storage is unavailable.") from None
        except EntityNotFound:
            raise CandidateNotFound("Sealed parsed evidence is unavailable.") from None
        except EntityAuthorizationError:
            raise CandidateAuthorizationError("Proposal approval is unavailable.") from None
        except (psycopg.Error, EntitySourceError):
            raise CandidateSourceError("Extraction source or storage is invalid.") from None

    @staticmethod
    def _quantity(connection: DatabaseConnection, item: QuantitativeContextRecord) -> None:
        q = item.quantity
        connection.execute(
            """INSERT INTO regintel.quantitative_contexts
            (id,parse_version_id,raw_value,normalized_value,raw_unit,normalized_unit,
             raw_currency,currency,period_kind,start_date,end_date,instant_date,raw_period_label,
             basis,raw_basis_label,denominator,stake_kind,ownership_date,evidence_count)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                item.id,
                item.parse_version_id,
                q.raw_value,
                q.normalized_value,
                q.raw_unit,
                q.normalized_unit,
                q.raw_currency,
                q.currency,
                q.period.kind,
                q.period.start_date,
                q.period.end_date,
                q.period.instant_date,
                q.period.raw_label,
                q.basis,
                q.raw_basis_label,
                q.denominator,
                q.stake_kind,
                q.ownership_date,
                len(q.evidence_ids),
            ),
        )
        for evidence_id in q.evidence_ids:
            connection.execute(
                "INSERT INTO regintel.quantitative_context_evidence"
                "(context_id,parse_version_id,evidence_id) VALUES(%s,%s,%s)",
                (item.id, item.parse_version_id, evidence_id),
            )

    @staticmethod
    def _candidate(connection: DatabaseConnection, item: CandidateRecord) -> None:
        connection.execute(
            """INSERT INTO regintel.candidates
            (id,parse_version_id,kind,state,subject_entity_id,object_entity_id,metric_id,
             relation_type,raw_text,quantitative_context_id,evidence_count)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                item.id,
                item.parse_version_id,
                item.kind,
                item.state,
                item.subject_entity_id,
                item.object_entity_id,
                item.metric_id,
                item.relation_type,
                item.raw_text,
                item.quantitative_context_id,
                len(item.evidence_ids),
            ),
        )
        for evidence_id in item.evidence_ids:
            connection.execute(
                "INSERT INTO regintel.candidate_evidence"
                "(candidate_id,parse_version_id,evidence_id) "
                "VALUES(%s,%s,%s)",
                (item.id, item.parse_version_id, evidence_id),
            )

    @staticmethod
    def _get_run(connection: DatabaseConnection, run_id: str) -> CandidateRun:
        from regintel.candidates.extraction import validate_bundle

        row = connection.execute(
            """SELECT input_bytes,input_sha256,configuration_bytes,configuration_sha256,
            bundle_bytes,bundle_sha256,candidate_count FROM regintel.candidate_runs WHERE id=%s""",
            (UUID(run_id),),
        ).fetchone()
        if row is None:
            raise CandidateNotFound("Extraction run does not exist.")
        source = ExtractionInput.model_validate_json(checked(row[0], row[1]))
        configuration = ExtractionConfiguration.model_validate_json(checked(row[2], row[3]))
        bundle = CandidateBundle.model_validate_json(checked(row[4], row[5]))
        validate_bundle(source, bundle)
        if not isinstance(row[1], str):
            raise CandidateSourceError("Extraction input fingerprint is invalid.")
        expected = materialize(source, configuration, bundle, input_sha256=row[1])
        members = connection.execute(
            "SELECT candidate_id,draft_bytes FROM regintel.candidate_run_items WHERE run_id=%s",
            (UUID(run_id),),
        ).fetchall()
        expected_members = {
            UUID(record.id): canonical_bytes(draft)
            for record, draft in zip(expected.candidates, drafts(bundle), strict=True)
        }
        actual = {
            member[0]: bytes(member[1])
            for member in members
            if isinstance(member[1], (bytes, memoryview))
        }
        if (
            expected.id != run_id
            or row[6] != len(expected.candidates)
            or actual != expected_members
        ):
            raise CandidateSourceError("Extraction members differ from their sealed input.")
        return expected

    def get_run(self, run_id: str) -> CandidateRun | None:
        try:
            with connect_database(self.database) as connection:
                return self._get_run(connection, run_id)
        except CandidateNotFound:
            return None
        except UNAVAILABLE_STORAGE:
            raise CandidateUnavailable("Proposal storage is unavailable.") from None
        except psycopg.Error:
            raise CandidateSourceError("Extraction storage is invalid.") from None
