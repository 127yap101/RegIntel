"""Immutable mandatory-gate audits and staged reviews, without publication."""

import hashlib
from uuid import UUID

import psycopg

from regintel.auth.types import User
from regintel.candidates.models import ExtractionInput, _exact_span
from regintel.candidates.records import drafts
from regintel.candidates.repository import (
    CandidateNotFound,
    CandidateRepository,
    CandidateSourceError,
    CandidateUnavailable,
)
from regintel.candidates.repository import (
    checked as candidate_checked,
)
from regintel.db.config import DatabaseSettings
from regintel.db.migrations import DatabaseConnection, MigrationError, connect_database
from regintel.entities.models import EntityReview, canonical_bytes
from regintel.parsing.models import ParseArtifact
from regintel.validation.models import (
    NumericMetricPolicy,
    ReviewDecision,
    ValidationConfiguration,
    ValidationInput,
    ValidationRun,
)

POLICY_LOCK_ID = 5928237198818004553
UNAVAILABLE_STORAGE = (
    psycopg.OperationalError,
    psycopg.InterfaceError,
    psycopg.errors.UndefinedTable,
    psycopg.errors.UndefinedColumn,
    MigrationError,
    CandidateUnavailable,
)


class ValidationConflict(ValueError):
    """An immutable identity, decision or current validation snapshot conflicts."""


class ValidationNotFound(ValueError):
    """The requested owned source, candidate or validation run is unavailable."""


class ValidationSourceError(ValueError):
    """The source, gate audit or review support violates its contract."""


class ValidationAuthorizationError(ValueError):
    """A current administrator is required for this stage."""


class ValidationUnavailable(ValueError):
    """Storage or migration prerequisites are unavailable."""


def authorize(connection: DatabaseConnection, user: User) -> None:
    row = connection.execute(
        "SELECT role,is_active,auth_version FROM regintel.users WHERE id=%s FOR SHARE",
        (user.id,),
    ).fetchone()
    if row != ("admin", True, user.auth_version):
        raise ValidationAuthorizationError("Validation writes require a current administrator.")


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def checked(value: object, expected: object, *, maximum: int = 64_000_000) -> bytes:
    """Match the validation input SQL limit; candidate payloads keep their limit."""
    if not isinstance(value, (bytes, memoryview)):
        raise ValidationSourceError("Validation payload storage is invalid.")
    payload = bytes(value)
    if not 0 < len(payload) <= maximum or _digest(payload) != expected:
        raise ValidationSourceError("Validation payload fingerprint is invalid.")
    return payload


