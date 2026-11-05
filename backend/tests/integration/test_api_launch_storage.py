"""Owned populated schema upgrade and real CLI assembly through the four module APIs."""

import hashlib
import json
import sys
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import SecretStr

from backend.tests.integration.conftest import clear_auth_test_schemas
from backend.tests.integration.test_evidence_storage import context, parsed, persist
from backend.tests.integration.test_publication_storage import configuration, prepared
from backend.tests.integration.test_publication_storage import publication as publication
from backend.tests.integration.test_validation_storage import validated as validated
from regintel.analysis.models import ComparisonRequest
from regintel.auth import cli
from regintel.auth.repository import seed_users
from regintel.auth.types import SeedAccount
from regintel.db.migrations import DEFAULT_MIGRATIONS, connect_database, migrate, migration_status

pytestmark = pytest.mark.integration


def snapshot(database, columns=None):
    with connect_database(database) as connection, connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        if columns is None:
            columns = {}
            for table, column in connection.execute(
                "SELECT table_name,column_name FROM information_schema.columns "
                "WHERE table_schema='regintel' ORDER BY table_name,ordinal_position"
            ).fetchall():
                columns.setdefault(table, []).append(column)
        result = {}
        for table, names in columns.items():
            rows = connection.execute(
                sql.SQL(
                    "SELECT row_to_json(t)::TEXT FROM (SELECT {} FROM {}) t "
                    "ORDER BY row_to_json(t)::TEXT"
                ).format(
                    sql.SQL(",").join(map(sql.Identifier, names)), sql.Identifier("regintel", table)
                )
            ).fetchall()
            result[table] = hashlib.sha256(json.dumps(rows).encode()).hexdigest()
    return columns, result


def test_populated_m1_upgrade_preserves_old_columns_and_assembles_current_module_apis(
    auth_database, tmp_path, monkeypatch, capsys, request
):
    clear_auth_test_schemas(auth_database)
    old = tmp_path / "schema-11"
    old.mkdir()
    files = sorted(DEFAULT_MIGRATIONS.glob("*.sql"))[:11]
    assert len(files) == 11
    for file in files:
        (old / file.name).write_bytes(file.read_bytes())
    migrate(auth_database, old)
    existing = context(auth_database)
    with connect_database(auth_database) as connection, connection.transaction():
        persist(connection, existing)
        parsed(connection, existing)
        original_artifact = connection.execute(
            "SELECT artifact_bytes,configuration_bytes FROM regintel.parse_artifacts "
            "WHERE parse_version_id=%s",
            (existing.artifact.id,),
        ).fetchone()
        assert original_artifact is not None
    original_columns, before = snapshot(auth_database)
    source = tmp_path / "existing-assets"
    (source / "data").mkdir(parents=True)
    (source / "data/parser-runtime-config.json").write_bytes(
        (cli.ROOT / "data/parser-runtime-config.json").read_bytes()
    )
    environment = tmp_path / "selected.env"
    environment.write_text(
        "REGINTEL_DATABASE_URL="
        + auth_database.database_url.get_secret_value()
        + "\nREDIS_PASSWORD=syntheticredispassword\n",
        encoding="utf-8",
    )
    authentication = tmp_path / "selected.auth"
    authentication.write_text("REGINTEL_JWT_SECRET=" + "ab" * 32 + "\n")
    arguments = [
        "regintel-api",
        "--env-file",
        str(environment),
        "--auth-env-file",
        str(authentication),
        "--asset-project",
        str(source),
    ]
    monkeypatch.setattr(sys, "argv", [*arguments, "--check"])
    with pytest.raises(SystemExit, match="12 pending migrations"):
        cli.serve_main()
    assert snapshot(auth_database, original_columns)[1] == before
    assert migration_status(auth_database, old).applied == tuple(range(1, 12))
    assert not (source / "data/uploads").exists()
    migrate(auth_database)
    assert snapshot(auth_database, original_columns)[1] == before
    all_columns, upgraded = snapshot(auth_database)
    cli.serve_main()
    report = json.loads(capsys.readouterr().out)
    assert report["database_schema_version"] == 23
    assert not report["authentication_checked"] and not report["content_approved"]
    assert snapshot(auth_database, all_columns)[1] == upgraded
    assert not (source / "data/uploads").exists()

    # Publish authored engineering evidence through the existing full workflow,
    # independently of the configuration check and the retained old source.
    repository, user, proposed = request.getfixturevalue("publication")
    manifest = repository.build(proposed, configuration(), user)
    repository.finalize(manifest.id, configuration(), user, prepared(repository, user, manifest))
    password = "Synthetic runtime learner password!"
    seed_users(auth_database, (SeedAccount("learner", SecretStr(password), "learner"),))
    applications = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: applications.append(app))
    monkeypatch.setattr(sys, "argv", arguments)
    cli.serve_main()
    assert len(applications) == 1 and (source / "data/uploads").is_dir()
    assert not (source / "models").exists()
    with TestClient(applications[0]) as client:
        authenticated = client.post(
            "/v1/auth/token",
            data={
                "username": "learner",
                "password": password,
                "grant_type": "password",
            },
        )
        assert authenticated.status_code == 200
        headers = {"Authorization": "Bearer " + authenticated.json()["access_token"]}
        companies = client.get(
            "/v1/companies", headers=headers, params={"corpus_version_id": manifest.id}
        )
        assert companies.status_code == 200
        ids = tuple(item["id"] for item in companies.json()["data"]["companies"])
        assert len(ids) == 2
        numeric = next(item for item in manifest.observations if item.quantity is not None)
        compared = client.post(
            "/v1/compare",
            headers=headers,
            json=ComparisonRequest(
                corpus_version_id=manifest.id,
                company_ids=ids,
                metric_ids=(numeric.metric_id,),
                period=numeric.quantity.period,
                basis=numeric.quantity.basis,
            ).model_dump(mode="json"),
        )
        assert compared.status_code == 200
        assert {cell["state"] for cell in compared.json()["data"]["rows"][0]["cells"]} == {
            "AVAILABLE",
            "MISSING",
        }
        learned = client.get("/v1/learning/status", headers=headers)
        assert learned.status_code == 200 and learned.json()["data"]["glossary_version_id"] is None
        opened = client.post("/v1/portfolio/accounts", headers=headers, json={})
        assert opened.status_code == 200 and opened.json()["data"]["state"]["cash"] == "100000.00"
        rejected = client.post(
            "/v1/portfolio/orders",
            headers=headers,
            json={
                "request_id": str(uuid4()),
                "corpus_version_id": manifest.id,
                "company_id": ids[0],
                "side": "BUY",
                "quantity": 1,
            },
        )
        assert rejected.status_code == 200
        assert rejected.json()["data"]["entry"]["evaluation"]["reason"] == "QUOTES_UNAVAILABLE"
        assert (
            client.get("/v1/portfolio", headers=headers).json()["data"]["state"]["cash"]
            == "100000.00"
        )
    # Module tests must not rewrite any pre-upgrade source/evidence values.
    with connect_database(auth_database) as connection:
        retained = connection.execute(
            "SELECT artifact_bytes,configuration_bytes FROM regintel.parse_artifacts "
            "WHERE parse_version_id=%s",
            (existing.artifact.id,),
        ).fetchone()
        assert retained == original_artifact
    assert migration_status(auth_database).pending == ()
