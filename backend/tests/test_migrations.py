import hashlib
from pathlib import Path

import pytest

from regintel.db.migrations import (
    AppliedMigration,
    Migration,
    MigrationError,
    load_migrations,
    validate_history,
)


def test_migration_hash_changes_when_sql_changes(tmp_path: Path) -> None:
    path = tmp_path / "0001_foundation.sql"
    original = b"CREATE SCHEMA regintel;\n"
    path.write_bytes(original)
    first = load_migrations(tmp_path)
    assert first[0].checksum == hashlib.sha256(original).hexdigest()
    path.write_bytes(original + b"-- reviewed amendment\n")
    with pytest.raises(MigrationError, match="checksum"):
        validate_history(
            load_migrations(tmp_path),
            (AppliedMigration(1, "foundation", first[0].checksum),),
        )


@pytest.mark.parametrize(
    "filenames",
    (
        ("0002_foundation.sql",),
        ("0001_first.sql", "0003_third.sql"),
        ("0001_first.sql", "0001_duplicate.sql"),
        ("1_foundation.sql",),
        ("0000_foundation.sql",),
    ),
)
def test_invalid_migration_sequence_is_rejected(tmp_path: Path, filenames: tuple[str, ...]) -> None:
    for filename in filenames:
        (tmp_path / filename).write_text("SELECT 1;\n")
    with pytest.raises(MigrationError):
        load_migrations(tmp_path)


def test_empty_or_unreadable_sql_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "0001_foundation.sql"
    path.write_text(" \n")
    with pytest.raises(MigrationError, match="empty"):
        load_migrations(tmp_path)
    path.write_bytes(b"\xff")
    with pytest.raises(MigrationError, match="UTF-8"):
        load_migrations(tmp_path)


@pytest.mark.parametrize(
    "history",
    (
        (AppliedMigration(3, "unknown", "a" * 64),),
        (AppliedMigration(2, "second", "b" * 64),),
        (AppliedMigration(2, "second", "b" * 64), AppliedMigration(1, "first", "a" * 64)),
        (AppliedMigration(1, "renamed", "a" * 64),),
        (AppliedMigration(1, "first", "c" * 64),),
    ),
)
def test_invalid_applied_history_is_rejected(history: tuple[AppliedMigration, ...]) -> None:
    migrations = (
        Migration(1, "first", "a" * 64, "SELECT 1;"),
        Migration(2, "second", "b" * 64, "SELECT 2;"),
    )
    with pytest.raises(MigrationError):
        validate_history(migrations, history)


def test_verified_prefix_allows_only_remaining_migrations() -> None:
    migrations = (
        Migration(1, "first", "a" * 64, "SELECT 1;"),
        Migration(2, "second", "b" * 64, "SELECT 2;"),
    )
    validate_history(migrations, (AppliedMigration(1, "first", "a" * 64),))
