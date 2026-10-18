"""Read-only M2 acceptance cases over a pinned published corpus; missing coverage exits 2."""

import argparse
import hashlib
import json
import runpy
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from regintel.analysis.acceptance import AcceptancePlan, evaluate
from regintel.analysis.service import ComparisonService
from regintel.db.config import load_database_settings
from regintel.evidence.api import EvidenceService
from regintel.evidence.repository import EvidenceRepository
from regintel.ingestion.config import native_ingestion_settings
from regintel.ingestion.storage import SourceStorage
from regintel.publication.repository import PublicationRepository
from regintel.reads.repository import ReadRepository
from regintel.reads.service import PublishedReadService

ROOT = Path(__file__).resolve().parents[1]
MAX_PLAN_BYTES = 1_000_000


def run(plan_path: Path, source_project: Path) -> dict[str, object]:
    with plan_path.open("rb") as stream:
        raw = stream.read(MAX_PLAN_BYTES + 1)
    if len(raw) > MAX_PLAN_BYTES:
        raise ValueError("Acceptance plan exceeds its explicit size bound.")
    plan = AcceptancePlan.model_validate_json(raw)
    source_project = source_project.resolve()
    settings = load_database_settings(source_project / ".env")
    snapshot = cast(
        Callable[[], dict[str, str]],
        runpy.run_path(str(source_project / "scripts/check-published-reads-runtime.py"))[
            "snapshot"
        ],
    )
    before = snapshot()
    reads = PublishedReadService(
        PublicationRepository(settings),
        ReadRepository(settings),
        EvidenceService(
            EvidenceRepository(settings),
            SourceStorage(native_ingestion_settings(source_project, source_project / ".env")),
        ),
        None,
    )
    try:
        scope = reads.scope(plan.corpus_version_id, None, False)
        catalog = reads.catalog.catalog(scope.manifest)
        report = evaluate(plan, scope.info, ComparisonService(reads).compare)
        report["inventory"] = {
            "published_companies": sum(entity.kind == "COMPANY" for entity in catalog.entities),
            "active_observations": len(scope.view.observations),
            "active_numeric_facts": sum(
                item.kind == "numeric_fact" for item in scope.view.observations
            ),
            "numeric_metric_definitions": sum(
                metric.kind == "numeric_fact" for metric in catalog.metrics
            ),
        }
    finally:
        after = snapshot()
        if before != after:
            raise ValueError("Authoritative state changed during the read-only acceptance run.")
    report.update(
        checked_at_utc=datetime.now(UTC).isoformat(),
        plan_sha256=hashlib.sha256(raw).hexdigest(),
        state_table_hashes=before,
        state_tables_unchanged=len(before),
        provider_calls=0,
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selected = parser.add_mutually_exclusive_group(required=True)
    selected.add_argument("--plan", type=Path)
    selected.add_argument(
        "--schema", action="store_true", help="Print the plan schema without a database connection."
    )
    parser.add_argument("--source-project", type=Path, default=ROOT)
    options = parser.parse_args()
    if options.schema:
        print(json.dumps(AcceptancePlan.model_json_schema(), indent=2, sort_keys=True))
        return 0
    try:
        report = run(options.plan, options.source_project)
        folder = ROOT / ".cache" / ("analysis-acceptance-" + uuid4().hex)
        folder.mkdir(parents=True, exist_ok=False)
        path = folder / "report.json"
        path.write_text(
            json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"M2 acceptance {report['status']}; report: {path}")
        return {"CASES_PASS": 0, "FAIL": 1, "BLOCKED": 2}[str(report["status"])]
    except Exception:
        print("M2 acceptance failed; credentials and diagnostics omitted.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
