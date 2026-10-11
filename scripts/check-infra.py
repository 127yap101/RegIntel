"""Verify real local services, with optional synthetic restart probes and no secret output."""

import argparse
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from regintel.db.checks import check_database
from regintel.db.config import load_database_settings
from regintel.db.migrations import MigrationError, connect_database

ROOT = Path(__file__).resolve().parents[1]


class InfraError(Exception):
    """Safe operator diagnostic; command output/credentials are deliberately omitted."""


class ServiceStatus(TypedDict):
    ID: str
    Service: str
    State: str
    Health: str


class Docker:
    def __init__(self) -> None:
        executable = shutil.which("docker")
        if executable is None and sys.platform == "win32":
            executable = str(
                Path(os.environ["LOCALAPPDATA"]) / "Programs/DockerDesktop/resources/bin/docker.exe"
            )
        if executable is None or not Path(executable).is_file():
            raise InfraError("Docker CLI is unavailable.")
        if sys.platform == "win32":
            host = "npipe:////./pipe/dockerDesktopLinuxEngine"
        else:
            socket = Path(os.environ.get("REGINTEL_DOCKER_SOCKET", "/var/run/docker.sock"))
            if "REGINTEL_DOCKER_SOCKET" not in os.environ and not socket.is_socket():
                socket = Path.home() / ".docker/run/docker.sock"
            if not socket.is_absolute() or not socket.is_socket():
                raise InfraError("An existing absolute local Unix Docker socket is required.")
            host = f"unix://{socket}"
        if not (ROOT / ".cache/docker/config.json").is_file():
            raise InfraError("Run the project Compose wrapper first to configure local plugins.")
        self.prefix = [
            executable,
            "--config",
            str(ROOT / ".cache/docker"),
            "--host",
            host,
        ]
        self.compose_prefix = [
            "compose",
            "--env-file",
            str(ROOT / ".env"),
            "-f",
            str(ROOT / "infra/compose.yaml"),
        ]

    def run(self, *arguments: str, timeout: int = 40) -> str:
        try:
            result = subprocess.run(
                [*self.prefix, *arguments],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise InfraError("A local Docker operation could not complete.") from None
        if result.returncode != 0:
            raise InfraError("A local Docker operation failed; inspect service readiness safely.")
        return result.stdout.strip()

    def compose(self, *arguments: str, timeout: int = 40) -> str:
        return self.run(*self.compose_prefix, *arguments, timeout=timeout)

    def execute(self, service: str, *arguments: str) -> str:
        return self.compose("exec", "-T", service, *arguments)

    def neo4j(self, query: str) -> list[list[str]]:
        command = (
            'export NEO4J_USERNAME="${NEO4J_AUTH%%/*}" NEO4J_PASSWORD="${NEO4J_AUTH#*/}"; '
            'exec cypher-shell --format plain -a bolt://localhost:7687 "$1"'
        )
        output = self.execute("neo4j", "sh", "-ec", command, "regintel-check", query)
        return list(csv.reader(io.StringIO(output), skipinitialspace=True))

    def redis(self, *arguments: str) -> str:
        return self.execute(
            "redis",
            "sh",
            "-ec",
            'REDISCLI_AUTH="$REDIS_PASSWORD" exec redis-cli -e --raw "$@"',
            "regintel-check",
            *arguments,
        )


def service_status(docker: Docker) -> list[ServiceStatus]:
    output = docker.compose("ps", "--all", "--format", "json")
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        parsed = [json.loads(line) for line in output.splitlines() if line.strip()]
    rows = parsed if isinstance(parsed, list) else [parsed]
    result: list[ServiceStatus] = []
    for row in rows:
        if not isinstance(row, dict):
            raise InfraError("Docker returned invalid service metadata.")
        fields: dict[str, str] = {}
        for field in ("ID", "Service", "State", "Health"):
            value = row.get(field)
            if not isinstance(value, str):
                raise InfraError("Docker service metadata is missing a required string field.")
            fields[field] = value
        result.append(
            ServiceStatus(
                ID=fields["ID"],
                Service=fields["Service"],
                State=fields["State"],
                Health=fields["Health"],
            )
        )
    return result


def wait_healthy(docker: Docker, timeout: int = 180) -> list[ServiceStatus]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = service_status(docker)
        if {row.get("Service") for row in rows} == {
            "postgres",
            "neo4j",
            "redis",
        } and all(row.get("State") == "running" and row.get("Health") == "healthy" for row in rows):
            return rows
        time.sleep(2)
    raise InfraError("All three project services must become healthy before acceptance.")


def verify_bindings_and_volumes(docker: Docker, rows: list[ServiceStatus]) -> None:
    ports = {"postgres": "5432", "neo4j": "7687", "redis": "6379"}
    destinations = {
        "postgres": "/var/lib/postgresql/data",
        "neo4j": "/data",
        "redis": "/data",
    }
    for row in rows:
        service = str(row["Service"])
        container_id = str(row["ID"])
        bindings = json.loads(
            docker.run("inspect", container_id, "--format", "{{json .NetworkSettings.Ports}}")
        )
        published = {key: value for key, value in bindings.items() if value}
        expected_port = ports[service]
        if published != {
            f"{expected_port}/tcp": [{"HostIp": "127.0.0.1", "HostPort": expected_port}]
        }:
            raise InfraError(
                "A service port is not bound exclusively to its expected loopback port."
            )
        mounts = json.loads(docker.run("inspect", container_id, "--format", "{{json .Mounts}}"))
        expected_volume = f"regintel_{service}_data"
        if not any(
            mount.get("Type") == "volume"
            and mount.get("Name") == expected_volume
            and mount.get("Destination") == destinations[service]
            for mount in mounts
        ):
            raise InfraError("A service lacks its expected project-owned named data volume.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Verify orderly service restart persistence",
    )
    options = parser.parse_args()
    try:
        docker = Docker()
        if docker.run("info", "--format", "{{.OSType}}") != "linux":
            raise InfraError("The project requires a local Linux container engine.")
        rows = wait_healthy(docker)
        verify_bindings_and_volumes(docker, rows)
        settings = load_database_settings(ROOT / ".env")
        parameters = conninfo_to_dict(settings.database_url.get_secret_value())
        if (
            parameters.get("host") != "127.0.0.1"
            or parameters.get("hostaddr") not in {None, "127.0.0.1"}
            or parameters.get("port") not in {"5432", 5432}
            or parameters.get("dbname") != "regintel"
            or parameters.get("user") != "regintel"
        ):
            raise InfraError(
                "The SQL probe must target the generated project database on127.0.0.1:5432."
            )
        database_check = check_database(settings)
        neo_versions = docker.neo4j(
            "CALL dbms.components() YIELD versions,edition RETURN versions[0] AS version,edition;"
        )
        if ["5.26.31", "community"] not in neo_versions:
            raise InfraError("Neo4j runtime does not match the selected Community release.")
        redis_info = docker.redis("INFO", "server")
        if "redis_version:7.2.16" not in redis_info.splitlines():
            raise InfraError("Redis runtime does not match the selected patch.")
        if docker.redis("PING") != "PONG":
            raise InfraError("Authenticated Redis connectivity failed.")
        if "NOAUTH" not in docker.execute("redis", "redis-cli", "PING"):
            raise InfraError("Redis unexpectedly accepts unauthenticated commands.")
        redis_uid = docker.execute("redis", "id", "-u")
        if not redis_uid.isdigit() or int(redis_uid) == 0:
            raise InfraError("Redis must run as its non-root service user.")
        if docker.redis("CONFIG", "GET", "appendonly").splitlines() != [
            "appendonly",
            "yes",
        ]:
            raise InfraError("Redis append-only persistence is not configured.")
        if docker.redis("CONFIG", "GET", "appendfsync").splitlines() != [
            "appendfsync",
            "everysec",
        ]:
            raise InfraError("Redis appendfsync does not match the selected policy.")
        if options.restart:
            identifier = uuid4().hex
            table = sql.Identifier("regintel", f"_infra_probe_{identifier}")
            key = f"regintel:m0:probe:{identifier}"
            amount = Decimal("12345678.9012")
            created_table = False
            print(
                "Creating labeled synthetic probes and restarting only project services.",
                flush=True,
            )
            try:
                with connect_database(settings) as connection:
                    connection.execute(
                        sql.SQL("CREATE TABLE {} (amount NUMERIC(20,4) NOT NULL)").format(table)
                    )
                    created_table = True
                    connection.execute(
                        sql.SQL("INSERT INTO {} (amount) VALUES (%s)").format(table),
                        (amount,),
                    )
                docker.neo4j(
                    f"CREATE (:FoundationProbe {{id:'{identifier}',marker:'synthetic-m0'}});"
                )
                if docker.redis("SET", key, "synthetic-m0") != "OK":
                    raise InfraError("Redis synthetic probe write failed.")
                docker.compose("restart", "--timeout", "30", timeout=100)
                wait_healthy(docker)
                verify_bindings_and_volumes(docker, service_status(docker))
                with connect_database(settings) as connection:
                    result = connection.execute(
                        sql.SQL("SELECT amount FROM {}").format(table)
                    ).fetchone()
                    if result != (amount,):
                        raise InfraError(
                            "PostgreSQL Decimal probe did not survive restart exactly."
                        )
                if ["synthetic-m0"] not in docker.neo4j(
                    f"MATCH (p:FoundationProbe {{id:'{identifier}'}}) RETURN p.marker AS marker;"
                ):
                    raise InfraError("Neo4j probe did not survive restart.")
                if docker.redis("GET", key) != "synthetic-m0":
                    raise InfraError("Redis probe did not survive orderly restart.")
            finally:
                cleanup_failures: list[str] = []
                if created_table:
                    try:
                        with connect_database(settings) as connection:
                            connection.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(table))
                    except (psycopg.Error, MigrationError, OSError, ValueError):
                        cleanup_failures.append("postgres")
                try:
                    docker.neo4j(f"MATCH (p:FoundationProbe {{id:'{identifier}'}}) DELETE p;")
                except InfraError:
                    cleanup_failures.append("neo4j")
                try:
                    docker.redis("DEL", key)
                except InfraError:
                    cleanup_failures.append("redis")
                if cleanup_failures:
                    print(
                        f"Retained synthetic probe {identifier} in: {', '.join(cleanup_failures)}.",
                        file=sys.stderr,
                    )
                    if sys.exc_info()[0] is None:
                        raise InfraError(
                            "Synthetic probe cleanup failed; acceptance is incomplete."
                        )
        print(
            json.dumps(
                {
                    "postgres": database_check.postgres_version,
                    "pgvector": database_check.vector_version,
                    "vector_distance": database_check.vector_distance,
                    "neo4j": "5.26.31",
                    "redis": "7.2.16",
                    "loopback_bindings": True,
                    "named_volumes": True,
                    "persistence": "verified_orderly_service_restart"
                    if options.restart
                    else "not_run",
                }
            )
        )
        return 0
    except (InfraError, MigrationError, psycopg.Error, OSError, ValueError) as error:
        diagnostic = (
            str(error)
            if isinstance(error, InfraError)
            else "Infrastructure verification failed; secret values are omitted."
        )
        print(diagnostic, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
