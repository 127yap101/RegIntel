"""Run live migration tests against a newly created, narrowly scoped local test database."""

import argparse
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from psycopg import sql

from regintel.db.config import load_database_settings
from regintel.db.migrations import MigrationError, connect_database


def report_test_failures(path: Path) -> None:
    """Expose bounded test identities in CI annotations, never failure payloads/secrets."""
    try:
        with path.open("rb") as stream:
            payload = stream.read(16 * 1024 * 1024 + 1)
        if len(payload) > 16 * 1024 * 1024:
            return
        root = ET.fromstring(payload)
    except (OSError, ET.ParseError):
        return
    failures = [
        case
        for case in root.iter("testcase")
        if case.find("failure") is not None or case.find("error") is not None
    ]
    for case in failures[:20]:
        # Parameter values, tracebacks, assertion text and captured output stay in
        # the local report. Only source-authored test identities enter annotations.
        identity = re.sub(
            r"[^A-Za-z0-9_.:\[\]-]",
            "?",
            case.get("classname", "") + "::" + case.get("name", "").split("[", 1)[0],
        )[:300]
        print("Integration test failure: " + identity, flush=True)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print("::error title=Integration test failed::" + identity, flush=True)


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
    parser.add_argument(
        "--junit-report",
        type=Path,
        help="XML report inside the project cache; expose failed test names to CI.",
    )
    options = parser.parse_args()
    junit_report = None
    if options.junit_report is not None:
        junit_report = (root / options.junit_report).resolve()
        if (
            not junit_report.is_relative_to((root / ".cache").resolve())
            or junit_report.suffix != ".xml"
        ):
            parser.error("The JUnit report must be an XML file inside the project cache.")
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
                *(["--junitxml", str(junit_report)] if junit_report is not None else []),
            ],
            env=test_environment,
            cwd=root,
            check=False,
        )
        exit_code = result.returncode
        if exit_code and junit_report is not None:
            report_test_failures(junit_report)
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
