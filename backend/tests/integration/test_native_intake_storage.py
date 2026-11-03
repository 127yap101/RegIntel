"""Actual source/job/capture sealing in owned PostgreSQL; authored declarations only."""

import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import UUID

import pytest
from psycopg import sql
from pydantic import SecretStr

from backend.tests.integration.test_numerical_context_storage import snapshot
from backend.tests.native_context_fixtures import NativeCase
from backend.tests.native_intake_fixtures import intake_case, reference
from regintel.auth.repository import PostgreSQLAuthRepository, seed_users
from regintel.auth.types import SeedAccount, User
from regintel.db.config import DatabaseSettings
from regintel.evidence.repository import EvidenceRepository
from regintel.ingestion.config import IngestionSettings
from regintel.ingestion.repository import JobRepository
from regintel.ingestion.storage import SourceStorage, UploadError
from regintel.numerical.repository import (
    NumericalAuthorizationError,
    NumericalRepository,
    NumericalSourceError,
)
from regintel.parsing.intake import import_intake, prepare_intake
from regintel.parsing.intake_cli import main as intake_main
from regintel.parsing.intake_models import NativeIntakePlan

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class IntakeFixture:
    case: NativeCase
    plan: NativeIntakePlan
    source: NumericalRepository
    user: User
    learner: User


@pytest.fixture
def intake(auth_database: DatabaseSettings, tmp_path: Path) -> IntakeFixture:
    case, plan = intake_case(tmp_path)
    seed_users(
        auth_database,
        (
            SeedAccount("admin", SecretStr("Authored native intake password!"), "admin"),
            SeedAccount("learner", SecretStr("Authored native reader password!"), "learner"),
        ),
    )
    auth = PostgreSQLAuthRepository(auth_database)
    user, learner = auth.get_by_username("admin"), auth.get_by_username("learner")
    assert user is not None and learner is not None
    settings = IngestionSettings(
        source_root=tmp_path / "owned-originals",
        broker_url=SecretStr("redis://:authored@127.0.0.1:6379/0"),
    )
    source = NumericalRepository(
        auth_database,
        SourceStorage(settings),
        case.result.configuration.context_parser_configuration,
    )
    return IntakeFixture(case, plan, source, user, learner)


def test_intact_source_seals_once_and_exposes_exact_existing_m1_evidence(intake):
    fixture = intake
    source = fixture.source
    outcome = import_intake(source, fixture.plan, fixture.user)
    assert outcome.job.state == "PARSED" and outcome.job.attempts == 1
    assert outcome.job.page_count == 2 and not outcome.acceptance_eligible
    assert outcome.job.source_sha256 == fixture.plan.source.sha256
    stored = source.get(outcome.capture_ids[0], fixture.user)
    assert stored.capture.page_index == 1
    assert stored.submitted_by == fixture.user.id
    with source.connect() as connection:
        assert connection.execute("SELECT count(*) FROM regintel.job_dispatch").fetchone() == (0,)
        evidence_id = connection.execute(
            "SELECT id FROM regintel.evidence WHERE parse_version_id=%s LIMIT 1",
            (UUID(outcome.job.parse_version_id),),
        ).fetchone()
        for table in (
            "fact_observations",
            "acceptance_audits",
            "corpus_versions",
            "numerical_context_reviews",
            "bound_numerical_gate_runs",
        ):
            assert connection.execute(f"SELECT count(*) FROM regintel.{table}").fetchone() == (0,)
    assert evidence_id is not None
    evidence = EvidenceRepository(source.database).get_evidence(str(evidence_id[0]))
    assert evidence is not None and evidence[0].source.page_index == 1
    stored_pdf = source.storage.root / f"sha256/{fixture.plan.source.sha256}.pdf"
    assert stored_pdf.read_bytes() == fixture.case.source.read_bytes()
    before = snapshot(source.database)
    assert import_intake(source, fixture.plan, fixture.user) == outcome
    assert snapshot(source.database) == before
    assert JobRepository(source.database).dispatch(lambda _: pytest.fail("No worker dispatch")) == 0


def test_concurrent_imports_keep_one_job_parse_and_capture(intake):
    with ThreadPoolExecutor(max_workers=2) as workers:
        calls = [
            workers.submit(import_intake, intake.source, intake.plan, intake.user) for _ in range(2)
        ]
        outcomes = [call.result(timeout=60) for call in calls]
    assert outcomes[0] == outcomes[1] and outcomes[0].job.attempts == 1
    with intake.source.connect() as connection:
        for table in ("filing_jobs", "parse_versions", "numerical_page_captures"):
            assert connection.execute(f"SELECT count(*) FROM regintel.{table}").fetchone() == (1,)


