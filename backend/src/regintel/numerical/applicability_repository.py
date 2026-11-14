"""Immutable applicability attestations over exact retained numerical evidence."""

import hashlib
from uuid import UUID

import psycopg
from pydantic import TypeAdapter

from regintel.auth.types import User
from regintel.contracts.primitives import CanonicalId
from regintel.db.migrations import DatabaseConnection, MigrationError
from regintel.entities.models import canonical_bytes
from regintel.evidence.projection import ProjectionError
from regintel.ingestion.storage import UploadError
from regintel.numerical.applicability import (
    applicability_configuration_sha256,
    applicability_requirements,
    require_applicability_membership,
    validate_applicability_request,
)
from regintel.numerical.applicability_models import (
    MAX_APPLICABILITY_BYTES,
    NumericalApplicabilityRequest,
    NumericalApplicabilityRequirements,
    ReviewedNumericalApplicability,
    applicability_identity,
)
from regintel.numerical.gate_repository import _read as read_gate
from regintel.numerical.repository import (
    NumericalAuthorizationError,
    NumericalNotFound,
    NumericalRepository,
    NumericalSourceError,
    NumericalUnavailable,
    _authorize,
    _checked,
)
from regintel.numerical.review_repository import NumericalReviewConflict, _fresh


class NumericalApplicabilityConflict(NumericalReviewConflict):
    """The source-specific attestation conflicts with its current or retained context."""


def _read(connection: DatabaseConnection, gate_id: str) -> ReviewedNumericalApplicability:
    row = connection.execute(
        "SELECT request_bytes,request_sha256,review_bytes,review_sha256,"
        "configuration_sha256,reviewed_by,auth_version,id "
        "FROM regintel.numerical_applicability_reviews WHERE gate_run_id=%s",
        (UUID(gate_id),),
    ).fetchone()
    if row is None:
        raise NumericalNotFound("The selected numerical applicability review is unavailable.")
    request_bytes = _checked(row[0], row[1], MAX_APPLICABILITY_BYTES)
    body = _checked(row[2], row[3], MAX_APPLICABILITY_BYTES)
    review = ReviewedNumericalApplicability.model_validate_json(body)
    gate = read_gate(connection, gate_id)
    # History verifies the original membership, without applying today's policy
    # to a decision recorded under a retained older configuration.
    require_applicability_membership(gate, review.request)
    if (
        canonical_bytes(review) != body
        or canonical_bytes(review.request) != request_bytes
        or review.configuration_sha256 != row[4]
        or review.reviewed_by != str(row[5])
        or review.auth_version != row[6]
        or review.id != str(row[7])
    ):
        raise NumericalSourceError("Applicability review differs from its immutable membership.")
    return review


