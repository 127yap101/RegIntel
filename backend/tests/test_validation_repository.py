"""Unavailable schema/services map to safe operational failures on every operation."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

import psycopg
import pytest
from pydantic import SecretStr

from backend.tests.test_validation_api import validation_source
from regintel.auth.types import User
from regintel.candidates.repository import CandidateUnavailable
from regintel.db.config import DatabaseSettings
from regintel.db.migrations import DatabaseConnection, MigrationError
from regintel.fixtures.sources import fixture_id
from regintel.validation.gate import validate
from regintel.validation.models import NumericMetricPolicy, ReviewDecision
from regintel.validation.repository import ValidationRepository, ValidationUnavailable


@pytest.mark.parametrize(
    "failure",
    (
        psycopg.OperationalError("private db"),
        psycopg.InterfaceError("private interface"),
        psycopg.errors.UndefinedTable("private schema"),
        psycopg.errors.UndefinedColumn("private column"),
        MigrationError("private migration"),
        CandidateUnavailable("private candidate"),
    ),
)
@pytest.mark.parametrize("operation", ("policy", "input", "validate", "read", "review", "reviews"))
def test_unavailable_prerequisites(
    monkeypatch: pytest.MonkeyPatch, failure: Exception, operation: str
) -> None:
    @contextmanager
    def missing(_: DatabaseSettings) -> Iterator[DatabaseConnection]:
        raise failure
        yield  # pragma: no cover

    monkeypatch.setattr("regintel.validation.repository.connect_database", missing)
    settings = DatabaseSettings(
        database_url=SecretStr("postgresql://regintel:synthetic-unused@127.0.0.1:5432/regintel")
    )
    user = User(UUID(fixture_id(1)), "admin", SecretStr("unused"), "admin", True, 1)
    repository = ValidationRepository(settings)
    source = validation_source()
    run = validate(source)
    with pytest.raises(ValidationUnavailable, match="^Validation storage is unavailable\\.$"):
        if operation == "policy":
            repository.register_policy(
                NumericMetricPolicy(
                    id=fixture_id(500),
                    metric_id=fixture_id(501),
                    quantity_kind="MONEY",
                    period_kind="DURATION",
                    allowed_unit_labels=("crore",),
                    review_note="Synthetic policy",
                ),
                user,
            )
        elif operation == "input":
            repository.input_for_run(source.candidate_run.id)
        elif operation == "validate":
            repository.validate(source.candidate_run.id, user)
        elif operation == "read":
            repository.get_run(run.id)
        elif operation == "reviews":
            repository.reviews(run.id)
        else:
            repository.review(
                ReviewDecision(
                    id=fixture_id(502),
                    validation_run_id=run.id,
                    candidate_id=run.results[0].candidate_id,
                    decision="REJECT",
                    supports=source.candidate_run.bundle.narrative_facts[0].supports,
                    review_note="Synthetic reviewer decision",
                ),
                user,
            )