class ValidationRepository:
    def __init__(self, database: DatabaseSettings) -> None:
        self.database = database
        self.candidates = CandidateRepository(database)

    def register_policy(self, policy: NumericMetricPolicy, user: User) -> bool:
        policy = NumericMetricPolicy.model_validate(policy.model_dump(mode="python"))
        payload = canonical_bytes(policy)
        try:
            with connect_database(self.database) as connection, connection.transaction():
                authorize(connection, user)
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (POLICY_LOCK_ID,))
                existing = connection.execute(
                    "SELECT policy_bytes,policy_sha256 FROM regintel.numeric_metric_policies "
                    "WHERE id=%s",
                    (policy.id,),
                ).fetchone()
                if existing is not None:
                    if checked(existing[0], existing[1]) != payload:
                        raise ValidationConflict("Existing immutable metric policy conflicts.")
                    return False
                connection.execute(
                    """INSERT INTO regintel.numeric_metric_policies
                    (id,metric_id,policy_bytes,policy_sha256,registered_by,auth_version)
                    VALUES(%s,%s,%s,%s,%s,%s)""",
                    (
                        policy.id,
                        policy.metric_id,
                        payload,
                        _digest(payload),
                        user.id,
                        user.auth_version,
                    ),
                )
                return True
        except psycopg.errors.UniqueViolation:
            raise ValidationConflict(
                "An immutable policy ID or metric binding conflicts."
            ) from None
        except UNAVAILABLE_STORAGE:
            raise ValidationUnavailable("Validation storage is unavailable.") from None
        except (psycopg.Error, CandidateSourceError):
            raise ValidationSourceError("Metric policy source or storage is invalid.") from None

    def _input(self, connection: DatabaseConnection, candidate_run_id: str) -> ValidationInput:
        from regintel.validation.scope import table_evidence_ids, transcription_evidence_ids

        run = self.candidates._get_run(connection, candidate_run_id)
        row = connection.execute(
            "SELECT input_bytes,input_sha256 FROM regintel.candidate_runs WHERE id=%s",
            (UUID(candidate_run_id),),
        ).fetchone()
        if row is None or not isinstance(row[1], str):
            raise ValidationNotFound("A sealed candidate run is required.")
        source = ExtractionInput.model_validate_json(candidate_checked(row[0], row[1]))
        reviews = connection.execute(
            "SELECT review_bytes,review_sha256 FROM regintel.entity_reviews "
            "WHERE run_id=%s ORDER BY mention_id,id",
            (run.entity_run_id,),
        ).fetchall()
        policies = connection.execute(
            "SELECT policy_bytes,policy_sha256 FROM regintel.numeric_metric_policies "
            "WHERE metric_id=ANY(%s::uuid[]) ORDER BY id",
            ([metric.id for metric in source.metrics if metric.kind == "numeric_fact"],),
        ).fetchall()
        artifact_row = connection.execute(
            "SELECT a.artifact_bytes,p.artifact_sha256 FROM regintel.parse_artifacts a "
            "JOIN regintel.parse_versions p ON p.id=a.parse_version_id WHERE p.id=%s",
            (run.parse_version_id,),
        ).fetchone()
        if artifact_row is None:
            raise ValidationSourceError("The candidate source artifact is unavailable.")
        from regintel.evidence.projection import MAX_ARTIFACT_BYTES

        artifact = ParseArtifact.model_validate_json(
            checked(artifact_row[0], artifact_row[1], maximum=MAX_ARTIFACT_BYTES)
        )
        return ValidationInput(
            candidate_run=run,
            source=source,
            source_input_sha256=row[1],
            entity_reviews=tuple(
                EntityReview.model_validate_json(checked(r[0], r[1])) for r in reviews
            ),
            policies=tuple(
                NumericMetricPolicy.model_validate_json(checked(r[0], r[1])) for r in policies
            ),
            table_evidence_ids=table_evidence_ids(artifact, source.evidence),
            transcription_evidence_ids=transcription_evidence_ids(artifact, source.evidence),
        )

    def input_for_run(self, candidate_run_id: str) -> ValidationInput:
        try:
            with connect_database(self.database) as connection, connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                return self._input(connection, candidate_run_id)
        except UNAVAILABLE_STORAGE:
            raise ValidationUnavailable("Validation storage is unavailable.") from None
        except CandidateNotFound:
            raise ValidationNotFound("An owned sealed candidate run is required.") from None
        except (psycopg.Error, CandidateSourceError):
            raise ValidationSourceError("Validation source storage is invalid.") from None

    @staticmethod
    def _snapshot_lock(connection: DatabaseConnection) -> None:
        connection.execute("LOCK TABLE regintel.entity_reviews IN SHARE MODE")
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (POLICY_LOCK_ID,))

    def validate(self, candidate_run_id: str, user: User) -> ValidationRun:
        from regintel.validation.gate import validate

        try:
            with connect_database(self.database) as connection, connection.transaction():
                authorize(connection, user)
                self._snapshot_lock(connection)
                source = self._input(connection, candidate_run_id)
                run = validate(source)
                existing = connection.execute(
                    "SELECT run_bytes,run_sha256 FROM regintel.validation_runs WHERE id=%s",
                    (run.id,),
                ).fetchone()
                if existing is not None:
                    stored = self._get_run(connection, run.id)
                    if stored != run:
                        raise ValidationConflict("An immutable validation run conflicts.")
                    return stored
                source_bytes = canonical_bytes(source)
                config_bytes = canonical_bytes(run.configuration)
                run_bytes = canonical_bytes(run)
                if len(source_bytes) > 64_000_000 or len(run_bytes) > 32_000_000:
                    raise ValidationSourceError("Validation payload exceeds its storage bound.")
                connection.execute(
                    """INSERT INTO regintel.validation_runs
                    (id,candidate_run_id,parse_version_id,input_bytes,input_sha256,
                     configuration_bytes,configuration_sha256,run_bytes,run_sha256,
                     result_count,submitted_by,auth_version)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        run.id,
                        run.candidate_run_id,
                        run.parse_version_id,
                        source_bytes,
                        run.input_sha256,
                        config_bytes,
                        run.configuration.sha256,
                        run_bytes,
                        _digest(run_bytes),
                        len(run.results),
                        user.id,
                        user.auth_version,
                    ),
                )
                return run
        except psycopg.errors.UniqueViolation:
            raise ValidationConflict("An immutable validation identity conflicts.") from None
        except UNAVAILABLE_STORAGE:
            raise ValidationUnavailable("Validation storage is unavailable.") from None
        except CandidateNotFound:
            raise ValidationNotFound("An owned sealed candidate run is required.") from None
        except (psycopg.Error, CandidateSourceError):
            raise ValidationSourceError("Validation source or storage is invalid.") from None

    def _get_run(self, connection: DatabaseConnection, run_id: str) -> ValidationRun:
        from regintel.validation.gate import current_configuration, validate

        row = connection.execute(
            """SELECT input_bytes,input_sha256,configuration_bytes,configuration_sha256,
            run_bytes,run_sha256,result_count FROM regintel.validation_runs WHERE id=%s""",
            (UUID(run_id),),
        ).fetchone()
        if row is None:
            raise ValidationNotFound("Validation run does not exist.")
        source = ValidationInput.model_validate_json(checked(row[0], row[1]))
        config = ValidationConfiguration.model_validate_json(checked(row[2], row[3]))
        run = ValidationRun.model_validate_json(checked(row[4], row[5]))
        if (
            run.id != run_id
            or run.input_sha256 != row[1]
            or run.configuration != config
            or run.configuration.sha256 != row[3]
            or len(run.results) != row[6]
            or run.candidate_run_id != source.candidate_run.id
            or run.parse_version_id != source.candidate_run.parse_version_id
            or {result.candidate_id for result in run.results}
            != {item.id for item in source.candidate_run.candidates}
        ):
            raise ValidationSourceError("Stored validation does not match its complete source.")
        # Historical audits stay readable after code updates. Current-code rows
        # are recomputed to prevent caller-authored PASS decisions entering APIs.
        if config == current_configuration():
            from regintel.evidence.projection import MAX_ARTIFACT_BYTES
            from regintel.validation.scope import table_evidence_ids, transcription_evidence_ids

            actual_candidate = self.candidates._get_run(connection, run.candidate_run_id)
            artifact_row = connection.execute(
                "SELECT a.artifact_bytes,p.artifact_sha256 FROM regintel.parse_artifacts a "
                "JOIN regintel.parse_versions p ON p.id=a.parse_version_id WHERE p.id=%s",
                (run.parse_version_id,),
            ).fetchone()
            if artifact_row is None:
                raise ValidationSourceError("Validation source artifact is unavailable.")
            artifact = ParseArtifact.model_validate_json(
                checked(artifact_row[0], artifact_row[1], maximum=MAX_ARTIFACT_BYTES)
            )
            if (
                actual_candidate != source.candidate_run
                or table_evidence_ids(artifact, source.source.evidence) != source.table_evidence_ids
                or transcription_evidence_ids(artifact, source.source.evidence)
                != source.transcription_evidence_ids
            ):
                raise ValidationSourceError("Validation scope differs from its sealed source.")
            if not isinstance(row[1], str) or validate(source, input_sha256=row[1]) != run:
                raise ValidationSourceError("Stored validation differs from deterministic gates.")
        return run

    def get_run(self, run_id: str) -> ValidationRun | None:
        try:
            with connect_database(self.database) as connection:
                return self._get_run(connection, run_id)
        except ValidationNotFound:
            return None
        except UNAVAILABLE_STORAGE:
            raise ValidationUnavailable("Validation storage is unavailable.") from None
        except (psycopg.Error, CandidateSourceError):
            raise ValidationSourceError("Validation storage is invalid.") from None

    def review(self, decision: ReviewDecision, user: User) -> bool:
        """Stage one final supported decision; never write observations or a corpus."""
        from regintel.validation.gate import current_configuration, validate

        decision = ReviewDecision.model_validate(decision.model_dump(mode="python"))
        payload = canonical_bytes(decision)
        try:
            with connect_database(self.database) as connection, connection.transaction():
                authorize(connection, user)
                self._snapshot_lock(connection)
                existing = connection.execute(
                    "SELECT review_bytes,review_sha256 FROM regintel.validation_reviews "
                    "WHERE candidate_id=%s",
                    (decision.candidate_id,),
                ).fetchone()
                if existing is not None:
                    if checked(existing[0], existing[1]) != payload:
                        raise ValidationConflict("The candidate already has a final review.")
                    return False
                run = self._get_run(connection, decision.validation_run_id)
                source_row = connection.execute(
                    "SELECT input_bytes,input_sha256 FROM regintel.validation_runs WHERE id=%s",
                    (run.id,),
                ).fetchone()
                if source_row is None:
                    raise ValidationSourceError("Validation source is unavailable.")
                source = ValidationInput.model_validate_json(checked(source_row[0], source_row[1]))
                members = tuple(
                    zip(
                        source.candidate_run.candidates,
                        drafts(source.candidate_run.bundle),
                        strict=True,
                    )
                )
                selected = next(
                    (draft for record, draft in members if record.id == decision.candidate_id), None
                )
                if selected is None:
                    raise ValidationNotFound("A selected owned candidate is required.")
                records = {record.id: record for record in source.source.evidence}
                primary = selected.supports[0]
                if (
                    any(
                        span.evidence_id not in records
                        or not _exact_span(span, records[span.evidence_id])
                        or span.evidence_id != primary.evidence_id
                        or span.start < primary.start
                        or span.end > primary.end
                        for span in decision.supports
                    )
                    or primary not in decision.supports
                ):
                    raise ValidationSourceError(
                        "Review requires the complete exact source statement."
                    )
                if decision.decision == "APPROVE_FOR_PUBLICATION":
                    current = self._input(connection, run.candidate_run_id)
                    if (
                        run.configuration != current_configuration()
                        or current.sha256 != run.input_sha256
                    ):
                        raise ValidationConflict(
                            "Validation configuration or source decisions changed."
                        )
                    actual = validate(current)
                    result = next(
                        item
                        for item in actual.results
                        if item.candidate_id == decision.candidate_id
                    )
                    if actual != run or not result.reviewer_eligible:
                        raise ValidationConflict("Mandatory checks cannot be reviewer-overridden.")
                connection.execute(
                    """INSERT INTO regintel.validation_reviews
                    (id,validation_run_id,candidate_id,decision,review_bytes,review_sha256,
                     reviewed_by,auth_version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        decision.id,
                        run.id,
                        decision.candidate_id,
                        decision.decision,
                        payload,
                        _digest(payload),
                        user.id,
                        user.auth_version,
                    ),
                )
                return True
        except psycopg.errors.UniqueViolation:
            raise ValidationConflict("An immutable review identity conflicts.") from None
        except UNAVAILABLE_STORAGE:
            raise ValidationUnavailable("Validation storage is unavailable.") from None
        except CandidateNotFound:
            raise ValidationNotFound("An owned sealed candidate run is required.") from None
        except (psycopg.Error, CandidateSourceError):
            raise ValidationSourceError("Review source or storage is invalid.") from None

    def reviews(self, run_id: str) -> tuple[ReviewDecision, ...]:
        try:
            with connect_database(self.database) as connection:
                rows = connection.execute(
                    "SELECT review_bytes,review_sha256 FROM regintel.validation_reviews "
                    "WHERE validation_run_id=%s ORDER BY candidate_id,id",
                    (UUID(run_id),),
                ).fetchall()
            return tuple(ReviewDecision.model_validate_json(checked(r[0], r[1])) for r in rows)
        except UNAVAILABLE_STORAGE:
            raise ValidationUnavailable("Validation storage is unavailable.") from None
        except (psycopg.Error, CandidateSourceError):
            raise ValidationSourceError("Review storage is invalid.") from None
