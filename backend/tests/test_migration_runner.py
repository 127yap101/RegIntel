"""Disposable migration checks can read an existing config without changing its source."""

import importlib.util
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from psycopg import sql

from regintel.db.config import DatabaseSettings

REPOSITORY = Path(__file__).resolve().parents[2]
LOCAL_URL = "postgresql://runner:synthetic-private@127.0.0.1:5432/regintel"


@pytest.fixture
def runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "regintel_migration_runner_tests", REPOSITORY / "scripts/check-migrations.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "clone"
    (root / "scripts").mkdir(parents=True)
    monkeypatch.setattr(module, "__file__", str(root / "scripts/check-migrations.py"))
    return module


@pytest.fixture
def statements(runner: ModuleType, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    recorded: list[str] = []

    class Connection:
        def execute(self, statement: sql.Composed) -> None:
            recorded.append(statement.as_string())

    @contextmanager
    def connect(settings: DatabaseSettings) -> Iterator[Connection]:
        assert settings.database_url.get_secret_value() == LOCAL_URL
        yield Connection()

    monkeypatch.setattr(runner, "connect_database", connect)
    return recorded


@pytest.mark.parametrize("selection", ["default", "absolute", "relative"])
@pytest.mark.parametrize("pytest_result", [0, 5])
def test_selected_config_is_read_only_and_only_owned_database_is_created_and_dropped(
    runner: ModuleType,
    statements: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    selection: str,
    pytest_result: int,
) -> None:
    root = Path(runner.__file__).resolve().parents[1]
    source = root / ".env" if selection == "default" else tmp_path / "existing.env"
    contents = f"# Preserve original configuration\nREGINTEL_DATABASE_URL={LOCAL_URL}\n"
    source.write_text(contents, encoding="utf-8")
    before = source.read_bytes(), source.stat().st_mtime_ns
    monkeypatch.chdir(tmp_path)
    argv = ["check-migrations.py"]
    if selection != "default":
        argv.extend(["--env-file", str(source) if selection == "absolute" else source.name])
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setenv("REGINTEL_DATABASE_URL", "ignored-ambient-private")
    run = Mock(return_value=subprocess.CompletedProcess([], pytest_result))
    monkeypatch.setattr(runner.subprocess, "run", run)

    assert runner.main() == pytest_result

    assert (source.read_bytes(), source.stat().st_mtime_ns) == before
    assert sorted(path for path in tmp_path.rglob("*") if path.is_file()) == [source]
    assert run.call_count == 1
    arguments, options = run.call_args
    assert arguments[0][:3] == [sys.executable, "-m", "pytest"]
    assert options["cwd"] == root
    assert options["check"] is False
    test_url = urlsplit(options["env"]["REGINTEL_TEST_DATABASE_URL"])
    database_name = test_url.path.removeprefix("/")
    assert database_name.startswith("regintel_test_m0_3_")
    assert test_url.hostname == "127.0.0.1" and test_url.port == 5432
    assert statements == [
        f'CREATE DATABASE "{database_name}"',
        f'DROP DATABASE "{database_name}"',
    ]
    output = capsys.readouterr()
    assert "synthetic-private" not in output.out + output.err
    assert "ignored-ambient-private" not in output.out + output.err


@pytest.mark.parametrize(
    "configured_url",
    [
        None,
        "invalid-private-value",
        "postgresql://runner:synthetic-private@127.0.0.1:invalid/regintel",
        "postgresql://runner:synthetic-private@remote.example:5432/regintel",
        "postgresql://runner:synthetic-private@localhost:5432/regintel",
        "postgresql://runner:synthetic-private@127.0.0.1:6432/regintel",
        "postgresql://runner:synthetic-private@127.0.0.1:5432/existing_other_database",
        LOCAL_URL + "?host=remote.example",
        LOCAL_URL + "?hostaddr=192.0.2.1",
        LOCAL_URL + "?dbname=existing_other_database",
    ],
)
def test_invalid_selected_target_is_rejected_before_connection_or_pytest(
    runner: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    configured_url: str | None,
) -> None:
    source = tmp_path / "existing.env"
    if configured_url is not None:
        source.write_text(f"REGINTEL_DATABASE_URL={configured_url}\n", encoding="utf-8")
    before = (source.read_bytes(), source.stat().st_mtime_ns) if source.exists() else None
    monkeypatch.setattr(sys, "argv", ["check-migrations.py", "--env-file", str(source)])
    connect = Mock(side_effect=AssertionError("Must reject before a database connection"))
    run = Mock(side_effect=AssertionError("Must reject before starting pytest"))
    monkeypatch.setattr(runner, "connect_database", connect)
    monkeypatch.setattr(runner.subprocess, "run", run)

    assert runner.main() == 1

    connect.assert_not_called()
    run.assert_not_called()
    after = (source.read_bytes(), source.stat().st_mtime_ns) if source.exists() else None
    assert after == before
    output = capsys.readouterr()
    assert "connection secrets are omitted" in output.err
    assert "private" not in output.out + output.err


def test_pytest_launch_failure_still_drops_only_its_created_database(
    runner: ModuleType,
    statements: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "existing.env"
    source.write_text(f"REGINTEL_DATABASE_URL={LOCAL_URL}\n", encoding="utf-8")
    before = source.read_bytes(), source.stat().st_mtime_ns
    monkeypatch.setattr(sys, "argv", ["check-migrations.py", "--env-file", str(source)])
    monkeypatch.setattr(
        runner.subprocess, "run", Mock(side_effect=OSError("private process failure"))
    )

    assert runner.main() == 1

    assert len(statements) == 2
    assert statements[0].startswith('CREATE DATABASE "regintel_test_m0_3_')
    assert statements[1] == statements[0].replace("CREATE DATABASE", "DROP DATABASE", 1)
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before
    output = capsys.readouterr()
    assert "private" not in output.out + output.err
