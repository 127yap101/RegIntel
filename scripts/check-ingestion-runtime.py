"""Native API -> Redis -> approved Linux worker check on the controlled real source.

A new source/configuration exercises first-upload broker outage and durable intent
replay. Existing jobs are resumed or replayed without changing immutable records.
Terminal duplicates must actually drain before and after a graceful worker restart.
Only the owned API and the existing project Redis/worker services are controlled.
"""

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

import httpx2

from regintel.auth.config import load_seed_accounts
from regintel.db.config import load_database_settings
from regintel.ingestion.broker import TASK_NAME, CeleryApplication, create_celery, sender
from regintel.ingestion.config import native_ingestion_settings
from regintel.ingestion.jobs import FilingJob, FilingJobEnvelope, UploadMetadata
from regintel.ingestion.repository import JobRepository

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "a15329da96a20117a5cfaccf535ab3dc805c6ed195e392bb5ec6131f8f246347"
SOURCE_URL = "https://www.sebi.gov.in/sebi_data/attachdocs/aug-2024/1725009610554.PDF"
WORKER = "ingestion@regintel"
QUEUE = "regintel-ingestion"


class ProbeError(ValueError):
    """A fixed diagnostic safe to display without connection or inspection data."""


class CeleryInspector(Protocol):
    def stats(self) -> object: ...

    def active(self, *, safe: bool) -> object: ...

    def reserved(self, *, safe: bool) -> object: ...

    def scheduled(self, *, safe: bool) -> object: ...


class CeleryControl(Protocol):
    def inspect(self, *, destination: list[str], timeout: float) -> CeleryInspector: ...


class ProbeCeleryApplication(CeleryApplication, Protocol):
    control: CeleryControl

    def close(self) -> None: ...


class RedisClient(Protocol):
    def ping(self) -> bool: ...

    def llen(self, name: str) -> int: ...

    def hlen(self, name: str) -> int: ...

    def close(self) -> None: ...


class RedisFactory(Protocol):
    def from_url(
        self,
        url: str,
        *,
        socket_connect_timeout: float,
        socket_timeout: float,
        retry_on_timeout: bool,
        retry: None,
    ) -> RedisClient: ...


class RedisChannelDefaults(Protocol):
    priority_steps: list[int]
    sep: str
    unacked_key: str


@dataclass(frozen=True)
class Service:
    container_id: str
    started_at: datetime


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ProbeError("Runtime inspection returned an unexpected structure.")
    return cast(dict[str, object], value)


