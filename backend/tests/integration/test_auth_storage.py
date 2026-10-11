"""Live PostgreSQL account constraints, upgrades, versioning and atomic seeding."""

import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from pydantic import SecretStr

from regintel.auth.errors import SeedConflict
from regintel.auth.passwords import hash_password, verify_password
from regintel.auth.repository import PostgreSQLAuthRepository, seed_users
from regintel.auth.types import Role, SeedAccount
from regintel.db.config import DatabaseSettings
from regintel.db.migrations import (
    DEFAULT_MIGRATIONS,
    connect_database,
    load_migrations,
    migrate,
    migration_status,
)

pytestmark = pytest.mark.integration
PASSWORD = "synthetic-local-passphrase-123"
OTHER_PASSWORD = "alternate-local-passphrase-456"


def accounts() -> tuple[SeedAccount, ...]:
    return (
        SeedAccount("admin", SecretStr(PASSWORD), "admin"),
        SeedAccount("learner", SecretStr(PASSWORD), "learner"),
    )


def snapshot(settings: DatabaseSettings, username: str) -> tuple[object, ...]:
    with connect_database(settings) as connection:
        row = connection.execute(
            "SELECT * FROM regintel.users WHERE username = %s", (username,)
        ).fetchone()
    assert row is not None
    return row


def test_fresh_auth_schema_is_empty_and_fully_migrated(auth_database: DatabaseSettings) -> None:
    expected_versions = tuple(
        migration.version for migration in load_migrations(DEFAULT_MIGRATIONS)
    )
    assert migration_status(auth_database).applied == expected_versions
    with connect_database(auth_database) as connection:
        assert connection.execute("SELECT count(*) FROM regintel.users").fetchone() == (0,)


def test_foundation_upgrade_preserves_first_migration_checksum(
    auth_database: DatabaseSettings, tmp_path: Path
) -> None:
    with connect_database(auth_database) as connection:
        connection.execute("DROP SCHEMA regintel_meta CASCADE")
        connection.execute("DROP SCHEMA regintel CASCADE")
        connection.execute("DROP EXTENSION vector CASCADE")
    shutil.copyfile(DEFAULT_MIGRATIONS / "0001_foundation.sql", tmp_path / "0001_foundation.sql")
    assert migrate(auth_database, tmp_path).newly_applied == (1,)
    report = migrate(auth_database)
    assert report.already_applied == (1,)
    assert report.newly_applied == tuple(
        migration.version for migration in load_migrations(DEFAULT_MIGRATIONS)[1:]
    )
    with connect_database(auth_database) as connection:
        assert connection.execute(
            "SELECT sha256 FROM regintel_meta.schema_migrations WHERE version = 1"
        ).fetchone() == (load_migrations(DEFAULT_MIGRATIONS)[0].checksum,)
        assert connection.execute("SELECT count(*) FROM regintel.users").fetchone() == (0,)


def test_seed_is_idempotent_and_preserves_all_existing_account_data(
    auth_database: DatabaseSettings,
) -> None:
    first = seed_users(auth_database, accounts())
    assert first.created == ("admin", "learner")
    assert first.existing == ()
    repository = PostgreSQLAuthRepository(auth_database)
    admin = repository.get_by_username(" ADMIN ")
    assert admin is not None
    assert admin.id.version == 4
    assert admin.is_active and admin.auth_version == 1
    assert admin.password_hash.get_secret_value() != PASSWORD
    assert verify_password(PASSWORD, admin.password_hash.get_secret_value())
    assert repository.get_by_id(admin.id) == admin
    assert repository.get_by_id(uuid4()) is None
    assert repository.get_by_username("missing") is None
    with connect_database(auth_database) as connection:
        connection.execute(
            "UPDATE regintel.users SET is_active = FALSE WHERE username = %s", ("admin",)
        )
    before = tuple(snapshot(auth_database, seed.username) for seed in accounts())
    second = seed_users(auth_database, accounts())
    assert second.created == ()
    assert second.existing == ("admin", "learner")
    assert tuple(snapshot(auth_database, seed.username) for seed in accounts()) == before
    retained = repository.get_by_username("admin")
    assert retained is not None
    assert not retained.is_active and retained.auth_version == 2


