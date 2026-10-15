"""Live M1.1 storage constraints; no upload, parser, worker or acceptance is exercised."""

import hashlib
import shutil
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from pydantic import SecretStr

from regintel.auth.repository import seed_users
from regintel.auth.types import SeedAccount
from regintel.db.config import DatabaseSettings, require_disposable_database
from regintel.db.migrations import (
    DEFAULT_MIGRATIONS,
    DatabaseConnection,
    MigrationError,
    connect_database,
    load_migrations,
    migrate,
    migration_status,
)

pytestmark = pytest.mark.integration
PREFIX = "Lead 😀 e\u0301\n"
QUOTE = "Helio Fixture Ltd owns 51% of Prism Fixture Pvt Ltd."
BLOCK_TEXT = PREFIX + QUOTE


@dataclass(frozen=True)
class StoredFixture:
    source: UUID
    filing: UUID
    version: UUID
    parse: UUID
    first_page: UUID
    second_page: UUID
    block: UUID
    table: UUID
    value_cell: UUID
    header_cell: UUID
    text_evidence: UUID
    cell_evidence: UUID


def insert_row(connection: DatabaseConnection, table: str, values: dict[str, object]) -> None:
    """Only caller-authored test identifiers are composed; all values remain parameters."""
    connection.execute(
        sql.SQL("INSERT INTO regintel.{} ({}) VALUES ({})").format(
            sql.Identifier(table),
            sql.SQL(", ").join(sql.Identifier(column) for column in values),
            sql.SQL(", ").join(sql.Placeholder() for _ in values),
        ),
        tuple(values.values()),
    )


def store_fixture(
    connection: DatabaseConnection, name: str = "first", *, quote: str = QUOTE, boxes: bool = True
) -> StoredFixture:
    with connection.transaction():
        return _store_fixture(connection, name, quote=quote, boxes=boxes)


def _store_fixture(
    connection: DatabaseConnection, name: str, *, quote: str = QUOTE, boxes: bool = True
) -> StoredFixture:
    identifiers = StoredFixture(*(uuid4() for _ in range(12)))
    source_bytes = f"Synthetic storage-only source {name}".encode()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    insert_row(
        connection,
        "source_blobs",
        {
            "id": identifiers.source,
            "sha256": source_hash,
            "byte_size": len(source_bytes),
            "storage_key": f"sha256/{source_hash}.pdf",
        },
    )
    insert_row(
        connection,
        "filings",
        {"id": identifiers.filing, "company_name_raw": "Helio Fixture Ltd"},
    )
    insert_row(
        connection,
        "filing_versions",
        {
            "id": identifiers.version,
            "filing_id": identifiers.filing,
            "source_blob_id": identifiers.source,
            "document_type": "RHP",
            "source_url": f"https://example.invalid/synthetic-{name}.pdf",
        },
    )
    insert_row(
        connection,
        "parse_versions",
        {
            "id": identifiers.parse,
            "filing_version_id": identifiers.version,
            "source_blob_id": identifiers.source,
            "adapter_name": "docling-fixture",
            "adapter_version": "fixture-only",
            "configuration_sha256": hashlib.sha256(b"synthetic configuration").hexdigest(),
            "artifact_sha256": hashlib.sha256(name.encode()).hexdigest(),
            "page_count": 2,
            "block_count": 1,
            "table_count": 1,
            "cell_count": 2,
            "evidence_count": 2,
        },
    )
    for page_index, page_id in enumerate((identifiers.first_page, identifiers.second_page)):
        insert_row(
            connection,
            "pages",
            {
                "id": page_id,
                "parse_version_id": identifiers.parse,
                "filing_version_id": identifiers.version,
                "page_index": page_index,
                "width": 612.0,
                "height": 792.0,
                "media_x0": -10.0,
                "media_y0": -20.0,
                "media_x1": 602.0,
                "media_y1": 772.0,
                "crop_x0": -5.0,
                "crop_y0": -15.0,
                "crop_x1": 595.0,
                "crop_y1": 765.0,
                "rotation": page_index * 90,
            },
        )
    insert_row(
        connection,
        "blocks",
        {
            "id": identifiers.block,
            "parse_version_id": identifiers.parse,
            "page_id": identifiers.first_page,
            "text": BLOCK_TEXT,
        },
    )
    insert_row(
        connection,
        "tables",
        {
            "id": identifiers.table,
            "parse_version_id": identifiers.parse,
            "first_page_id": identifiers.second_page,
            "row_count": 5,
            "column_count": 4,
        },
    )
    for cell_id, row_index, column_index, column_span, raw_text in (
        (identifiers.header_cell, 0, 1, 3, "INR lakh"),
        (identifiers.value_cell, 3, 1, 1, "100.00"),
    ):
        insert_row(
            connection,
            "cells",
            {
                "id": cell_id,
                "parse_version_id": identifiers.parse,
                "table_id": identifiers.table,
                "page_id": identifiers.second_page,
                "row_index": row_index,
                "column_index": column_index,
                "row_span": 1,
                "column_span": column_span,
                "raw_text": raw_text,
            },
        )
    insert_row(
        connection,
        "cell_context",
        {
            "cell_id": identifiers.value_cell,
            "parse_version_id": identifiers.parse,
            "table_id": identifiers.table,
            "context_cell_id": identifiers.header_cell,
            "role": "UNIT_HEADER",
        },
    )
    insert_row(
        connection,
        "evidence",
        {
            "id": identifiers.text_evidence,
            "parse_version_id": identifiers.parse,
            "filing_version_id": identifiers.version,
            "page_id": identifiers.first_page,
            "kind": "text",
            "block_id": identifiers.block,
            "start_offset": BLOCK_TEXT.index(quote),
            "end_offset": BLOCK_TEXT.index(quote) + len(quote),
            "quote": quote,
        },
    )
    insert_row(
        connection,
        "evidence",
        {
            "id": identifiers.cell_evidence,
            "parse_version_id": identifiers.parse,
            "filing_version_id": identifiers.version,
            "page_id": identifiers.second_page,
            "kind": "table_cell",
            "cell_id": identifiers.value_cell,
        },
    )
    for evidence_id in (identifiers.text_evidence, identifiers.cell_evidence) if boxes else ():
        insert_row(
            connection,
            "evidence_boxes",
            {
                "evidence_id": evidence_id,
                "box_index": 0,
                "x0": 30.0,
                "y0": 40.0,
                "x1": 300.0,
                "y1": 70.0,
            },
        )
    return identifiers