def docker(*arguments: str) -> str:
    executable = shutil.which("docker")
    if executable is None and sys.platform == "win32":
        location = os.environ.get("LOCALAPPDATA")
        if location is not None:
            executable = str(Path(location) / "Programs/DockerDesktop/resources/bin/docker.exe")
    if executable is None or sys.platform != "win32":
        raise ProbeError("This runtime probe supports the approved Windows host.")
    try:
        result = subprocess.run(
            [
                executable,
                "--config",
                str(ROOT / ".cache/docker"),
                "--host",
                "npipe:////./pipe/dockerDesktopLinuxEngine",
                *arguments,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        raise ProbeError("Project Docker operation failed or exceeded its time bound.") from None
    if result.returncode:
        raise ProbeError("Project Docker operation failed; diagnostics omitted.")
    return result.stdout


def compose(*arguments: str) -> str:
    return docker(
        "compose",
        "--env-file",
        str(ROOT / ".env"),
        "-f",
        str(ROOT / "infra/compose.yaml"),
        "--profile",
        "ingestion",
        *arguments,
    )


def service(name: str) -> Service:
    output = compose("ps", "--all", "--format", "json", name).strip()
    if not output:
        raise ProbeError("Required project service is missing.")
    # Compose releases emit either a JSON array or one JSON object per line.
    decoded: object = (
        json.loads(output)
        if output.startswith("[")
        else [json.loads(line) for line in output.splitlines()]
    )
    if not isinstance(decoded, list) or len(decoded) != 1:
        raise ProbeError("The runtime check requires exactly one existing service container.")
    row = mapping(decoded[0])
    identifier = row.get("ID")
    if (
        row.get("Project") != "regintel"
        or row.get("Service") != name
        or not isinstance(identifier, str)
        or re.fullmatch(r"[0-9a-f]{12,64}", identifier) is None
    ):
        raise ProbeError("Container identity does not match the existing Compose project.")
    state = mapping(json.loads(docker("inspect", "--format", "{{json .State}}", identifier)))
    health = mapping(state.get("Health"))
    started = state.get("StartedAt")
    if (
        state.get("Running") is not True
        or state.get("Paused") is not False
        or state.get("Restarting") is not False
        or health.get("Status") != "healthy"
        or not isinstance(started, str)
    ):
        raise ProbeError("Required existing Redis/worker service is not running and healthy.")
    timestamp = datetime.fromisoformat(started.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ProbeError("Worker start timestamp is not an explicit instant.")
    return Service(identifier, timestamp)


def restore_service(name: str, original: Service) -> Service:
    # Compose start only operates on existing containers; it cannot build/recreate.
    compose("start", "--wait", "--wait-timeout", "45", name)
    restored = service(name)
    if restored.container_id != original.container_id:
        raise ProbeError("Service restoration unexpectedly changed the container identity.")
    return restored


def existing_job(
    repository: JobRepository, metadata: UploadMetadata, config: str
) -> FilingJob | None:
    with repository.connect() as connection:
        row = connection.execute(
            """SELECT k.metadata_sha256, j.id FROM regintel.source_blobs s
            LEFT JOIN regintel.filing_ingestion_keys k ON k.source_blob_id=s.id
            LEFT JOIN regintel.filing_jobs j ON j.filing_version_id=k.filing_version_id
                AND j.configuration_sha256=%s WHERE s.sha256=%s""",
            (config, SOURCE_SHA),
        ).fetchone()
    if row is None:
        return None
    if row[0] is not None and row[0] != metadata.sha256:
        raise ProbeError("Existing source metadata conflicts; no services were changed.")
    if row[1] is None:
        return None
    job = repository.get(str(row[1]))
    if job is None or job.state == "FAILED":
        raise ProbeError("Existing job is missing or terminally failed; no services were changed.")
    return job


def worker_reply(value: object) -> object:
    replies = mapping(value)
    if set(replies) != {WORKER}:
        raise ProbeError("The expected single worker did not return a control response.")
    return replies[WORKER]


def worker_snapshot(application: ProbeCeleryApplication) -> tuple[int, bool]:
    inspector = application.control.inspect(destination=[WORKER], timeout=2)
    total = mapping(mapping(worker_reply(inspector.stats())).get("total"))
    count = total.get(TASK_NAME, 0)
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise ProbeError("Worker task counter is invalid.")
    idle = True
    for reply in (
        inspector.active(safe=True),
        inspector.reserved(safe=True),
        inspector.scheduled(safe=True),
    ):
        tasks = worker_reply(reply)
        if not isinstance(tasks, list):
            raise ProbeError("Worker task inspection returned an unexpected structure.")
        idle = idle and not tasks
    return count, idle


def broker_empty(redis: RedisClient) -> bool:
    # Use the installed pinned Kombu defaults, including all Redis priority lists.
    # No task contents, broker information, environment or inspection data is printed.
    channel = cast(RedisChannelDefaults, import_module("kombu.transport.redis").Channel)
    pending = sum(
        redis.llen(QUEUE if priority == 0 else f"{QUEUE}{channel.sep}{priority}")
        for priority in channel.priority_steps
    )
    return pending == 0 and redis.hlen(channel.unacked_key) == 0


def wait_for_drain(
    application: ProbeCeleryApplication, redis: RedisClient, *, expected: int | None = None
) -> int:
    deadline = time.monotonic() + 60
    stable: int | None = None
    while time.monotonic() < deadline:
        try:
            count, idle = worker_snapshot(application)
            drained = broker_empty(redis)
        except Exception:
            # Connection/control failures never become a success or expose diagnostics.
            stable = None
            time.sleep(1)
            continue
        if expected is not None and count > expected:
            raise ProbeError("Unexpected worker activity prevents an isolated delivery proof.")
        if idle and drained and (expected is None or count == expected):
            if stable == count:
                return count
            stable = count
        else:
            stable = None
        time.sleep(1)
    raise ProbeError("Worker task counter and broker did not reach the expected drained state.")


def wait_for_job(client: httpx2.Client, authorization: dict[str, str], job_id: str) -> FilingJob:
    deadline = time.monotonic() + 75
    while time.monotonic() < deadline:
        result = client.get(f"/v1/filing-jobs/{job_id}", headers=authorization, timeout=5)
        result.raise_for_status()
        job = FilingJobEnvelope.model_validate_json(result.text).data
        if job.state == "SOURCE_VERIFIED":
            return job
        if job.state == "FAILED":
            raise ProbeError("Source verification returned a terminal failure.")
        time.sleep(1)
    raise ProbeError("Worker did not finish inside the bounded runtime check.")


def stop_owned_api(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
    except OSError:
        if process.poll() is None:
            raise ProbeError("Owned API termination failed.") from None
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    source = ROOT / "data/raw/premier-energies-addendum-rhp-sebi-20240826.pdf"
    original = source.read_bytes()
    if hashlib.sha256(original).hexdigest() != SOURCE_SHA:
        raise ProbeError("Controlled source hash mismatch.")
    settings = native_ingestion_settings(ROOT, ROOT / ".env")
    repository = JobRepository(load_database_settings(ROOT / ".env"))
    accounts = load_seed_accounts(ROOT / ".env.auth")
    metadata = UploadMetadata(
        company_name_raw="Premier Energies Limited", document_type="ADDENDUM", source_url=SOURCE_URL
    )
    previous = existing_job(repository, metadata, settings.configuration_sha256)
    application = cast(ProbeCeleryApplication, create_celery(settings))
    broker_send = sender(application)
    redis_factory = cast(RedisFactory, import_module("redis").Redis)
    redis = redis_factory.from_url(
        settings.broker_url.get_secret_value(),
        socket_connect_timeout=3,
        socket_timeout=3,
        retry_on_timeout=False,
        retry=None,
    )
    process: subprocess.Popen[bytes] | None = None
    redis_original: Service | None = None
    worker_original: Service | None = None
    redis_needs_restore = False
    worker_needs_restore = False
    try:
        redis_original = service("redis")
        worker_original = service("worker")
        if not redis.ping():
            raise ProbeError("Project Redis did not answer its authenticated health check.")
        wait_for_drain(application, redis)
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "from regintel.auth.cli import serve_main; serve_main()",
                "--env-file",
                str(ROOT / ".env"),
                "--auth-env-file",
                str(ROOT / ".env.auth"),
                "--port",
                str(port),
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        with httpx2.Client(base_url=f"http://127.0.0.1:{port}", timeout=15) as client:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise ProbeError("Owned API process exited.")
                try:
                    if client.get("/health/live", timeout=1).status_code == 200:
                        break
                except httpx2.TransportError:
                    pass
                time.sleep(0.25)
            else:
                raise ProbeError("Owned API did not start.")
            auth: dict[str, dict[str, str]] = {}
            for account in accounts:
                result = client.post(
                    "/v1/auth/token",
                    data={
                        "grant_type": "password",
                        "username": account.username,
                        "password": account.password.get_secret_value(),
                    },
                )
                result.raise_for_status()
                auth[account.role] = {
                    "Authorization": f"Bearer {result.json()['access_token']}",
                    "Content-Type": "application/pdf",
                }
            parameters = {
                "company_name_raw": metadata.company_name_raw,
                "document_type": metadata.document_type,
                "source_url": metadata.source_url,
            }
            denied = client.post(
                "/v1/filings", params=parameters, headers=auth["learner"], content=original
            )
            if denied.status_code != 403:
                raise ProbeError("Learner upload did not fail closed.")
            if previous is None:
                # Set both flags before a command can partially stop Redis.
                redis_needs_restore = True
                worker_needs_restore = True
                compose("stop", "--timeout", "15", "redis")
            upload = client.post(
                "/v1/filings", params=parameters, headers=auth["admin"], content=original
            )
            upload.raise_for_status()
            submitted = FilingJobEnvelope.model_validate_json(upload.text).data
            if previous is None:
                with repository.connect() as connection:
                    intent = connection.execute(
                        "SELECT sent_at, last_failure_code FROM regintel.job_dispatch "
                        "WHERE job_id=%s",
                        (submitted.id,),
                    ).fetchone()
                if submitted.state != "QUEUED" or intent != (None, "BROKER_UNAVAILABLE"):
                    raise ProbeError(
                        "Fresh outage upload did not retain its unsent durable intent."
                    )
                print(
                    "Fresh upload committed offline; PostgreSQL dispatch intent retained.",
                    flush=True,
                )
                restore_service("redis", redis_original)
                redis_needs_restore = False
                if repository.dispatch(broker_send, limit=1, job_id=submitted.id) != 1:
                    raise ProbeError("Durable dispatch replay did not send.")
                mode = "fresh upload/outage"
            else:
                if submitted.id != previous.id:
                    raise ProbeError("Repeated upload did not preserve the existing job identity.")
                if submitted.state in {"QUEUED", "RUNNING"}:
                    # Normal upload already replays any unsent intent. An explicit
                    # duplicate also resumes a sent job without editing its state.
                    broker_send(submitted.id)
                mode = "existing job replay (first-upload outage was not rerun)"
                print(f"Runtime mode: {mode}.", flush=True)
            verified = wait_for_job(client, auth["admin"], submitted.id)
            if (
                verified.page_count != 3
                or verified.source_sha256 != SOURCE_SHA
                or verified.configuration_sha256 != settings.configuration_sha256
                or (previous is None and verified.attempts != 1)
            ):
                raise ProbeError("Real source worker identity/count mismatch.")
            repeat = client.post(
                "/v1/filings", params=parameters, headers=auth["admin"], content=original
            )
            repeat.raise_for_status()
            if FilingJobEnvelope.model_validate_json(repeat.text).data != verified:
                raise ProbeError("Repeated real upload changed the terminal job.")
            baseline = wait_for_drain(application, redis)
            broker_send(submitted.id)
            broker_send(submitted.id)
            wait_for_drain(application, redis, expected=baseline + 2)
            if repository.get(submitted.id) != verified:
                raise ProbeError("Consumed terminal duplicates changed the result.")
            print(
                "Two duplicate deliveries consumed and drained; terminal result unchanged.",
                flush=True,
            )
            before_restart = service("worker")
            if before_restart.container_id != worker_original.container_id:
                raise ProbeError("Worker container changed during the check.")
            worker_needs_restore = True
            compose("restart", "--timeout", "15", "worker")
            restarted = restore_service("worker", worker_original)
            if restarted.started_at <= before_restart.started_at:
                raise ProbeError("Worker start timestamp did not advance after restart.")
            baseline = wait_for_drain(application, redis)
            broker_send(submitted.id)
            wait_for_drain(application, redis, expected=baseline + 1)
            final = wait_for_job(client, auth["admin"], submitted.id)
            if final != verified:
                raise ProbeError("Consumed duplicate after restart changed the terminal job.")
            # Both services must still be healthy before clearing recovery flags.
            restore_service("redis", redis_original)
            restore_service("worker", worker_original)
            worker_needs_restore = False
            print(
                f"Real Linux worker verified {final.page_count} pages; job {final.id}; "
                f"{mode}; graceful restart and post-restart delivery verified.",
                flush=True,
            )
    finally:
        failures: list[str] = []
        # Independently attempt every cleanup, even when another cleanup fails.
        if process is not None:
            try:
                stop_owned_api(process)
            except Exception:
                failures.append("owned API")
        for name, required, original_service in (
            ("redis", redis_needs_restore, redis_original),
            ("worker", worker_needs_restore, worker_original),
        ):
            if required and original_service is not None:
                try:
                    restore_service(name, original_service)
                except Exception:
                    failures.append(name)
        try:
            redis.close()
        except Exception:
            failures.append("Redis client")
        try:
            application.close()
        except Exception:
            failures.append("Celery client")
        if failures:
            raise ProbeError(f"Cleanup requires attention: {', '.join(failures)}.")
    print(
        "Check passed; owned API stopped; sources/accounts retained; "
        "no evidence/publication claimed."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProbeError as error:
        raise SystemExit(f"Runtime ingestion check failed: {error}") from None
    except Exception:
        raise SystemExit(
            "Runtime ingestion check failed; configuration and secrets omitted."
        ) from None
