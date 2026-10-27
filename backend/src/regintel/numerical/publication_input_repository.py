"""Read-only preparation with current-admin and fresh authoritative source checks."""

import psycopg
from pydantic import TypeAdapter

from regintel.auth.types import User
from regintel.contracts.primitives import CanonicalId
from regintel.db.migrations import MigrationError
from regintel.evidence.projection import ProjectionError
from regintel.ingestion.storage import UploadError
from regintel.numerical.gate_repository import _read as read_gate
from regintel.numerical.publication_input import prepare_numerical_publication
from regintel.numerical.publication_models import NumericalPublicationPreparation
from regintel.numerical.repository import (
    NumericalAuthorizationError,
    NumericalNotFound,
    NumericalRepository,
    NumericalSourceError,
    NumericalUnavailable,
    _authorize,
)
from regintel.numerical.review_repository import (
    NumericalReviewConflict,
    _fresh,
)
from regintel.numerical.review_repository import (
    _read as read_review,
)


class NumericalPublicationInputRepository:
    def __init__(self, source: NumericalRepository) -> None:
        self.source = source

    def prepare(self, gate_id: str, user: User) -> NumericalPublicationPreparation:
        TypeAdapter(CanonicalId).validate_python(gate_id)
        try:
            with self.source.connect() as connection, connection.transaction():
                # The existing current-admin check holds a user-row share lock;
                # all application statements here read and no state is persisted.
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                _authorize(connection, user)
                gate = read_gate(connection, gate_id)
                _fresh(connection, self.source, gate)
                try:
                    review = read_review(connection, gate_id)
                except NumericalNotFound:
                    review = None
                return prepare_numerical_publication(gate, review)
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
            raise NumericalUnavailable(
                "Numerical publication input storage is unavailable."
            ) from None
        except (psycopg.Error, ValueError, OSError, UploadError, ProjectionError):
            raise NumericalReviewConflict(
                "The numerical publication input could not be verified."
            ) from None