def clear_owned_schemas(settings: DatabaseSettings) -> None:
    require_disposable_database(settings)
    with connect_database(settings) as connection:
        assert connection.info.dbname.startswith("regintel_test_")
        assert connection.info.hostaddr in {"127.0.0.1", "::1"}
        connection.execute("DROP SCHEMA regintel_meta CASCADE")
        connection.execute("DROP SCHEMA regintel CASCADE")
        connection.execute("DROP EXTENSION vector CASCADE")


def prepare_auth_upgrade(
    settings: DatabaseSettings, directory: Path
) -> tuple[tuple[object, ...], ...]:
    directory.mkdir()
    clear_owned_schemas(settings)
    for filename in ("0001_foundation.sql", "0002_auth.sql"):
        shutil.copyfile(DEFAULT_MIGRATIONS / filename, directory / filename)
    assert migrate(settings, directory).newly_applied == (1, 2)
    seed_users(
        settings,
        (
            SeedAccount("admin", SecretStr("Synthetic storage admin 2026!"), "admin"),
            SeedAccount("learner", SecretStr("Synthetic storage learner 2026!"), "learner"),
        ),
    )
    with connect_database(settings) as connection:
        return tuple(
            connection.execute("SELECT * FROM regintel.users ORDER BY username").fetchall()
        )


def test_ingestion_upgrade_preserves_accounts_and_existing_checksums(
    auth_database: DatabaseSettings, tmp_path: Path
) -> None:
    accounts_before = prepare_auth_upgrade(auth_database, tmp_path / "auth-only")
    original_checksums = tuple(
        migration.checksum for migration in load_migrations(DEFAULT_MIGRATIONS)[:2]
    )
    report = migrate(auth_database)
    assert report.already_applied == (1, 2)
    assert report.newly_applied == tuple(
        migration.version for migration in load_migrations(DEFAULT_MIGRATIONS)[2:]
    )
    with connect_database(auth_database) as connection:
        assert (
            tuple(connection.execute("SELECT * FROM regintel.users ORDER BY username").fetchall())
            == accounts_before
        )
        assert (
            tuple(
                row[0]
                for row in connection.execute(
                    "SELECT sha256 FROM regintel_meta.schema_migrations "
                    "WHERE version <= 2 ORDER BY version"
                ).fetchall()
            )
            == original_checksums
        )
        assert connection.execute("SELECT count(*) FROM regintel.source_blobs").fetchone() == (0,)


