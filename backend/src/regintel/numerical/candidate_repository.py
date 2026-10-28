"""Append-only reviewed numerical proposals with exact retries and fresh new writes."""

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
from regintel.numerical.candidate_models import (
    MAX_CANDIDATE_RECORD_BYTES,
    NumericalCandidateRecord,
    NumericalCandidateRequest,
    StoredNumericalCandidate,
    numerical_candidate_identity,
)
from regintel.numerical.gate_repository import _read as read_gate
from regintel.numerical.publication_input import publication_input_configuration_sha256
from regintel.numerical.publication_input_repository import prepare_in_transaction
from regintel.numerical.publication_models import (
    MAX_PUBLICATION_INPUT_BYTES,
    NumericalPublicationPreparation,
)
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
from regintel.numerical.review_repository import _read as read_review


def candidate_storage_configuration_sha256() -> str:
    package = Path(__file__).resolve().parent
    digest = hashlib.sha256(publication_input_configuration_sha256().encode("ascii"))
    for name, path in (
        ("candidate_models.py", package / "candidate_models.py"),
        ("candidate_repository.py", package / "candidate_repository.py"),
        (
            "0019_numerical_candidates.sql",
            package.parents[3] / "infra/migrations/0019_numerical_candidates.sql",
        ),
    ):
        body = path.read_bytes()
        digest.update(name.encode("ascii") + b"\0" + len(body).to_bytes(8, "big") + body)
    return digest.hexdigest()


def _read(connection: DatabaseConnection, candidate_id: str) -> StoredNumericalCandidate:
    row = connection.execute(
        "SELECT record_bytes,record_sha256,preparation_bytes,preparation_sha256,"
        "gate_run_id,prepared_input_id,parse_version_id,context_review_id,"
        "storage_configuration_sha256,submitted_by,auth_version "
        "FROM regintel.numerical_candidates WHERE id=%s",
        (UUID(candidate_id),),
    ).fetchone()
    if row is None:
        raise NumericalNotFound("The numerical candidate is unavailable.")
    record_bytes = _checked(row[0], row[1], MAX_CANDIDATE_RECORD_BYTES)
    preparation_bytes = _checked(row[2], row[3], MAX_PUBLICATION_INPUT_BYTES)
    candidate = StoredNumericalCandidate(
        record=NumericalCandidateRecord.model_validate_json(record_bytes),
        preparation=NumericalPublicationPreparation.model_validate_json(preparation_bytes),
    )
    record, preparation = candidate.record, candidate.preparation
    prepared = preparation.proposed_input
    assert prepared is not None
    gate = read_gate(connection, record.request.gate_run_id)
    reviewed = read_review(connection, record.request.gate_run_id)
    retained = gate.source_input.context.source_input
    if (
        canonical_bytes(record) != record_bytes
        or canonical_bytes(preparation) != preparation_bytes
        or record.id != candidate_id
        or record.request.gate_run_id != str(row[4])
        or record.request.prepared_input_id != str(row[5])
        or prepared.proof.parse_version_id != str(row[6])
        or prepared.context_review.id != str(row[7])
        or record.storage_configuration_sha256 != row[8]
        or record.submitted_by != str(row[9])
        or record.auth_version != row[10]
        or prepared.gate != gate.result
        or prepared.proof != gate.source_input.binding
        or prepared.context_review != reviewed
        or prepared.metric != retained.metric
        or prepared.policy != retained.policy
        or prepared.subject_entity_id != retained.draft.subject_entity_id
    ):
        raise NumericalSourceError(
            "Stored numerical candidate differs from its immutable source membership."
        )
    return candidate


class NumericalCandidateRepository:
    def __init__(self, source: NumericalRepository) -> None:
        self.source = source

    def _save(self, request: NumericalCandidateRequest, user: User) -> StoredNumericalCandidate:
        with self.source.connect() as connection, connection.transaction():
            # READ COMMITTED lets a request waiting on this input's lock see a
            # predecessor's committed record. Approval locks stabilize new writes.
            connection.execute(
                "LOCK TABLE regintel.entity_registrations,regintel.metric_definitions,"
                "regintel.numeric_metric_policies,regintel.numerical_context_reviews IN SHARE MODE"
            )
            _authorize(connection, user)
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("numerical-candidate:" + request.prepared_input_id,),
            )
            row = connection.execute(
                "SELECT id FROM regintel.numerical_candidates WHERE prepared_input_id=%s",
                (UUID(request.prepared_input_id),),
            ).fetchone()
            if row is not None:
                existing = _read(connection, str(row[0]))
                if existing.record.request != request:
                    raise NumericalReviewConflict(
                        "The prepared input belongs to a different candidate request."
                    )
                return existing
            preparation = prepare_in_transaction(connection, self.source, request.gate_run_id, user)
            prepared = preparation.proposed_input
            if (
                preparation.state != "READY_FOR_ADAPTER"
                or prepared is None
                or prepared.id != request.prepared_input_id
            ):
                raise NumericalReviewConflict(
                    "Create a candidate only from the current complete reviewed preparation."
                )
            record = NumericalCandidateRecord(
                id=numerical_candidate_identity(prepared.id),
                request=request,
                preparation_sha256=preparation.sha256,
                storage_configuration_sha256=candidate_storage_configuration_sha256(),
                submitted_by=str(user.id),
                auth_version=user.auth_version,
            )
            body, proof = canonical_bytes(record), canonical_bytes(preparation)
            connection.execute(
                "INSERT INTO regintel.numerical_candidates "
                "(id,gate_run_id,prepared_input_id,parse_version_id,context_review_id,"
                "record_bytes,record_sha256,preparation_bytes,preparation_sha256,"
                "storage_configuration_sha256,submitted_by,auth_version) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    UUID(record.id),
                    UUID(request.gate_run_id),
                    UUID(prepared.id),
                    UUID(prepared.proof.parse_version_id),
                    UUID(prepared.context_review.id),
                    body,
                    hashlib.sha256(body).hexdigest(),
                    proof,
                    preparation.sha256,
                    record.storage_configuration_sha256,
                    user.id,
                    user.auth_version,
                ),
            )
            return _read(connection, record.id)

    def save(self, request: NumericalCandidateRequest, user: User) -> StoredNumericalCandidate:
        request = NumericalCandidateRequest.model_validate(request.model_dump(mode="python"))
        for attempt in range(3):
            try:
                return self._save(request, user)
            except (psycopg.errors.SerializationFailure, psycopg.errors.DeadlockDetected):
                if attempt == 2:
                    raise NumericalUnavailable(
                        "Retry the concurrent numerical candidate request."
                    ) from None
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
                raise NumericalUnavailable("Numerical candidate storage is unavailable.") from None
            except (psycopg.Error, ValueError, OSError, UploadError, ProjectionError):
                raise NumericalReviewConflict(
                    "The exact numerical candidate could not commit."
                ) from None
        raise AssertionError("Bounded numerical candidate retry exhausted.")

    def get(self, candidate_id: str, user: User) -> StoredNumericalCandidate:
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
            raise NumericalUnavailable("Numerical candidate storage is unavailable.") from None
        except (psycopg.Error, ValueError, OSError):
            raise NumericalSourceError(
                "The immutable numerical candidate could not be verified."
            ) from None
