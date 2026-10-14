"""Controlled M1.7 HTTP proof against one existing sealed real-filing candidate run.

Validates/replays the original proposal and optionally stages its complete
conditional extractive statement. No accepted observation, corpus, provider call,
source acquisition or parsing is created. Staging requires --stage-review.
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
from regintel.candidates.records import drafts, stable_id
from regintel.contracts.models import TextEvidence
from regintel.db.config import DatabaseSettings, load_database_settings
from regintel.db.migrations import connect_database, migration_status
from regintel.validation.api import ReviewEnvelope, ValidationEnvelope
from regintel.validation.gate import current_configuration
from regintel.validation.models import ReviewDecision, ValidationRun
from regintel.validation.repository import ValidationRepository, checked

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "a15329da96a20117a5cfaccf535ab3dc805c6ed195e392bb5ec6131f8f246347"
PROBE_METRIC_ID = "157319cf-8d48-4549-9d10-6b0d35854466"
SOURCE_STATEMENT = (
    "PREMIER ENERGIES LIMITED is proposing, subject to applicable statutory and regulatory "
    "requirements, receipt of requisite approvals, market conditions and other considerations, "
    "to undertake an initial public offering of its Equity Shares and has filed "
    "the RHP with the RoC."
)
AUTHORITY_TABLES = (
    "acceptance_audits",
    "fact_observations",
    "relation_observations",
    "corpus_versions",
)


class ProofFailure(ValueError):
    """Fixed operator diagnostics that contain no credential or source payload."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProofFailure(message)


