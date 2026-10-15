"""Read the existing controlled real publication; never create or accept data."""

import argparse
import hashlib
import json
import runpy
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx2
import psycopg
from psycopg import sql

from regintel.auth.config import load_seed_accounts
from regintel.contracts.models import SuccessEnvelope
from regintel.db.config import load_database_settings
from regintel.db.migrations import connect_database, migration_status
from regintel.publication.service import current_configuration
from regintel.reads.models import (
    CompanyGraph,
    CompanyPage,
    FactPage,
    PublishedEvidence,
    ViewInfo,
)

ROOT = Path(__file__).resolve().parents[1]
TABLES = (
    "publication_builds",
    "publication_retrieval",
    "retrieval_chunks",
    "publication_graph_receipts",
    "publication_commits",
    "publication_observations",
    "publication_head",
    "retrieval_rebuilds",
    "acceptance_audits",
    "fact_observations",
    "relation_observations",
    "corpus_versions",
)


def require(condition: bool) -> None:
    if not condition:
        raise ValueError("The read-only controlled publication proof did not match recorded state.")


def snapshot() -> dict[str, str]:
    database = load_database_settings(ROOT / ".env")
    helper = runpy.run_path(str(ROOT / "scripts/check-publication-runtime.py"))
    original: dict[str, str] = helper["snapshot"](database)
    with connect_database(database) as connection, connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        for table in TABLES:
            rows = connection.execute(
                sql.SQL(
                    "SELECT row_to_json(t)::TEXT FROM {} t ORDER BY row_to_json(t)::TEXT"
                ).format(sql.Identifier("regintel", table))
            ).fetchall()
            original[table] = hashlib.sha256(
                json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
            ).hexdigest()
    return original