def test_failed_ingestion_upgrade_rolls_back_new_schema_and_can_retry(
    auth_database: DatabaseSettings, tmp_path: Path
) -> None:
    directory = tmp_path / "upgrade"
    accounts_before = prepare_auth_upgrade(auth_database, directory)
    ingestion = next(path for path in DEFAULT_MIGRATIONS.glob("0003_*.sql"))
    copied = directory / ingestion.name
    shutil.copyfile(ingestion, copied)
    with copied.open("ab") as failed_migration:
        failed_migration.write(b"\nSELECT 1/0;\n")
    with pytest.raises(MigrationError, match="22012"):
        migrate(auth_database, directory)
    with connect_database(auth_database) as connection:
        assert (
            tuple(connection.execute("SELECT * FROM regintel.users ORDER BY username").fetchall())
            == accounts_before
        )
        assert connection.execute("SELECT to_regclass('regintel.source_blobs')").fetchone() == (
            None,
        )
    assert migration_status(auth_database).applied == (1, 2)
    shutil.copyfile(ingestion, copied)
    assert migrate(auth_database, directory).newly_applied == (3,)
    assert migration_status(auth_database, directory).pending == ()
    assert migration_status(auth_database).pending == tuple(
        migration.version for migration in load_migrations(DEFAULT_MIGRATIONS)[3:]
    )


@pytest.fixture
def stored(auth_database: DatabaseSettings) -> StoredFixture:
    with connect_database(auth_database) as connection:
        return store_fixture(connection)


def test_persisted_unicode_geometry_and_exact_evidence_keep_their_source_versions(
    auth_database: DatabaseSettings, stored: StoredFixture
) -> None:
    with connect_database(auth_database) as connection:
        assert connection.execute(
            "SELECT b.text, e.quote, e.start_offset, e.end_offset, "
            "e.parse_version_id, e.filing_version_id, e.page_id "
            "FROM regintel.evidence e JOIN regintel.blocks b ON b.id = e.block_id "
            "WHERE e.id = %s",
            (stored.text_evidence,),
        ).fetchone() == (
            BLOCK_TEXT,
            QUOTE,
            len(PREFIX),
            len(BLOCK_TEXT),
            stored.parse,
            stored.version,
            stored.first_page,
        )
        assert connection.execute(
            "SELECT page_index, width, height, media_x0, media_y0, media_x1, media_y1, "
            "crop_x0, crop_y0, crop_x1, crop_y1, rotation "
            "FROM regintel.pages WHERE parse_version_id = %s ORDER BY page_index",
            (stored.parse,),
        ).fetchall() == [
            (0, 612.0, 792.0, -10.0, -20.0, 602.0, 772.0, -5.0, -15.0, 595.0, 765.0, 0),
            (1, 612.0, 792.0, -10.0, -20.0, 602.0, 772.0, -5.0, -15.0, 595.0, 765.0, 90),
        ]
        assert connection.execute(
            "SELECT c.raw_text, h.raw_text, h.column_span, x.role "
            "FROM regintel.cell_context x "
            "JOIN regintel.cells c ON c.id = x.cell_id "
            "JOIN regintel.cells h ON h.id = x.context_cell_id "
            "WHERE x.cell_id = %s",
            (stored.value_cell,),
        ).fetchone() == ("100.00", "INR lakh", 3, "UNIT_HEADER")


@pytest.mark.parametrize(
    "changes",
    [
        {"quote": QUOTE.replace("51", "49")},
        {"start_offset": len(PREFIX) + 1, "end_offset": len(BLOCK_TEXT) + 1},
        {"end_offset": len(BLOCK_TEXT) + 1},
        {"start_offset": -1},
        {"start_offset": len(BLOCK_TEXT), "end_offset": len(BLOCK_TEXT)},
    ],
    ids=["equal-length-changed-quote", "shifted-slice", "past-block-end", "negative", "empty"],
)
def test_text_evidence_rejects_mismatched_actual_block_slices(
    auth_database: DatabaseSettings, stored: StoredFixture, changes: dict[str, object]
) -> None:
    values: dict[str, object] = {
        "id": uuid4(),
        "parse_version_id": stored.parse,
        "filing_version_id": stored.version,
        "page_id": stored.first_page,
        "kind": "text",
        "block_id": stored.block,
        "start_offset": len(PREFIX),
        "end_offset": len(BLOCK_TEXT),
        "quote": QUOTE,
    }
    values.update(changes)
    with (
        connect_database(auth_database) as connection,
        pytest.raises(psycopg.errors.CheckViolation) as failure,
        connection.transaction(),
    ):
        insert_row(connection, "evidence", values)
        insert_row(
            connection,
            "evidence_boxes",
            {
                "evidence_id": values["id"],
                "box_index": 0,
                "x0": 30.0,
                "y0": 40.0,
                "x1": 300.0,
                "y1": 70.0,
            },
        )
    if changes.get("start_offset") == -1:
        assert failure.value.diag.constraint_name == "safe_index_check"
    else:
        assert failure.value.diag.message_primary == (
            "Evidence quote must exactly match its immutable source span"
        )