@pytest.mark.parametrize("conflict", ["password", "role"])
def test_seed_conflict_rolls_back_new_accounts_and_preserves_existing(
    auth_database: DatabaseSettings, conflict: str
) -> None:
    existing = SeedAccount("learner", SecretStr(PASSWORD), "learner")
    seed_users(auth_database, (existing,))
    before = snapshot(auth_database, "learner")
    conflicting = SeedAccount(
        "learner",
        SecretStr(OTHER_PASSWORD if conflict == "password" else PASSWORD),
        "admin" if conflict == "role" else "learner",
    )
    with pytest.raises(SeedConflict, match="conflict"):
        seed_users(auth_database, (accounts()[0], conflicting))
    assert snapshot(auth_database, "learner") == before
    assert PostgreSQLAuthRepository(auth_database).get_by_username("admin") is None
    # The failed transaction also releases its advisory/row locks for a valid retry.
    assert seed_users(auth_database, accounts()).created == ("admin",)


def test_concurrent_identical_seeders_create_only_two_accounts(
    auth_database: DatabaseSettings,
) -> None:
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(seed_users, auth_database, accounts()) for _ in range(2)]
        reports = [future.result(timeout=30) for future in futures]
    assert sorted(report.created for report in reports) == [(), ("admin", "learner")]
    assert sorted(report.existing for report in reports) == [(), ("admin", "learner")]
    with connect_database(auth_database) as connection:
        rows = connection.execute(
            "SELECT id, username, auth_version FROM regintel.users ORDER BY username"
        ).fetchall()
    assert len(rows) == 2
    assert all(isinstance(row[0], UUID) and row[0].version == 4 for row in rows)
    assert [row[1:] for row in rows] == [("admin", 1), ("learner", 1)]


@pytest.mark.parametrize("invalid_case", ["empty", "duplicate", "short", "large", "role", "name"])
def test_invalid_seeds_fail_before_opening_a_connection(
    auth_database: DatabaseSettings, monkeypatch: pytest.MonkeyPatch, invalid_case: str
) -> None:
    invalid = {
        "empty": (),
        "duplicate": (
            SeedAccount("ADMIN", SecretStr(PASSWORD), "admin"),
            SeedAccount(" admin ", SecretStr(PASSWORD), "admin"),
        ),
        "short": (SeedAccount("admin", SecretStr("x" * 15), "admin"),),
        "large": (SeedAccount("admin", SecretStr("é" * 513), "admin"),),
        "role": (SeedAccount("admin", SecretStr(PASSWORD), cast(Role, "reviewer")),),
        "name": (SeedAccount("admin' OR TRUE--", SecretStr(PASSWORD), "admin"),),
    }[invalid_case]

    def unexpected_connection(settings: DatabaseSettings) -> None:
        pytest.fail("Invalid seed input must be rejected before connecting to PostgreSQL.")

    monkeypatch.setattr("regintel.auth.repository.connect_database", unexpected_connection)
    with pytest.raises(ValueError):
        seed_users(auth_database, invalid)
    with connect_database(auth_database) as connection:
        assert connection.execute("SELECT count(*) FROM regintel.users").fetchone() == (0,)


@pytest.mark.parametrize(
    ("column", "invalid"),
    [
        ("username", "ab"),
        ("username", "Admin"),
        ("username", "admin name"),
        ("username", "admin\n"),
        ("username", "a" * 65),
        ("username", "éclair"),
        ("password_hash", "plaintext"),
        ("role", "reviewer"),
        ("auth_version", 0),
        ("auth_version", -1),
        ("auth_version", None),
        ("is_active", None),
    ],
)
def test_database_rejects_invalid_account_state(
    auth_database: DatabaseSettings, column: str, invalid: object
) -> None:
    values: dict[str, object] = {
        "username": "valid-user",
        "password_hash": hash_password(PASSWORD),
        "role": "learner",
        "is_active": True,
        "auth_version": 1,
    }
    values[column] = invalid
    with connect_database(auth_database) as connection, pytest.raises(psycopg.IntegrityError):
        connection.execute(
            "INSERT INTO regintel.users "
            "(id, username, password_hash, role, is_active, auth_version) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (uuid4(), *(values[key] for key in values)),
        )


