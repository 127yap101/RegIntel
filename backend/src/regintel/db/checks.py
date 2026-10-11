"""Authenticated foundation checks; vector distance is not financial arithmetic."""

from dataclasses import dataclass
from math import isclose

import psycopg

from regintel.db.config import DatabaseSettings
from regintel.db.migrations import MigrationError, connect_database


@dataclass(frozen=True)
class DatabaseCheck:
    postgres_version: str
    vector_version: str
    vector_distance: float


def check_database(
    settings: DatabaseSettings, expected_postgres: str = "16.15", expected_vector: str = "0.8.7"
) -> DatabaseCheck:
    try:
        with connect_database(settings) as connection:
            row = connection.execute(
                "SELECT current_setting('server_version'), "
                "(SELECT extversion FROM pg_extension WHERE extname = 'vector')"
            ).fetchone()
            if row is None:
                raise MigrationError("PostgreSQL or vector version metadata is missing.")
            postgres_version, vector_version = row
            if not isinstance(postgres_version, str) or not isinstance(vector_version, str):
                raise MigrationError("PostgreSQL or vector version metadata is missing.")
            if postgres_version.split()[0] != expected_postgres:
                raise MigrationError("PostgreSQL runtime does not match the expected pinned patch.")
            if vector_version != expected_vector:
                raise MigrationError("pgvector runtime does not match the expected pinned version.")
            distance_row = connection.execute(
                "SELECT '[0,0,0]'::vector <-> '[1,2,2]'::vector"
            ).fetchone()
            if (
                distance_row is None
                or not isinstance(distance_row[0], float)
                or not isclose(distance_row[0], 3.0, rel_tol=1e-12)
            ):
                raise MigrationError("pgvector distance verification failed.")
            return DatabaseCheck(postgres_version, vector_version, distance_row[0])
    except psycopg.Error as error:
        raise MigrationError(
            f"Database check failed (SQLSTATE {error.sqlstate or 'unavailable'})."
        ) from None