def test_source_hash_identity_and_storage_key_are_enforced_by_the_database(
    auth_database: DatabaseSettings, stored: StoredFixture
) -> None:
    with connect_database(auth_database) as connection:
        existing = connection.execute(
            "SELECT sha256, byte_size, storage_key FROM regintel.source_blobs WHERE id = %s",
            (stored.source,),
        ).fetchone()
        assert existing is not None
        with pytest.raises(psycopg.errors.UniqueViolation):
            insert_row(
                connection,
                "source_blobs",
                {
                    "id": uuid4(),
                    "sha256": existing[0],
                    "byte_size": existing[1],
                    "storage_key": existing[2],
                },
            )
    for changes in (
        {"storage_key": "../outside.pdf"},
        {"storage_key": f"sha256/{'d' * 64}.pdf"},
        {"byte_size": 0},
        {"sha256": "E" * 64},
    ):
        values: dict[str, object] = {
            "id": uuid4(),
            "sha256": "e" * 64,
            "byte_size": 1,
            "storage_key": f"sha256/{'e' * 64}.pdf",
        }
        values.update(changes)
        with (
            connect_database(auth_database) as connection,
            pytest.raises(psycopg.errors.CheckViolation),
        ):
            insert_row(connection, "source_blobs", values)


def test_foreign_keys_reject_valid_ids_from_another_source_parse_or_page(
    auth_database: DatabaseSettings, stored: StoredFixture
) -> None:
    with connect_database(auth_database) as connection:
        other = store_fixture(connection, "second")
    examples: tuple[tuple[str, dict[str, object]], ...] = (
        (
            "parse_versions",
            {
                "id": uuid4(),
                "filing_version_id": stored.version,
                "source_blob_id": other.source,
                "adapter_name": "docling-fixture",
                "adapter_version": "fixture-only",
                "configuration_sha256": "a" * 64,
                "artifact_sha256": "b" * 64,
                "page_count": 1,
                "block_count": 0,
                "table_count": 0,
                "cell_count": 0,
                "evidence_count": 0,
            },
        ),
        (
            "blocks",
            {
                "id": uuid4(),
                "parse_version_id": stored.parse,
                "page_id": other.first_page,
                "text": "Unrelated source",
            },
        ),
        (
            "tables",
            {
                "id": uuid4(),
                "parse_version_id": stored.parse,
                "first_page_id": other.first_page,
                "row_count": 1,
                "column_count": 1,
            },
        ),
        (
            "cells",
            {
                "id": uuid4(),
                "parse_version_id": stored.parse,
                "table_id": other.table,
                "page_id": stored.second_page,
                "row_index": 0,
                "column_index": 0,
                "row_span": 1,
                "column_span": 1,
                "raw_text": "Wrong table",
            },
        ),
        (
            "cells",
            {
                "id": uuid4(),
                "parse_version_id": stored.parse,
                "table_id": stored.table,
                "page_id": other.second_page,
                "row_index": 1,
                "column_index": 0,
                "row_span": 1,
                "column_span": 1,
                "raw_text": "Wrong page",
            },
        ),
        (
            "cell_context",
            {
                "cell_id": stored.value_cell,
                "parse_version_id": stored.parse,
                "table_id": stored.table,
                "context_cell_id": other.header_cell,
                "role": "BASIS_HEADER",
            },
        ),
        (
            "evidence",
            {
                "id": uuid4(),
                "parse_version_id": stored.parse,
                "filing_version_id": other.version,
                "page_id": stored.first_page,
                "kind": "table_cell",
                "cell_id": stored.value_cell,
            },
        ),
        (
            "evidence",
            {
                "id": uuid4(),
                "parse_version_id": stored.parse,
                "filing_version_id": stored.version,
                "page_id": stored.first_page,
                "kind": "table_cell",
                "cell_id": stored.value_cell,
            },
        ),
        (
            "evidence",
            {
                "id": uuid4(),
                "parse_version_id": stored.parse,
                "filing_version_id": stored.version,
                "page_id": stored.second_page,
                "kind": "text",
                "block_id": stored.block,
                "start_offset": len(PREFIX),
                "end_offset": len(BLOCK_TEXT),
                "quote": QUOTE,
            },
        ),
    )
    for table, values in examples:
        with (
            connect_database(auth_database) as connection,
            pytest.raises(psycopg.errors.ForeignKeyViolation),
            connection.transaction(),
        ):
            insert_row(connection, table, values)