def test_database_rejects_duplicate_canonical_username(auth_database: DatabaseSettings) -> None:
    seed_users(auth_database, (accounts()[0],))
    with (
        connect_database(auth_database) as connection,
        pytest.raises(psycopg.errors.UniqueViolation),
    ):
        connection.execute(
            "INSERT INTO regintel.users (id, username, password_hash, role) "
            "VALUES (%s, %s, %s, %s)",
            (uuid4(), "admin", hash_password(PASSWORD), "admin"),
        )


@pytest.mark.parametrize(
    "invalid_id",
    [
        UUID("aaaaaaaa-aaaa-1aaa-8aaa-aaaaaaaaaaaa"),
        UUID("aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa"),
        UUID("00000000-0000-0000-0000-000000000000"),
        UUID("aaaaaaaa-aaaa-4aaa-caaa-aaaaaaaaaaaa"),
    ],
    ids=["version1", "version7", "nil", "reserved-variant"],
)
def test_database_rejects_ids_outside_rfc_uuid4(
    auth_database: DatabaseSettings, invalid_id: UUID
) -> None:
    with (
        connect_database(auth_database) as connection,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        connection.execute(
            "INSERT INTO regintel.users (id, username, password_hash, role) "
            "VALUES (%s, %s, %s, %s)",
            (invalid_id, "valid-user", hash_password(PASSWORD), "learner"),
        )
    with connect_database(auth_database) as connection:
        assert connection.execute("SELECT count(*) FROM regintel.users").fetchone() == (0,)


def test_security_changes_increment_version_once_and_noop_preserves_version(
    auth_database: DatabaseSettings,
) -> None:
    seed_users(auth_database, (accounts()[0],))
    repository = PostgreSQLAuthRepository(auth_database)
    with connect_database(auth_database) as connection:
        connection.execute("UPDATE regintel.users SET role = role WHERE username = %s", ("admin",))
        assert connection.execute(
            "SELECT auth_version FROM regintel.users WHERE username = %s", ("admin",)
        ).fetchone() == (1,)
        connection.execute(
            "UPDATE regintel.users SET role = 'learner' WHERE username = %s", ("admin",)
        )
        connection.execute(
            "UPDATE regintel.users SET password_hash = %s WHERE username = %s",
            (hash_password(OTHER_PASSWORD), "admin"),
        )
        connection.execute(
            "UPDATE regintel.users SET is_active = FALSE WHERE username = %s", ("admin",)
        )
    changed = repository.get_by_username("admin")
    assert changed is not None
    assert changed.role == "learner" and changed.auth_version == 4 and not changed.is_active
    assert verify_password(OTHER_PASSWORD, changed.password_hash.get_secret_value())
    with connect_database(auth_database) as connection:
        connection.execute(
            "UPDATE regintel.users SET role = 'admin', is_active = TRUE, password_hash = %s "
            "WHERE username = %s",
            (hash_password(PASSWORD), "admin"),
        )
    changed = repository.get_by_username("admin")
    assert changed is not None
    assert changed.role == "admin" and changed.auth_version == 5 and changed.is_active
    with connect_database(auth_database) as connection:
        connection.execute(
            "UPDATE regintel.users SET auth_version = 10, role = 'learner' WHERE username = %s",
            ("admin",),
        )
    changed = repository.get_by_username("admin")
    assert changed is not None and changed.auth_version == 10


@pytest.mark.parametrize("invalid_version", [0, 9, None])
def test_version_cannot_decrease_or_be_null_even_during_security_change(
    auth_database: DatabaseSettings, invalid_version: int | None
) -> None:
    seed_users(auth_database, (accounts()[0],))
    with connect_database(auth_database) as connection:
        connection.execute(
            "UPDATE regintel.users SET auth_version = 10 WHERE username = %s", ("admin",)
        )
    before = snapshot(auth_database, "admin")
    with (
        connect_database(auth_database) as connection,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        connection.execute(
            "UPDATE regintel.users SET auth_version = %s, role = 'learner' WHERE username = %s",
            (invalid_version, "admin"),
        )
    assert snapshot(auth_database, "admin") == before
