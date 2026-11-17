"""Append a fresh gate from one exact stored applicability decision; never accept facts."""

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
from regintel.numerical.applicability_repository import _read as read_applicability
from regintel.numerical.bound_gate import validate_bound_numerical
from regintel.numerical.gate_models import ApplicabilityGateInput, StoredBoundNumericalGate
from regintel.numerical.gate_repository import _read as read_gate
from regintel.numerical.repository import (
    NumericalAuthorizationError,
    NumericalNotFound,
    NumericalRepository,
    NumericalSourceError,
    NumericalUnavailable,
    _authorize,
)
from regintel.numerical.review_repository import NumericalReviewConflict, _fresh


def require_retained_applicability(
    connection: DatabaseConnection, packet: ApplicabilityGateInput
) -> None:
    """Historical reads retain original decisions even after configurations change."""
    base = read_gate(connection, packet.base_result.id)
    review = read_applicability(connection, packet.base_result.id)
    if (
        isinstance(base.source_input, ApplicabilityGateInput)
        or base.source_input != packet.base_input()
        or base.result != packet.base_result
        or base.submitted_by != packet.base_submitted_by
        or base.auth_version != packet.base_auth_version
        or review != packet.applicability
    ):
        raise NumericalSourceError("The resolved gate differs from its retained source decision.")


class ResolvedNumericalGateRepository:
    def __init__(self, source: NumericalRepository) -> None:
        self.source = source

    def _run(self, gate_id: str, user: User) -> StoredBoundNumericalGate:
        with self.source.connect() as connection, connection.transaction():
            connection.execute(
                "LOCK TABLE regintel.entity_registrations,regintel.metric_definitions,"
                "regintel.numeric_metric_policies IN SHARE MODE"
            )
            _authorize(connection, user)
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("numerical-applicability-gate:" + gate_id,),
            )
            base = read_gate(connection, gate_id)
            if isinstance(base.source_input, ApplicabilityGateInput):
                raise NumericalReviewConflict("Select the unresolved original gate.")
            review = read_applicability(connection, gate_id)
            _fresh(connection, self.source, base)
            packet = ApplicabilityGateInput(
                context=base.source_input.context,
                current_context=base.source_input.current_context,
                binding=base.source_input.binding,
                base_result=base.result,
                base_submitted_by=base.submitted_by,
                base_auth_version=base.auth_version,
                applicability=review,
            )
            result = validate_bound_numerical(packet)
            body, output = canonical_bytes(packet), canonical_bytes(result)
            connection.execute(
                "INSERT INTO regintel.bound_numerical_gate_runs "
                "(id,context_record_id,parse_version_id,input_bytes,input_sha256,"
                "result_bytes,result_sha256,configuration_sha256,state,submitted_by,auth_version) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                (
                    UUID(result.id),
                    UUID(result.context_record_id),
                    UUID(result.parse_version_id),
                    body,
                    result.input_sha256,
                    output,
                    hashlib.sha256(output).hexdigest(),
                    result.configuration_sha256,
                    result.state,
                    user.id,
                    user.auth_version,
                ),
            )
            retained = read_gate(connection, result.id)
            if retained.source_input != packet or retained.result != result:
                raise NumericalSourceError("The new gate identity belongs to different inputs.")
            return retained

    def run(self, gate_id: str, user: User) -> StoredBoundNumericalGate:
        TypeAdapter(CanonicalId).validate_python(gate_id)
        for attempt in range(3):
            try:
                return self._run(gate_id, user)
            except (psycopg.errors.SerializationFailure, psycopg.errors.DeadlockDetected):
                if attempt == 2:
                    raise NumericalUnavailable("Retry the concurrent applicability gate.") from None
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
                raise NumericalUnavailable("Applicability gate storage is unavailable.") from None
            except (psycopg.Error, ValueError, OSError, UploadError, ProjectionError):
                raise NumericalReviewConflict(
                    "The exact applicability decision cannot resolve this gate."
                ) from None
        raise AssertionError("Bounded applicability gate retry exhausted.")
