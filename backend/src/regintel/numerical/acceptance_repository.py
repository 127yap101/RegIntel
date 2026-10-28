"""Immutable numerical acceptance decisions with fresh checks and serialized retries."""

import hashlib
from pathlib import Path
from uuid import UUID

import psycopg
from pydantic import TypeAdapter

from regintel.auth.types import User
from regintel.contracts.primitives import CanonicalId
from regintel.db.migrations import DatabaseConnection, MigrationError
from regintel.entities.models import canonical_bytes
from regintel.evidence.projection import ProjectionError
from regintel.ingestion.storage import UploadError
from regintel.numerical.acceptance_models import (
    MAX_ACCEPTANCE_BYTES,
    NumericalAcceptanceRecord,
    NumericalAcceptanceRequest,
    StoredNumericalAcceptance,
    numerical_acceptance_identity,
)
from regintel.numerical.candidate_repository import _read as read_candidate
from regintel.numerical.candidate_repository import (
    candidate_storage_configuration_sha256,
)
from regintel.numerical.publication_input_repository import prepare_in_transaction
from regintel.numerical.repository import (
    NumericalAuthorizationError,
    NumericalNotFound,
    NumericalRepository,
    NumericalSourceError,
    NumericalUnavailable,
    _authorize,
    _checked,
)
from regintel.numerical.review_repository import NumericalReviewConflict


def acceptance_configuration_sha256() -> str:
    package = Path(__file__).resolve().parent
    digest = hashlib.sha256(candidate_storage_configuration_sha256().encode("ascii"))
    for name, path in (
        ("acceptance_models.py", package / "acceptance_models.py"),
        ("acceptance_repository.py", package / "acceptance_repository.py"),
        (
            "0020_numerical_acceptances.sql",
            package.parents[3] / "infra/migrations/0020_numerical_acceptances.sql",
        ),
    ):
        body = path.read_bytes()
        digest.update(name.encode("ascii") + b"\0" + len(body).to_bytes(8, "big") + body)
    return digest.hexdigest()


def _read(connection: DatabaseConnection, candidate_id: str) -> StoredNumericalAcceptance:
    row = connection.execute(
        "SELECT id,record_bytes,record_sha256,candidate_record_sha256,"
        "candidate_preparation_sha256,configuration_sha256,decision,reviewed_by,auth_version "
        "FROM regintel.numerical_acceptances WHERE candidate_id=%s",
        (UUID(candidate_id),),
    ).fetchone()
    if row is None:
        raise NumericalNotFound("The numerical acceptance decision is unavailable.")
    payload = _checked(row[1], row[2], MAX_ACCEPTANCE_BYTES)
    record = NumericalAcceptanceRecord.model_validate_json(payload)
    stored = StoredNumericalAcceptance(
        record=record, candidate=read_candidate(connection, candidate_id)
    )
    if (
        canonical_bytes(record) != payload
        or record.id != str(row[0])
        or record.candidate_record_sha256 != row[3]
        or record.candidate_preparation_sha256 != row[4]
        or record.configuration_sha256 != row[5]
        or record.request.decision != row[6]
        or record.reviewed_by != str(row[7])
        or record.auth_version != row[8]
    ):
        raise NumericalSourceError("Stored numerical acceptance differs from its audit metadata.")
    return stored


