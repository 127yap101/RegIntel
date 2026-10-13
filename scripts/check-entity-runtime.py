"""Real M1.5 HTTP proof; preserves source/jobs and accepts no financial facts.

Requires an already configured local API, sealed PARSED input and generated
project credentials. It registers only the known source-backed Premier issuer,
persists/replays resolution runs, and saves a new ignored proof directory.
"""

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx2

from regintel.auth.config import load_seed_accounts
from regintel.contracts.models import TextEvidence
from regintel.db.config import load_database_settings
from regintel.db.migrations import connect_database, migration_status
from regintel.entities.api import RegistrationEnvelope, RunEnvelope
from regintel.entities.models import ApprovedIdentifier, EntityRegistration, EvidenceAnchor
from regintel.entities.repository import EntityRepository
from regintel.entities.resolution import stable_id

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "a15329da96a20117a5cfaccf535ab3dc805c6ed195e392bb5ec6131f8f246347"
CIN = "U40106TG1995PLC019909"


class ProofFailure(ValueError):
    """Only fixed operator diagnostics; never driver/credential/source payloads."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProofFailure(message)


def anchor(value: str, evidence: tuple[TextEvidence, ...]) -> EvidenceAnchor:
    for record in sorted(evidence, key=lambda item: (item.source.page_index, item.id)):
        index = record.span.quote.casefold().find(value.casefold())
        if index >= 0:
            # The selected English issuer/identifier strings are ASCII, so casefold
            # retains code-point offsets. Actual source bytes remain untouched.
            quote = record.span.quote[index : index + len(value)]
            require(quote.casefold() == value.casefold(), "Issuer span is unavailable.")
            return EvidenceAnchor(
                evidence_id=record.id,
                start=record.span.start + index,
                end=record.span.start + index + len(quote),
                quote=quote,
            )
    raise ProofFailure("Known issuer/identifier has no exact source support.")


def snapshot() -> dict[str, object]:
    settings = load_database_settings(ROOT / ".env")
    with connect_database(settings) as connection, connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        result: dict[str, object] = {}
        for table in (
            "source_blobs",
            "filings",
            "filing_versions",
            "parse_versions",
            "evidence",
            "filing_jobs",
            "candidates",
            "acceptance_audits",
            "fact_observations",
            "relation_observations",
            "corpus_versions",
        ):
            # Identifiers come solely from the constant list above, never user input.
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
    parser.add_argument("--parse-version-id", required=True)
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
        base = args.api_base.rstrip("/")
        settings = load_database_settings(ROOT / ".env")
        repository = EntityRepository(settings)
        evidence, artifact_sha = repository.evidence_for_parse(args.parse_version_id)
        source = ROOT / "data/raw/premier-energies-addendum-rhp-sebi-20240826.pdf"
        require(
            source.is_file()
            and not source.is_symlink()
            and not source.is_junction()
            and source.stat().st_size == 196270,
            "Controlled original is unavailable.",
        )
        require(
            hashlib.sha256(source.read_bytes()).hexdigest() == SOURCE_SHA,
            "Controlled original source hash differs.",
        )
        with connect_database(settings) as connection:
            row = connection.execute(
                "SELECT s.sha256 FROM regintel.parse_versions p JOIN regintel.source_blobs s "
                "ON s.id=p.source_blob_id WHERE p.id=%s",
                (args.parse_version_id,),
            ).fetchone()
        require(row == (SOURCE_SHA,), "Parse is not the controlled original source.")
        before = snapshot()
        name_support = anchor("Premier Energies Limited", evidence)
        cin_support = anchor(CIN, evidence)
        registration = EntityRegistration(
            id=stable_id(f"regintel-company:CIN:{CIN}"),
            kind="COMPANY",
            legal_name=name_support.quote,
            legal_name_support=name_support,
            identifiers=(ApprovedIdentifier(kind="CIN", value=CIN, support=cin_support),),
            review_note="M1.5 engineering proof: issuer name and CIN verified against the "
            "controlled source. Not a research gold annotation or financial acceptance.",
        )
        accounts = load_seed_accounts(ROOT / ".env.auth")
        with httpx2.Client(timeout=120, trust_env=False) as client:
            headers: dict[str, dict[str, str]] = {}
            for account in accounts:
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
            require(set(headers) == {"admin", "learner"}, "Seeded role identities are unavailable.")
            response = client.post(
                base + "/v1/admin/entities",
                headers=headers["admin"],
                json=registration.model_dump(mode="json"),
            )
            require(response.status_code == 200, "Source-backed registration failed.")
            receipt = RegistrationEnvelope.model_validate_json(response.content)
            repeated = client.post(
                base + "/v1/admin/entities",
                headers=headers["admin"],
                json=registration.model_dump(mode="json"),
            )
            require(
                repeated.status_code == 200
                and RegistrationEnvelope.model_validate_json(repeated.content).data.already_exists,
                "Registration replay was not a no-op.",
            )
            run_body = {"parse_version_id": args.parse_version_id}
            response = client.post(
                base + "/v1/admin/entities/runs", headers=headers["admin"], json=run_body
            )
            require(response.status_code == 200, "Real entity resolution failed.")
            result = RunEnvelope.model_validate_json(response.content)
            run = result.data.run
            repeated = client.post(
                base + "/v1/admin/entities/runs", headers=headers["admin"], json=run_body
            )
            require(
                repeated.status_code == 200
                and RunEnvelope.model_validate_json(repeated.content).data.run == run,
                "Real entity replay changed the immutable result.",
            )
            response = client.get(
                base + f"/v1/admin/entities/runs/{run.id}", headers=headers["admin"]
            )
            require(
                response.status_code == 200
                and RunEnvelope.model_validate_json(response.content).data.run == run,
                "Persisted run read differs.",
            )
            cin_mentions = [item for item in run.mentions if item.support.quote == CIN]
            require(
                bool(cin_mentions)
                and all(
                    item.resolution.state == "RESOLVED"
                    and item.resolution.entity_id == registration.id
                    for item in cin_mentions
                ),
                "Known CIN was not resolved through the approved identifier.",
            )
            require(
                any(
                    item.kind == "NAME" and item.resolution.entity_id == registration.id
                    for item in run.mentions
                ),
                "Known issuer name was not resolved.",
            )
            for path in ("/v1/admin/entities", "/v1/admin/entities/runs"):
                body = (
                    registration.model_dump(mode="json") if path.endswith("entities") else run_body
                )
                require(
                    client.post(base + path, headers=headers["learner"], json=body).status_code
                    == 403,
                    "Learner entity write was not denied.",
                )
                require(
                    client.post(base + path, json=body).status_code == 401,
                    "Anonymous entity write was not denied.",
                )
            for support in (name_support, cin_support):
                response = client.get(
                    base + f"/v1/evidence/{support.evidence_id}", headers=headers["admin"]
                )
                require(response.status_code == 200, "Original evidence read failed.")
                actual = TextEvidence.model_validate(response.json()["data"]["record"])
                require(actual in evidence, "Original source evidence changed.")
        require(snapshot() == before, "Source/jobs or financial authority changed.")
        migration_report = migration_status(settings)
        require(
            migration_report.applied == (1, 2, 3, 4, 5, 6) and not migration_report.pending,
            "Entity migration checkpoint is incomplete.",
        )
        counts = dict(Counter(item.resolution.state for item in run.mentions))
        report = {
            "recorded_at_utc": datetime.now(UTC).isoformat(),
            "phase": "M1.5",
            "source_sha256": SOURCE_SHA,
            "parse_version_id": run.parse_version_id,
            "artifact_sha256": artifact_sha,
            "entity_id": registration.id,
            "run_id": run.id,
            "registration_already_existed": receipt.data.already_exists,
            "registry_revision": run.registry_revision,
            "registry_sha256": run.registry_sha256,
            "configuration": run.configuration.model_dump(mode="json"),
            "configuration_sha256": run.configuration.sha256,
            "evidence_count": len(evidence),
            "mention_count": len(run.mentions),
            "resolution_counts": counts,
            "registration_and_run_replay": "passed",
            "anonymous_and_learner_denials": "passed",
            "original_evidence_reads": "passed",
            "source_job_and_financial_snapshot_unchanged": True,
            "migration_applied": list(migration_report.applied),
            "limitations": [
                "One controlled three-page source; not held-out research accuracy.",
                "Exact table-cell originals remain unavailable.",
                "Engineering operator registration; not independently human-reviewed gold data.",
                "No candidates, accepted financial observations or corpus publication.",
            ],
        }
        directory = ROOT / ".cache" / f"entity-runtime-{uuid4().hex}"
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
                    "mention_count": len(run.mentions),
                    "resolution_counts": counts,
                }
            )
        )
        return 0
    except Exception as error:
        # Never echo credentials, request bodies, driver or source diagnostics.
        diagnostic = str(error) if isinstance(error, ProofFailure) else type(error).__name__
        print(f"Entity runtime proof failed: {diagnostic} Secrets omitted.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