class NumericalApplicabilityRepository:
    def __init__(self, source: NumericalRepository) -> None:
        self.source = source

    def requirements(self, gate_id: str, user: User) -> NumericalApplicabilityRequirements:
        TypeAdapter(CanonicalId).validate_python(gate_id)
        try:
            with self.source.connect() as connection, connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                _authorize(connection, user)
                gate = read_gate(connection, gate_id)
                _fresh(connection, self.source, gate)
                return applicability_requirements(gate)
        except (NumericalAuthorizationError, NumericalNotFound, NumericalSourceError):
            raise
        except NumericalReviewConflict as error:
            raise NumericalApplicabilityConflict(str(error)) from None
        except (
            psycopg.OperationalError,
            psycopg.InterfaceError,
            psycopg.errors.UndefinedTable,
            MigrationError,
        ):
            raise NumericalUnavailable("Applicability prerequisites are unavailable.") from None
        except (psycopg.Error, ValueError, OSError, UploadError, ProjectionError):
            raise NumericalSourceError(
                "Applicability prerequisites could not be verified."
            ) from None

    def _save(
        self, request: NumericalApplicabilityRequest, user: User
    ) -> ReviewedNumericalApplicability:
        with self.source.connect() as connection, connection.transaction():
            connection.execute(
                "LOCK TABLE regintel.entity_registrations,regintel.metric_definitions,"
                "regintel.numeric_metric_policies IN SHARE MODE"
            )
            _authorize(connection, user)
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("numerical-applicability-review:" + request.gate_run_id,),
            )
            gate = read_gate(connection, request.gate_run_id)
            require_applicability_membership(gate, request)
            existing = connection.execute(
                "SELECT 1 FROM regintel.numerical_applicability_reviews WHERE gate_run_id=%s",
                (UUID(request.gate_run_id),),
            ).fetchone()
            if existing is not None:
                retained = _read(connection, request.gate_run_id)
                if retained.request != request:
                    raise NumericalApplicabilityConflict(
                        "This gate already has a different applicability attestation."
                    )
                return retained
            _fresh(connection, self.source, gate)
            validate_applicability_request(gate, request)
            configuration = applicability_configuration_sha256()
            review = ReviewedNumericalApplicability(
                id=applicability_identity(request, configuration),
                request=request,
                configuration_sha256=configuration,
                reviewed_by=str(user.id),
                auth_version=user.auth_version,
            )
            payload, body = canonical_bytes(request), canonical_bytes(review)
            connection.execute(
                "INSERT INTO regintel.numerical_applicability_reviews "
                "(id,gate_run_id,request_bytes,request_sha256,review_bytes,review_sha256,"
                "configuration_sha256,reviewed_by,auth_version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(gate_run_id) DO NOTHING",
                (
                    UUID(review.id),
                    UUID(request.gate_run_id),
                    payload,
                    hashlib.sha256(payload).hexdigest(),
                    body,
                    hashlib.sha256(body).hexdigest(),
                    configuration,
                    user.id,
                    user.auth_version,
                ),
            )
            retained = _read(connection, request.gate_run_id)
            if retained != review:
                raise NumericalApplicabilityConflict(
                    "This gate already has another immutable applicability attestation."
                )
            return retained

    def save(
        self, request: NumericalApplicabilityRequest, user: User
    ) -> ReviewedNumericalApplicability:
        request = NumericalApplicabilityRequest.model_validate(request.model_dump(mode="python"))
        for attempt in range(3):
            try:
                return self._save(request, user)
            except (psycopg.errors.SerializationFailure, psycopg.errors.DeadlockDetected):
                if attempt == 2:
                    raise NumericalUnavailable(
                        "Retry the concurrent applicability review."
                    ) from None
            except (NumericalAuthorizationError, NumericalNotFound, NumericalSourceError):
                raise
            except NumericalReviewConflict as error:
                raise NumericalApplicabilityConflict(str(error)) from None
            except (
                psycopg.OperationalError,
                psycopg.InterfaceError,
                psycopg.errors.UndefinedTable,
                MigrationError,
            ):
                raise NumericalUnavailable("Applicability storage is unavailable.") from None
            except (psycopg.Error, ValueError, OSError, UploadError, ProjectionError):
                raise NumericalApplicabilityConflict(
                    "The exact applicability attestation could not commit."
                ) from None
        raise AssertionError("Bounded applicability review retry exhausted.")

    def get(self, gate_id: str, user: User) -> ReviewedNumericalApplicability:
        TypeAdapter(CanonicalId).validate_python(gate_id)
        try:
            with self.source.connect() as connection, connection.transaction():
                _authorize(connection, user)
                return _read(connection, gate_id)
        except (NumericalAuthorizationError, NumericalNotFound, NumericalSourceError):
            raise
        except (
            psycopg.OperationalError,
            psycopg.InterfaceError,
            psycopg.errors.UndefinedTable,
            MigrationError,
        ):
            raise NumericalUnavailable("Applicability review history is unavailable.") from None
        except (psycopg.Error, ValueError, OSError):
            raise NumericalSourceError("Applicability review history is invalid.") from None