def test_cell_context_rejects_a_header_from_another_table_in_the_same_parse(
    auth_database: DatabaseSettings,
) -> None:
    # Use the creating transaction to check membership independently of sealing.
    with (
        connect_database(auth_database) as connection,
        pytest.raises(psycopg.errors.ForeignKeyViolation),
        connection.transaction(),
    ):
        stored = _store_fixture(connection, "header-membership")
        second_table, second_header = uuid4(), uuid4()
        insert_row(
            connection,
            "tables",
            {
                "id": second_table,
                "parse_version_id": stored.parse,
                "first_page_id": stored.second_page,
                "row_count": 1,
                "column_count": 1,
            },
        )
        insert_row(
            connection,
            "cells",
            {
                "id": second_header,
                "parse_version_id": stored.parse,
                "table_id": second_table,
                "page_id": stored.second_page,
                "row_index": 0,
                "column_index": 0,
                "row_span": 1,
                "column_span": 1,
                "raw_text": "INR crore",
            },
        )
        insert_row(
            connection,
            "cell_context",
            {
                "cell_id": stored.value_cell,
                "parse_version_id": stored.parse,
                "table_id": stored.table,
                "context_cell_id": second_header,
                "role": "UNIT_HEADER",
            },
        )


def test_cell_spans_must_fit_the_declared_table_dimensions(
    auth_database: DatabaseSettings, stored: StoredFixture
) -> None:
    for changes, expected_constraint in (
        ({"row_index": 4, "row_span": 2}, None),
        ({"column_index": 3, "column_span": 2}, None),
        ({"row_span": 0}, "positive_safe_integer_check"),
        ({"row_index": -1}, "safe_index_check"),
    ):
        values: dict[str, object] = {
            "id": uuid4(),
            "parse_version_id": stored.parse,
            "table_id": stored.table,
            "page_id": stored.second_page,
            "row_index": 4,
            "column_index": 0,
            "row_span": 1,
            "column_span": 1,
            "raw_text": "",
        }
        values.update(changes)
        with (
            connect_database(auth_database) as connection,
            pytest.raises(psycopg.errors.CheckViolation) as failure,
        ):
            insert_row(connection, "cells", values)
        if expected_constraint is not None:
            assert failure.value.diag.constraint_name == expected_constraint
        else:
            assert failure.value.diag.message_primary == (
                "Cell span exceeds its source table dimensions"
            )


def test_immutable_sources_parse_artifacts_and_evidence_refuse_update_or_delete(
    auth_database: DatabaseSettings, stored: StoredFixture
) -> None:
    examples = (
        ("source_blobs", "id", stored.source, "sha256"),
        ("filings", "id", stored.filing, "company_name_raw"),
        ("filing_versions", "id", stored.version, "published_on"),
        ("parse_versions", "id", stored.parse, "adapter_name"),
        ("pages", "id", stored.first_page, "width"),
        ("blocks", "id", stored.block, "text"),
        ("tables", "id", stored.table, "row_count"),
        ("cells", "id", stored.value_cell, "raw_text"),
        ("cell_context", "cell_id", stored.value_cell, "role"),
        ("evidence", "id", stored.text_evidence, "quote"),
        ("evidence_boxes", "evidence_id", stored.text_evidence, "x0"),
    )
    for table, key, identifier, column in examples:
        for statement in (
            sql.SQL("UPDATE regintel.{} SET {} = {} WHERE {} = %s").format(
                sql.Identifier(table),
                sql.Identifier(column),
                sql.Identifier(column),
                sql.Identifier(key),
            ),
            sql.SQL("DELETE FROM regintel.{} WHERE {} = %s").format(
                sql.Identifier(table), sql.Identifier(key)
            ),
        ):
            with (
                connect_database(auth_database) as connection,
                pytest.raises(psycopg.errors.CheckViolation),
            ):
                connection.execute(statement, (identifier,))
        with connect_database(auth_database) as connection:
            assert connection.execute(
                sql.SQL("SELECT count(*) FROM regintel.{} WHERE {} = %s").format(
                    sql.Identifier(table), sql.Identifier(key)
                ),
                (identifier,),
            ).fetchone() == (1,)


