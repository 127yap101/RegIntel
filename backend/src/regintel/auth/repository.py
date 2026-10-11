"""Parameterized PostgreSQL account reads and atomic, non-resetting local seeding."""

from uuid import UUID

import psycopg
from pydantic import SecretStr

from regintel.auth.errors import AuthUnavailable, SeedConflict
from regintel.auth.passwords import (
    MIN_SEED_PASSWORD_BYTES,
    hash_password,
    password_within_bounds,
    verify_password,
)
from regintel.auth.types import Role, SeedAccount, SeedReport, User, normalize_username
from regintel.db.config import DatabaseSettings
from regintel.db.migrations import MigrationError, connect_database

# A separate stable signed-bigint lock serializes seed transactions in this database.
SEED_LOCK_ID = 0x5245474155544853
USER_COLUMNS = "id, username, password_hash, role, is_active, auth_version"


def _user_from_row(row: tuple[object, ...]) -> User:
    if len(row) != 6:
        raise ValueError("Invalid authentication account state.")
    user_id, username, password_hash, raw_role, is_active, auth_version = row
    if (
        not isinstance(user_id, UUID)
        or user_id.version != 4
        or not isinstance(username, str)
        or normalize_username(username) != username
        or not isinstance(password_hash, str)
        or not password_hash.startswith("$argon2id$v=19$")
        or not isinstance(is_active, bool)
        or type(auth_version) is not int
        or auth_version <= 0
    ):
        raise ValueError("Invalid authentication account state.")
    role: Role
    if raw_role == "admin":
        role = "admin"
    elif raw_role == "learner":
        role = "learner"
    else:
        raise ValueError("Invalid authentication account state.")
    return User(user_id, username, SecretStr(password_hash), role, is_active, auth_version)


class PostgreSQLAuthRepository:
    def __init__(self, settings: DatabaseSettings) -> None:
        self._settings = settings

    def get_by_username(self, username: str) -> User | None:
        canonical = normalize_username(username)
        try:
            with connect_database(self._settings) as connection:
                row = connection.execute(
                    f"SELECT {USER_COLUMNS} FROM regintel.users WHERE username = %s",
                    (canonical,),
                ).fetchone()
                return _user_from_row(row) if row is not None else None
        except (psycopg.Error, MigrationError, ValueError):
            raise AuthUnavailable("Authentication storage is unavailable.") from None

    def get_by_id(self, user_id: UUID) -> User | None:
        try:
            with connect_database(self._settings) as connection:
                row = connection.execute(
                    f"SELECT {USER_COLUMNS} FROM regintel.users WHERE id = %s", (user_id,)
                ).fetchone()
                return _user_from_row(row) if row is not None else None
        except (psycopg.Error, MigrationError, ValueError):
            raise AuthUnavailable("Authentication storage is unavailable.") from None


def _prepare_seeds(seeds: tuple[SeedAccount, ...]) -> tuple[tuple[SeedAccount, str, str], ...]:
    if not seeds:
        raise ValueError("At least one seed account is required.")
    names: set[str] = set()
    validated: list[tuple[SeedAccount, str]] = []
    for seed in seeds:
        canonical = normalize_username(seed.username)
        password = seed.password.get_secret_value()
        if (
            canonical in names
            or seed.role not in {"admin", "learner"}
            or not password_within_bounds(password)
            or len(password.encode("utf-8")) < MIN_SEED_PASSWORD_BYTES
        ):
            raise ValueError("Seed accounts require distinct valid names and bounded passwords.")
        names.add(canonical)
        validated.append((seed, canonical))
    # Expensive hashing finishes before opening a connection or taking the DB lock.
    return tuple(
        (seed, canonical, hash_password(seed.password.get_secret_value()))
        for seed, canonical in validated
    )


def seed_users(settings: DatabaseSettings, seeds: tuple[SeedAccount, ...]) -> SeedReport:
    prepared = _prepare_seeds(seeds)
    created: list[str] = []
    existing: list[str] = []
    try:
        with connect_database(settings) as connection, connection.transaction():
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (SEED_LOCK_ID,))
            for seed, username, password_hash in prepared:
                row = connection.execute(
                    f"SELECT {USER_COLUMNS} FROM regintel.users WHERE username = %s FOR UPDATE",
                    (username,),
                ).fetchone()
                if row is not None:
                    user = _user_from_row(row)
                    if user.role != seed.role or not verify_password(
                        seed.password.get_secret_value(), user.password_hash.get_secret_value()
                    ):
                        raise SeedConflict("Existing seed account credentials or role conflict.")
                    existing.append(username)
                    continue
                connection.execute(
                    "INSERT INTO regintel.users (username, password_hash, role) "
                    "VALUES (%s, %s, %s)",
                    (username, password_hash, seed.role),
                )
                created.append(username)
            return SeedReport(tuple(created), tuple(existing))
    except (psycopg.Error, MigrationError, ValueError):
        raise AuthUnavailable("Authentication storage is unavailable.") from None
