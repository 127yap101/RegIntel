"""Immutable current-admin context reviews with fresh source/approval checks."""

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
from regintel.numerical.bound_gate import bound_gate_configuration_sha256, validate_bound_numerical
from regintel.numerical.context_inputs import load_context_input
from regintel.numerical.evidence_binding import bind_context_evidence
from regintel.numerical.evidence_binding_repository import _sealed_parse, _stored_evidence
from regintel.numerical.gate_models import BoundGateInput, StoredBoundNumericalGate
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
from regintel.numerical.review_models import (
    MAX_REVIEW_BYTES,
    NumericalContextReviewRequest,
    ReviewedNumericalContext,
    require_reviewable,
    review_identity,
)


class NumericalReviewConflict(ValueError):
    """A final decision, current context or complete evidence membership conflicts."""


def review_configuration_sha256() -> str:
    package = Path(__file__).resolve().parent
    digest = hashlib.sha256(bound_gate_configuration_sha256().encode("ascii"))
    for name, path in (
        ("numerical/review_models.py", package / "review_models.py"),
        ("numerical/review_repository.py", package / "review_repository.py"),
        (
            "infra/migrations/0018_numerical_context_reviews.sql",
            package.parents[3] / "infra/migrations/0018_numerical_context_reviews.sql",
        ),
    ):
        body = path.read_bytes()
        digest.update(name.encode("ascii") + b"\0" + len(body).to_bytes(8, "big") + body)
    return digest.hexdigest()


def _read(connection: DatabaseConnection, gate_id: str) -> ReviewedNumericalContext:
    row = connection.execute(
        "SELECT review_bytes,review_sha256 FROM regintel.numerical_context_reviews "
        "WHERE gate_run_id=%s",
        (UUID(gate_id),),
    ).fetchone()
    if row is None:
        raise NumericalNotFound("The selected numerical context review is unavailable.")
    body = _checked(row[0], row[1], MAX_REVIEW_BYTES)
    review = ReviewedNumericalContext.model_validate_json(body)
    gate = read_gate(connection, gate_id)
    require_reviewable(gate, review.request)
    if (
        canonical_bytes(review) != body
        or review.gate_input_sha256 != gate.result.input_sha256
        or review.gate_result_sha256 != hashlib.sha256(canonical_bytes(gate.result)).hexdigest()
    ):
        raise NumericalSourceError("Numerical review differs from its immutable gate membership.")
    return review


def _fresh(
    connection: DatabaseConnection, source: NumericalRepository, gate: StoredBoundNumericalGate
) -> None:
    if gate.result.configuration_sha256 != bound_gate_configuration_sha256():
        raise NumericalReviewConflict("Run the installed numerical gates before reviewing context.")
    context = gate.source_input.context
    current, _ = load_context_input(connection, source, context.source_input.draft)
    artifact, configuration = _sealed_parse(connection, gate.result.parse_version_id)
    binding = bind_context_evidence(context, artifact, configuration)
    _stored_evidence(connection, binding)
    packet = BoundGateInput(context=context, current_context=current, binding=binding)
    if packet != gate.source_input or validate_bound_numerical(packet) != gate.result:
        raise NumericalReviewConflict(
            "Source or approval context changed; inspect and bind it again."
        )


class NumericalContextReviewRepository:
    def __init__(self, source: NumericalRepository) -> None:
        self.source = source

    def _save(self, request: NumericalContextReviewRequest, user: User) -> ReviewedNumericalContext:
        with self.source.connect() as connection, connection.transaction():
            # Approval rows are append-only. These locks keep the fresh snapshot stable
            # until the immutable decision commits, without changing any approval.
            connection.execute(
                "LOCK TABLE regintel.entity_registrations,regintel.metric_definitions,"
                "regintel.numeric_metric_policies IN SHARE MODE"
            )
            _authorize(connection, user)
            gate = read_gate(connection, request.gate_run_id)
            require_reviewable(gate, request)
            existing = connection.execute(
                "SELECT 1 FROM regintel.numerical_context_reviews WHERE gate_run_id=%s",
                (UUID(request.gate_run_id),),
            ).fetchone()
            if existing is not None:
                retained = _read(connection, request.gate_run_id)
                if retained.request != request:
                    raise NumericalReviewConflict("This gate already has a different final review.")
                return retained
            _fresh(connection, self.source, gate)
            configuration = review_configuration_sha256()
            review = ReviewedNumericalContext(
                id=review_identity(request, gate.result.input_sha256, configuration),
                request=request,
                gate_input_sha256=gate.result.input_sha256,
                gate_result_sha256=hashlib.sha256(canonical_bytes(gate.result)).hexdigest(),
                configuration_sha256=configuration,
                reviewed_by=str(user.id),
                auth_version=user.auth_version,
            )
            payload, body = canonical_bytes(request), canonical_bytes(review)
            connection.execute(
                "INSERT INTO regintel.numerical_context_reviews "
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
            if retained.request != request or retained.id != review.id:
                raise NumericalReviewConflict("This gate already has another immutable review.")
            return retained

    def save(self, request: NumericalContextReviewRequest, user: User) -> ReviewedNumericalContext:
        request = NumericalContextReviewRequest.model_validate(request.model_dump(mode="python"))
        for attempt in range(3):
            try:
                return self._save(request, user)
            except (psycopg.errors.SerializationFailure, psycopg.errors.DeadlockDetected):
                if attempt == 2:
                    raise NumericalUnavailable("Retry the concurrent numerical review.") from None
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
                raise NumericalUnavailable("Numerical review storage is unavailable.") from None
            except (psycopg.Error, ValueError, OSError, UploadError, ProjectionError):
                raise NumericalReviewConflict(
                    "The exact numerical review could not commit."
                ) from None
        raise AssertionError("Bounded numerical review retry exhausted.")

    def get(self, gate_id: str, user: User) -> ReviewedNumericalContext:
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
            raise NumericalUnavailable("Numerical review history is unavailable.") from None
        except (psycopg.Error, ValueError, OSError):
            raise NumericalSourceError("Numerical review history is invalid.") from None