def test_evidence_box_support_is_atomic_bounded_and_cannot_be_appended_later(
    auth_database: DatabaseSettings, stored: StoredFixture
) -> None:
    malformed_boxes = (
        ({"box_index": 1}, None),
        ({"x0": -11.0}, None),
        ({"x0": 40.0, "x1": 40.0}, "evidence_boxes_check"),
    )
    for index, (changes, expected_constraint) in enumerate(malformed_boxes):
        with (
            connect_database(auth_database) as connection,
            pytest.raises(psycopg.errors.CheckViolation) as failure,
            connection.transaction(),
        ):
            # Both source evidence slots are unused in the new parse's creating
            # transaction. Neither a duplicate PK nor the sealing barrier can
            # account for rejection of the malformed text-evidence box below.
            fresh = _store_fixture(connection, f"malformed-box-{index}", boxes=False)
            cell_box: dict[str, object] = {
                "evidence_id": fresh.cell_evidence,
                "box_index": 0,
                "x0": 10.0,
                "y0": 20.0,
                "x1": 40.0,
                "y1": 50.0,
            }
            insert_row(connection, "evidence_boxes", cell_box)
            invalid_box = cell_box | {"evidence_id": fresh.text_evidence} | changes
            insert_row(connection, "evidence_boxes", invalid_box)
        if expected_constraint is not None:
            assert failure.value.diag.constraint_name == expected_constraint
        else:
            assert failure.value.diag.message_primary == (
                "Evidence box must occupy its declared source page and slot"
            )
        with connect_database(auth_database) as connection:
            assert connection.execute(
                "SELECT count(*) FROM regintel.parse_versions"
            ).fetchone() == (1,)
    with connect_database(auth_database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation, match="declared source page and slot"):
            insert_row(
                connection,
                "evidence_boxes",
                {
                    "evidence_id": stored.text_evidence,
                    "box_index": 1,
                    "x0": 10.0,
                    "y0": 20.0,
                    "x1": 40.0,
                    "y1": 50.0,
                },
            )
        missing_id = uuid4()
        with (
            pytest.raises(psycopg.errors.CheckViolation, match="completed parse"),
            connection.transaction(),
        ):
            insert_row(
                connection,
                "evidence",
                {
                    "id": missing_id,
                    "parse_version_id": stored.parse,
                    "filing_version_id": stored.version,
                    "page_id": stored.first_page,
                    "kind": "text",
                    "block_id": stored.block,
                    "start_offset": len(PREFIX),
                    "end_offset": len(BLOCK_TEXT),
                    "quote": QUOTE,
                },
            )
        assert connection.execute(
            "SELECT count(*) FROM regintel.evidence WHERE id = %s", (missing_id,)
        ).fetchone() == (0,)


def store_quantity(
    connection: DatabaseConnection, stored: StoredFixture, value: Decimal | None, raw_value: str
) -> UUID:
    identifier = uuid4()
    insert_row(
        connection,
        "quantitative_contexts",
        {
            "id": identifier,
            "parse_version_id": stored.parse,
            "raw_value": raw_value,
            "normalized_value": value,
            "period_kind": "UNKNOWN",
            "basis": "UNKNOWN",
        },
    )
    insert_row(
        connection,
        "quantitative_context_evidence",
        {
            "context_id": identifier,
            "parse_version_id": stored.parse,
            "evidence_id": stored.cell_evidence,
        },
    )
    return identifier


def test_numeric_storage_retains_decimal_precision_and_missing_values(
    auth_database: DatabaseSettings, stored: StoredFixture
) -> None:
    exact = Decimal("100.000000000000000000000000000001")
    with connect_database(auth_database) as connection, connection.transaction():
        identifier = store_quantity(connection, stored, exact, str(exact))
        missing = [store_quantity(connection, stored, None, raw) for raw in ("-", "")]
    with connect_database(auth_database) as connection:
        result = connection.execute(
            "SELECT normalized_value, pg_typeof(normalized_value)::text, raw_value "
            "FROM regintel.quantitative_contexts WHERE id = %s",
            (identifier,),
        ).fetchone()
        assert result == (exact, "numeric", str(exact))
        assert isinstance(result[0], Decimal)
        assert connection.execute(
            "SELECT raw_value, normalized_value, period_kind, basis, denominator, ownership_date "
            "FROM regintel.quantitative_contexts WHERE id = ANY(%s) ORDER BY raw_value",
            (missing,),
        ).fetchall() == [
            ("", None, "UNKNOWN", "UNKNOWN", None, None),
            ("-", None, "UNKNOWN", "UNKNOWN", None, None),
        ]


@pytest.mark.parametrize(
    "invalid",
    [
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Decimal("1e120"),
        Decimal("1e-121"),
    ],
)
def test_numeric_storage_rejects_nonfinite_and_out_of_contract_precision(
    auth_database: DatabaseSettings, stored: StoredFixture, invalid: Decimal
) -> None:
    with (
        connect_database(auth_database) as connection,
        pytest.raises(psycopg.errors.CheckViolation),
        connection.transaction(),
    ):
        store_quantity(connection, stored, invalid, "Synthetic invalid candidate value")


