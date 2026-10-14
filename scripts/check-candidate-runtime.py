"""Controlled M1.6 HTTP proof against one existing sealed real-filing entity run.

Registers the explicitly supplied extraction-only probe metric, persists/replays
raw proposals, verifies exact evidence and preserves all earlier authority. No
provider calls, financial acceptance, publication, source acquisition or parsing.
"""

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx2

from regintel.auth.config import load_seed_accounts
from regintel.candidates.api import CandidateEnvelope, MetricEnvelope
from regintel.candidates.extraction import current_configuration
from regintel.candidates.models import MetricDefinition
from regintel.candidates.repository import CandidateRepository
from regintel.contracts.models import TextEvidence
from regintel.db.config import DatabaseSettings, load_database_settings
from regintel.db.migrations import connect_database, migration_status

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "a15329da96a20117a5cfaccf535ab3dc805c6ed195e392bb5ec6131f8f246347"


class ProofFailure(ValueError):
    """Fixed operator diagnostics that contain no credential or source payload."""


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
            "parse_versions",
            "evidence",
            "filing_jobs",
            "entity_registrations",
            "entity_runs",
            "entity_reviews",
            "acceptance_audits",
            "fact_observations",
            "relation_observations",
            "corpus_versions",
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--entity-run-id", required=True)
    parser.add_argument(
        "--metric-file", type=Path, default=ROOT / "data/candidate-probe-metric.json"
    )
    args = parser.parse_args()
    try:
        target = urlsplit(args.api_base)
        require(
            target.scheme == "http"
            and target.hostname == "127.0.0.1"
            and target.username is None
            and target.password is None
            and target.port is not None
            and 1 <= target.port <= 65535
            and target.path in {"", "/"}
            and not target.query
            and not target.fragment,
            "Use an explicit loopback HTTP API.",
        )
        require(
            str(UUID(args.entity_run_id)) == args.entity_run_id, "Use a canonical entity-run ID."
        )
        base = args.api_base.rstrip("/")
        metric_path = args.metric_file.resolve()
        require(
            metric_path.is_relative_to(ROOT)
            and metric_path.is_file()
            and metric_path.stat().st_size <= 65536,
            "Use an explicit bounded project metric definition.",
        )
        metric = MetricDefinition.model_validate_json(metric_path.read_bytes())
        database = load_database_settings(ROOT / ".env")
        repository = CandidateRepository(database)
        source = repository.input_for_run(args.entity_run_id, ())
        original = ROOT / "data/raw/premier-energies-addendum-rhp-sebi-20240826.pdf"
        require(
            original.is_file()
            and not original.is_symlink()
            and not original.is_junction()
            and original.stat().st_size == 196270,
            "Controlled original is unavailable.",
        )
        require(
            hashlib.sha256(original.read_bytes()).hexdigest() == SOURCE_SHA,
            "Controlled original source hash differs.",
        )
        with connect_database(database) as connection:
            source_row = connection.execute(
                "SELECT s.sha256 FROM regintel.parse_versions p JOIN regintel.source_blobs s "
                "ON s.id=p.source_blob_id WHERE p.id=%s",
                (source.parse_version_id,),
            ).fetchone()
        require(source_row == (SOURCE_SHA,), "Entity run is not the controlled original source.")
        before = snapshot(database)
        headers: dict[str, dict[str, str]] = {}
        with httpx2.Client(timeout=120, trust_env=False) as client:
            for account in load_seed_accounts(ROOT / ".env.auth"):
                response = client.post(
                    base + "/v1/auth/token",
                    data={
                        "grant_type": "password",
                        "username": account.username,
                        "password": account.password.get_secret_value(),
                    },
                )
                require(response.status_code == 200, "Local authentication failed.")
                token = response.json().get("access_token")
                require(isinstance(token, str), "Local authentication failed.")
                headers[account.role] = {"Authorization": f"Bearer {token}"}
            require(set(headers) == {"admin", "learner"}, "Seeded roles are unavailable.")
            path = base + "/v1/admin/candidates/metrics"
            response = client.post(
                path, headers=headers["admin"], json=metric.model_dump(mode="json")
            )
            require(response.status_code == 200, "Explicit metric registration failed.")
            receipt = MetricEnvelope.model_validate_json(response.content)
            repeated = client.post(
                path, headers=headers["admin"], json=metric.model_dump(mode="json")
            )
            require(
                repeated.status_code == 200
                and MetricEnvelope.model_validate_json(repeated.content).data.already_exists,
                "Metric replay was not a no-op.",
            )
            body = {"entity_run_id": args.entity_run_id, "metric_ids": [metric.id]}
            response = client.post(
                base + "/v1/admin/candidates/runs", headers=headers["admin"], json=body
            )
            require(response.status_code == 200, "Real candidate extraction failed.")
            run = CandidateEnvelope.model_validate_json(response.content).data
            require(bool(run.candidates), "Controlled source produced no exact proposal.")
            require(
                run.configuration == current_configuration(), "Extraction configuration differs."
            )
            repeated = client.post(
                base + "/v1/admin/candidates/runs", headers=headers["admin"], json=body
            )
            require(
                repeated.status_code == 200
                and CandidateEnvelope.model_validate_json(repeated.content).data == run,
                "Real extraction replay changed the immutable result.",
            )
            response = client.get(
                base + "/v1/admin/candidates/runs/" + run.id, headers=headers["admin"]
            )
            require(
                response.status_code == 200
                and CandidateEnvelope.model_validate_json(response.content).data == run,
                "Persisted candidate read differs.",
            )
            for path, request_body in (
                ("/v1/admin/candidates/metrics", metric.model_dump(mode="json")),
                ("/v1/admin/candidates/runs", body),
            ):
                require(
                    client.post(
                        base + path, headers=headers["learner"], json=request_body
                    ).status_code
                    == 403,
                    "Learner candidate write was not denied.",
                )
                require(
                    client.post(base + path, json=request_body).status_code == 401,
                    "Anonymous candidate write was not denied.",
                )
            for denied_headers, expected in ((headers["learner"], 403), ({}, 401)):
                require(
                    client.get(
                        base + "/v1/admin/candidates/runs/" + run.id, headers=denied_headers
                    ).status_code
                    == expected,
                    "Protected candidate read was not denied.",
                )
            evidence_ids = {
                identifier for item in run.candidates for identifier in item.evidence_ids
            }
            for evidence_id in evidence_ids:
                response = client.get(
                    base + "/v1/evidence/" + evidence_id, headers=headers["admin"]
                )
                require(response.status_code == 200, "Original evidence read failed.")
                actual = TextEvidence.model_validate(response.json()["data"]["record"])
                require(actual in source.evidence, "Original exact evidence changed.")
        require(snapshot(database) == before, "Earlier source/jobs/entities or authority changed.")
        migration = migration_status(database)
        require(
            migration.applied == (1, 2, 3, 4, 5, 6, 7) and not migration.pending,
            "Candidate migration checkpoint is incomplete.",
        )
        with connect_database(database) as connection:
            orphans = connection.execute(
                "SELECT count(*) FROM regintel.candidates c "
                "LEFT JOIN regintel.candidate_run_items i "
                "ON i.candidate_id=c.id WHERE i.candidate_id IS NULL"
            ).fetchone()
            authority = {
                table: connection.execute(f"SELECT count(*) FROM regintel.{table}").fetchone()
                for table in (
                    "acceptance_audits",
                    "fact_observations",
                    "relation_observations",
                    "corpus_versions",
                )
            }
        require(orphans == (0,), "An unowned candidate exists outside a sealed run.")
        require(
            all(count == (0,) for count in authority.values()), "Financial authority is not closed."
        )
        report = {
            "recorded_at_utc": datetime.now(UTC).isoformat(),
            "phase": "M1.6",
            "source_sha256": SOURCE_SHA,
            "parse_version_id": run.parse_version_id,
            "artifact_sha256": source.entity_run.artifact_sha256,
            "entity_run_id": run.entity_run_id,
            "run_id": run.id,
            "input_sha256": run.input_sha256,
            "configuration": run.configuration.model_dump(mode="json"),
            "configuration_sha256": run.configuration.sha256,
            "metric": metric.model_dump(mode="json"),
            "metric_already_existed": receipt.data.already_exists,
            "evidence_count": len(source.evidence),
            "candidate_count": len(run.candidates),
            "candidate_kind_counts": dict(Counter(item.kind for item in run.candidates)),
            "issue_counts": dict(Counter(item.code for item in run.bundle.issues)),
            "metric_and_run_replay": "passed",
            "anonymous_and_learner_denials": "passed",
            "original_evidence_reads": "passed",
            "earlier_snapshot_unchanged": True,
            "unowned_candidate_count": 0,
            "authority_counts": {table: 0 for table in authority},
            "migration_applied": list(migration.applied),
            "provider_calls": 0,
            "limitations": [
                "One controlled source and one explicit probe metric; not research effectiveness.",
                "The original conditional disclosure remains an unaccepted narrative proposal.",
                "No real numeric/relation result, table-cell extraction or context normalization "
                "demonstrated.",
                "Provider adapter verified with offline mocks; live SDK/model selection/usage "
                "not performed.",
                "M1.7 acceptance/review, recovery and amendment/publication remain later work.",
            ],
        }
        directory = ROOT / ".cache" / f"candidate-runtime-{uuid4().hex}"
        directory.mkdir()
        (directory / "report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        (directory / "run.json").write_text(run.model_dump_json(indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "proof_directory": str(directory),
                    "run_id": run.id,
                    "candidate_count": len(run.candidates),
                    "kind_counts": report["candidate_kind_counts"],
                }
            )
        )
        return 0
    except Exception as error:
        diagnostic = str(error) if isinstance(error, ProofFailure) else type(error).__name__
        print(f"Candidate runtime proof failed: {diagnostic} Secrets omitted.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
