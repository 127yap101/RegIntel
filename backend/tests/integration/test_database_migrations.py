"""These tests modify only a caller-selected, disposable regintel_test_ database."""

import os
import shutil
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import SecretStr

from regintel.db.checks import check_database
from regintel.db.config import DatabaseSettings, require_disposable_database
from regintel.db.migrations import (
    DEFAULT_MIGRATIONS,
    MigrationError,
    connect_database,
    load_migrations,
    migrate,
    migration_status,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def database_settings() -> DatabaseSettings:
    url = os.environ.get("REGINTEL_TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "Explicit integration requires REGINTEL_TEST_DATABASE_URL; it cannot be skipped."
        )
    settings = DatabaseSettings(database_url=SecretStr(url))
    require_disposable_database(settings)
    return settings


def clear_test_schemas(settings: DatabaseSettings) -> None:
    require_disposable_database(settings)
    with connect_database(settings) as connection:
        if not connection.info.dbname.startswith(
            "regintel_test_"
        ) or connection.info.hostaddr not in {"127.0.0.1", "::1"}:
            pytest.fail("Connected integration target is not the disposable loopback database.")
        connection.execute("DROP SCHEMA IF EXISTS regintel_meta CASCADE")
        connection.execute("DROP SCHEMA IF EXISTS regintel CASCADE")
        connection.execute("DROP EXTENSION IF EXISTS vector CASCADE")


@pytest.fixture(autouse=True)
def clean_disposable_database(database_settings: DatabaseSettings) -> Iterator[None]:
    clear_test_schemas(database_settings)
    try:
        yield
    finally:
        clear_test_schemas(database_settings)


def test_clean_repeatable_migration_and_vector_query(database_settings: DatabaseSettings) -> None:
    expected_versions = tuple(
        migration.version for migration in load_migrations(DEFAULT_MIGRATIONS)
    )
    assert migration_status(database_settings).applied == ()
    assert migration_status(database_settings).pending == expected_versions
    first = migrate(database_settings)
    assert first.already_applied == ()
    assert first.newly_applied == expected_versions
    second = migrate(database_settings)
    assert second.already_applied == expected_versions
    assert second.newly_applied == ()
    check = check_database(database_settings)
    assert check.vector_version == "0.8.7"
    assert check.vector_distance == 3.0
    assert migration_status(database_settings).pending == ()


def test_applied_checksum_drift_is_rejected(
    database_settings: DatabaseSettings, tmp_path: Path
) -> None:
    migrate(database_settings)
    original = load_migrations(DEFAULT_MIGRATIONS)[0]
    for migration_path in DEFAULT_MIGRATIONS.glob("*.sql"):
        shutil.copyfile(migration_path, tmp_path / migration_path.name)
    sql_file = tmp_path / "0001_foundation.sql"
    with sql_file.open("ab") as changed:
        changed.write(b"\n-- edited after application\n")
    with pytest.raises(MigrationError, match="checksum"):
        migrate(database_settings, tmp_path)
    with connect_database(database_settings) as connection:
        row = connection.execute(
            "SELECT sha256 FROM regintel_meta.schema_migrations WHERE version = 1"
        ).fetchone()
        assert row == (original.checksum,)


def test_unknown_applied_migration_is_rejected(database_settings: DatabaseSettings) -> None:
    migrate(database_settings)
    with connect_database(database_settings) as connection:
        connection.execute(
            "INSERT INTO regintel_meta.schema_migrations (version, name, sha256) "
            "VALUES (99, 'unknown', %s)",
            ("a" * 64,),
        )
    with pytest.raises(MigrationError, match="unknown"):
        migrate(database_settings)


def test_applied_history_gap_is_rejected(
    database_settings: DatabaseSettings, tmp_path: Path
) -> None:
    shutil.copyfile(DEFAULT_MIGRATIONS / "0001_foundation.sql", tmp_path / "0001_foundation.sql")
    (tmp_path / "0002_probe.sql").write_text("SELECT 1;\n")
    migrate(database_settings, tmp_path)
    with connect_database(database_settings) as connection:
        connection.execute("DELETE FROM regintel_meta.schema_migrations WHERE version = 1")
    with pytest.raises(MigrationError, match="gap"):
        migrate(database_settings, tmp_path)


def test_entire_failed_batch_rolls_back_and_can_retry(
    database_settings: DatabaseSettings, tmp_path: Path
) -> None:
    shutil.copyfile(DEFAULT_MIGRATIONS / "0001_foundation.sql", tmp_path / "0001_foundation.sql")
    second = tmp_path / "0002_probe.sql"
    second.write_text("CREATE TABLE regintel.atomic_probe (id INTEGER); SELECT 1/0;\n")
    with pytest.raises(MigrationError, match="22012"):
        migrate(database_settings, tmp_path)
    with connect_database(database_settings) as connection:
        assert connection.execute(
            "SELECT to_regclass('regintel_meta.schema_migrations')"
        ).fetchone() == (None,)
        assert connection.execute("SELECT to_regclass('regintel.atomic_probe')").fetchone() == (
            None,
        )
        assert (
            connection.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            ).fetchone()
            is None
        )
    second.write_text("CREATE TABLE regintel.atomic_probe (id INTEGER);\n")
    assert migrate(database_settings, tmp_path).newly_applied == (1, 2)


def test_migration_cannot_commit_outside_atomic_batch(
    database_settings: DatabaseSettings, tmp_path: Path
) -> None:
    shutil.copyfile(DEFAULT_MIGRATIONS / "0001_foundation.sql", tmp_path / "0001_foundation.sql")
    (tmp_path / "0002_escape.sql").write_text(
        "CREATE TABLE regintel.transaction_escape (id INTEGER); COMMIT;\n"
    )
    with pytest.raises(MigrationError, match="Database migration failed"):
        migrate(database_settings, tmp_path)
    with connect_database(database_settings) as connection:
        assert connection.execute(
            "SELECT to_regclass('regintel_meta.schema_migrations')"
        ).fetchone() == (None,)
        assert connection.execute(
            "SELECT to_regclass('regintel.transaction_escape')"
        ).fetchone() == (None,)


def test_concurrent_runners_serialize(database_settings: DatabaseSettings) -> None:
    expected_versions = tuple(
        migration.version for migration in load_migrations(DEFAULT_MIGRATIONS)
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(migrate, database_settings) for _ in range(2)]
        reports = [future.result(timeout=30) for future in futures]
    assert sorted(report.newly_applied for report in reports) == [(), expected_versions]
    assert migration_status(database_settings).applied == expected_versions