def prove(api_base: str) -> dict[str, object]:
    target = urlsplit(api_base)
    require(
        target.scheme == "http"
        and target.hostname == "127.0.0.1"
        and target.port is not None
        and target.path in ("", "/")
        and not target.username
        and not target.password
        and not target.query
        and not target.fragment
    )
    recorded = json.loads((ROOT / "data/publication-validation-report.json").read_text())
    database = load_database_settings(ROOT / ".env")
    status = migration_status(database)
    require(status.applied == tuple(range(1, 12)) and not status.pending)
    require(
        current_configuration(ROOT / "models/bge-small-en-v1.5").sha256
        == recorded["configuration_sha256"]
    )
    before = snapshot()
    accounts = load_seed_accounts(ROOT / ".env.auth")
    learner = next(account for account in accounts if account.role == "learner")
    corpus = recorded["corpus_version_id"]
    observation_id = recorded["observation_id"]
    with httpx2.Client(base_url=api_base, timeout=30, trust_env=False) as client:
        login = client.post(
            "/v1/auth/token",
            data={
                "grant_type": "password",
                "username": learner.username,
                "password": learner.password.get_secret_value(),
            },
        )
        require(login.status_code == 200)
        token = login.json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        current = client.get("/v1/published-corpus", headers=headers)
        require(current.status_code == 200)
        info = SuccessEnvelope[ViewInfo].model_validate_json(current.content)
        require(
            info.data.corpus_version_id == corpus
            and info.data.manifest_sha256 == recorded["manifest_sha256"]
        )
        require(info.meta.versions.corpus_version_id == corpus)
        companies_response = client.get(
            "/v1/companies",
            params={"corpus_version_id": corpus, "q": "Premier"},
            headers=headers,
        )
        require(companies_response.status_code == 200)
        companies = SuccessEnvelope[CompanyPage].model_validate_json(companies_response.content)
        require(companies.data.total == 1 and len(companies.data.companies) == 1)
        company = companies.data.companies[0]
        require(company.id == "581d1b0d-98fd-4a23-8e15-5574dac650a2")
        facts_response = client.get(
            f"/v1/companies/{company.id}/facts",
            params={"corpus_version_id": corpus},
            headers=headers,
        )
        require(facts_response.status_code == 200)
        facts = SuccessEnvelope[FactPage].model_validate_json(facts_response.content)
        require(facts.data.total == 1 and facts.data.facts[0].observation.id == observation_id)
        observation = facts.data.facts[0].observation
        require(
            observation.kind == "narrative_fact"
            and observation.quantity is None
            and observation.review_id == recorded["original_review_id"]
            and observation.validation_run_id == recorded["fresh_validation_run_id"]
        )
        graph_response = client.get(
            f"/v1/companies/{company.id}/graph",
            params={"corpus_version_id": corpus},
            headers=headers,
        )
        require(graph_response.status_code == 200)
        graph = SuccessEnvelope[CompanyGraph].model_validate_json(graph_response.content)
        require(len(graph.data.nodes) == 1 and not graph.data.edges)
        base = f"/v1/corpora/{corpus}/observations/{observation.id}"
        support = observation.supports[0]
        evidence_response = client.get(base + "/evidence/" + support.evidence_id, headers=headers)
        require(evidence_response.status_code == 200)
        evidence = SuccessEnvelope[PublishedEvidence].model_validate_json(evidence_response.content)
        require(
            evidence.data.supports == observation.supports
            and evidence.data.evidence.source_sha256 == recorded["source_sha256"]
        )
        pdf = client.get(base + "/source.pdf", headers=headers)
        require(
            pdf.status_code == 200
            and hashlib.sha256(pdf.content).hexdigest() == recorded["source_sha256"]
        )
        require(pdf.headers.get("x-corpus-version-id") == corpus)
        head = client.head(base + "/source.pdf", headers=headers)
        require(
            head.status_code == 200
            and not head.content
            and head.headers["etag"] == pdf.headers["etag"]
        )
        ranged = client.get(base + "/source.pdf", headers={**headers, "Range": "bytes=0-63"})
        require(ranged.status_code == 206 and ranged.content == pdf.content[:64])
        require(
            client.get(
                base + "/source.pdf",
                headers={**headers, "If-None-Match": pdf.headers["etag"]},
            ).status_code
            == 304
        )
        for path in (
            "/v1/companies",
            f"/v1/companies/{company.id}/facts",
            f"/v1/companies/{company.id}/graph",
            base + "/source.pdf",
            base + "/evidence/" + support.evidence_id,
        ):
            require(client.get(path).status_code == 401)
        require(
            client.get("/v1/evidence/" + support.evidence_id, headers=headers).status_code == 403
        )
        require(
            client.get(
                f"/v1/filing-versions/{observation.filing_version_id}/source.pdf",
                headers=headers,
            ).status_code
            == 403
        )
        require(
            client.get(
                "/v1/companies",
                params={"corpus_version_id": str(uuid4())},
                headers=headers,
            ).status_code
            == 404
        )
        require(client.get(base + "/evidence/" + str(uuid4()), headers=headers).status_code == 404)
        require(
            client.get(
                f"/v1/corpora/{corpus}/observations/{uuid4()}/source.pdf",
                headers=headers,
            ).status_code
            == 404
        )
        temporal_response = client.get(
            "/v1/companies",
            params={"corpus_version_id": corpus, "as_of_date": "2026-01-01"},
            headers=headers,
        )
        require(temporal_response.status_code == 200)
        temporal = SuccessEnvelope[CompanyPage].model_validate_json(temporal_response.content)
        require(
            temporal.data.view.state == "TEMPORAL_SUPPORT_UNAVAILABLE"
            and not temporal.data.companies
        )
    after = snapshot()
    require(before == after)
    return {
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "phase": "M1.10",
        "status": "passed — bounded real published reads",
        "corpus_version_id": corpus,
        "manifest_sha256": recorded["manifest_sha256"],
        "company_id": company.id,
        "observation_id": observation.id,
        "evidence_id": support.evidence_id,
        "source_sha256": recorded["source_sha256"],
        "source_byte_size": len(pdf.content),
        "page_index": evidence.data.evidence.record.source.page_index,
        "published_facts": facts.data.total,
        "corporate_graph_nodes": len(graph.data.nodes),
        "corporate_graph_edges": 0,
        "learner_reads_exact_versions": "passed",
        "anonymous_denials": "passed",
        "administrator_only_original_routes_preserved": "passed",
        "cross_corpus_observation_evidence_denials": "passed",
        "original_pdf_hash_head_range_conditional": "passed",
        "unknown_date_as_of": "TEMPORAL_SUPPORT_UNAVAILABLE",
        "source_processing_publication_snapshots_unchanged": True,
        "snapshot_sha256": after,
        "migration_applied": list(status.applied),
        "new_migrations": 0,
        "provider_calls": 0,
        "limitations": [
            "One real conditional narrative; parent remains unresolved.",
            "No real numeric/relation positive or amendment pair is claimed.",
            "Engineering verification only; no held-out research effectiveness.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", required=True)
    options = parser.parse_args()
    try:
        result = prove(options.api_base)
        directory = ROOT / ".cache" / ("published-reads-runtime-" + uuid4().hex)
        directory.mkdir()
        (directory / "report.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "status": "passed",
                    "report": str(directory / "report.json"),
                    "published_facts": 1,
                    "corporate_relations": 0,
                }
            )
        )
        return 0
    except (OSError, ValueError, StopIteration, KeyError, httpx2.HTTPError, psycopg.Error):
        print("Read-only published proof failed; secrets and source payloads omitted.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
