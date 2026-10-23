"""Authored native declarations on blank PDFs; no genuine decoding/financial-review claim."""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from pypdf import PdfReader

from backend.tests.test_native_source import configuration as native_configuration
from backend.tests.test_numerical_context import authored
from regintel.entities.models import canonical_bytes as entity_bytes
from regintel.numerical.context_gate import inspect_context
from regintel.numerical.context_models import NumericalContextInput, WordPhrase
from regintel.numerical.context_records import (
    NumericalContextRecord,
    context_record_id,
    storage_configuration_sha256,
)
from regintel.numerical.models import StoredNumericalPage, page_capture_id
from regintel.numerical.source_pages import build_page_capture, capture_bytes
from regintel.parsing.configuration import ParserRuntimeConfiguration
from regintel.parsing.geometry import geometry_from_pdf_page
from regintel.parsing.native_context import (
    ContextCapture,
    NativeContextParse,
    build_native_context_parse,
)
from regintel.parsing.native_source import (
    NativePageReceipt,
    NativeSourceBank,
    NativeSourceManifest,
    NativeSourcePage,
    NativeSourceWord,
    canonical_bytes,
)


def complete_raw(raw):
    raw = deepcopy(raw)
    for index, table in enumerate(raw["document"]["tables"]):
        table["self_ref"] = f"#/tables/{index}"
        boxes = [cell["bbox"] for cell in table["data"]["table_cells"]]
        table["prov"] = [
            {
                "page_no": raw["requested_original_pdf_page"],
                "bbox": {
                    "l": min(b["l"] for b in boxes),
                    "t": min(b["t"] for b in boxes),
                    "r": max(b["r"] for b in boxes),
                    "b": max(b["b"] for b in boxes),
                    "coord_origin": "TOPLEFT",
                },
            }
        ]
        for cell in table["data"]["table_cells"]:
            cell["row_section"] = False
    return raw


def declared_bank(directory: Path, source: Path, stored: StoredNumericalPage) -> NativeSourceBank:
    directory.mkdir()
    receipts = []
    prepared = stored.capture
    for index, original in enumerate(PdfReader(source).pages):
        geometry = geometry_from_pdf_page(original)
        words = []
        if index == prepared.page_index:
            for word in prepared.words:
                rect = word.raw_rectangle.model_dump(mode="python")
                for corner in range(4):
                    rect[f"r_y{corner}"] = geometry.height - rect[f"r_y{corner}"]
                rect["coord_origin"] = "BOTTOMLEFT"
                words.append(
                    NativeSourceWord(
                        index=word.word_index,
                        orig=word.orig,
                        text=word.orig,
                        from_ocr=False,
                        raw_rectangle=rect,
                    )
                )
        page = NativeSourcePage(
            source_sha256=prepared.source_sha256,
            page_index=index,
            page_geometry=geometry,
            raw_dimension={"authored": "Engineering native declaration"},
            words=tuple(words),
        )
        data = canonical_bytes(page)
        (directory / f"page-{index:04}.json").write_bytes(data)
        receipts.append(
            NativePageReceipt(
                page_index=index,
                word_count=len(words),
                byte_size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            )
        )
    manifest = NativeSourceManifest(
        source_sha256=prepared.source_sha256,
        source_byte_size=source.stat().st_size,
        source_page_count=len(receipts),
        configuration=native_configuration(),
        pages=tuple(receipts),
    )
    (directory / "manifest.json").write_bytes(canonical_bytes(manifest))
    return NativeSourceBank(directory, manifest)


def remap_draft(draft, stored):
    def mapped(phrase: WordPhrase) -> WordPhrase:
        return phrase.model_copy(
            update={
                "words": tuple(
                    ref.model_copy(update={"capture_id": stored.id}) for ref in phrase.words
                )
            }
        )

    return draft.model_copy(
        update={
            "filing_version_id": stored.filing_version_id,
            "value": draft.value.model_copy(update={"phrase": mapped(draft.value.phrase)}),
            "row_label": draft.row_label.model_copy(
                update={"phrase": mapped(draft.row_label.phrase)}
            ),
            "period_header": draft.period_header.model_copy(
                update={"phrase": mapped(draft.period_header.phrase)}
            ),
            "issuer_header": mapped(draft.issuer_header),
            "table_scope": mapped(draft.table_scope),
            "unit_header": mapped(draft.unit_header),
            "fiscal_definitions": tuple(mapped(p) for p in draft.fiscal_definitions),
            "currency_definitions": tuple(mapped(p) for p in draft.currency_definitions),
            "basis_context": mapped(draft.basis_context) if draft.basis_context else None,
        }
    )


def remap_input(source, stored):
    return NumericalContextInput.model_validate(
        source.model_dump(mode="python")
        | {
            "draft": remap_draft(source.draft, stored),
            "pages": (stored,),
        }
    )


def record_for(source):
    inspection = inspect_context(source)
    version = storage_configuration_sha256()
    return NumericalContextRecord(
        id=context_record_id(inspection.id, version),
        filing_version_id=source.draft.filing_version_id,
        source_blob_id=source.pages[0].source_blob_id,
        source_sha256=source.pages[0].capture.source_sha256,
        input_sha256=hashlib.sha256(entity_bytes(source)).hexdigest(),
        inspection_sha256=hashlib.sha256(entity_bytes(inspection)).hexdigest(),
        storage_configuration_sha256=version,
        submitted_by=uuid4(),
        auth_version=1,
        source_input=source,
        inspection=inspection,
    )


@dataclass(frozen=True)
class NativeCase:
    source: Path
    result: NativeContextParse
    record: NumericalContextRecord


def native_case(tmp_path: Path) -> NativeCase:
    case = authored(tmp_path)
    old = case.input.pages[0]
    raw = complete_raw(case.raw)
    body = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    prepared = build_page_capture(
        raw,
        source=case.source,
        pdf_page=2,
        expected_source_sha256=old.capture.source_sha256,
        expected_sdk_configuration_sha256=old.capture.sdk_configuration_sha256,
    )
    digest = hashlib.sha256(capture_bytes(prepared)).hexdigest()
    stored = old.model_copy(
        update={
            "capture": prepared,
            "prepared_sha256": digest,
            "id": page_capture_id(old.filing_version_id, old.source_blob_id, digest),
        }
    )
    bank = declared_bank(tmp_path / "native-bank", case.source, stored)
    baseline = ParserRuntimeConfiguration.model_validate_json(
        (Path(__file__).resolve().parents[2] / "data/parser-runtime-config.json").read_bytes()
    ).model_copy(
        update={
            "sdk_configuration_sha256": prepared.sdk_configuration_sha256,
            "package_manifest_sha256": bank.manifest.configuration.package_manifest_sha256,
        }
    )
    result = build_native_context_parse(
        bank,
        source=case.source,
        baseline=baseline,
        captures=(ContextCapture(stored, body),),
        parse_id=str(uuid4()),
        filing_id=str(uuid4()),
        filing_version_id=stored.filing_version_id,
        source_blob_id=stored.source_blob_id,
    )
    return NativeCase(case.source, result, record_for(remap_input(case.input, stored)))
