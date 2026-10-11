"""Run live migration tests against a newly created, narrowly scoped local test database."""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from psycopg import sql

from regintel.db.config import load_database_settings
from regintel.db.migrations import MigrationError, connect_database


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Verify live contracts in a fresh disposable database."
    )
    parser.add_argument(
        "--test-file",
        type=Path,
        help="Explicitly select one integration test file; default runs all tests.",
    )
    options = parser.parse_args()
    selected = root / "backend/tests"
    if options.test_file is not None:
        candidate = (root / options.test_file).resolve()
        permitted = (root / "backend/tests/integration").resolve()
        if candidate.parent != permitted or not candidate.is_file() or candidate.suffix != ".py":
            parser.error("Selected tests must be an existing project integration Python file.")
        selected = candidate
    database_name = f"regintel_test_m0_3_{uuid4().hex}"
    created = False
    exit_code = 1
    try:
        settings = load_database_settings(root / ".env")
        uri = urlsplit(settings.database_url.get_secret_value())
        if uri.hostname != "127.0.0.1" or uri.port != 5432 or uri.path != "/regintel" or uri.query:
            raise ValueError("Use the generated project-local database configuration.")
        with connect_database(settings) as connection:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created = True
        test_url = urlunsplit(uri._replace(path=f"/{database_name}"))
        test_environment = os.environ.copy()
        test_environment["REGINTEL_TEST_DATABASE_URL"] = test_url
        # Each execution owns fresh cache paths, including across Windows security contexts.
        cache_root = (root / ".cache").resolve()
        test_temp = cache_root / f"migration-tmp-{uuid4().hex}"
        test_cache = cache_root / f"migration-cache-{uuid4().hex}"
        if test_temp.parent != cache_root or test_temp.exists():
            raise ValueError("The test temporary directory must be fresh inside the project cache.")
        print(
            f"Running live migration checks in newly created {database_name}.",
            flush=True,
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(selected),
                "-m",
                "integration",
                "--basetemp",
                str(test_temp),
                "-o",
                f"cache_dir={test_cache}",
            ],
            env=test_environment,
            cwd=root,
            check=False,
        )
        exit_code = result.returncode
    except (OSError, ValueError, psycopg.Error, MigrationError):
        print(
            "Live migration checks failed; connection secrets are omitted.",
            file=sys.stderr,
        )
    finally:
        if created:
            try:
                with connect_database(settings) as connection:
                    connection.execute(
                        sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name))
                    )
                print(
                    f"Removed only the newly created test database {database_name}.",
                    flush=True,
                )
            except (psycopg.Error, MigrationError, OSError, ValueError):
                print(
                    f"Test database retained for inspection: {database_name}.",
                    file=sys.stderr,
                )
                exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