@pytest.mark.parametrize("change", ["learner", "forged_role", "stale", "inactive", "demoted"])
def test_current_admin_authority_is_required_before_any_source_write(intake, change):
    user = intake.user
    if change == "learner":
        user = intake.learner
    elif change == "forged_role":
        user = replace(intake.learner, role="admin")
    elif change == "stale":
        user = replace(user, auth_version=user.auth_version + 1)
    else:
        with intake.source.connect() as connection:
            connection.execute(
                "UPDATE regintel.users SET is_active=%s,role=%s WHERE id=%s",
                (change != "inactive", "learner" if change == "demoted" else "admin", user.id),
            )
    before = snapshot(intake.source.database)
    with pytest.raises(NumericalAuthorizationError):
        import_intake(intake.source, intake.plan, user)
    assert snapshot(intake.source.database) == before
    assert list((intake.source.storage.root / "sha256").iterdir()) == []


def test_preflight_failure_creates_no_database_identity_or_source_copy(intake):
    before = snapshot(intake.source.database)
    Path(intake.plan.context_pages[0].raw_capture.path).write_bytes(b"PRIVATE INVALID DATA")
    with pytest.raises(ValueError):
        import_intake(intake.source, intake.plan, intake.user)
    assert snapshot(intake.source.database) == before
    assert list((intake.source.storage.root / "sha256").iterdir()) == []


def test_metadata_conflicts_preserve_original_sealed_history(intake):
    original = import_intake(intake.source, intake.plan, intake.user)
    before = snapshot(intake.source.database)
    plan = intake.plan.model_copy(
        update={
            "metadata": intake.plan.metadata.model_copy(update={"company_name_raw": "Other issuer"})
        }
    )
    with pytest.raises(UploadError, match="FILING_METADATA_CONFLICT"):
        import_intake(intake.source, plan, intake.user)
    assert snapshot(intake.source.database) == before
    assert JobRepository(intake.source.database).get(original.job.id) == original.job


@pytest.mark.parametrize("first_worker", [True, False])
def test_existing_job_cannot_change_its_dispatch_owner(intake, first_worker):
    prepared = prepare_intake(intake.plan)
    stage = intake.source.storage.stage()
    stage.write(prepared.source_bytes)
    original = stage.finish()
    jobs = JobRepository(intake.source.database)
    job = jobs.submit(
        original,
        intake.plan.metadata,
        prepared.check.processing_configuration_sha256,
        intake.user.id,
        intake.user.auth_version,
        worker_dispatch=first_worker,
    )
    before = snapshot(intake.source.database)
    with pytest.raises(UploadError, match="JOB_DISPATCH_CONFLICT"):
        jobs.submit(
            original,
            intake.plan.metadata,
            prepared.check.processing_configuration_sha256,
            intake.user.id,
            intake.user.auth_version,
            worker_dispatch=not first_worker,
        )
    assert snapshot(intake.source.database) == before
    assert jobs.get(job.id) == job


def test_interrupted_capture_retention_can_resume_without_a_worker(intake, monkeypatch):
    original_save = intake.source.save

    def interrupted(*args, **kwargs):
        original_save(*args, **kwargs)
        raise OSError("Authored process interruption after durable capture")

    monkeypatch.setattr(intake.source, "save", interrupted)
    with pytest.raises(OSError):
        import_intake(intake.source, intake.plan, intake.user)
    with intake.source.connect() as connection:
        assert connection.execute("SELECT state FROM regintel.filing_jobs").fetchone() == (
            "QUEUED",
        )
        assert connection.execute("SELECT count(*) FROM regintel.job_dispatch").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM regintel.parse_versions").fetchone() == (0,)
    monkeypatch.setattr(intake.source, "save", original_save)
    result = import_intake(intake.source, intake.plan, intake.user)
    assert result.job.state == "PARSED" and result.job.attempts == 1


def test_changed_capture_cannot_be_claimed_as_an_old_terminal_success(intake):
    original = import_intake(intake.source, intake.plan, intake.user)
    selected = intake.plan.context_pages[0]
    path = Path(selected.raw_capture.path)
    raw = json.loads(path.read_bytes())
    raw["intake_engineering_marker"] = "Same words, different retained capture"
    path.write_bytes(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode())
    changed = selected.model_copy(update={"raw_capture": reference(path)})
    plan = intake.plan.model_copy(update={"context_pages": (changed,)})
    assert prepare_intake(plan).check.processing_configuration_sha256 == (
        original.job.configuration_sha256
    )
    before = snapshot(intake.source.database)
    with pytest.raises(NumericalSourceError, match="different contextual captures"):
        import_intake(intake.source, plan, intake.user)
    assert snapshot(intake.source.database) == before


