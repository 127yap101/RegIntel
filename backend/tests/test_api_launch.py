"""Explicit assets, fail-closed schema and read-only native API configuration checks."""

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from regintel.auth import cli
from regintel.db.migrations import MigrationError, MigrationStatus


@dataclass(frozen=True)
class LaunchFiles:
    code: Path
    assets: Path


@pytest.fixture
def launch_files(tmp_path, monkeypatch):
    descriptor = (cli.ROOT / "data/parser-runtime-config.json").read_bytes()
    code, assets = tmp_path / "code", tmp_path / "original-assets"
    for root in (code, assets):
        (root / "data").mkdir(parents=True)
        (root / "data/parser-runtime-config.json").write_bytes(descriptor)
    (code / ".env").write_text(
        "REGINTEL_DATABASE_URL=postgresql://user:synthetic-db-secret@127.0.0.1:5432/selected\n"
        "REDIS_PASSWORD=syntheticredispassword\n",
        encoding="utf-8",
    )
    (code / ".env.auth").write_text("REGINTEL_JWT_SECRET=" + "ab" * 32 + "\n")
    # Asset selection must never load this unrelated environment file.
    (assets / ".env").write_text("REGINTEL_DATABASE_URL=unrelated-asset-secret\n")
    monkeypatch.setattr(cli, "ROOT", code)
    monkeypatch.setattr(cli, "migration_status", lambda _: MigrationStatus(tuple(range(1, 24)), ()))
    return LaunchFiles(code, assets)


def invoke(monkeypatch, *arguments):
    monkeypatch.setattr(sys, "argv", ["regintel-api", *map(str, arguments)])
    cli.serve_main()


def test_check_uses_explicit_assets_without_services_credentials_or_filesystem_writes(
    launch_files, monkeypatch, capsys
):
    before = {
        path: path.read_bytes() for path in launch_files.code.parent.rglob("*") if path.is_file()
    }

    def forbidden(*args, **kwargs):
        pytest.fail("Check-only mode must not start an application or broker.")

    monkeypatch.setattr(cli.uvicorn, "run", forbidden)
    from regintel.ingestion import broker

    monkeypatch.setattr(broker, "create_celery", forbidden)
    invoke(monkeypatch, "--check", "--asset-project", launch_files.assets)
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["status"] == "CONFIGURATION_VALIDATED"
    assert report["database_schema_version"] == 23
    assert report["asset_project"] == str(launch_files.assets)
    assert not report["source_directory_present"]
    assert not report["publication_model_directory_present"]
    assert not report["numerical_review_configured"]
    assert not report["live_services_checked"]
    assert not report["authentication_checked"]
    assert not report["content_approved"]
    assert "secret" not in output.out and not output.err
    after = {
        path: path.read_bytes() for path in launch_files.code.parent.rglob("*") if path.is_file()
    }
    assert before == after and not (launch_files.assets / "data/uploads").exists()


def test_default_assets_remain_the_code_checkout_and_presence_is_not_model_readiness(
    launch_files, monkeypatch, capsys
):
    (launch_files.code / "models/bge-small-en-v1.5").mkdir(parents=True)
    invoke(monkeypatch, "--check")
    report = json.loads(capsys.readouterr().out)
    assert report["asset_project"] == str(launch_files.code)
    assert report["publication_model_directory_present"]
    assert not report["live_services_checked"]


def test_numerical_review_requires_an_explicit_readable_descriptor(
    launch_files, monkeypatch, capsys
):
    descriptor = launch_files.assets / "data/parser-runtime-config.json"
    invoke(monkeypatch, "--check", "--numerical-runtime-file", descriptor)
    assert json.loads(capsys.readouterr().out)["numerical_review_configured"]
    with pytest.raises(SystemExit, match="configuration/schema check failed"):
        invoke(
            monkeypatch, "--check", "--numerical-runtime-file", descriptor.with_suffix(".missing")
        )
    assert not capsys.readouterr().out


