"""Controlled real-source processing proof, with optional owned-workflow crash recovery.

Uses existing approved local accounts, services and original Premier evidence.
No source acquisition, reparse, review decision, acceptance or publication.
The explicit --crash-worker option interrupts only the idle approved worker after
this proof's new job has frozen an input, then restarts that same container.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import urlsplit
from uuid import uuid4

import httpx2

from regintel.auth.config import load_seed_accounts
from regintel.db.config import DatabaseSettings, load_database_settings
from regintel.db.migrations import connect_database, migration_status
from regintel.entities.repository import REGISTRY_LOCK_ID, EntityRepository
from regintel.evidence.api import EvidenceEnvelope
from regintel.ingestion.broker import create_celery
from regintel.ingestion.config import native_ingestion_settings
from regintel.processing.api import ProcessingEnvelope
from regintel.processing.broker import TASK_NAME, sender
from regintel.processing.configuration import current_configuration
from regintel.processing.models import ProcessingJob, ProcessingRequest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "a15329da96a20117a5cfaccf535ab3dc805c6ed195e392bb5ec6131f8f246347"
AUTHORITY = ("acceptance_audits", "fact_observations", "relation_observations", "corpus_versions")
BASE = "/v1/admin/processing/jobs"


class ProofFailure(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProofFailure(message)


def snapshot(database: DatabaseSettings) -> dict[str, object]:
    result: dict[str, object] = {}
    with connect_database(database) as connection, connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        for table in (
            "source_blobs",
            "filings",
            "filing_versions",
            "filing_jobs",
            "parse_versions",
            "evidence",
            "entity_registrations",
            "entity_runs",
            "entity_reviews",
            "metric_definitions",
            "candidates",
            "candidate_runs",
            "numeric_metric_policies",
            "validation_runs",
            "validation_reviews",
            *AUTHORITY,
        ):
            rows = connection.execute(
                f"SELECT row_to_json(t)::text FROM regintel.{table} t ORDER BY id"
            ).fetchall()
            result[table] = {
                "count": len(rows),
                "sha256": hashlib.sha256(
                    json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
                ).hexdigest(),
            }
    return result


def stage_inputs(database: DatabaseSettings, job_id: str) -> dict[str, object]:
    result: dict[str, object] = {}
    with connect_database(database) as connection:
        rows = connection.execute(
            "SELECT stage,input_sha256,configuration_sha256,generation,input_bytes "
            "FROM regintel.processing_inputs WHERE job_id=%s ORDER BY stage_index",
            (job_id,),
        ).fetchall()
    for stage, input_sha, config_sha, generation, payload in rows:
        require(isinstance(payload, (bytes, memoryview)), "Frozen input storage is invalid.")
        assert isinstance(payload, (bytes, memoryview))
        require(hashlib.sha256(payload).hexdigest() == input_sha, "Frozen input bytes differ.")
        result[str(stage)] = {
            "input_sha256": input_sha,
            "configuration_sha256": config_sha,
            "generation": generation,
        }
    return result


class Inspector(Protocol):
    def stats(self) -> dict[str, dict[str, object]] | None: ...


class Control(Protocol):
    def inspect(self, *, timeout: float) -> Inspector: ...


class App(Protocol):
    control: Control


def consumed(app: App) -> int:
    stats = app.control.inspect(timeout=5).stats()
    require(stats is not None and len(stats) == 1, "Require the one approved responsive worker.")
    assert stats is not None
    total = next(iter(stats.values())).get("total")
    require(isinstance(total, dict), "Worker task totals are unavailable.")
    assert isinstance(total, dict)
    count = total.get(TASK_NAME, 0)
    require(isinstance(count, int) and count >= 0, "Worker task total is invalid.")
    assert isinstance(count, int)
    return count


def worker(action: str) -> None:
    executable = shutil.which("docker")
    require(executable is not None, "Existing Docker CLI is unavailable.")
    assert executable is not None
    command = [executable, "--config", str(ROOT / ".cache/docker")]
    if sys.platform == "win32":
        command += ["--host", "npipe:////./pipe/dockerDesktopLinuxEngine"]
    # Fixed container identity and no shell/client path. Do not enumerate targets.
    if action == "inspect":
        args = [
            "inspect",
            "--format",
            '{{index .Config.Labels "com.docker.compose.project"}}/'
            '{{index .Config.Labels "com.docker.compose.service"}}',
            "regintel-worker-1",
        ]
    elif action == "kill":
        args = ["kill", "--signal=KILL", "regintel-worker-1"]
    elif action == "start":
        args = ["start", "regintel-worker-1"]
    else:
        raise ProofFailure("Unsupported fixed worker operation.")
    result = subprocess.run(command + args, cwd=ROOT, capture_output=True, check=False, timeout=45)
    require(result.returncode == 0, "Approved worker operation failed; diagnostics omitted.")
    if action == "inspect":
        require(result.stdout.decode().strip() == "regintel/worker", "Worker ownership differs.")


def read(client: httpx2.Client, base: str, headers: dict[str, str], job_id: str) -> ProcessingJob:
    response = client.get(base + BASE + "/" + job_id, headers=headers)
    require(response.status_code == 200, "Workflow read failed.")
    require(response.headers.get("cache-control") == "no-store", "Workflow read must not cache.")
    return ProcessingEnvelope.model_validate_json(response.text).data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default="http://127.0.0.1:8011")
    parser.add_argument("--parse-version-id", required=True)
    parser.add_argument("--metric-id", action="append", default=[])
    parser.add_argument("--crash-worker", action="store_true")
    args = parser.parse_args()
    try:
        target = urlsplit(args.api_base)
        require(
            target.scheme == "http"
            and target.hostname == "127.0.0.1"
            and target.username is None
            and target.password is None
            and target.port is not None
            and target.path in {"", "/"}
            and not target.query
            and not target.fragment,
            "Use an explicit loopback API.",
        )
        request = ProcessingRequest(
            idempotency_key=str(uuid4()),
            parse_version_id=args.parse_version_id,
            metric_ids=tuple(sorted(args.metric_id)),
        )
        base = args.api_base.rstrip("/")
        database = load_database_settings(ROOT / ".env")
        migration = migration_status(database)
        require(
            migration.applied == tuple(range(1, 11)) and not migration.pending,
            "Require verified schema1–10.",
        )
        evidence, artifact_sha = EntityRepository(database).evidence_for_parse(
            request.parse_version_id
        )
        original = ROOT / "data/raw/premier-energies-addendum-rhp-sebi-20240826.pdf"
        require(
            original.is_file()
            and not original.is_symlink()
            and not original.is_junction()
            and original.stat().st_size == 196270
            and hashlib.sha256(original.read_bytes()).hexdigest() == SOURCE_SHA,
            "Controlled original source differs.",
        )
        with connect_database(database) as connection:
            require(
                connection.execute(
                    "SELECT s.sha256 FROM regintel.parse_versions p JOIN regintel.source_blobs s "
                    "ON s.id=p.source_blob_id WHERE p.id=%s",
                    (request.parse_version_id,),
                ).fetchone()
                == (SOURCE_SHA,),
                "Parse is not the controlled source.",
            )
            require(
                connection.execute(
                    "SELECT count(*) FROM regintel.processing_jobs "
                    "WHERE state IN ('QUEUED','RUNNING')"
                ).fetchone()
                == (0,),
                "Finish existing processing jobs before this controlled interruption.",
            )
            for table in AUTHORITY:
                require(
                    connection.execute(f"SELECT count(*) FROM regintel.{table}").fetchone() == (0,),
                    "This proof requires unpublished pilot data.",
                )
        before = snapshot(database)
        directory = ROOT / ".cache" / ("processing-runtime-" + uuid4().hex)
        directory.mkdir()
        (directory / "before.json").write_text(
            json.dumps(before, indent=2) + "\n", encoding="utf-8"
        )
        application = create_celery(native_ingestion_settings(ROOT, ROOT / ".env"))
        app = cast(App, application)
        worker("inspect")
        consumed(app)
        stopped = False
        frozen: ProcessingJob | None = None
        interrupted_inputs: dict[str, object] = {}
        with (
            connect_database(database) as barrier,
            httpx2.Client(timeout=120, trust_env=False) as client,
        ):
            # Hold the existing registry lock only for this controlled crash.
            # The real worker freezes its input and executes the resolver, then
            # waits at its normal domain transaction. This makes SIGKILL timing
            # repeatable without a production fault flag or a mocked stage.
            barrier_locked = args.crash_worker
            if barrier_locked:
                barrier.execute("SELECT pg_advisory_lock(%s)", (REGISTRY_LOCK_ID,))
            headers: dict[str, dict[str, str]] = {}
            for account in load_seed_accounts(ROOT / ".env.auth"):
                token = client.post(
                    base + "/v1/auth/token",
                    data={
                        "grant_type": "password",
                        "username": account.username,
                        "password": account.password.get_secret_value(),
                    },
                )
                require(token.status_code == 200, "Local proof account login failed.")
                headers[account.role] = {
                    "Authorization": "Bearer " + str(token.json()["access_token"])
                }
            response = client.post(
                base + BASE, headers=headers["admin"], json=request.model_dump(mode="json")
            )
            require(response.status_code == 200, "Workflow submission failed.")
            submitted = ProcessingEnvelope.model_validate_json(response.text).data
            (directory / "submitted.json").write_text(
                submitted.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
            print("Submitted controlled workflow " + submitted.id, flush=True)
            try:
                deadline = time.monotonic() + 1200
                while time.monotonic() < deadline:
                    job = read(client, base, headers["admin"], submitted.id)
                    if args.crash_worker and frozen is None:
                        inputs = sum(event.kind == "INPUT_FROZEN" for event in job.events)
                        if job.state == "RUNNING" and inputs > len(job.checkpoints):
                            worker("kill")
                            stopped = True
                            frozen = read(client, base, headers["admin"], submitted.id)
                            require(
                                frozen.state == "RUNNING" and frozen.generation == 1,
                                "Interruption did not retain a running first attempt.",
                            )
                            interrupted_inputs = stage_inputs(database, submitted.id)
                            require(
                                len(interrupted_inputs) > len(frozen.checkpoints),
                                "The interrupted attempt had already sealed its work.",
                            )
                            (directory / "interrupted.json").write_text(
                                frozen.model_dump_json(indent=2) + "\n", encoding="utf-8"
                            )
                            barrier.execute("SELECT pg_advisory_unlock(%s)", (REGISTRY_LOCK_ID,))
                            barrier_locked = False
                            worker("start")
                            stopped = False
                            dispatch = client.post(
                                base + BASE + "/" + job.id + "/dispatch", headers=headers["admin"]
                            )
                            require(
                                dispatch.status_code == 200
                                and dispatch.json()["data"]["dispatched"] is True,
                                "Orphan recovery dispatch failed.",
                            )
                            print(
                                "Worker interrupted in flight and restarted; recovery dispatched.",
                                flush=True,
                            )
                    if job.state in {"SUCCEEDED", "FAILED"}:
                        break
                    time.sleep(0.1)
                else:
                    raise ProofFailure("Controlled workflow timed out; durable state is retained.")
            finally:
                if barrier_locked and not barrier.closed:
                    barrier.execute("SELECT pg_advisory_unlock(%s)", (REGISTRY_LOCK_ID,))
                if stopped:
                    worker("start")
            result = read(client, base, headers["admin"], submitted.id)
            (directory / "terminal.json").write_text(
                result.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
            require(
                result.state == "SUCCEEDED",
                "Controlled processing failed; inspect its safe job code.",
            )
            require(
                result.configuration == current_configuration(),
                "Worker/native configuration differs.",
            )
            if args.crash_worker:
                require(
                    frozen is not None and result.generation == 2,
                    "Actual crash recovery was not observed.",
                )
                assert frozen is not None
                require(
                    result.checkpoints[: len(frozen.checkpoints)] == frozen.checkpoints,
                    "Recovery replaced a committed checkpoint.",
                )
                final_inputs = stage_inputs(database, result.id)
                require(
                    all(
                        final_inputs.get(stage) == value
                        for stage, value in interrupted_inputs.items()
                    ),
                    "Recovery replaced frozen input bytes or metadata.",
                )
            for role, status in ((None, 401), ("learner", 403)):
                for method, path, body in (
                    ("POST", BASE, request.model_dump(mode="json")),
                    ("GET", BASE + "/" + result.id, None),
                    ("POST", BASE + "/" + result.id + "/dispatch", None),
                ):
                    denied = client.request(
                        method, base + path, headers=headers[role] if role else {}, json=body
                    )
                    require(denied.status_code == status, "Workflow permission check failed.")
            replay = client.post(
                base + BASE, headers=headers["admin"], json=request.model_dump(mode="json")
            )
            require(
                replay.status_code == 200
                and ProcessingEnvelope.model_validate_json(replay.text).data == result,
                "Completed request replay differs.",
            )
            task_count = consumed(app)
            send = sender(application)
            send(result.id)
            send(result.id)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if consumed(app) >= task_count + 2:
                    break
                time.sleep(0.25)
            else:
                raise ProofFailure("Actual duplicate worker consumption was not observed.")
            require(
                read(client, base, headers["admin"], result.id) == result,
                "Duplicate delivery changed completed history.",
            )
            exact = client.get(base + "/v1/evidence/" + evidence[0].id, headers=headers["admin"])
            require(exact.status_code == 200, "Original exact evidence read failed.")
            require(
                EvidenceEnvelope.model_validate_json(exact.text).data.record == evidence[0],
                "Original evidence text, geometry or provenance differs.",
            )
            require(
                snapshot(database) == before,
                "Original source/domain/review/authority snapshot changed.",
            )
            report = {
                "phase": "M1.8",
                "measured_at": datetime.now(UTC).isoformat(),
                "status": "passed",
                "job": result.model_dump(mode="json"),
                "source_sha256": SOURCE_SHA,
                "parse_artifact_sha256": artifact_sha,
                "evidence_count": len(evidence),
                "actual_crash_recovery": args.crash_worker,
                "crash_synchronization": "owned registry lock; real worker killed before checkpoint"
                if args.crash_worker
                else None,
                "inputs_at_interruption": interrupted_inputs,
                "sealed_stage_inputs": stage_inputs(database, result.id),
                "actual_duplicate_consumptions": 2,
                "unchanged_source_domain_review_snapshots": before,
                "authority_counts": dict.fromkeys(AUTHORITY, 0),
                "anonymous_and_learner_denials": "passed",
                "provider_calls": 0,
                "limitations": [
                    "One controlled filing; engineering recovery, not research effectiveness.",
                    "A completed workflow does not approve reviews or publish observations.",
                    "Redis can redeliver; no exactly-once execution guarantee.",
                ],
            }
            (directory / "result.json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
            print(
                json.dumps(
                    {
                        "status": "passed",
                        "proof_directory": str(directory),
                        "job_id": result.id,
                        "generation": result.generation,
                    }
                )
            )
        return 0
    except ProofFailure as error:
        print(str(error) + " Durable state is retained.", file=sys.stderr)
        return 1
    except Exception:
        print(
            "Processing proof failed; private diagnostics omitted. Durable state is retained.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
