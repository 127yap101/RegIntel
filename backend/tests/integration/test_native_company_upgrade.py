"""Append migration 23 to an owned populated 22-schema registry without rewriting it."""

from dataclasses import replace
from uuid import uuid4

import pytest

from backend.tests.evidence_fixtures import synthetic_artifact
from backend.tests.integration.conftest import clear_auth_test_schemas
from backend.tests.integration.test_evidence_storage import context, parsed, persist
from backend.tests.integration.test_numerical_context_storage import snapshot
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.db.migrations import DEFAULT_MIGRATIONS, connect_database, migrate
from regintel.entities.models import EntityRegistration, EvidenceAnchor, canonical_bytes
from regintel.entities.repository import EntityRepository

pytestmark = pytest.mark.integration


def test_upgrade_keeps_existing_registration_registry_hash_and_legacy_guard(
    auth_database, tmp_path
):
    clear_auth_test_schemas(auth_database)
    selected = tmp_path / "legacy-migrations"
    selected.mkdir()
    original_migrations = sorted(DEFAULT_MIGRATIONS.glob("*.sql"))[:22]
    assert len(original_migrations) == 22
    for file in original_migrations:
        (selected / file.name).write_bytes(file.read_bytes())
    migrate(auth_database, selected)
    fixture = context(auth_database)
    label = "Legacy Solar Limited"
    fixture = replace(
        fixture,
        artifact=synthetic_artifact(
            configuration=fixture.configuration,
            blob=fixture.blob,
            parse_id=fixture.artifact.id,
            filing_id=fixture.artifact.filing_id,
            filing_version_id=fixture.artifact.filing_version_id,
            original=label,
        ),
    )
    with connect_database(auth_database) as connection, connection.transaction():
        persist(connection, fixture)
        parsed(connection, fixture)
    repository = EntityRepository(auth_database)
    user = PostgreSQLAuthRepository(auth_database).get_by_username("admin")
    assert user is not None
    evidence = repository.evidence_for_parse(fixture.artifact.id)[0][0]
    body = EntityRegistration(
        id=str(uuid4()),
        kind="COMPANY",
        legal_name=label,
        legal_name_support=EvidenceAnchor(
            evidence_id=evidence.id, start=evidence.span.start, end=evidence.span.end, quote=label
        ),
        review_note="Authored legacy registry before migration 23; no real source approval.",
    )
    assert repository.register(body, user)
    before = snapshot(auth_database)
    registry = repository.snapshot()
    with connect_database(auth_database) as connection:
        guard_before = connection.execute(
            "SELECT oid,pg_get_functiondef(oid) FROM pg_proc "
            "WHERE oid='regintel.validate_entity_registration()'::regprocedure"
        ).fetchone()
    migrate(auth_database)
    after = snapshot(auth_database)
    assert {table: after[table] for table in before} == before
    assert set(after) - set(before) == {"numerical_applicability_reviews"}
    assert canonical_bytes(repository.snapshot()) == canonical_bytes(registry)
    with connect_database(auth_database) as connection:
        assert (
            connection.execute(
                "SELECT oid,pg_get_functiondef(oid) FROM pg_proc "
                "WHERE oid='regintel.validate_entity_registration()'::regprocedure"
            ).fetchone()
            == guard_before
        )
        versions = connection.execute(
            "SELECT version FROM regintel_meta.schema_migrations ORDER BY applied_order"
        ).fetchall()
        assert [row[0] for row in versions] == list(range(1, 25))
        assert connection.execute(
            "SELECT count(*) FROM regintel.numerical_applicability_reviews"
        ).fetchone() == (0,)
    assert not repository.register(body, user)
    assert repository.register(body.model_copy(update={"id": str(uuid4())}), user)
