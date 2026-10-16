"""Generate strict administrator wire types/schema; preserve frozen domain schemas."""

import argparse
import json
import runpy
from collections.abc import Callable
from pathlib import Path
from typing import cast, get_args

from regintel.admin.models import AdminWire, QueueItem, QueuePage, ReviewItem, ReviewPage
from regintel.candidates.models import DraftCandidate, ExtractionConfiguration, MetricDefinition
from regintel.candidates.records import stable_id
from regintel.contracts.models import ResponseMeta, SuccessEnvelope
from regintel.entities.models import ResolverConfiguration
from regintel.evidence.api import EvidenceData
from regintel.fixtures.sources import fixture_id
from regintel.ingestion.jobs import FilingJob
from regintel.ingestion.models import CandidateRecord
from regintel.processing.models import (
    STAGES,
    ProcessingConfiguration,
    ProcessingJob,
    ProcessingRequest,
    StageCheckpoint,
)
from regintel.publication.models import CorpusManifest, FilingSnapshot, PublicationConfiguration
from regintel.validation.models import (
    CheckCode,
    ReviewDecision,
    ValidationCheck,
    ValidationConfiguration,
    ValidationResult,
    ValidationRun,
)


def fixtures() -> bytes:
    generate = cast(
        Callable[[], bytes],
        runpy.run_path(str(ROOT / "scripts/generate-read-fixtures.py"))["artifact"],
    )
    reads = json.loads(generate())
    observation = reads["facts"]["data"]["facts"][0]["observation"]
    evidence = EvidenceData.model_validate(reads["evidence"]["data"]["evidence"])
    support = reads["evidence"]["data"]["supports"][0]
    primary = evidence.record.source
    candidate = CandidateRecord.model_validate(
        {
            "id": fixture_id(840),
            "parse_version_id": primary.parse_version_id,
            "kind": "narrative_fact",
            "state": "CANDIDATE",
            "subject_entity_id": observation["subject_entity_id"],
            "object_entity_id": None,
            "metric_id": observation["metric_id"],
            "relation_type": None,
            "raw_text": observation["raw_text"],
            "quantitative_context_id": None,
            "evidence_ids": [evidence.record.id],
        }
    )
    assert candidate.metric_id is not None
    draft = DraftCandidate.model_validate(
        {
            "kind": "narrative_fact",
            "subject_entity_id": candidate.subject_entity_id,
            "subject_mention_id": fixture_id(841),
            "metric_id": candidate.metric_id,
            "raw_text": candidate.raw_text,
            "supports": [support],
        }
    )
    result = ValidationResult(
        candidate_id=candidate.id,
        state="REVIEW",
        checks=tuple(
            ValidationCheck(
                code=code,
                state="REVIEW" if code == "EXTRACTIVE_REVIEW" else "PASS",
                message="Authored engineering fixture check; not a measured filing result.",
            )
            for code in get_args(CheckCode)
        ),
        quantity=None,
        context_supports=(),
        reviewer_eligible=True,
    )
    config = ValidationConfiguration(code_sha256="b" * 64)
    run = ValidationRun(
        id=stable_id("validation-run:" + "c" * 64 + ":" + config.sha256),
        candidate_run_id=fixture_id(843),
        parse_version_id=primary.parse_version_id,
        input_sha256="c" * 64,
        configuration=config,
        results=(result,),
    )
    page = ReviewPage(
        run_id=run.id,
        candidate_run_id=fixture_id(843),
        parse_version_id=primary.parse_version_id,
        configuration_sha256=config.sha256,
        approval_current=True,
        state_filter="ALL",
        offset=0,
        limit=20,
        has_more=False,
        items=(
            ReviewItem(
                candidate=candidate,
                draft=draft,
                result=result,
                review=None,
                metric_label="Authored proposed offering",
                accepted_observation_id=None,
            ),
        ),
    )
    job = FilingJob(
        id=fixture_id(844),
        filing_version_id=primary.filing_version_id,
        source_blob_id=fixture_id(845),
        source_sha256=evidence.source_sha256,
        configuration_sha256="b" * 64,
        state="PARSED",
        attempts=1,
        page_count=1,
        parse_version_id=primary.parse_version_id,
        failure_code=None,
    )
    decision = ReviewDecision(
        id=fixture_id(849),
        validation_run_id=run.id,
        candidate_id=candidate.id,
        decision="APPROVE_FOR_PUBLICATION",
        supports=draft.supports,
        review_note="Authored reviewed approval.",
    )
    observation.update(
        candidate_id=candidate.id,
        candidate_run_id=page.candidate_run_id,
        validation_run_id=run.id,
        validation_input_sha256=run.input_sha256,
        validator_configuration_sha256=config.sha256,
        review_id=decision.id,
        first_corpus_version_id=fixture_id(846),
    )
    manifest = CorpusManifest.model_validate(
        {
            "id": fixture_id(846),
            "parent_corpus_version_id": None,
            "request_sha256": "c" * 64,
            "configuration": PublicationConfiguration(
                code_sha256="d" * 64,
                validator_configuration_sha256="b" * 64,
                embedding_manifest_sha256="e" * 64,
            ).model_dump(mode="json"),
            "approved_by": fixture_id(847),
            "approved_auth_version": 1,
            "filings": [
                FilingSnapshot(
                    filing_id=primary.filing_id,
                    filing_version_id=primary.filing_version_id,
                    parse_version_id=primary.parse_version_id,
                    source_sha256=evidence.source_sha256,
                    document_type="RHP",
                    published_on=None,
                ).model_dump(mode="json")
            ],
            "observations": [observation],
            "new_acceptances": [
                {
                    "observation": observation,
                    "fresh_validation": run.model_dump(mode="json"),
                    "original_review": {
                        "decision": decision.model_dump(mode="json"),
                        "reviewed_by": fixture_id(847),
                        "auth_version": 1,
                    },
                }
            ],
            "lineages": [],
            "effects": [],
            "active_observation_ids": [observation["id"]],
            "unresolved_parent_filing_version_ids": [],
        }
    )
    meta = ResponseMeta.model_validate(reads["info"]["meta"])
    source_meta = ResponseMeta.model_validate(reads["evidence"]["meta"])
    review_meta = meta.model_copy(
        update={
            "versions": meta.versions.model_copy(
                update={"corpus_version_id": None, "parse_version_id": primary.parse_version_id}
            )
        }
    )
    empty_meta = meta.model_copy(
        update={"versions": meta.versions.model_copy(update={"corpus_version_id": None})}
    )
    workflow = ProcessingJob(
        id=fixture_id(848),
        request=ProcessingRequest(
            idempotency_key=fixture_id(851),
            parse_version_id=primary.parse_version_id,
            metric_ids=(candidate.metric_id,),
        ),
        configuration=ProcessingConfiguration(
            code_sha256="a" * 64,
            entity=ResolverConfiguration(
                spacy_version="authored-version",
                rapidfuzz_version="authored-version",
                code_sha256="a" * 64,
            ),
            candidate=ExtractionConfiguration(code_sha256="a" * 64),
            validation=config,
        ),
        submitted_by=fixture_id(847),
        submitted_auth_version=1,
        state="QUEUED",
        generation=0,
        failure_code=None,
        checkpoints=(),
        events=(),
    )
    completed = ProcessingJob.model_validate(
        workflow.model_dump(mode="python")
        | {
            "state": "SUCCEEDED",
            "generation": 1,
            "checkpoints": tuple(
                StageCheckpoint(
                    stage=stage,
                    output_id=identity,
                    input_sha256="a" * 64,
                    configuration_sha256="a" * 64,
                    generation=1,
                )
                for stage, identity in zip(
                    STAGES, (fixture_id(852), page.candidate_run_id, page.run_id), strict=True
                )
            ),
            "events": (
                {
                    "sequence": 1,
                    "generation": 1,
                    "kind": "STARTED",
                    "stage": None,
                    "failure_code": None,
                },
                {
                    "sequence": 2,
                    "generation": 1,
                    "kind": "COMPLETED",
                    "stage": None,
                    "failure_code": None,
                },
            ),
        }
    )

    def envelope(value: object, selected: ResponseMeta = empty_meta) -> dict[str, object]:
        return SuccessEnvelope(data=value, meta=selected).model_dump(mode="json")

    queues = {}
    for kind, identity, label, state in (
        ("filings", job.id, "Authored Alpha Energy filing", "PARSED"),
        ("processing", fixture_id(848), "Authored processing", "SUCCEEDED"),
        ("validations", page.run_id, "Authored validation", "AUDIT"),
        ("publications", manifest.id, "Authored corpus build", "BUILDING"),
    ):
        queues[kind] = envelope(
            QueuePage.model_validate(
                dict(
                    kind=kind,
                    items=[
                        QueueItem(
                            id=identity,
                            label=label,
                            state=state,
                            parse_version_id=primary.parse_version_id,
                            related_id=None,
                        )
                    ],
                    offset=0,
                    limit=20,
                    has_more=False,
                    published_corpus_id=None,
                )
            )
        )
    payload = {
        "description": (
            "Authored administrator/browser scenarios; "
            "not real filings, gold data or publication proof."
        ),
        "queues": queues,
        "review_page": envelope(page, review_meta),
        "filing_job": envelope(
            job,
            source_meta.model_copy(
                update={
                    "versions": source_meta.versions.model_copy(update={"corpus_version_id": None})
                }
            ),
        ),
        "manifest": envelope(manifest),
        "processing_queued": envelope(workflow, review_meta),
        "processing_completed": envelope(completed, review_meta),
        "metrics": envelope(
            {
                "items": [
                    MetricDefinition(
                        id=candidate.metric_id,
                        key="authored_offering",
                        label="Authored offering metric",
                        kind="narrative_fact",
                        cue_phrases=("initial public offering",),
                    ).model_dump(mode="json")
                ]
            }
        ),
        "evidence": envelope(evidence, source_meta),
        "identity": envelope(
            {"id": fixture_id(847), "username": "authored-admin", "role": "admin"}
        ),
        "pdf_base64": reads["pdf_base64"],
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


ROOT = Path(__file__).resolve().parents[1]


def standard_bounds(value: object) -> None:
    """Pydantic metadata on legacy safe integers needs standard JSON Schema bounds."""
    if isinstance(value, dict):
        for source, target in (("ge", "minimum"), ("le", "maximum")):
            if source in value:
                bound = value.pop(source)
                previous = value.get(target)
                if not isinstance(bound, (int, float)) or isinstance(bound, bool):
                    raise ValueError("Invalid schema bound.")
                value[target] = (
                    bound
                    if previous is None
                    else (max(previous, bound) if source == "ge" else min(previous, bound))
                )
        value.pop("discriminator", None)
        for child in value.values():
            standard_bounds(child)
    elif isinstance(value, list):
        for child in value:
            standard_bounds(child)


def artifacts() -> dict[Path, bytes]:
    emit = cast(
        Callable[[dict[str, object]], str],
        runpy.run_path(str(ROOT / "scripts/export-contracts.py"))["ts_type"],
    )
    schema = AdminWire.model_json_schema(mode="serialization")
    standard_bounds(schema)
    schema["$id"] = "https://regintel.local/admin/1.0.0"
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    lines = [
        "// Generated by scripts/export-admin.py; edit Python workspace/domain models.",
        "import type { CanonicalId, DecimalString, DateString } from '../contracts/generated'",
    ]
    lines.extend(
        f"export type {name} = {emit(schema['$defs'][name])};" for name in sorted(schema["$defs"])
    )
    folder = ROOT / "frontend/src/admin"
    return {
        folder / "fixtures.generated.json": fixtures(),
        folder / "schema.json": (json.dumps(schema, indent=2, sort_keys=True) + "\n").encode(),
        folder / "generated.ts": ("\n".join(lines) + "\n").encode(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    for path, content in artifacts().items():
        if options.check:
            if not path.is_file() or path.read_bytes() != content:
                print("Administrator contracts differ; run scripts/export-admin.py.")
                return 1
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    print(
        "Administrator contracts match." if options.check else "Administrator contracts generated."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
