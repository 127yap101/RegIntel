"""Generate reproducible authored M2 wire/PDF cases, never real filing data."""

import argparse
import base64
import hashlib
import json
import runpy
from io import BytesIO
from pathlib import Path
from typing import cast

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen.canvas import Canvas

from regintel.analysis.arithmetic import difference, normalize
from regintel.analysis.models import (
    CALCULATION_POLICY,
    QUOTES_UNAVAILABLE,
    ComparisonCell,
    ComparisonRequest,
    ComparisonResult,
    ComparisonRow,
)
from regintel.candidates.models import MetricDefinition, SourceSpan
from regintel.contracts.models import QuantitativeValue, ResponseMeta, SuccessEnvelope
from regintel.evidence.api import EvidenceData
from regintel.fixtures.sources import fixture_id
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
from regintel.validation.models import ContextWitness

ROOT = Path(__file__).resolve().parents[1]


def artifact() -> bytes:
    helpers = runpy.run_path(str(ROOT / "scripts/generate-read-fixtures.py"))
    make_base = cast(object, helpers["artifact"])
    if not callable(make_base):
        raise ValueError("The authored base fixture generator is unavailable.")
    base = json.loads(make_base())
    view = ViewInfo.model_validate_json(json.dumps(base["info"]["data"]))
    meta = ResponseMeta.model_validate_json(json.dumps(base["info"]["meta"]))
    template = PublishedObservation.model_validate_json(
        json.dumps(base["facts"]["data"]["facts"][0]["observation"])
    )
    base_evidence = PublishedEvidence.model_validate_json(json.dumps(base["evidence"]["data"]))
    companies = (
        EntityLabel(id=fixture_id(760), kind="COMPANY", name="Alpha Energy Limited"),
        EntityLabel(id=fixture_id(9100), kind="COMPANY", name="Beta Solar Limited"),
    )
    metric = MetricDefinition(
        id=fixture_id(9101),
        key="authored_revenue",
        label="Revenue (authored fixture)",
        kind="numeric_fact",
        cue_phrases=("revenue",),
    )
    request = ComparisonRequest.model_validate(
        {
            "corpus_version_id": view.corpus_version_id,
            "company_ids": tuple(company.id for company in companies),
            "metric_ids": (metric.id,),
            "period": {
                "kind": "DURATION",
                "start_date": "2025-04-01",
                "end_date": "2026-03-31",
                "instant_date": None,
                "raw_label": None,
            },
            "basis": "CONSOLIDATED",
            "as_of_date": None,
        }
    )
    pdf_bytes = BytesIO()
    pdf = Canvas(pdf_bytes, pagesize=(792, 612), invariant=True, pageCompression=0)
    facts = []
    records = []
    cells = []
    contexts = []
    for index, (company, value, unit) in enumerate(
        zip(companies, ("12.50", "150"), ("crore", "million"), strict=True)
    ):
        quote = (
            f"{company.name} consolidated revenue INR {value} {unit} "
            "from 1 April 2025 to 31 March 2026."
        )
        pdf.setFont("Helvetica", 9)
        pdf.drawString(
            40, 570, "Authored engineering fixture. Not a real filing or research gold data."
        )
        pdf.drawString(40, 520, quote)
        pdf.showPage()
        evidence_id = fixture_id(9110 + index)
        support = SourceSpan(evidence_id=evidence_id, start=0, end=len(quote), quote=quote)
        witnesses = []
        for role, text in (
            ("VALUE", value),
            ("UNIT", unit),
            ("CURRENCY", "INR"),
            ("BASIS", "consolidated"),
            ("PERIOD", "from 1 April 2025 to 31 March 2026"),
        ):
            start = quote.index(text)
            witnesses.append(
                ContextWitness.model_validate(
                    {
                        "role": role,
                        "span": {
                            "evidence_id": evidence_id,
                            "start": start,
                            "end": start + len(text),
                            "quote": text,
                        },
                    }
                )
            )
        quantity = QuantitativeValue.model_validate(
            {
                "raw_value": value,
                "normalized_value": value,
                "raw_unit": unit,
                "normalized_unit": unit,
                "raw_currency": "INR",
                "currency": "INR",
                "period": request.period,
                "basis": "CONSOLIDATED",
                "raw_basis_label": "consolidated",
                "denominator": None,
                "stake_kind": None,
                "ownership_date": None,
                "evidence_ids": (evidence_id,),
            }
        )
        observation = PublishedObservation.model_validate(
            template.model_dump()
            | {
                "id": fixture_id(9120 + index),
                "subject_entity_id": company.id,
                "kind": "numeric_fact",
                "metric_id": metric.id,
                "raw_text": quote,
                "quantity": quantity,
                "supports": (support,),
                "context_supports": tuple(witnesses),
            }
        )
        fact = PublishedFact(observation=observation, metric=metric)
        record = base_evidence.evidence.record.model_copy(
            update={
                "id": evidence_id,
                "source": base_evidence.evidence.record.source.model_copy(
                    update={"page_index": index, "page_id": fixture_id(9130 + index)}
                ),
                "page_geometry": base_evidence.evidence.record.page_geometry.model_validate(
                    {
                        "width": 792.0,
                        "height": 612.0,
                        "rotation": 0,
                        "coordinate_space": "UNROTATED_PDF_POINTS",
                        "origin": "BOTTOM_LEFT",
                        "media_box": {"x0": 0.0, "y0": 0.0, "x1": 792.0, "y1": 612.0},
                        "crop_box": {"x0": 0.0, "y0": 0.0, "x1": 792.0, "y1": 612.0},
                    }
                ),
                "span": base_evidence.evidence.record.span.model_copy(
                    update={
                        "block_id": fixture_id(9140 + index),
                        "start": 0,
                        "end": len(quote),
                        "quote": quote,
                    }
                ),
                "boxes": (
                    base_evidence.evidence.record.boxes[0].model_copy(
                        update={
                            "x0": 40.0,
                            "y0": 518.0,
                            "x1": 40.0 + pdfmetrics.stringWidth(quote, "Helvetica", 9),
                            "y1": 530.0,
                        }
                    ),
                ),
            }
        )
        facts.append(fact)
        records.append(record)
        contexts.append(tuple(witnesses))
        cells.append(
            ComparisonCell(
                company_id=company.id,
                state="AVAILABLE",
                explanation="One authored accepted input matches the selected context.",
                inputs=(fact,),
                normalized=normalize(quantity),
            )
        )
    pdf.save()
    data = pdf_bytes.getvalue()
    sha = hashlib.sha256(data).hexdigest()

    def wrapped(value: object, selected_meta: ResponseMeta = meta) -> object:
        return json.loads(SuccessEnvelope(data=value, meta=selected_meta).model_dump_json())

    result = ComparisonResult(
        view=view,
        selection=request,
        companies=companies,
        policy=CALCULATION_POLICY,
        warnings=(),
        rows=(
            ComparisonRow(
                metric=metric, cells=tuple(cells), differences=(difference(cells[0], cells[1]),)
            ),
        ),
    )
    evidence = {}
    for fact, record, source_contexts in zip(facts, records, contexts, strict=True):
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
        evidence[record.id] = wrapped(
            PublishedEvidence(
                view=view,
                observation_id=fact.observation.id,
                supports=fact.observation.supports,
                context_supports=source_contexts,
                evidence=EvidenceData(
                    record=record,
                    provenance=base_evidence.evidence.provenance,
                    source_sha256=sha,
                    processing_configuration_sha256=base_evidence.evidence.processing_configuration_sha256,
                ),
            ),
            source_meta,
        )
    artifact = {
        "description": "Authored M2 engineering fixture; not real filing or effectiveness data.",
        "request": request.model_dump(mode="json"),
        "comparison": wrapped(result),
        "info": wrapped(view),
        "quotes": wrapped(QUOTES_UNAVAILABLE),
        "companies": wrapped(
            CompanyPage(view=view, companies=companies, total=2, offset=0, limit=25)
        ),
        "facts": {
            company.id: wrapped(
                FactPage(view=view, company=company, facts=(fact,), total=1, offset=0, limit=25)
            )
            for company, fact in zip(companies, facts, strict=True)
        },
        "graphs": {
            company.id: wrapped(
                CompanyGraph(view=view, company=company, nodes=(company,), edges=())
            )
            for company in companies
        },
        "evidence": evidence,
        "pdf_base64": base64.b64encode(data).decode("ascii"),
    }
    return (json.dumps(artifact, indent=2, sort_keys=True) + "\n").encode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    path = ROOT / "frontend/src/analysis/fixtures.generated.json"
    content = artifact()
    if options.check:
        if not path.is_file() or path.read_bytes() != content:
            print("Authored M2 fixture differs; run scripts/generate-analysis-fixtures.py.")
            return 1
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    print("Authored M2 fixture matches." if options.check else "Authored M2 fixture generated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
