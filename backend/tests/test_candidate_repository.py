"""Missing migration prerequisites are unavailable, rather than invalid filing data."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

import psycopg
import pytest
from pydantic import SecretStr

from backend.tests.test_candidate_models import metric
from regintel.auth.types import User
from regintel.candidates.repository import CandidateRepository, CandidateUnavailable
from regintel.db.config import DatabaseSettings
from regintel.db.migrations import DatabaseConnection, MigrationError
from regintel.entities.repository import EntityUnavailable
from regintel.fixtures.sources import fixture_id


@pytest.mark.parametrize(
    "failure",
    (
        psycopg.OperationalError("private connection"),
        psycopg.InterfaceError("private interface"),
        psycopg.errors.UndefinedTable("private missing migration"),
        psycopg.errors.UndefinedColumn("private missing schema"),
        MigrationError("private migration"),
        EntityUnavailable("private entity prerequisite"),
    ),
)
@pytest.mark.parametrize("operation", ("register", "metrics", "input", "extract", "read"))
def test_prerequisite_unavailability(
    monkeypatch: pytest.MonkeyPatch, failure: Exception, operation: str
) -> None:
    @contextmanager
    def missing(_: DatabaseSettings) -> Iterator[DatabaseConnection]:
        raise failure
        yield  # pragma: no cover

    monkeypatch.setattr("regintel.candidates.repository.connect_database", missing)
    database = DatabaseSettings(
        database_url=SecretStr("postgresql://regintel:synthetic-unused@127.0.0.1:5432/regintel")
    )
    repository = CandidateRepository(database)
    user = User(UUID(fixture_id(1)), "admin", SecretStr("unused"), "admin", True, 1)
    with pytest.raises(CandidateUnavailable, match="^Proposal storage is unavailable\\.$"):
        if operation == "register":
            repository.register_metric(metric(), user)
        elif operation == "metrics":
            repository.metrics((fixture_id(301),))
        elif operation == "input":
            repository.input_for_run(fixture_id(100), ())
        elif operation == "extract":
            repository.extract(fixture_id(100), (), user)
        else:
            repository.get_run(fixture_id(100))
