from pathlib import Path

import psycopg
import pytest
from pydantic import SecretStr, ValidationError

from regintel.db.cli import main
from regintel.db.config import (
    DatabaseSettings,
    load_database_settings,
    require_disposable_database,
)
from regintel.db.migrations import DatabaseConnection, connect_database


def test_database_settings_do_not_implicitly_read_process_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REGINTEL_DATABASE_URL", "postgresql://user:secret@localhost/implicit")
    with pytest.raises(ValidationError):
        DatabaseSettings()


def test_explicit_env_file_wins_and_settings_hide_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    selected = "postgresql://user:unique-secret@localhost:5432/selected"
    env_file.write_text(f"REGINTEL_DATABASE_URL={selected}\nPOSTGRES_PASSWORD=other\n")
    monkeypatch.setenv("REGINTEL_DATABASE_URL", "postgresql://user:other@localhost:5432/unrelated")
    settings = load_database_settings(env_file)
    assert settings.database_url.get_secret_value() == selected
    assert "unique-secret" not in repr(settings)
    assert "unique-secret" not in settings.model_dump_json()


@pytest.mark.parametrize(
    "connection_string",
    (
        "sqlite:///database.db",
        "postgresql://user:private@localhost",
        "postgresql://user:private@localhost:0/database",
        "postgresql://user:private@localhost:invalid/database",
        "postgresql://localhost/database",
        "postgresql://user@localhost:5432/database",
        "postgresql://user:private@localhost:5432/database?dbname=",
        "postgresql://user:private@localhost:5432/database?user=",
        "postgresql://user:private@localhost/database#fragment",
    ),
)
def test_database_url_validation_hides_input(connection_string: str) -> None:
    with pytest.raises(ValidationError) as captured:
        DatabaseSettings(database_url=SecretStr(connection_string))
    assert "private" not in str(captured.value)


def test_cli_configuration_failure_has_nonzero_result_and_no_secret(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("REGINTEL_DATABASE_URL=invalid-private-value\n")
    assert main(["migrate", "--env-file", str(env_file)]) == 1
    output = capsys.readouterr()
    assert "invalid-private-value" not in output.err
    assert "invalid" in output.err


def test_cli_connection_failure_does_not_print_driver_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("REGINTEL_DATABASE_URL=postgresql://user:private@localhost:5432/database\n")

    def unavailable_connection(settings: DatabaseSettings) -> DatabaseConnection:
        raise psycopg.OperationalError("Driver included private credential in error text")

    monkeypatch.setattr("regintel.db.migrations.connect_database", unavailable_connection)
    assert main(["migrate", "--env-file", str(env_file)]) == 1
    output = capsys.readouterr()
    assert "private" not in output.err
    assert "unavailable" in output.err


@pytest.mark.parametrize(
    "url",
    (
        "postgresql://user:private@localhost:5432/main",
        "postgresql://user:private@remote:5432/regintel_test_safe",
        "postgresql://user:private@localhost:5432/regintel_test_safe?dbname=main",
        "postgresql://user:private@localhost:5432/regintel_test_safe?host=remote",
        "postgresql://user:private@localhost:5432/regintel_test_safe?hostaddr=192.0.2.1",
    ),
)
def test_disposable_database_guard_checks_effective_libpq_target(url: str) -> None:
    with pytest.raises(ValueError, match="disposable"):
        require_disposable_database(DatabaseSettings(database_url=SecretStr(url)))


def test_cli_refuses_ambient_service_file_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("REGINTEL_DATABASE_URL=postgresql://user:private@localhost:5432/database\n")
    monkeypatch.setenv("PGSERVICE", "unrelated-private-service")
    assert main(["migrate", "--env-file", str(env_file)]) == 1
    output = capsys.readouterr()
    assert "service selectors" in output.err
    assert "unrelated-private-service" not in output.err


def test_explicit_env_file_does_not_expand_ambient_database_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("REGINTEL_DATABASE_URL=${OTHER_DATABASE_URL}\n")
    monkeypatch.setenv(
        "OTHER_DATABASE_URL", "postgresql://user:ambient-private@127.0.0.1:5432/unrelated"
    )
    with pytest.raises(ValidationError) as captured:
        load_database_settings(env_file)
    assert "ambient-private" not in str(captured.value)


def test_connection_requires_scram_and_passes_explicit_local_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, object]] = []

    def capture_connection(**kwargs: object) -> DatabaseConnection:
        captured.append(kwargs)
        raise RuntimeError("Synthetic connection capture; no network operation")

    monkeypatch.delenv("PGSERVICE", raising=False)
    monkeypatch.delenv("PGSERVICEFILE", raising=False)
    monkeypatch.setenv("PGHOSTADDR", "192.0.2.1")
    monkeypatch.setenv("PGPORT", "6432")
    monkeypatch.setenv("PGPASSWORD", "unrelated-private")
    monkeypatch.setattr("regintel.db.migrations.psycopg.connect", capture_connection)
    settings = DatabaseSettings(
        database_url=SecretStr("postgresql://user:explicit-private@localhost:5432/selected")
    )
    with pytest.raises(RuntimeError, match="Synthetic"):
        connect_database(settings)
    assert captured[0]["require_auth"] == "scram-sha-256"
    assert captured[0]["hostaddr"] == "127.0.0.1"
    assert captured[0]["port"] == "5432"
    assert captured[0]["user"] == "user"
    assert captured[0]["dbname"] == "selected"
    assert captured[0]["password"] == "explicit-private"
