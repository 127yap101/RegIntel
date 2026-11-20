"""Read-only current-schema row digests for bounded engineering preservation checks.

These digests detect changed rows and table inventory, not semantic equivalence
or a complete schema audit. They never export raw database rows.
"""

import hashlib

from psycopg import sql

from regintel.db.config import DatabaseSettings
from regintel.db.migrations import (
    DEFAULT_MIGRATIONS,
    _read_history,
    connect_database,
    load_migrations,
    validate_history,
)

SNAPSHOT_VERSION = "current-database-rows-1"


class SnapshotError(ValueError):
    """Fixed preservation-check diagnostics without connection or row contents."""


def snapshot_database(settings: DatabaseSettings) -> dict[str, str]:
    """Hash all current application tables and migration history in one snapshot.

    Catalog discovery is not filtered by SELECT privilege. A missing permission
    or row-security policy therefore fails rather than silently omitting state.
    The caller compares both keys and hashes before/after its read operation.
    """
    migrations = load_migrations(DEFAULT_MIGRATIONS)
    result: dict[str, str] = {}
    with connect_database(settings) as connection, connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        connection.execute("SET LOCAL TIME ZONE 'UTC'")
        connection.execute("SET LOCAL DateStyle = 'ISO, YMD'")
        connection.execute("SET LOCAL bytea_output = 'hex'")
        connection.execute("SET LOCAL row_security = off")
        history = _read_history(connection)
        validate_history(migrations, history)
        if len(history) != len(migrations):
            raise SnapshotError("Preservation checks require the complete current schema history.")
        tables = connection.execute(
            "SELECT n.nspname, c.relname, c.relkind FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
            "WHERE (n.nspname='regintel' OR "
            "(n.nspname='regintel_meta' AND c.relname='schema_migrations')) "
            "AND c.relkind IN ('r', 'p', 'f') ORDER BY n.nspname, c.relname"
        ).fetchall()
        if not any(row[0] == "regintel" for row in tables) or not any(
            row[:2] == ("regintel_meta", "schema_migrations") for row in tables
        ):
            raise SnapshotError(
                "Preservation checks require application tables and schema history."
            )
        for schema, table, kind in tables:
            if not isinstance(schema, str) or not isinstance(table, str) or kind not in ("r", "p"):
                raise SnapshotError("Preservation checks require readable local base tables.")
            digest = hashlib.sha256()
            query = sql.SQL(
                'SELECT row_to_json(t)::TEXT FROM {} t ORDER BY row_to_json(t)::TEXT COLLATE "C"'
            ).format(sql.Identifier(schema, table))
            # A named cursor fetches bounded batches rather than retaining each
            # table's complete JSON representation in application memory.
            with connection.cursor(name="regintel_preservation_rows") as cursor:
                cursor.execute(query)
                for row in cursor:
                    if len(row) != 1 or not isinstance(row[0], str):
                        raise SnapshotError("Preservation checks received an invalid row encoding.")
                    payload = row[0].encode("utf-8")
                    digest.update(len(payload).to_bytes(8, "big"))
                    digest.update(payload)
            result[f"{schema}.{table}"] = digest.hexdigest()
    return result
