"""Generate labelled authored browser wire/PDF fixtures, never real filing results."""

import argparse
import base64
import hashlib
import json
from io import BytesIO
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen.canvas import Canvas

from regintel.candidates.models import MetricDefinition, SourceSpan
from regintel.contracts.http import new_response_meta
from regintel.contracts.models import (
    EvidenceSource,
    PageGeometry,
    PdfRectangle,
    SuccessEnvelope,
    TextEvidence,
    TextSpan,
)
from regintel.evidence.api import EvidenceData
from regintel.fixtures.sources import fixture_id
from regintel.parsing.models import (
    PackageVersion,
    ParseProvenance,
    package_manifest_sha256,
)
from regintel.publication.models import PublishedObservation
from regintel.reads.models import (
    CompanyGraph,
    CompanyPage,
    EntityLabel,
    FactPage,
    PublishedEvidence,
    PublishedFact,
    ViewInfo,
)

ROOT = Path(__file__).resolve().parents[1]


def artifact() -> bytes:
    quote = "Alpha Energy Limited proposes an initial public offering, subject to approvals."
    pdf_bytes = BytesIO()
    pdf = Canvas(pdf_bytes, pagesize=(612, 792), invariant=True, pageCompression=0)
    pdf.setFont("Helvetica", 10)
    pdf.drawString(50, 750, "Authored browser fixture. Not a real filing or research gold data.")
    pdf.drawString(50, 700, quote)
    pdf.save()
    data = pdf_bytes.getvalue()
    source_sha = hashlib.sha256(data).hexdigest()
    support = SourceSpan(evidence_id=fixture_id(750), start=0, end=len(quote), quote=quote)
    view = ViewInfo(
        corpus_version_id=fixture_id(751),
        manifest_sha256="a" * 64,
        state="AVAILABLE",
        as_of_date=None,
        historical=False,
        unresolved_parent_filing_version_ids=(),
    )
    observation = PublishedObservation(
        id=fixture_id(752),
        acceptance_audit_id=fixture_id(753),
        first_corpus_version_id=view.corpus_version_id,
        candidate_id=fixture_id(754),
        candidate_run_id=fixture_id(755),
        parse_version_id=fixture_id(756),
        filing_version_id=fixture_id(757),
        validation_run_id=fixture_id(758),
        validation_input_sha256="b" * 64,
        validator_configuration_sha256="c" * 64,
        review_id=fixture_id(759),
        kind="narrative_fact",
        subject_entity_id=fixture_id(760),
        object_entity_id=None,
        relation_type=None,
        metric_id=fixture_id(761),
        raw_text=quote,
        quantity=None,
        supports=(support,),
        context_supports=(),
        source_published_on=None,
    )
    company = EntityLabel(
        id=observation.subject_entity_id, kind="COMPANY", name="Alpha Energy Limited"
    )
    metric = MetricDefinition(
        id=fixture_id(761),
        key="offering_proposal",
        label="Offering proposal",
        kind="narrative_fact",
        cue_phrases=("proposes",),
    )
    record = TextEvidence(
        id=support.evidence_id,
        kind="text",
        source=EvidenceSource(
            filing_id=fixture_id(762),
            filing_version_id=observation.filing_version_id,
            parse_version_id=observation.parse_version_id,
            page_id=fixture_id(763),
            page_index=0,
        ),
        page_geometry=PageGeometry(
            width=612.0,
            height=792.0,
            media_box=PdfRectangle(x0=0.0, y0=0.0, x1=612.0, y1=792.0),
            crop_box=PdfRectangle(x0=0.0, y0=0.0, x1=612.0, y1=792.0),
            rotation=0,
            coordinate_space="UNROTATED_PDF_POINTS",
            origin="BOTTOM_LEFT",
        ),
        boxes=(
            PdfRectangle(
                x0=50.0,
                y0=698.0,
                x1=50.0 + pdfmetrics.stringWidth(quote, "Helvetica", 10),
                y1=711.0,
            ),
        ),
        span=TextSpan(block_id=fixture_id(764), start=0, end=len(quote), quote=quote),
    )
    packages = (PackageVersion(name="authored-fixture", version="1.0.0"),)
    provenance = ParseProvenance(
        adapter_name="authored-browser-fixture",
        adapter_version="1.0.0",
        adapter_code_sha256="d" * 64,
        backend_name="authored",
        backend_version="1.0.0",
        backend_code_sha256="e" * 64,
        coordinate_frame="RAW_PDF_BOTTOM_LEFT",
        packages=packages,
        package_manifest_sha256=package_manifest_sha256(packages),
        configuration_sha256="f" * 64,
        model_manifest_sha256="0" * 64,
    )
    evidence = PublishedEvidence(
        view=view,
        observation_id=observation.id,
        evidence=EvidenceData(
            record=record,
            provenance=provenance,
            source_sha256=source_sha,
            processing_configuration_sha256="1" * 64,
        ),
        supports=(support,),
        context_supports=(),
    )
    meta = new_response_meta().model_copy(
        update={
            "request_id": fixture_id(765),
            "versions": new_response_meta().versions.model_copy(
                update={"corpus_version_id": view.corpus_version_id}
            ),
        }
    )
    source_meta = meta.model_copy(
        update={
            "versions": meta.versions.model_copy(
                update={
                    "filing_version_id": record.source.filing_version_id,
                    "parse_version_id": record.source.parse_version_id,
                }
            )
        }
    )
    result = {
        "description": (
            "Labelled authored browser contracts; not a real filing or evaluation result."
        ),
        "info": SuccessEnvelope(data=view, meta=meta).model_dump(mode="json"),
        "companies": SuccessEnvelope(
            data=CompanyPage(view=view, companies=(company,), total=1, offset=0, limit=25),
            meta=meta,
        ).model_dump(mode="json"),
        "facts": SuccessEnvelope(
            data=FactPage(
                view=view,
                company=company,
                facts=(PublishedFact(observation=observation, metric=metric),),
                total=1,
                offset=0,
                limit=25,
            ),
            meta=meta,
        ).model_dump(mode="json"),
        "graph": SuccessEnvelope(
            data=CompanyGraph(view=view, company=company, nodes=(company,), edges=()),
            meta=meta,
        ).model_dump(mode="json"),
        "evidence": SuccessEnvelope(data=evidence, meta=source_meta).model_dump(mode="json"),
        "pdf_base64": base64.b64encode(data).decode("ascii"),
    }
    return (json.dumps(result, indent=2, sort_keys=True) + "\n").encode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    path = ROOT / "frontend/src/published/fixtures.generated.json"
    content = artifact()
    if options.check:
        if not path.is_file() or path.read_bytes() != content:
            print("Authored read fixture differs; run scripts/generate-read-fixtures.py.")
            return 1
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    print(
        "Authored browser wire/PDF fixture matches."
        if options.check
        else "Authored browser wire/PDF fixture generated."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