@pytest.mark.parametrize(
    "table,column",
    [
        ("parse_artifacts", "artifact_bytes"),
        ("native_parse_manifests", "manifest_bytes"),
        ("native_parse_source_pages", "page_bytes"),
    ],
)
def test_terminal_job_does_not_hide_corrupted_retained_source_bytes(intake, table, column):
    import_intake(intake.source, intake.plan, intake.user)
    # Deliberately simulate storage corruption in this owned fictional database.
    # Normal writes remain blocked by the unchanged append-only database guards.
    with intake.source.connect() as connection, connection.transaction():
        connection.execute(
            sql.SQL("ALTER TABLE regintel.{} DISABLE TRIGGER USER").format(sql.Identifier(table))
        )
        connection.execute(
            sql.SQL("UPDATE regintel.{} SET {}=%s").format(
                sql.Identifier(table), sql.Identifier(column)
            ),
            (b"{}",),
        )
        connection.execute(
            sql.SQL("ALTER TABLE regintel.{} ENABLE TRIGGER USER").format(sql.Identifier(table))
        )
    before = snapshot(intake.source.database)
    with pytest.raises(NumericalSourceError):
        import_intake(intake.source, intake.plan, intake.user)
    assert snapshot(intake.source.database) == before


def test_revocation_during_preparation_is_rechecked_before_job_submission(intake, monkeypatch):
    import regintel.parsing.intake as module

    original = module.prepare_intake

    def revoke(plan):
        result = original(plan)
        with intake.source.connect() as connection:
            connection.execute("UPDATE regintel.users SET auth_version=auth_version+1")
        return result

    monkeypatch.setattr(module, "prepare_intake", revoke)
    with pytest.raises(NumericalAuthorizationError):
        import_intake(intake.source, intake.plan, intake.user)
    with intake.source.connect() as connection:
        assert connection.execute("SELECT count(*) FROM regintel.filing_jobs").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM regintel.parse_versions").fetchone() == (0,)
    assert list((intake.source.storage.root / "sha256").iterdir()) == []


@pytest.mark.parametrize("account", ["admin", "learner", "wrong_password"])
def test_command_import_uses_real_authentication_and_omits_credentials(
    intake, tmp_path, monkeypatch, capsys, account
):
    installation = tmp_path / "installation"
    (installation / "data").mkdir(parents=True)
    runtime = Path(intake.plan.parser_configuration.path).read_bytes()
    (installation / "data/parser-runtime-config.json").write_bytes(runtime)
    env_file = installation / ".env"
    env_file.write_text(
        "REGINTEL_DATABASE_URL="
        + intake.source.database.database_url.get_secret_value()
        + "\nREDIS_PASSWORD=authoredIntakeBrokerNotUsed\n",
        encoding="utf-8",
    )
    auth_file = installation / ".env.auth"
    token_key = secrets.token_hex(32)
    auth_file.write_text("REGINTEL_JWT_SECRET=" + token_key + "\n", encoding="utf-8")
    plan_file = tmp_path / "explicit-plan.json"
    plan_file.write_text(intake.plan.model_dump_json(), encoding="utf-8")
    username = "learner" if account == "learner" else "admin"
    password = (
        "Authored native reader password!"
        if account == "learner"
        else (
            "Invalid entered password!"
            if account == "wrong_password"
            else "Authored native intake password!"
        )
    )
    monkeypatch.setattr("getpass.getpass", lambda _: password)
    monkeypatch.setattr(
        "sys.argv",
        [
            "intake",
            "import",
            "--plan",
            str(plan_file),
            "--project-root",
            str(installation),
            "--env-file",
            str(env_file),
            "--auth-env-file",
            str(auth_file),
            "--username",
            username,
        ],
    )
    before = snapshot(intake.source.database)
    code = intake_main()
    printed = capsys.readouterr()
    assert token_key not in printed.out + printed.err
    assert password not in printed.out + printed.err
    if account == "admin":
        assert code == 0 and printed.err == ""
        receipt = json.loads(printed.out)
        assert receipt["status"] == "SOURCE_EVIDENCE_SEALED"
        assert receipt["job"]["state"] == "PARSED" and not receipt["acceptance_eligible"]
    else:
        assert code == 1 and printed.out == ""
        assert json.loads(printed.err)["status"] == "INTAKE_FAILED"
        assert snapshot(intake.source.database) == before
        assert not (installation / "data/uploads").exists()
