"""Explicit disposable database fixtures for live authentication storage checks."""

import os
from collections.abc import Iterator

import pytest
from pydantic import SecretStr

from regintel.db.config import DatabaseSettings, require_disposable_database
from regintel.db.migrations import connect_database, migrate


def clear_auth_test_schemas(settings: DatabaseSettings) -> None:
    require_disposable_database(settings)
    with connect_database(settings) as connection:
        if not connection.info.dbname.startswith(
            "regintel_test_"
        ) or connection.info.hostaddr not in {"127.0.0.1", "::1"}:
            pytest.fail("Connected integration target is not the disposable loopback database.")
        connection.execute("DROP SCHEMA IF EXISTS regintel_meta CASCADE")
        connection.execute("DROP SCHEMA IF EXISTS regintel CASCADE")
        connection.execute("DROP EXTENSION IF EXISTS vector CASCADE")


@pytest.fixture
def auth_database() -> Iterator[DatabaseSettings]:
    url = os.environ.get("REGINTEL_TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "Explicit integration requires REGINTEL_TEST_DATABASE_URL; it cannot be skipped."
        )
    settings = DatabaseSettings(database_url=SecretStr(url))
    require_disposable_database(settings)
    clear_auth_test_schemas(settings)
    try:
        migrate(settings)
        yield settings
    finally:
        clear_auth_test_schemas(settings)