def test_quantity_and_candidate_evidence_cannot_cross_parse_boundaries(
    auth_database: DatabaseSettings, stored: StoredFixture
) -> None:
    with connect_database(auth_database) as connection:
        other = store_fixture(connection, "second")
    with connect_database(auth_database) as connection, connection.transaction():
        quantity = store_quantity(connection, stored, Decimal("100.00"), "100.00")
        candidate = uuid4()
        insert_row(
            connection,
            "candidates",
            {
                "id": candidate,
                "parse_version_id": stored.parse,
                "kind": "numeric_fact",
                "subject_entity_id": uuid4(),
                "metric_id": uuid4(),
                "raw_text": "100.00",
                "quantitative_context_id": quantity,
            },
        )
        insert_row(
            connection,
            "candidate_evidence",
            {
                "candidate_id": candidate,
                "parse_version_id": stored.parse,
                "evidence_id": stored.cell_evidence,
            },
        )
    for table, values in (
        (
            "quantitative_context_evidence",
            {
                "context_id": quantity,
                "parse_version_id": stored.parse,
                "evidence_id": other.cell_evidence,
            },
        ),
        (
            "candidate_evidence",
            {
                "candidate_id": candidate,
                "parse_version_id": stored.parse,
                "evidence_id": other.cell_evidence,
            },
        ),
        (
            "candidates",
            {
                "id": uuid4(),
                "parse_version_id": other.parse,
                "kind": "numeric_fact",
                "subject_entity_id": uuid4(),
                "metric_id": uuid4(),
                "raw_text": "100.00",
                "quantitative_context_id": quantity,
            },
        ),
    ):
        with (
            connect_database(auth_database) as connection,
            pytest.raises(psycopg.errors.ForeignKeyViolation),
            connection.transaction(),
        ):
            insert_row(connection, table, values)
    with connect_database(auth_database) as connection:
        assert connection.execute(
            "SELECT state FROM regintel.candidates WHERE id = %s", (candidate,)
        ).fetchone() == ("CANDIDATE",)


def test_unicode_quote_and_cross_page_support_persist_without_reinterpreting_source_text(
    auth_database: DatabaseSettings, stored: StoredFixture
) -> None:
    candidate = uuid4()
    with connect_database(auth_database) as connection:
        stored = store_fixture(connection, "unicode-prefix", quote=PREFIX)
    unicode_evidence = stored.text_evidence
    with connect_database(auth_database) as connection, connection.transaction():
        insert_row(
            connection,
            "candidates",
            {
                "id": candidate,
                "parse_version_id": stored.parse,
                "kind": "narrative_fact",
                "subject_entity_id": uuid4(),
                "metric_id": uuid4(),
                "raw_text": "Synthetic cross-page candidate; unvalidated",
                "evidence_count": 2,
            },
        )
        for evidence_id in (stored.text_evidence, stored.cell_evidence):
            insert_row(
                connection,
                "candidate_evidence",
                {
                    "candidate_id": candidate,
                    "parse_version_id": stored.parse,
                    "evidence_id": evidence_id,
                },
            )
    with connect_database(auth_database) as connection:
        assert connection.execute(
            "SELECT quote, end_offset, char_length(quote), octet_length(quote) "
            "FROM regintel.evidence WHERE id = %s",
            (unicode_evidence,),
        ).fetchone() == (PREFIX, len(PREFIX), len(PREFIX), len(PREFIX.encode()))
        assert connection.execute(
            "SELECT p.page_index FROM regintel.candidate_evidence c "
            "JOIN regintel.evidence e ON e.id = c.evidence_id "
            "JOIN regintel.pages p ON p.id = e.page_id "
            "WHERE c.candidate_id = %s ORDER BY p.page_index",
            (candidate,),
        ).fetchall() == [(0,), (1,)]
        assert connection.execute(
            "SELECT state FROM regintel.candidates WHERE id = %s", (candidate,)
        ).fetchone() == ("CANDIDATE",)


def test_new_parse_version_preserves_old_artifacts_and_has_its_own_page_indices(
    auth_database: DatabaseSettings, stored: StoredFixture
) -> None:
    next_parse, next_page = uuid4(), uuid4()
    with connect_database(auth_database) as connection, connection.transaction():
        insert_row(
            connection,
            "parse_versions",
            {
                "id": next_parse,
                "filing_version_id": stored.version,
                "source_blob_id": stored.source,
                "adapter_name": "docling-fixture",
                "adapter_version": "second-fixture-version",
                "configuration_sha256": "c" * 64,
                "artifact_sha256": "d" * 64,
                "page_count": 1,
                "block_count": 0,
                "table_count": 0,
                "cell_count": 0,
                "evidence_count": 0,
            },
        )
        connection.execute(
            "INSERT INTO regintel.pages "
            "(id, parse_version_id, filing_version_id, page_index, width, height, "
            "media_x0, media_y0, media_x1, media_y1, crop_x0, crop_y0, crop_x1, crop_y1, rotation) "
            "SELECT %s, %s, filing_version_id, page_index, width, height, "
            "media_x0, media_y0, media_x1, media_y1, crop_x0, crop_y0, crop_x1, crop_y1, rotation "
            "FROM regintel.pages WHERE id = %s",
            (next_page, next_parse, stored.first_page),
        )
        with pytest.raises(psycopg.errors.UniqueViolation), connection.transaction():
            connection.execute(
                "INSERT INTO regintel.pages "
                "SELECT %s, parse_version_id, filing_version_id, page_index, width, height, "
                "media_x0, media_y0, media_x1, media_y1, "
                "crop_x0, crop_y0, crop_x1, crop_y1, rotation, "
                "coordinate_space, origin FROM regintel.pages WHERE id = %s",
                (uuid4(), next_page),
            )
    with connect_database(auth_database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM regintel.parse_versions WHERE filing_version_id = %s",
            (stored.version,),
        ).fetchone() == (2,)
        assert connection.execute(
            "SELECT count(*) FROM regintel.pages WHERE parse_version_id = %s",
            (stored.parse,),
        ).fetchone() == (2,)
        assert connection.execute(
            "SELECT count(*) FROM regintel.evidence WHERE parse_version_id = %s",
            (stored.parse,),
        ).fetchone() == (2,)
        assert connection.execute(
            "SELECT page_index FROM regintel.pages WHERE parse_version_id = %s",
            (next_parse,),
        ).fetchone() == (0,)


