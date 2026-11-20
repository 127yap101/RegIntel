"""Preservation checks discover current tables in an owned disposable database."""

import hashlib
import json
from decimal import Decimal

import psycopg
import pytest

from regintel.db import snapshot
from regintel.db.migrations import MigrationError, connect_database

pytestmark = pytest.mark.integration


def test_snapshot_includes_every_current_application_table_and_migration_history(auth_database):
    before = snapshot.snapshot_database(auth_database)
    with connect_database(auth_database) as connection:
        rows = connection.execute(
            "SELECT schemaname,tablename FROM pg_tables WHERE "
            "schemaname='regintel' OR (schemaname='regintel_meta' "
            "AND tablename='schema_migrations')"
        ).fetchall()
    assert set(before) == {f"{schema}.{name}" for schema, name in rows}
    assert {"regintel.learning_definitions", "regintel.portfolio_accounts"} <= before.keys()
    assert "regintel_meta.schema_migrations" in before
    assert len(before) > 37
    assert all(len(value) == 64 for value in before.values())
    assert snapshot.snapshot_database(auth_database) == before


def test_new_table_row_updates_duplicates_and_removal_change_the_snapshot(auth_database):
    before = snapshot.snapshot_database(auth_database)
    with connect_database(auth_database) as connection:
        connection.execute("CREATE TABLE regintel.snapshot_probe (amount NUMERIC, note TEXT)")
    empty = snapshot.snapshot_database(auth_database)
    key = "regintel.snapshot_probe"
    assert empty.keys() == before.keys() | {key}
    assert empty[key] == hashlib.sha256(b"").hexdigest()
    with connect_database(auth_database) as connection:
        connection.execute(
            "INSERT INTO regintel.snapshot_probe VALUES (%s,%s),(%s,%s)",
            (Decimal("1.10"), "line\nUnicode ₹", Decimal("2.20"), "second"),
        )
    populated = snapshot.snapshot_database(auth_database)
    assert populated[key] != empty[key]
    assert {name: value for name, value in populated.items() if name != key} == before
    with connect_database(auth_database) as connection:
        connection.execute("UPDATE regintel.snapshot_probe SET amount=3.30 WHERE amount=1.10")
    changed = snapshot.snapshot_database(auth_database)
    assert changed[key] != populated[key]
    with connect_database(auth_database) as connection:
        connection.execute(
            "INSERT INTO regintel.snapshot_probe SELECT * FROM regintel.snapshot_probe"
        )
    assert snapshot.snapshot_database(auth_database)[key] != changed[key]
    with connect_database(auth_database) as connection:
        connection.execute("DROP TABLE regintel.snapshot_probe")
    assert snapshot.snapshot_database(auth_database) == before


def test_digest_is_order_independent_and_uses_utf8_length_framing(auth_database):
    with connect_database(auth_database) as connection:
        connection.execute("CREATE TABLE regintel.snapshot_probe (value TEXT)")
        connection.execute("INSERT INTO regintel.snapshot_probe VALUES ('b'),('a'),('₹')")
    first = snapshot.snapshot_database(auth_database)
    digest = hashlib.sha256()
    for value in ("a", "b", "₹"):
        payload = json.dumps({"value": value}, ensure_ascii=False, separators=(",", ":")).encode()
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    assert first["regintel.snapshot_probe"] == digest.hexdigest()
    with connect_database(auth_database) as connection:
        connection.execute("DELETE FROM regintel.snapshot_probe")
        connection.execute("INSERT INTO regintel.snapshot_probe VALUES ('₹'),('a'),('b')")
    assert snapshot.snapshot_database(auth_database) == first


def test_snapshot_enforces_one_read_only_repeatable_read_transaction(auth_database, monkeypatch):
    with connect_database(auth_database) as connection:
        connection.execute("CREATE TABLE regintel.snapshot_probe (value TEXT)")
    read_history = snapshot._read_history

    def verify_transaction(connection):
        assert connection.execute("SHOW transaction_read_only").fetchone() == ("on",)
        assert connection.execute("SHOW transaction_isolation").fetchone() == ("repeatable read",)
        assert connection.execute("SHOW TimeZone").fetchone() == ("UTC",)
        assert connection.execute("SHOW row_security").fetchone() == ("off",)
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction), connection.transaction():
            connection.execute("INSERT INTO regintel.snapshot_probe VALUES ('must not persist')")
        return read_history(connection)

    monkeypatch.setattr(snapshot, "_read_history", verify_transaction)
    result = snapshot.snapshot_database(auth_database)
    assert result["regintel.snapshot_probe"] == hashlib.sha256(b"").hexdigest()


@pytest.mark.parametrize("change", ["missing_history", "incomplete_history", "changed_history"])
def test_invalid_or_incomplete_migration_history_cannot_produce_hashes(auth_database, change):
    with connect_database(auth_database) as connection:
        if change == "missing_history":
            connection.execute("DROP TABLE regintel_meta.schema_migrations")
        elif change == "incomplete_history":
            connection.execute("DELETE FROM regintel_meta.schema_migrations WHERE version=25")
        else:
            connection.execute("UPDATE regintel_meta.schema_migrations SET sha256=%s", ("0" * 64,))
    with pytest.raises((snapshot.SnapshotError, MigrationError)):
        snapshot.snapshot_database(auth_database)


def test_missing_application_schema_cannot_produce_a_preservation_claim(auth_database):
    with connect_database(auth_database) as connection:
        connection.execute("DROP SCHEMA regintel CASCADE")
    with pytest.raises(snapshot.SnapshotError, match="application tables"):
        snapshot.snapshot_database(auth_database)
