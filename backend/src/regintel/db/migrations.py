"""Small ordered SQL migration runner with immutable checksums and atomic batches."""

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import Connection, sql
from psycopg.conninfo import conninfo_to_dict

from regintel.db.config import DatabaseSettings

MIGRATION_NAME = re.compile(r"(?P<version>[0-9]{4})_(?P<name>[a-z][a-z0-9_]*)\.sql\Z")
# A stable signed-bigint key serializes migration runners in this database.
MIGRATION_LOCK_ID = 0x524547494E54454C
DEFAULT_MIGRATIONS = Path(__file__).resolve().parents[4] / "infra" / "migrations"
DatabaseConnection = Connection[tuple[object, ...]]


class MigrationError(Exception):
    """A safe diagnostic which never includes connection strings or SQL text."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    checksum: str
    statement: str


@dataclass(frozen=True)
class AppliedMigration:
    version: int
    name: str
    checksum: str


@dataclass(frozen=True)
class MigrationReport:
    already_applied: tuple[int, ...]
    newly_applied: tuple[int, ...]


@dataclass(frozen=True)
class MigrationStatus:
    applied: tuple[int, ...]
    pending: tuple[int, ...]


def load_migrations(directory: Path) -> tuple[Migration, ...]:
    if not directory.is_dir():
        raise MigrationError("The selected migration directory is missing.")
    result: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            raise MigrationError("Migration filenames must follow 0001_descriptive_name.sql.")
        version = int(match.group("version"))
        if version != len(result) + 1:
            raise MigrationError("Migration versions must be unique and consecutive from 0001.")
        try:
            contents = path.read_bytes()
            statement = contents.decode("utf-8")
        except (OSError, UnicodeError) as error:
            raise MigrationError("Migration files must be readable UTF-8 SQL.") from error
        if not statement.strip():
            raise MigrationError("Migration SQL must not be empty.")
        result.append(
            Migration(version, match.group("name"), hashlib.sha256(contents).hexdigest(), statement)
        )
    if not result:
        raise MigrationError("At least one ordered SQL migration is required.")
    return tuple(result)


def validate_history(
    migrations: tuple[Migration, ...], history: tuple[AppliedMigration, ...]
) -> None:
    available = {migration.version: migration for migration in migrations}
    for expected_version, applied in enumerate(history, start=1):
        if applied.version not in available:
            raise MigrationError("The database contains an unknown applied migration.")
        if applied.version != expected_version:
            raise MigrationError("Applied migration history has a gap or is out of order.")
        migration = available[applied.version]
        if applied.name != migration.name or applied.checksum != migration.checksum:
            raise MigrationError("An applied migration name or SHA-256 checksum has changed.")


def connect_database(settings: DatabaseSettings) -> DatabaseConnection:
    if psycopg.pq.version() < 160000:
        raise MigrationError("Foundation database commands require libpq 16 or newer.")
    if "PGSERVICE" in os.environ or "PGSERVICEFILE" in os.environ:
        raise MigrationError("Unset ambient libpq service selectors before database commands.")
    parameters = conninfo_to_dict(settings.database_url.get_secret_value())
    host = parameters["host"]
    host_address = parameters.get("hostaddr", "::1" if host == "::1" else "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"} or host_address not in {"127.0.0.1", "::1"}:
        raise MigrationError("Foundation database commands require an explicit loopback target.")
    return psycopg.connect(
        host=host,
        hostaddr=host_address,
        port=parameters["port"],
        dbname=parameters["dbname"],
        user=parameters["user"],
        password=parameters["password"],
        sslmode="disable",
        gssencmode="disable",
        require_auth="scram-sha-256",
        options="",
        application_name="regintel-foundation",
        autocommit=True,
        connect_timeout=5,
    )


def _read_history(connection: DatabaseConnection) -> tuple[AppliedMigration, ...]:
    existence = connection.execute(
        "SELECT to_regclass('regintel_meta.schema_migrations')"
    ).fetchone()
    if existence is None or existence[0] is None:
        return ()
    rows = connection.execute(
        "SELECT version, name, sha256 FROM regintel_meta.schema_migrations ORDER BY applied_order"
    ).fetchall()
    result: list[AppliedMigration] = []
    for version, name, checksum in rows:
        if (
            not isinstance(version, int)
            or not isinstance(name, str)
            or not isinstance(checksum, str)
        ):
            raise MigrationError("Applied migration metadata has invalid types.")
        result.append(AppliedMigration(version, name, checksum))
    return tuple(result)


def _create_ledger(connection: DatabaseConnection) -> None:
    connection.execute("CREATE SCHEMA IF NOT EXISTS regintel_meta")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS regintel_meta.schema_migrations (
            version INTEGER PRIMARY KEY CHECK (version > 0),
            name TEXT NOT NULL,
            sha256 TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            applied_order BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
        )
        """
    )


def _execute_migration(connection: DatabaseConnection, migration: Migration) -> None:
    # SPI rejects transaction-control SQL inside dynamic EXECUTE. This prevents a
    # migration's accidental COMMIT from escaping the batch or releasing its lock.
    # Quote both layers: a fixed dollar delimiter could collide with script text.
    body = sql.SQL("BEGIN EXECUTE {}; END;").format(sql.Literal(migration.statement))
    command = sql.SQL("DO {};").format(sql.Literal(body.as_string(connection)))
    connection.execute(command, prepare=False)


def migrate(settings: DatabaseSettings, directory: Path = DEFAULT_MIGRATIONS) -> MigrationReport:
    migrations = load_migrations(directory)
    try:
        with connect_database(settings) as connection, connection.transaction():
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK_ID,))
            _create_ledger(connection)
            history = _read_history(connection)
            validate_history(migrations, history)
            pending = migrations[len(history) :]
            for migration in pending:
                _execute_migration(connection, migration)
                connection.execute(
                    "INSERT INTO regintel_meta.schema_migrations (version, name, sha256) "
                    "VALUES (%s, %s, %s)",
                    (migration.version, migration.name, migration.checksum),
                )
            return MigrationReport(
                tuple(applied.version for applied in history),
                tuple(migration.version for migration in pending),
            )
    except psycopg.Error as error:
        raise MigrationError(
            f"Database migration failed (SQLSTATE {error.sqlstate or 'unavailable'}). "
            "Check local service availability, credentials and migration validity."
        ) from None


def migration_status(
    settings: DatabaseSettings, directory: Path = DEFAULT_MIGRATIONS
) -> MigrationStatus:
    migrations = load_migrations(directory)
    try:
        with connect_database(settings) as connection, connection.transaction():
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK_ID,))
            history = _read_history(connection)
            validate_history(migrations, history)
            return MigrationStatus(
                tuple(applied.version for applied in history),
                tuple(migration.version for migration in migrations[len(history) :]),
            )
    except psycopg.Error as error:
        raise MigrationError(
            f"Database status failed (SQLSTATE {error.sqlstate or 'unavailable'})."
        ) from None