def test_atomic_parse_tree_requires_declared_counts_and_box_support(
    auth_database: DatabaseSettings,
) -> None:
    with connect_database(auth_database) as connection:
        with (
            pytest.raises(psycopg.errors.CheckViolation, match="support"),
            connection.transaction(),
        ):
            _store_fixture(connection, "missing-boxes", boxes=False)
        assert connection.execute("SELECT count(*) FROM regintel.parse_versions").fetchone() == (0,)
        stored = store_fixture(connection)
        with pytest.raises(psycopg.errors.CheckViolation, match="declared artifact counts"):
            insert_row(
                connection,
                "parse_versions",
                {
                    "id": uuid4(),
                    "filing_version_id": stored.version,
                    "source_blob_id": stored.source,
                    "adapter_name": "incomplete",
                    "adapter_version": "fixture",
                    "configuration_sha256": "a" * 64,
                    "artifact_sha256": "b" * 64,
                    "page_count": 1,
                    "block_count": 0,
                    "table_count": 0,
                    "cell_count": 0,
                    "evidence_count": 0,
                },
            )


def test_completed_parse_cannot_gain_new_header_context(
    auth_database: DatabaseSettings,
    stored: StoredFixture,
) -> None:
    with connect_database(auth_database) as connection:
        with pytest.raises(psycopg.errors.CheckViolation, match="completed parse"):
            insert_row(
                connection,
                "cell_context",
                {
                    "cell_id": stored.value_cell,
                    "parse_version_id": stored.parse,
                    "table_id": stored.table,
                    "context_cell_id": stored.header_cell,
                    "role": "BASIS_HEADER",
                },
            )
        assert connection.execute(
            "SELECT count(*) FROM regintel.cell_context WHERE cell_id = %s",
            (stored.value_cell,),
        ).fetchone() == (1,)


@pytest.mark.parametrize(
    "table",
    ["corpus_versions", "acceptance_audits", "fact_observations", "relation_observations"],
)
def test_authoritative_inserts_require_approved_publication_transaction(
    auth_database: DatabaseSettings, table: str
) -> None:
    # The prerequisite guard fires before FK checks. UUID references are deliberate
    # placeholders: M1.1 must not be able to accept or publish an observation at all.
    anchor = {
        "id": uuid4(),
        "candidate_id": uuid4(),
        "parse_version_id": uuid4(),
        "acceptance_audit_id": uuid4(),
        "corpus_version_id": uuid4(),
        "subject_entity_id": uuid4(),
    }
    values_by_table: dict[str, dict[str, object]] = {
        "corpus_versions": {
            "id": uuid4(),
            "state": "BUILDING",
            "configuration_sha256": "a" * 64,
        },
        "acceptance_audits": {
            "id": uuid4(),
            "candidate_id": uuid4(),
            "parse_version_id": uuid4(),
            "actor_user_id": uuid4(),
            "decision": "ACCEPTED",
            "validator_configuration_sha256": "b" * 64,
        },
        "fact_observations": {
            **anchor,
            "kind": "narrative_fact",
            "metric_id": uuid4(),
            "raw_text": "Synthetic premature authoritative insertion",
        },
        "relation_observations": {
            **anchor,
            "object_entity_id": uuid4(),
            "relation_type": "OWNS",
        },
    }
    with (
        connect_database(auth_database) as connection,
        pytest.raises(psycopg.errors.CheckViolation, match="approved publication transaction"),
    ):
        insert_row(connection, table, values_by_table[table])