class NumericalAcceptanceRepository:
    def __init__(self, source: NumericalRepository) -> None:
        self.source = source

    def _save(self, request: NumericalAcceptanceRequest, user: User) -> StoredNumericalAcceptance:
        with self.source.connect() as connection, connection.transaction():
            connection.execute(
                "LOCK TABLE regintel.entity_registrations,regintel.metric_definitions,"
                "regintel.numeric_metric_policies,regintel.numerical_context_reviews,"
                "regintel.numerical_candidates IN SHARE MODE"
            )
            _authorize(connection, user)
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("numerical-acceptance:" + request.candidate_id,),
            )
            exists = connection.execute(
                "SELECT 1 FROM regintel.numerical_acceptances WHERE candidate_id=%s",
                (UUID(request.candidate_id),),
            ).fetchone()
            if exists is not None:
                previous = _read(connection, request.candidate_id)
                if previous.record.request != request:
                    raise NumericalReviewConflict("An immutable numerical decision already exists.")
                return previous
            candidate = read_candidate(connection, request.candidate_id)
            prepared = candidate.preparation.proposed_input
            assert prepared is not None
            if request.evidence_ids != prepared.gate.evidence_ids:
                raise NumericalReviewConflict("The decision must retain the complete exact proof.")
            accepted = request.decision == "ACCEPT"
            if accepted:
                fresh = prepare_in_transaction(
                    connection, self.source, candidate.record.request.gate_run_id, user
                )
                if (
                    fresh != candidate.preparation
                    or candidate.record.storage_configuration_sha256
                    != candidate_storage_configuration_sha256()
                ):
                    raise NumericalReviewConflict(
                        "Acceptance requires the candidate's exact current validated preparation."
                    )
            record = NumericalAcceptanceRecord(
                id=numerical_acceptance_identity(request.candidate_id),
                request=request,
                candidate_record_sha256=hashlib.sha256(
                    canonical_bytes(candidate.record)
                ).hexdigest(),
                candidate_preparation_sha256=candidate.preparation.sha256,
                configuration_sha256=acceptance_configuration_sha256(),
                reviewed_by=str(user.id),
                auth_version=user.auth_version,
                checks=candidate.preparation.checks if accepted else (),
                state="ACCEPTED_UNPUBLISHED" if accepted else "REJECTED",
                mandatory_m1_validation_complete=accepted,
            )
            payload = canonical_bytes(record)
            connection.execute(
                "INSERT INTO regintel.numerical_acceptances "
                "(id,candidate_id,candidate_record_sha256,candidate_preparation_sha256,"
                "configuration_sha256,decision,record_bytes,record_sha256,"
                "reviewed_by,auth_version) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    UUID(record.id),
                    UUID(request.candidate_id),
                    record.candidate_record_sha256,
                    record.candidate_preparation_sha256,
                    record.configuration_sha256,
                    request.decision,
                    payload,
                    hashlib.sha256(payload).hexdigest(),
                    user.id,
                    user.auth_version,
                ),
            )
            return _read(connection, request.candidate_id)

    def save(self, request: NumericalAcceptanceRequest, user: User) -> StoredNumericalAcceptance:
        request = NumericalAcceptanceRequest.model_validate(request.model_dump(mode="python"))
        for attempt in range(3):
            try:
                return self._save(request, user)
            except (psycopg.errors.SerializationFailure, psycopg.errors.DeadlockDetected):
                if attempt == 2:
                    raise NumericalUnavailable("Retry the concurrent numerical decision.") from None
            except (
                NumericalAuthorizationError,
                NumericalNotFound,
                NumericalSourceError,
                NumericalReviewConflict,
            ):
                raise
            except (
                psycopg.OperationalError,
                psycopg.InterfaceError,
                psycopg.errors.UndefinedTable,
                MigrationError,
            ):
                raise NumericalUnavailable("Numerical acceptance storage is unavailable.") from None
            except (psycopg.Error, ValueError, OSError, UploadError, ProjectionError):
                raise NumericalReviewConflict(
                    "The exact numerical decision could not commit."
                ) from None
        raise AssertionError("Bounded numerical acceptance retry exhausted.")

    def get(self, candidate_id: str, user: User) -> StoredNumericalAcceptance:
        TypeAdapter(CanonicalId).validate_python(candidate_id)
        try:
            with self.source.connect() as connection, connection.transaction():
                _authorize(connection, user)
                return _read(connection, candidate_id)
        except (NumericalAuthorizationError, NumericalNotFound, NumericalSourceError):
            raise
        except (
            psycopg.OperationalError,
            psycopg.InterfaceError,
            psycopg.errors.UndefinedTable,
            MigrationError,
        ):
            raise NumericalUnavailable("Numerical acceptance storage is unavailable.") from None
        except (psycopg.Error, ValueError, OSError):
            raise NumericalSourceError(
                "The immutable numerical decision could not be verified."
            ) from None
