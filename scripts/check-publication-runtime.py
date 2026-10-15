"""Explicitly publish/replay the existing controlled Premier narrative over local HTTP.

Uses its original staged review and a fresh mandatory gate. No new filing,
review, effect, entity, provider call or original source record is created.
"""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx2

from regintel.auth.config import load_seed_accounts
from regintel.auth.repository import PostgreSQLAuthRepository
from regintel.candidates.models import SourceSpan, _exact_span
from regintel.candidates.records import stable_id
from regintel.contracts.models import SuccessEnvelope
from regintel.db.config import DatabaseSettings, load_database_settings
from regintel.db.migrations import connect_database, migration_status
from regintel.evidence.api import EvidenceEnvelope
from regintel.publication.embeddings import CpuBgeEncoder, split_support
from regintel.publication.graph import Neo4jProjection
from regintel.publication.models import (
    CandidateSelection,
    CorpusManifest,
    CorpusView,
    PublicationRequest,
)
from regintel.publication.repository import PublicationRepository, body
from regintel.publication.service import current_configuration

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_RUN = "6311f8bd-d49d-4fa8-b038-817205e73fff"
CANDIDATE = "e30af8f7-a198-41e1-a039-a748ce516aef"
REVIEW = "5c42296e-e63f-4f84-9c52-ead243b9596c"
SOURCE_SHA = "a15329da96a20117a5cfaccf535ab3dc805c6ed195e392bb5ec6131f8f246347"
EVIDENCE = "7e340c65-8087-43cf-8d3c-2648b7c5f1b8"
PRESERVE_TABLES = (
    "source_blobs",
    "filings",
    "filing_versions",
    "parse_versions",
    "parse_artifacts",
    "pages",
    "blocks",
    "tables",
    "cells",
    "cell_context",
    "evidence",
    "evidence_boxes",
    "entity_registrations",
    "entity_runs",
    "entity_reviews",
    "metric_definitions",
    "candidates",
    "candidate_runs",
    "candidate_run_items",
    "numeric_metric_policies",
    "validation_reviews",
    "filing_jobs",
    "processing_jobs",
    "processing_events",
    "processing_checkpoints",
)


