"""Current-admin immutable bound numerical gate runs; no acceptance/publication writes."""

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
from regintel.numerical.bound_gate import bound_gate_configuration_sha256, validate_bound_numerical
from regintel.numerical.context_inputs import load_context_input
from regintel.numerical.context_storage import _history
from regintel.numerical.evidence_binding import bind_context_evidence
from regintel.numerical.evidence_binding_repository import _sealed_parse, _stored_evidence
from regintel.numerical.gate_models import (
    MAX_GATE_INPUT_BYTES,
    MAX_GATE_RESULT_BYTES,
    BoundGateInput,
    BoundNumericalGateRun,
    StoredBoundNumericalGate,
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


def _read(connection: DatabaseConnection, identity: str) -> StoredBoundNumericalGate:
    row = connection.execute(
        "SELECT input_bytes,input_sha256,result_bytes,result_sha256,submitted_by,auth_version "
        "FROM regintel.bound_numerical_gate_runs WHERE id=%s",
        (UUID(identity),),
    ).fetchone()
    if row is None:
        raise NumericalNotFound("The bound numerical gate run is unavailable.")
    body = _checked(row[0], row[1], MAX_GATE_INPUT_BYTES)
    result_bytes = _checked(row[2], row[3], MAX_GATE_RESULT_BYTES)
    packet = BoundGateInput.model_validate_json(body)
    result = BoundNumericalGateRun.model_validate_json(result_bytes)
    if (
        canonical_bytes(packet) != body
        or canonical_bytes(result) != result_bytes
        or result.id != identity
    ):
        raise NumericalSourceError(
            "Numerical gate history differs from its canonical stored bytes."
        )
    stored = StoredBoundNumericalGate.model_validate(
        {
            "source_input": packet,
            "result": result,
            "submitted_by": str(row[4]),
            "auth_version": row[5],
        }
    )
    if (
        result.configuration_sha256 == bound_gate_configuration_sha256()
        and validate_bound_numerical(packet) != result
    ):
        raise NumericalSourceError(
            "The gate result differs from its retained deterministic inputs."
        )
    return stored


class BoundNumericalGateRepository:
    def __init__(self, source: NumericalRepository) -> None:
        self.source = source

    def _run(self, record_id: str, parse_id: str, user: User) -> StoredBoundNumericalGate:
        with self.source.connect() as connection, connection.transaction():
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            _authorize(connection, user)
            context = _history(connection, record_id)
            current, _ = load_context_input(connection, self.source, context.source_input.draft)
            artifact, configuration = _sealed_parse(connection, parse_id)
            binding = bind_context_evidence(context, artifact, configuration)
            _stored_evidence(connection, binding)
            packet = BoundGateInput(context=context, current_context=current, binding=binding)
            result = validate_bound_numerical(packet)
            body, output = canonical_bytes(packet), canonical_bytes(result)
            connection.execute(
                "INSERT INTO regintel.bound_numerical_gate_runs "
                "(id,context_record_id,parse_version_id,input_bytes,input_sha256,"
                "result_bytes,result_sha256,configuration_sha256,state,submitted_by,auth_version) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                (
                    UUID(result.id),
                    UUID(record_id),
                    UUID(parse_id),
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
            retained = _read(connection, result.id)
            if retained.source_input != packet or retained.result != result:
                raise NumericalSourceError(
                    "The gate identity belongs to different immutable inputs."
                )
            return retained

    def run(self, record_id: str, parse_id: str, user: User) -> StoredBoundNumericalGate:
        for identity in (record_id, parse_id):
            TypeAdapter(CanonicalId).validate_python(identity)
        for attempt in range(3):
            try:
                return self._run(record_id, parse_id, user)
            except (psycopg.errors.SerializationFailure, psycopg.errors.DeadlockDetected):
                if attempt == 2:
                    raise NumericalUnavailable(
                        "Retry the concurrent numerical gate request."
                    ) from None
            except (NumericalAuthorizationError, NumericalNotFound, NumericalSourceError):
                raise
            except (
                psycopg.OperationalError,
                psycopg.InterfaceError,
                psycopg.errors.UndefinedTable,
                MigrationError,
            ):
                raise NumericalUnavailable(
                    "Bound numerical validation storage is unavailable."
                ) from None
            except (psycopg.Error, ValueError, OSError, UploadError, ProjectionError):
                raise NumericalSourceError(
                    "Bound numerical gate inputs cannot be committed."
                ) from None
        raise AssertionError("Bounded retry exhausted without a terminal result.")

    def get(self, identity: str, user: User) -> StoredBoundNumericalGate:
        TypeAdapter(CanonicalId).validate_python(identity)
        try:
            with self.source.connect() as connection, connection.transaction():
                _authorize(connection, user)
                return _read(connection, identity)
        except (NumericalAuthorizationError, NumericalNotFound, NumericalSourceError):
            raise
        except (
            psycopg.OperationalError,
            psycopg.InterfaceError,
            psycopg.errors.UndefinedTable,
            MigrationError,
        ):
            raise NumericalUnavailable("Numerical gate history is unavailable.") from None
        except (psycopg.Error, ValueError, OSError):
            raise NumericalSourceError("Numerical gate history is invalid.") from None
