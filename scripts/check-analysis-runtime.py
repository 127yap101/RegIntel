"""Read-only M2 boundary proof against the existing controlled real publication."""

import argparse
import hashlib
import json
import runpy
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from fastapi.testclient import TestClient

from regintel.analysis.models import QuotesResult
from regintel.auth.config import load_auth_settings, load_seed_accounts
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.auth.service import AuthService
from regintel.contracts.models import SuccessEnvelope
from regintel.db.config import load_database_settings
from regintel.db.migrations import migration_status
from regintel.evidence.api import EvidenceService
from regintel.evidence.repository import EvidenceRepository
from regintel.ingestion.config import native_ingestion_settings
from regintel.ingestion.storage import SourceStorage
from regintel.main import create_app
from regintel.publication.repository import PublicationRepository
from regintel.reads.models import CompanyPage, FactPage, PublishedEvidence, ViewInfo
from regintel.reads.repository import ReadRepository
from regintel.reads.service import PublishedReadService

ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool) -> None:
    if not condition:
        raise ValueError("The controlled read-only M2 proof differs from recorded state.")


def prove(source_project: Path) -> dict[str, object]:
    source_project = source_project.resolve()
    settings = load_database_settings(source_project / ".env")
    status = migration_status(settings)
    require(status.applied == tuple(range(1, 12)) and not status.pending)
    snapshot = cast(
        Callable[[], dict[str, str]],
        runpy.run_path(str(source_project / "scripts/check-published-reads-runtime.py"))[
            "snapshot"
        ],
    )
    before = snapshot()
    recorded = json.loads(
        (source_project / "data/publication-validation-report.json").read_text(encoding="utf-8")
    )
    corpus, observation = recorded["corpus_version_id"], recorded["observation_id"]
    learner = next(
        account
        for account in load_seed_accounts(source_project / ".env.auth")
        if account.role == "learner"
    )
    reads = PublishedReadService(
        PublicationRepository(settings),
        ReadRepository(settings),
        EvidenceService(
            EvidenceRepository(settings),
            SourceStorage(native_ingestion_settings(source_project, source_project / ".env")),
        ),
        None,
    )
    auth = AuthService(
        PostgreSQLAuthRepository(settings), load_auth_settings(source_project / ".env.auth")
    )
    with TestClient(create_app(auth_service=auth, read_service=reads)) as client:
        login = client.post(
            "/v1/auth/token",
            data={
                "grant_type": "password",
                "username": learner.username,
                "password": learner.password.get_secret_value(),
            },
        )
        require(login.status_code == 200)
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        response = client.get(
            "/v1/published-corpus", params={"corpus_version_id": corpus}, headers=headers
        )
        require(response.status_code == 200)
        view = SuccessEnvelope[ViewInfo].model_validate_json(response.content)
        require(view.data.manifest_sha256 == recorded["manifest_sha256"])
        response = client.get(
            "/v1/companies", params={"corpus_version_id": corpus}, headers=headers
        )
        require(response.status_code == 200)
        companies = SuccessEnvelope[CompanyPage].model_validate_json(response.content)
        require(companies.data.total == 1 and len(companies.data.companies) == 1)
        company = companies.data.companies[0]
        response = client.get(
            f"/v1/companies/{company.id}/facts",
            params={"corpus_version_id": corpus},
            headers=headers,
        )
        require(response.status_code == 200)
        facts = SuccessEnvelope[FactPage].model_validate_json(response.content)
        require(facts.data.total == 1 and len(facts.data.facts) == 1)
        fact = facts.data.facts[0]
        require(
            fact.observation.id == observation
            and fact.observation.kind == "narrative_fact"
            and fact.observation.quantity is None
        )
        evidence_id = fact.observation.supports[0].evidence_id
        prefix = f"/v1/corpora/{corpus}/observations/{observation}"
        response = client.get(prefix + "/evidence/" + evidence_id, headers=headers)
        require(response.status_code == 200)
        evidence = SuccessEnvelope[PublishedEvidence].model_validate_json(response.content)
        require(evidence.data.evidence.record.source.page_index == 2)
        response = client.get(prefix + "/source.pdf", headers=headers)
        require(
            response.status_code == 200
            and hashlib.sha256(response.content).hexdigest() == evidence.data.evidence.source_sha256
        )
        body = {
            "corpus_version_id": corpus,
            "company_ids": [company.id, str(uuid4())],
            "metric_ids": [fact.metric.id],
            "basis": "UNKNOWN",
            "period": {
                "kind": "UNKNOWN",
                "start_date": None,
                "end_date": None,
                "instant_date": None,
                "raw_label": None,
            },
        }
        require(client.post("/v1/compare", json=body).status_code == 401)
        require(client.post("/v1/compare", json=body, headers=headers).status_code == 404)
        require(
            client.post(
                "/v1/compare",
                json=body | {"company_ids": [company.id, company.id]},
                headers=headers,
            ).status_code
            == 422
        )
        require(client.get("/v1/quotes").status_code == 401)
        response = client.get("/v1/quotes", headers=headers)
        require(response.status_code == 200)
        quotes = SuccessEnvelope[QuotesResult].model_validate_json(response.content)
        require(quotes.data.quotes == () and quotes.meta.versions.quote_version_id is None)
    after = snapshot()
    require(before == after)
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "mode": "real_corpus_read_only",
        "corpus_version_id": corpus,
        "manifest_sha256": view.data.manifest_sha256,
        "published_companies": companies.data.total,
        "published_facts": facts.data.total,
        "numeric_facts": 0,
        "source_page_index": 2,
        "source_sha256": evidence.data.evidence.source_sha256,
        "unknown_company_status": 404,
        "duplicate_company_status": 422,
        "anonymous_compare_status": 401,
        "anonymous_quotes_status": 401,
        "quotes": "UNAVAILABLE_NO_CONFIGURED_SOURCE",
        "state_table_hashes": before,
        "state_tables_unchanged": len(before),
        "provider_calls": 0,
        "limitation": "The real corpus has one company and no numeric comparison inputs.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-project", type=Path, default=ROOT)
    options = parser.parse_args()
    try:
        result = prove(options.source_project)
        folder = ROOT / ".cache" / ("analysis-runtime-" + uuid4().hex)
        folder.mkdir(parents=True, exist_ok=False)
        path = folder / "report.json"
        path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        print(f"Read-only M2 corpus boundary proof passed; report: {path}")
        return 0
    except Exception:
        print("Read-only M2 proof failed; credentials and diagnostics omitted.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