class ProofFailure(ValueError):
    """Fixed safe diagnostics without credentials or submitted source payloads."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProofFailure(message)


def snapshot(database: DatabaseSettings) -> dict[str, str]:
    values = {}
    with connect_database(database) as connection, connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        for table in PRESERVE_TABLES:
            rows = connection.execute(
                f"SELECT row_to_json(t)::TEXT FROM regintel.{table} t ORDER BY row_to_json(t)::TEXT"
            ).fetchall()
            values[table] = hashlib.sha256(
                json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
            ).hexdigest()
    return values


def prove(api_base: str) -> dict[str, object]:
    target = urlsplit(api_base)
    require(
        target.scheme == "http"
        and target.hostname == "127.0.0.1"
        and target.port is not None
        and not target.username
        and not target.password
        and target.path in ("", "/")
        and not target.query
        and not target.fragment,
        "An explicit loopback API is required.",
    )
    database = load_database_settings(ROOT / ".env")
    migration = migration_status(database)
    require(
        migration.applied == tuple(range(1, 12)) and not migration.pending,
        "Primary migrations 1–11 are required.",
    )
    original = ROOT / "data/raw/premier-energies-addendum-rhp-sebi-20240826.pdf"
    require(
        hashlib.sha256(original.read_bytes()).hexdigest() == SOURCE_SHA,
        "The original controlled source differs.",
    )
    config = current_configuration(ROOT / "models/bge-small-en-v1.5")
    encoder = CpuBgeEncoder(ROOT / "models/bge-small-en-v1.5", config.embedding_manifest_sha256)
    authored_long = "Authored exact Unicode 😀 e\u0301 source passage. " * 600
    oversized = SourceSpan(
        evidence_id=EVIDENCE, start=17, end=17 + len(authored_long), quote=authored_long
    )
    pieces = split_support(oversized, encoder.token_count)
    require(
        "".join(item.quote for item in pieces) == authored_long
        and all(encoder.token_count(item.quote) <= 450 for item in pieces),
        "The actual tokenizer failed lossless bounded Unicode chunking.",
    )
    try:
        encoder.embed(authored_long)
    except ValueError:
        pass
    else:
        raise ProofFailure("Oversized actual token input was silently truncated.")
    reference = encoder.embed(pieces[0].quote)
    require(
        len(reference) == 384 and reference == encoder.embed(pieces[0].quote),
        "Actual CPU embeddings failed deterministic 384-dimensional inference.",
    )
    before = snapshot(database)
    repository = PublicationRepository(database)
    with connect_database(database) as connection:
        row = connection.execute(
            "SELECT corpus_version_id::TEXT FROM regintel.publication_head"
        ).fetchone()
        parent = str(row[0]) if row else None
        existing = connection.execute(
            "SELECT id::TEXT,request_bytes,request_sha256 FROM regintel.publication_builds "
            "WHERE idempotency_key=%s",
            (stable_id("controlled-premier-publication:" + config.sha256),),
        ).fetchone()
    request = (
        PublicationRequest.model_validate_json(body(existing[1], existing[2]))
        if existing
        else PublicationRequest(
            idempotency_key=stable_id("controlled-premier-publication:" + config.sha256),
            parent_corpus_version_id=parent,
            selections=(
                CandidateSelection(
                    candidate_run_id=CANDIDATE_RUN, candidate_id=CANDIDATE, review_id=REVIEW
                ),
            ),
        )
    )
    directory = ROOT / ".cache" / ("publication-runtime-" + uuid4().hex)
    directory.mkdir()
    with httpx2.Client(timeout=180) as client:
        headers = {}
        for account in load_seed_accounts(ROOT / ".env.auth"):
            response = client.post(
                api_base + "/v1/auth/login",
                json={
                    "username": account.username,
                    "password": account.password.get_secret_value(),
                },
            )
            require(
                response.status_code == 200, "A configured local account could not authenticate."
            )
            headers[account.role] = {"Authorization": "Bearer " + response.json()["access_token"]}
        base = api_base + "/v1/admin/publication/builds"
        response = client.post(base, headers=headers["admin"], json=request.model_dump(mode="json"))
        require(response.status_code == 200, "The controlled approved build failed.")
        manifest = SuccessEnvelope[CorpusManifest].model_validate_json(response.content).data
        require(
            len(manifest.new_acceptances) == 1 and len(manifest.observations) == 1,
            "The controlled publication must stay bounded.",
        )
        observation = manifest.observations[0]
        require(
            observation.kind == "narrative_fact"
            and observation.candidate_id == CANDIDATE
            and observation.review_id == REVIEW
            and observation.quantity is None
            and observation.supports[0].evidence_id == EVIDENCE
            and "is proposing, subject to" in observation.raw_text,
            "The exact conditional statement was not preserved.",
        )
        require(
            not manifest.lineages
            and not manifest.effects
            and bool(manifest.unresolved_parent_filing_version_ids),
            "The absent real parent must remain unresolved without a fabricated effect.",
        )
        for denied, code in (({}, 401), (headers["learner"], 403)):
            require(
                client.post(base, headers=denied, json=request.model_dump(mode="json")).status_code
                == code,
                "An unauthorized build was not denied.",
            )
            require(
                client.post(base + "/" + manifest.id + "/publish", headers=denied).status_code
                == code,
                "An unauthorized publication was not denied.",
            )
        response = client.post(base + "/" + manifest.id + "/publish", headers=headers["admin"])
        require(
            response.status_code == 200
            and SuccessEnvelope[CorpusManifest].model_validate_json(response.content).data
            == manifest,
            "The controlled publication failed.",
        )
        for _ in range(2):
            replay = client.post(base + "/" + manifest.id + "/publish", headers=headers["admin"])
            require(
                replay.status_code == 200
                and SuccessEnvelope[CorpusManifest].model_validate_json(replay.content).data
                == manifest,
                "Publication replay changed its immutable result.",
            )
        view_url = api_base + "/v1/corpora/" + manifest.id
        read = client.get(view_url, headers=headers["learner"])
        require(read.status_code == 200, "The authenticated published view failed.")
        view = SuccessEnvelope[CorpusView].model_validate_json(read.content)
        require(
            view.data.observations == (observation,)
            and view.meta.versions.corpus_version_id == manifest.id,
            "The published view mixed corpus versions or observations.",
        )
        unavailable = client.get(
            view_url, headers=headers["learner"], params={"as_of_date": "2026-10-15"}
        )
        require(
            unavailable.status_code == 200
            and SuccessEnvelope[CorpusView].model_validate_json(unavailable.content).data.state
            == "TEMPORAL_SUPPORT_UNAVAILABLE",
            "An unknown publication date must not be inferred.",
        )
        require(client.get(view_url).status_code == 401, "Anonymous corpus access was not denied.")
        evidence_response = client.get(
            api_base + "/v1/evidence/" + EVIDENCE, headers=headers["admin"]
        )
        require(evidence_response.status_code == 200, "The original exact evidence is unavailable.")
        evidence = EvidenceEnvelope.model_validate_json(evidence_response.content).data
        require(
            evidence.source_sha256 == SOURCE_SHA
            and evidence.record.source.parse_version_id == observation.parse_version_id
            and _exact_span(observation.supports[0], evidence.record),
            "The source-bound exact evidence differs from the accepted support.",
        )
        rebuilt = client.post(base + "/" + manifest.id + "/rebuild", headers=headers["admin"])
        require(rebuilt.status_code == 200, "The approved projection rebuild failed.")
    require(
        snapshot(database) == before, "An original source, candidate, review or workflow changed."
    )
    graph = Neo4jProjection.from_env(ROOT / ".env")
    try:
        receipt = graph.verify(manifest)
    finally:
        graph.close()
    user = PostgreSQLAuthRepository(database).get_by_username("admin")
    require(user is not None, "The original configured administrator is unavailable.")
    assert user is not None
    projection = repository.retrieval(manifest.id, user)
    require(
        projection is not None and projection.manifest_sha256 == manifest.sha256,
        "The actual retrieval projection differs.",
    )
    assert projection is not None
    with connect_database(database) as connection:
        counts = {
            table: connection.execute(f"SELECT count(*) FROM regintel.{table}").fetchone()
            for table in (
                "acceptance_audits",
                "fact_observations",
                "relation_observations",
                "corpus_versions",
            )
        }
    require(
        counts
        == {
            "acceptance_audits": (1,),
            "fact_observations": (1,),
            "relation_observations": (0,),
            "corpus_versions": (1,),
        },
        "The controlled authority counts exceed the intended single narrative.",
    )
    (directory / "manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (directory / "projection.json").write_text(
        projection.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    acceptance = manifest.new_acceptances[0]
    report: dict[str, object] = {
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "phase": "M1.9",
        "proof_directory": str(directory),
        "corpus_version_id": manifest.id,
        "manifest_sha256": manifest.sha256,
        "configuration_sha256": config.sha256,
        "configuration": config.model_dump(mode="json"),
        "source_sha256": SOURCE_SHA,
        "observation_id": observation.id,
        "acceptance_audit_id": observation.acceptance_audit_id,
        "candidate_run_id": CANDIDATE_RUN,
        "candidate_id": CANDIDATE,
        "original_review_id": REVIEW,
        "original_review_validation_run_id": acceptance.original_review.decision.validation_run_id
        if acceptance.original_review
        else None,
        "fresh_validation_run_id": observation.validation_run_id,
        "fresh_validation_input_sha256": observation.validation_input_sha256,
        "retrieval_sha256": projection.sha256,
        "chunk_count": len(projection.chunks),
        "chunk_token_counts": [item.token_count for item in projection.chunks],
        "embedding_dimensions": 384,
        "actual_tokenizer_oversized_input_rejected": True,
        "authored_unicode_exact_chunking": "passed",
        "authored_unicode_chunk_count": len(pieces),
        "cpu_repeatable_inference": "passed",
        "graph_receipt": receipt.model_dump(mode="json"),
        "authority_counts": {key: value[0] if value else None for key, value in counts.items()},
        "original_snapshots_unchanged": True,
        "snapshot_sha256": before,
        "publication_replay": "passed",
        "authenticated_view": "passed",
        "anonymous_and_learner_write_denials": "passed",
        "projection_rebuild": "passed",
        "unknown_date_as_of": "TEMPORAL_SUPPORT_UNAVAILABLE",
        "real_parent_lineage": "unresolved; parent not ingested",
        "real_amendment_effects": 0,
        "provider_calls": 0,
        "limitations": [
            "One conditional narrative, not gold or held-out research effectiveness.",
            "Authored multi-filing tests establish engineering behavior only.",
            "No real parent pair, numeric/relation positive, table-cell or OCR success is claimed.",
            "Cross-database preparation is recoverable; the PostgreSQL head commits atomically.",
            "Company/fact/graph APIs and learner source viewing belong to M1.10.",
        ],
    }
    (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default="http://127.0.0.1:8019")
    args = parser.parse_args()
    try:
        report = prove(args.api_base.rstrip("/"))
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in (
                        "proof_directory",
                        "corpus_version_id",
                        "manifest_sha256",
                        "chunk_count",
                        "authority_counts",
                        "real_parent_lineage",
                    )
                }
            )
        )
        return 0
    except Exception as error:
        reason = str(error) if isinstance(error, ProofFailure) else type(error).__name__
        print("Publication runtime proof failed: " + reason + ". Secrets omitted.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