def test_numerical_descriptor_must_match_installed_parser_code(launch_files, monkeypatch, capsys):
    descriptor = launch_files.assets / "data/parser-runtime-config.json"
    mismatched = json.loads(descriptor.read_bytes())
    mismatched["geometry_code_sha256"] = "0" * 64
    descriptor.write_text(json.dumps(mismatched))
    with pytest.raises(SystemExit, match="configuration/schema check failed"):
        invoke(monkeypatch, "--check", "--numerical-runtime-file", descriptor)
    assert not capsys.readouterr().out


@pytest.mark.parametrize("check_only", [False, True])
def test_old_schema_blocks_before_loading_assets_auth_or_serving(
    launch_files, monkeypatch, capsys, check_only
):
    monkeypatch.setattr(
        cli,
        "migration_status",
        lambda _: MigrationStatus(tuple(range(1, 12)), tuple(range(12, 24))),
    )
    (launch_files.code / ".env.auth").unlink()
    (launch_files.code / "data/parser-runtime-config.json").unlink()
    with pytest.raises(SystemExit, match="12 pending migrations") as captured:
        invoke(monkeypatch, *(["--check"] if check_only else []))
    assert "regintel-db migrate" in str(captured.value)
    assert "No migration was applied" in str(captured.value)
    assert not capsys.readouterr().out


def test_changed_history_diagnostics_cannot_leak_driver_or_configuration_secrets(
    launch_files, monkeypatch, capsys
):
    def broken(_):
        raise MigrationError("synthetic-driver-secret")

    monkeypatch.setattr(cli, "migration_status", broken)
    with pytest.raises(SystemExit, match="migration history; secrets omitted") as captured:
        invoke(monkeypatch, "--check")
    assert "synthetic-driver-secret" not in str(captured.value)
    assert not capsys.readouterr().out


@pytest.mark.parametrize("invalid", ["missing", "file", "descriptor", "code_identity", "auth"])
def test_invalid_asset_or_auth_configuration_fails_without_fallback_or_secret_output(
    launch_files, monkeypatch, capsys, invalid
):
    assets = launch_files.assets
    if invalid == "missing":
        assets = assets / "does-not-exist"
    elif invalid == "file":
        assets = assets / ".env"
    elif invalid == "descriptor":
        (assets / "data/parser-runtime-config.json").write_text("synthetic-invalid-private-value")
    elif invalid == "code_identity":
        path = assets / "data/parser-runtime-config.json"
        value = json.loads(path.read_bytes())
        value["adapter_code_sha256"] = "0" * 64
        path.write_text(json.dumps(value))
    else:
        (launch_files.code / ".env.auth").write_text(
            "REGINTEL_JWT_SECRET=synthetic-invalid-private-value"
        )
    with pytest.raises(SystemExit, match="configuration/schema check failed") as captured:
        invoke(monkeypatch, "--check", "--asset-project", assets)
    assert "synthetic-invalid-private-value" not in str(captured.value)
    assert "unrelated-asset-secret" not in str(captured.value)
    assert not capsys.readouterr().out


@pytest.mark.parametrize("port", [0, 65536])
def test_invalid_port_rejected_before_database_access(launch_files, monkeypatch, port):
    def forbidden(_):
        pytest.fail("Invalid command arguments must not connect to a database.")

    monkeypatch.setattr(cli, "migration_status", forbidden)
    with pytest.raises(SystemExit) as captured:
        invoke(monkeypatch, "--check", "--port", port)
    assert captured.value.code == 2


def test_actual_application_assembly_retains_loopback_and_uses_selected_source_storage(
    launch_files, monkeypatch
):
    captured = {}

    def serve(app, **options):
        captured.update(options)
        captured["paths"] = app.openapi()["paths"]

    monkeypatch.setattr(cli.uvicorn, "run", serve)
    invoke(monkeypatch, "--asset-project", launch_files.assets, "--port", 18000)
    assert captured["host"] == "127.0.0.1" and captured["port"] == 18000
    assert captured["access_log"] is False
    assert (launch_files.assets / "data/uploads").is_dir()
    assert not (launch_files.code / "data/uploads").exists()
    for path in ("/v1/filings", "/v1/compare", "/v1/learning/starter-pack", "/v1/portfolio/orders"):
        assert path in captured["paths"]
