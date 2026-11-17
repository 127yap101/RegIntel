"""Append the resolved gate guard to populated schema 24 without rewriting history."""

import pytest

from backend.tests.integration.conftest import clear_auth_test_schemas
from backend.tests.integration.test_numerical_applicability_storage import (
    persisted_gate,
    proposed,
    source_with_options,
)
from backend.tests.integration.test_numerical_context_storage import snapshot
from backend.tests.test_numerical_context import Options
from regintel.db.migrations import DEFAULT_MIGRATIONS, migrate
from regintel.entities.models import canonical_bytes
from regintel.numerical.applicability_repository import NumericalApplicabilityRepository
from regintel.numerical.gate_repository import BoundNumericalGateRepository
from regintel.numerical.resolved_gate_repository import ResolvedNumericalGateRepository

pytestmark = pytest.mark.integration


def test_populated_schema24_upgrade_retains_gate_and_attestation(
    auth_database, tmp_path, monkeypatch
):
    clear_auth_test_schemas(auth_database)
    previous = tmp_path / "schema24"
    previous.mkdir()
    files = sorted(DEFAULT_MIGRATIONS.glob("*.sql"))[:24]
    assert len(files) == 24
    for file in files:
        (previous / file.name).write_bytes(file.read_bytes())
    migrate(auth_database, previous)
    source = source_with_options(auth_database, tmp_path / "source", monkeypatch, Options())
    base = persisted_gate(source)
    reviews = NumericalApplicabilityRepository(source.source)
    review = reviews.save(proposed(reviews.requirements(base.result.id, source.user)), source.user)
    before = snapshot(auth_database)
    original_gate, original_review = canonical_bytes(base), canonical_bytes(review)
    report = migrate(auth_database)
    assert report.already_applied == tuple(range(1, 25)) and report.newly_applied == (25,)
    assert snapshot(auth_database) == before
    assert (
        canonical_bytes(
            BoundNumericalGateRepository(source.source).get(base.result.id, source.user)
        )
        == original_gate
    )
    assert canonical_bytes(reviews.get(base.result.id, source.user)) == original_review
    resolved = ResolvedNumericalGateRepository(source.source).run(base.result.id, source.user)
    assert resolved.result.state == "READY_FOR_REVIEW"
    assert (
        resolved.source_input.base_gate() == base and resolved.source_input.applicability == review
    )