def snapshot(database: DatabaseSettings) -> dict[str, object]:
    result: dict[str, object] = {}
    with connect_database(database) as connection, connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
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
            "metric_definitions",
            "candidates",
            "candidate_runs",
            "numeric_metric_policies",
            *AUTHORITY_TABLES,
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
    parser.add_argument("--candidate-run-id", required=True)
    parser.add_argument(
        "--stage-review", action="store_true", help="Explicitly stage the controlled narrative."
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
            str(UUID(args.candidate_run_id)) == args.candidate_run_id,
            "Use a canonical candidate-run ID.",
        )
        base = args.api_base.rstrip("/")
        database = load_database_settings(ROOT / ".env")
        source = ValidationRepository(database).input_for_run(args.candidate_run_id)
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
                (source.candidate_run.parse_version_id,),
            ).fetchone()
        require(source_row == (SOURCE_SHA,), "Candidate run is not the controlled original.")
        proposed = drafts(source.candidate_run.bundle)
        require(
            len(proposed) == 1
            and proposed[0].kind == "narrative_fact"
            and proposed[0].metric_id == PROBE_METRIC_ID
            and proposed[0].raw_text == SOURCE_STATEMENT
            and proposed[0].supports[0].quote == SOURCE_STATEMENT,
            "Use the existing complete conditional narrative probe.",
        )
        primary = proposed[0].supports[0]
        before = snapshot(database)
        headers: dict[str, dict[str, str]] = {}
        receipt: ReviewEnvelope | None = None
        review: ReviewDecision | None = None
        review_run: ValidationRun | None = None
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
            body = {"candidate_run_id": args.candidate_run_id}
            response = client.post(
                base + "/v1/admin/validation/runs", headers=headers["admin"], json=body
            )
            require(response.status_code == 200, "Real validation failed.")
            envelope = ValidationEnvelope.model_validate_json(response.content)
            run = envelope.data.run
            require(
                run.configuration == current_configuration()
                and run.input_sha256 == source.sha256
                and len(run.results) == 1
                and run.results[0].candidate_id == source.candidate_run.candidates[0].id
                and envelope.meta.versions.parse_version_id == run.parse_version_id
                and envelope.meta.versions.corpus_version_id is None
                and response.headers.get("cache-control") == "no-store",
                "Validation configuration, membership or authority boundary differs.",
            )
            for method, path, request_body in (
                ("POST", "/v1/admin/validation/runs", body),
                ("GET", "/v1/admin/validation/runs/" + run.id, None),
            ):
                response = client.request(
                    method, base + path, headers=headers["admin"], json=request_body
                )
                require(
                    response.status_code == 200
                    and ValidationEnvelope.model_validate_json(response.content).data.run == run,
                    "Validation replay or persisted read differs.",
                )
            response = client.get(
                base + "/v1/evidence/" + primary.evidence_id, headers=headers["admin"]
            )
            require(response.status_code == 200, "Original evidence read failed.")
            actual = TextEvidence.model_validate(response.json()["data"]["record"])
            require(
                actual in source.source.evidence
                and actual.span.quote[
                    primary.start - actual.span.start : primary.end - actual.span.start
                ]
                == SOURCE_STATEMENT,
                "Original complete conditional source statement differs.",
            )
            if args.stage_review:
                require(
                    run.results[0].state == "REVIEW"
                    and run.results[0].reviewer_eligible
                    and {item.code for item in run.results[0].checks if item.state != "PASS"}
                    == {"EXTRACTIVE_REVIEW"},
                    "The controlled statement is not eligible for extractive confirmation.",
                )
                proposed_review = ReviewDecision(
                    id=stable_id("validation-proof-review:" + run.id + ":" + primary.evidence_id),
                    validation_run_id=run.id,
                    candidate_id=run.results[0].candidate_id,
                    decision="APPROVE_FOR_PUBLICATION",
                    supports=proposed[0].supports,
                    review_note=(
                        "Controlled engineering proof: the complete exact issuer statement retains "
                        "proposing, statutory/regulatory approvals and market conditions. "
                        "Staged extractive eligibility only; not acceptance, publication, "
                        "independent gold annotation or an assertion that the offering occurred."
                    ),
                )
                with connect_database(database) as connection:
                    prior = connection.execute(
                        "SELECT review_bytes,review_sha256 FROM regintel.validation_reviews "
                        "WHERE candidate_id=%s",
                        (run.results[0].candidate_id,),
                    ).fetchone()
                review = (
                    ReviewDecision.model_validate_json(checked(prior[0], prior[1]))
                    if prior is not None
                    else proposed_review
                )
                require(
                    review.candidate_id == proposed_review.candidate_id
                    and review.decision == proposed_review.decision
                    and review.supports == proposed_review.supports,
                    "The candidate has a different immutable final review.",
                )
                # Code updates create a fresh gate run, not a second final review.
                # Preserve/replay the original audit and disclose its configuration.
                response = client.get(
                    base + "/v1/admin/validation/runs/" + review.validation_run_id,
                    headers=headers["admin"],
                )
                require(response.status_code == 200, "Original review gate read failed.")
                review_run = ValidationEnvelope.model_validate_json(response.content).data.run
                require(
                    any(item.candidate_id == review.candidate_id for item in review_run.results),
                    "Original review gate membership differs.",
                )
                response = client.post(
                    base + "/v1/admin/validation/reviews",
                    headers=headers["admin"],
                    json=review.model_dump(mode="json"),
                )
                require(response.status_code == 200, "Controlled staged review failed.")
                receipt = ReviewEnvelope.model_validate_json(response.content)
                repeated = client.post(
                    base + "/v1/admin/validation/reviews",
                    headers=headers["admin"],
                    json=review.model_dump(mode="json"),
                )
                require(
                    repeated.status_code == 200
                    and ReviewEnvelope.model_validate_json(repeated.content).data.already_exists,
                    "Staged review replay was not a no-op.",
                )
                response = client.get(
                    base + "/v1/admin/validation/runs/" + review.validation_run_id,
                    headers=headers["admin"],
                )
                require(
                    response.status_code == 200
                    and ValidationEnvelope.model_validate_json(response.content).data.reviews
                    == (review,),
                    "Persisted staged review differs.",
                )
            for denied_headers, expected in ((headers["learner"], 403), ({}, 401)):
                require(
                    client.post(
                        base + "/v1/admin/validation/runs", headers=denied_headers, json=body
                    ).status_code
                    == expected,
                    "Protected validation write was not denied.",
                )
                require(
                    client.get(
                        base + "/v1/admin/validation/runs/" + run.id, headers=denied_headers
                    ).status_code
                    == expected,
                    "Protected validation read was not denied.",
                )
                if review is not None:
                    require(
                        client.post(
                            base + "/v1/admin/validation/reviews",
                            headers=denied_headers,
                            json=review.model_dump(mode="json"),
                        ).status_code
                        == expected,
                        "Protected staged review write was not denied.",
                    )
        require(snapshot(database) == before, "Earlier source/candidates or authority changed.")
        migration = migration_status(database)
        require(
            migration.applied == tuple(range(1, 9)) and not migration.pending,
            "Validation migration checkpoint is incomplete.",
        )
        with connect_database(database) as connection:
            authority = {
                table: connection.execute(f"SELECT count(*) FROM regintel.{table}").fetchone()
                for table in AUTHORITY_TABLES
            }
        require(
            all(count == (0,) for count in authority.values()), "Financial authority is not closed."
        )
        report = {
            "recorded_at_utc": datetime.now(UTC).isoformat(),
            "phase": "M1.7",
            "source_sha256": SOURCE_SHA,
            "parse_version_id": run.parse_version_id,
            "artifact_sha256": source.source.entity_run.artifact_sha256,
            "candidate_run_id": run.candidate_run_id,
            "run_id": run.id,
            "input_sha256": run.input_sha256,
            "configuration": run.configuration.model_dump(mode="json"),
            "configuration_sha256": run.configuration.sha256,
            "evidence_count": len(source.source.evidence),
            "table_risk_evidence_count": len(source.table_evidence_ids),
            "transcription_risk_evidence_count": len(source.transcription_evidence_ids),
            "candidate_count": len(run.results),
            "state_counts": dict(Counter(item.state for item in run.results)),
            "nonpassing_check_counts": dict(
                Counter(
                    item.code
                    for result in run.results
                    for item in result.checks
                    if item.state != "PASS"
                )
            ),
            "reviewer_eligible_count": sum(result.reviewer_eligible for result in run.results),
            "review_id": review.id if review is not None else None,
            "review_decision": review.decision if review is not None else None,
            "review_validation_run_id": review.validation_run_id if review is not None else None,
            "review_configuration_sha256": review_run.configuration.sha256
            if review_run is not None
            else None,
            "review_recorded_for_current_configuration": review_run.configuration
            == run.configuration
            if review_run is not None
            else None,
            "review_already_existed": receipt.data.already_exists if receipt is not None else None,
            "validation_and_read_replay": "passed",
            "review_replay": "passed" if review is not None else "not requested",
            "anonymous_and_learner_denials": "passed",
            "original_evidence_read": "passed",
            "earlier_snapshot_unchanged": True,
            "authority_counts": {table: 0 for table in authority},
            "migration_applied": list(migration.applied),
            "provider_calls": 0,
            "limitations": [
                "One controlled narrative; not gold annotation or research effectiveness.",
                "The candidate stays CANDIDATE; staged approval is not acceptance/publication.",
                "Final reviews survive code updates; publication must freshly revalidate.",
                "No real numeric/relation positive, exact table-cell proof or OCR review.",
                "Recovery, amendment effects and publication are later stages.",
            ],
        }
        directory = ROOT / ".cache" / f"validation-runtime-{uuid4().hex}"
        directory.mkdir()
        (directory / "report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        (directory / "run.json").write_text(run.model_dump_json(indent=2) + "\n", encoding="utf-8")
        if review is not None:
            (directory / "review.json").write_text(
                review.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
        print(
            json.dumps(
                {
                    "proof_directory": str(directory),
                    "run_id": run.id,
                    "state_counts": report["state_counts"],
                    "staged_review": review is not None,
                    "authority_counts": report["authority_counts"],
                }
            )
        )
        return 0
    except Exception as error:
        diagnostic = str(error) if isinstance(error, ProofFailure) else type(error).__name__
        print(f"Validation runtime proof failed: {diagnostic} Secrets omitted.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
