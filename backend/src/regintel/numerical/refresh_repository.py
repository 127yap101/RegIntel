"""Atomically refresh current snapshots and base gates without accepting source facts."""

import psycopg

from regintel.auth.types import User
from regintel.db.migrations import MigrationError
from regintel.evidence.projection import ProjectionError
from regintel.ingestion.storage import UploadError
from regintel.numerical.context_storage import NumericalContextStorage
from regintel.numerical.gate_repository import BoundNumericalGateRepository
from regintel.numerical.gate_repository import _read as read_gate
from regintel.numerical.refresh_models import (
    NumericalRefreshRequest,
    RefreshedNumericalGate,
    require_refresh_membership,
    require_refresh_selection,
)
from regintel.numerical.repository import (
    NumericalAuthorizationError,
    NumericalNotFound,
    NumericalRepository,
    NumericalSourceError,
    NumericalUnavailable,
    _authorize,
)
from regintel.numerical.review_repository import NumericalReviewConflict


class NumericalRefreshRepository:
    def __init__(self, source: NumericalRepository) -> None:
        self.source = source

    def _refresh(self, request: NumericalRefreshRequest, user: User) -> RefreshedNumericalGate:
        with self.source.connect() as connection, connection.transaction():
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            # These append-only approvals must stay stable across context and gate creation.
            connection.execute(
                "LOCK TABLE regintel.entity_registrations,regintel.metric_definitions,"
                "regintel.numeric_metric_policies IN SHARE MODE"
            )
            _authorize(connection, user)
            previous = read_gate(connection, request.gate_run_id)
            try:
                require_refresh_selection(request, previous)
            except ValueError:
                raise NumericalReviewConflict(
                    "Refresh selection differs from its stored gate."
                ) from None
            context = NumericalContextStorage(self.source)._save_in_transaction(
                connection, previous.source_input.context.source_input.draft, user
            )
            gate = BoundNumericalGateRepository(self.source)._run_in_transaction(
                connection, context.id, previous.result.parse_version_id, user
            )
            require_refresh_membership(previous, gate)
            return RefreshedNumericalGate(
                request=request,
                previous_context_record_id=previous.result.context_record_id,
                gate=gate,
            )

    def refresh(self, request: NumericalRefreshRequest, user: User) -> RefreshedNumericalGate:
        request = NumericalRefreshRequest.model_validate(request.model_dump(mode="python"))
        for attempt in range(3):
            try:
                return self._refresh(request, user)
            except (psycopg.errors.SerializationFailure, psycopg.errors.DeadlockDetected):
                if attempt == 2:
                    raise NumericalUnavailable("Retry the concurrent numerical refresh.") from None
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
                raise NumericalUnavailable("Numerical refresh storage is unavailable.") from None
            except (psycopg.Error, ValueError, OSError, UploadError, ProjectionError):
                raise NumericalReviewConflict(
                    "The exact numerical refresh could not commit."
                ) from None
        raise AssertionError("Bounded numerical refresh retry exhausted.")
