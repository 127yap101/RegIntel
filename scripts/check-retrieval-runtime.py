"""Read-only real BGE/pgvector/Neo4j retrieval proof against the existing publication."""

import argparse
import json
import runpy
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit
from uuid import uuid4

import httpx2
import psycopg

from regintel.auth.config import load_seed_accounts
from regintel.contracts.models import SuccessEnvelope
from regintel.db.config import load_database_settings
from regintel.db.migrations import migration_status
from regintel.retrieval.models import AnswerResult, RetrievalResult
from regintel.retrieval.service import current_configuration

ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool) -> None:
    if not condition:
        raise ValueError("The controlled read-only retrieval proof differs from its contract.")


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
    read_snapshot = cast(
        Callable[[], dict[str, str]],
        runpy.run_path(str(ROOT / "scripts/check-published-reads-runtime.py"))["snapshot"],
    )
    before = read_snapshot()
    status = migration_status(load_database_settings(ROOT / ".env"))
    require(status.applied == tuple(range(1, 12)) and not status.pending)
    recorded = json.loads(
        (ROOT / "data/publication-validation-report.json").read_text(encoding="utf-8")
    )
    corpus, observation = recorded["corpus_version_id"], recorded["observation_id"]
    learner = next(
        account for account in load_seed_accounts(ROOT / ".env.auth") if account.role == "learner"
    )
    arms: dict[str, object] = {}
    query = {
        "question": "What does the filing disclose about an initial public offering?",
        "corpus_version_id": corpus,
        "context_budget": 2048,
        "top_k": 5,
    }
    with httpx2.Client(base_url=api_base, timeout=60, trust_env=False) as client:
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
        for arm in ("B0", "B1", "B2", "B3"):
            payload = query | {"arm": arm}
            require(client.post("/v1/retrieval", json=payload).status_code == 401)
            require(client.post("/v1/answers", json=payload).status_code == 401)
            response = client.post("/v1/retrieval", json=payload, headers=headers)
            require(response.status_code == 200)
            retrieval = SuccessEnvelope[RetrievalResult].model_validate_json(response.content)
            require(
                retrieval.meta.versions.corpus_version_id == corpus
                and retrieval.data.view.corpus_version_id == corpus
            )
            require(
                len(retrieval.data.hits) == 1
                and retrieval.data.hits[0].observation.id == observation
            )
            require(
                retrieval.data.trace.context_tokens <= 2048
                and retrieval.data.trace.provider_calls == 0
            )
            response = client.post("/v1/answers", json=payload, headers=headers)
            require(response.status_code == 200)
            answer = SuccessEnvelope[AnswerResult].model_validate_json(response.content)
            require(answer.data.state == "EXTRACTIVE_EVIDENCE" and len(answer.data.claims) == 1)
            claim = answer.data.claims[0]
            require(claim.observation_id == observation and "subject to" in claim.text)
            require(claim.citations[0].page_index == 2)
            citation = claim.citations[0]
            require(citation.span.evidence_id == "7e340c65-8087-43cf-8d3c-2648b7c5f1b8")
            require(
                citation.span.quote == claim.text
                and citation.span.start == 0
                and citation.span.end == 272
            )
            trace = answer.data.retrieval.trace
            require(trace.configuration_sha256 == current_configuration().sha256)
            arms[arm] = {
                "state": answer.data.state,
                "retrieved_observation_ids": [hit.observation.id for hit in retrieval.data.hits],
                "claim_count": len(answer.data.claims),
                "page_index": citation.page_index,
                "source_sha256": citation.source_sha256,
                "trace": trace.model_dump(mode="json"),
            }

        def answer_state(payload: dict[str, object]) -> AnswerResult:
            response = client.post("/v1/answers", json=payload, headers=headers)
            require(response.status_code == 200)
            return SuccessEnvelope[AnswerResult].model_validate_json(response.content).data

        temporal = answer_state(query | {"as_of_date": "2026-01-01"})
        require(temporal.state == "TEMPORAL_SUPPORT_UNAVAILABLE" and not temporal.claims)
        numeric = answer_state(query | {"question": "What is the revenue?"})
        require(numeric.state == "NUMERIC_CONTEXT_REQUIRED" and not numeric.claims)
        unsupported = answer_state(
            query | {"question": "What lunar fuel supply forecast has been guaranteed?"}
        )
        require(unsupported.state == "INSUFFICIENT_SUPPORT" and not unsupported.claims)
        budget = answer_state(query | {"context_budget": 128})
        require(
            budget.state == "CONTEXT_BUDGET_UNAVAILABLE"
            and budget.retrieval.trace.budget_omitted == 1
        )
        for path in ("/v1/retrieval", "/v1/answers"):
            require(
                client.post(
                    path, json=query | {"corpus_version_id": str(uuid4())}, headers=headers
                ).status_code
                == 404
            )
            require(
                client.post(
                    path, json=query | {"question": "界" * 900}, headers=headers
                ).status_code
                == 422
            )
            require(
                client.post(path, json=query | {"top_k": 0}, headers=headers).status_code == 422
            )
    after = read_snapshot()
    require(after == before)
    return {
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "phase": "M1.11",
        "status": "passed — bounded real retrieval engineering proof",
        "corpus_version_id": corpus,
        "manifest_sha256": recorded["manifest_sha256"],
        "observation_id": observation,
        "configuration_sha256": current_configuration().sha256,
        "arms": arms,
        "same_corpus_query_top_k_budget_policy": True,
        "original_snapshots_unchanged": True,
        "snapshot_sha256": after,
        "migration_applied": list(status.applied),
        "new_migrations": 0,
        "provider_calls": 0,
        "provider_cost": "0",
        "unknown_date_abstention": "passed",
        "unsupported_topic_abstention": "passed",
        "numeric_context_required": "passed",
        "complete_context_budget_omission": "passed",
        "cross_corpus_denial": "passed",
        "query_no_truncation": "passed",
        "limitations": [
            "One conditional narrative and no real relation/numeric positive or amendment pair.",
            "No gold-set relevance labels or held-out effectiveness measurement.",
            "Literal topic gate is conservative and uncalibrated; no generated conclusion.",
            "No live model/provider transport or paid call.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", required=True)
    options = parser.parse_args()
    try:
        result = prove(options.api_base)
        folder = ROOT / ".cache" / ("retrieval-runtime-" + uuid4().hex)
        folder.mkdir()
        (folder / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": "passed",
                    "report": str(folder / "report.json"),
                    "arms": 4,
                    "provider_calls": 0,
                }
            )
        )
        return 0
    except (OSError, ValueError, KeyError, StopIteration, httpx2.HTTPError, psycopg.Error):
        print("Read-only retrieval proof failed; connection secrets/source payloads omitted.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
