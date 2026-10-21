"""Join preparation words/grid to a complete sealed M1 artifact without manufacturing evidence."""

import hashlib
from pathlib import Path
from typing import Literal

from regintel.contracts.models import PdfRectangle, TextEvidence
from regintel.evidence.projection import ParseProjection, project_parse
from regintel.numerical.context_models import NumericalContextDraft, TableCellSupport, WordPhrase
from regintel.numerical.context_records import NumericalContextRecord
from regintel.numerical.evidence_binding_models import (
    BoundNumericalCell,
    BoundNumericalPhrase,
    BoundNumericalWord,
    CellRole,
    NumericalEvidenceBinding,
    PhraseRole,
    binding_identity,
)
from regintel.numerical.models import StoredNumericalPage
from regintel.numerical.source_pages import CellPreview
from regintel.parsing.configuration import ParserRuntimeConfiguration
from regintel.parsing.models import ParseArtifact, ParsedCell, ParsedTable, ReportedRectangle

WordKey = tuple[int, str, PdfRectangle, ReportedRectangle]

BindingErrorCode = Literal[
    "SOURCE_MISMATCH",
    "PAGE_COVERAGE_MISMATCH",
    "PREPARATION_MISMATCH",
    "WORD_SUPPORT_UNAVAILABLE",
    "WORD_SUPPORT_AMBIGUOUS",
    "TABLE_MEMBERSHIP_UNAVAILABLE",
    "TABLE_MEMBERSHIP_AMBIGUOUS",
]


class EvidenceBindingError(ValueError):
    def __init__(self, code: BindingErrorCode) -> None:
        self.code = code
        super().__init__(code)


def binding_configuration_sha256() -> str:
    package = Path(__file__).resolve().parents[1]
    sources = (
        "numerical/evidence_binding.py",
        "numerical/evidence_binding_models.py",
        "numerical/evidence_binding_repository.py",
        "evidence/projection.py",
        "parsing/configuration.py",
        "parsing/adapter.py",
        "parsing/geometry.py",
        "parsing/models.py",
        "contracts/models.py",
        "contracts/primitives.py",
    )
    digest = hashlib.sha256()
    for name in sources:
        body = (package / name).read_bytes()
        digest.update(name.encode("ascii") + b"\0" + len(body).to_bytes(8, "big") + body)
    return digest.hexdigest()


def named_phrases(draft: NumericalContextDraft) -> tuple[tuple[PhraseRole, int, WordPhrase], ...]:
    basis: tuple[tuple[PhraseRole, int, WordPhrase], ...] = (
        (("basis_context", 0, draft.basis_context),) if draft.basis_context is not None else ()
    )
    return (
        ("value", 0, draft.value.phrase),
        ("row_label", 0, draft.row_label.phrase),
        ("period_header", 0, draft.period_header.phrase),
        ("issuer_header", 0, draft.issuer_header),
        ("table_scope", 0, draft.table_scope),
        ("unit_header", 0, draft.unit_header),
        *basis,
        *(
            ("currency_definition", i, phrase)
            for i, phrase in enumerate(draft.currency_definitions)
        ),
        *(("fiscal_definition", i, phrase) for i, phrase in enumerate(draft.fiscal_definitions)),
    )


def _word_index(
    artifact: ParseArtifact, projection: ParseProjection
) -> dict[WordKey, list[TextEvidence]]:
    blocks = {block.id: block for block in artifact.blocks}
    result: dict[WordKey, list[TextEvidence]] = {}
    for item in projection.evidence:
        block = blocks[item.span.block_id]
        if (
            block.page_index is None
            or block.orig is None
            or block.from_ocr is not False
            or block.boxes is None
            or len(block.boxes) != 1
            or len(block.provenance) != 1
            or block.provenance[0].raw_rectangle is None
            or item.span.start != 0
            or item.span.end != len(block.orig)
            or item.span.quote != block.orig
        ):
            continue
        key = (block.page_index, block.orig, block.boxes[0], block.provenance[0].raw_rectangle)
        result.setdefault(key, []).append(item)
    return result


def _phrase(
    role: PhraseRole,
    ordinal: int,
    phrase: WordPhrase,
    page: StoredNumericalPage,
    index: dict[WordKey, list[TextEvidence]],
) -> BoundNumericalPhrase:
    words = []
    for reference in phrase.words:
        if reference.word_index >= len(page.capture.words):
            raise EvidenceBindingError("WORD_SUPPORT_UNAVAILABLE")
        native = page.capture.words[reference.word_index]
        if (
            native.orig != reference.quote
            or reference.start != 0
            or reference.end != len(native.orig or "")
            or native.from_ocr is not False
            or native.box is None
            or native.raw_rectangle is None
        ):
            raise EvidenceBindingError("WORD_SUPPORT_UNAVAILABLE")
        matches = index.get(
            (page.capture.page_index, reference.quote, native.box, native.raw_rectangle), []
        )
        if len(matches) != 1:
            raise EvidenceBindingError(
                "WORD_SUPPORT_AMBIGUOUS" if matches else "WORD_SUPPORT_UNAVAILABLE"
            )
        words.append(BoundNumericalWord(reference=reference, evidence=matches[0]))
    return BoundNumericalPhrase(role=role, ordinal=ordinal, words=tuple(words))


def _matches_cell(cell: ParsedCell, preview: CellPreview, page: StoredNumericalPage) -> bool:
    return (
        cell.page_index == page.capture.page_index
        and cell.text == preview.text
        and (
            cell.row_index,
            cell.column_index,
            cell.row_span,
            cell.column_span,
            cell.column_header,
            cell.row_header,
        )
        == (
            preview.row_index,
            preview.column_index,
            preview.row_span,
            preview.column_span,
            preview.column_header,
            preview.row_header,
        )
        and preview.box is not None
        and cell.boxes == (preview.box,)
        and len(cell.provenance) == 1
        and cell.provenance[0].page_no == page.capture.page_index + 1
        and preview.raw_box is not None
        and cell.provenance[0].raw_box == preview.raw_box
    )


def _cells(
    draft: NumericalContextDraft,
    pages: dict[str, StoredNumericalPage],
    phrases: tuple[BoundNumericalPhrase, ...],
    artifact: ParseArtifact,
) -> tuple[BoundNumericalCell, ...]:
    supports: tuple[tuple[CellRole, TableCellSupport], ...] = (
        ("value", draft.value),
        ("row_label", draft.row_label),
        ("period_header", draft.period_header),
    )
    page = pages[draft.value.phrase.capture_id]
    previews = []
    for _role, support in supports:
        found = [
            cell
            for cell in page.capture.cells
            if (cell.table_index, cell.cell_index) == (support.table_index, support.cell_index)
        ]
        mappings = [
            mapping
            for mapping in page.capture.mappings
            if (mapping.table_index, mapping.cell_index)
            == (support.table_index, support.cell_index)
        ]
        if (
            len(found) != 1
            or support.phrase.capture_id != page.id
            or support.table_index != draft.value.table_index
            or len(mappings) != 1
            or mappings[0].state != "PROPOSED"
            or mappings[0].word_indices != tuple(word.word_index for word in support.phrase.words)
        ):
            raise EvidenceBindingError("TABLE_MEMBERSHIP_UNAVAILABLE")
        previews.append(found[0])
    matches: list[tuple[ParsedTable, tuple[ParsedCell, ...]]] = []
    for table in artifact.tables:
        if not any(
            region.page_index == page.capture.page_index for region in table.page_regions
        ) or any(
            (preview.table_rows, preview.table_columns) != (table.row_count, table.column_count)
            for preview in previews
        ):
            continue
        candidates = [
            tuple(cell for cell in table.cells if _matches_cell(cell, preview, page))
            for preview in previews
        ]
        if all(len(cells) == 1 for cells in candidates):
            matches.append((table, tuple(cells[0] for cells in candidates)))
    if len(matches) != 1:
        raise EvidenceBindingError(
            "TABLE_MEMBERSHIP_AMBIGUOUS" if matches else "TABLE_MEMBERSHIP_UNAVAILABLE"
        )
    table, cells = matches[0]
    return tuple(
        BoundNumericalCell(
            role=role,
            artifact_table_id=table.id,
            artifact_cell_id=cell.id,
            source=phrase.words[0].evidence.source,
            row_index=cell.row_index,
            column_index=cell.column_index,
            row_span=cell.row_span,
            column_span=cell.column_span,
            word_evidence_ids=tuple(word.evidence.id for word in phrase.words),
        )
        for (role, _support), cell, phrase in zip(supports, cells, phrases[:3], strict=True)
    )


def bind_context_evidence(
    record: NumericalContextRecord,
    artifact: ParseArtifact,
    configuration: ParserRuntimeConfiguration,
) -> NumericalEvidenceBinding:
    """Pure trusted-input operation; the repository additionally verifies sealed database rows."""
    record = NumericalContextRecord.model_validate(record.model_dump(mode="python"))
    projection = project_parse(artifact, configuration)
    if (record.filing_version_id, record.source_blob_id, record.source_sha256) != (
        artifact.filing_version_id,
        artifact.source_blob_id,
        artifact.source_sha256,
    ):
        raise EvidenceBindingError("SOURCE_MISMATCH")
    if any(
        diagnostic.code in {"PARSE_PARTIAL", "BACKEND_ERROR"} for diagnostic in artifact.diagnostics
    ):
        raise EvidenceBindingError("PAGE_COVERAGE_MISMATCH")
    if any(check.state != "PASS" for check in record.inspection.checks[:3]):
        raise EvidenceBindingError("PREPARATION_MISMATCH")
    pages = {page.id: page for page in record.source_input.pages}
    for page in pages.values():
        capture = page.capture
        if (
            page.filing_version_id != artifact.filing_version_id
            or page.source_blob_id != artifact.source_blob_id
            or capture.source_sha256 != artifact.source_sha256
            or capture.sdk_configuration_sha256 != configuration.sdk_configuration_sha256
        ):
            raise EvidenceBindingError("SOURCE_MISMATCH")
        if capture.source_page_count != len(artifact.pages) or capture.page_index >= len(
            artifact.pages
        ):
            raise EvidenceBindingError("PAGE_COVERAGE_MISMATCH")
        if artifact.pages[capture.page_index].geometry != capture.page_geometry:
            raise EvidenceBindingError("PREPARATION_MISMATCH")
    index = _word_index(artifact, projection)
    phrases = tuple(
        _phrase(role, ordinal, phrase, pages[phrase.capture_id], index)
        for role, ordinal, phrase in named_phrases(record.source_input.draft)
    )
    cells = _cells(record.source_input.draft, pages, phrases, artifact)
    payload = {
        "schema_version": "numerical-context-evidence-binding-1",
        "scope": "EXISTING_M1_WORD_EVIDENCE_ONLY",
        "context_record_id": record.id,
        "context_input_sha256": record.input_sha256,
        "context_inspection_sha256": record.inspection_sha256,
        "filing_id": artifact.filing_id,
        "filing_version_id": artifact.filing_version_id,
        "source_blob_id": artifact.source_blob_id,
        "source_sha256": artifact.source_sha256,
        "parse_version_id": artifact.id,
        "parse_artifact_sha256": projection.version.artifact_sha256,
        "processing_configuration_sha256": projection.version.configuration_sha256,
        "binding_configuration_sha256": binding_configuration_sha256(),
        "phrases": [phrase.model_dump(mode="json") for phrase in phrases],
        "cells": [cell.model_dump(mode="json") for cell in cells],
        "acceptance_eligible": False,
        "mandatory_m1_validation_complete": False,
        "review_required": True,
    }
    return NumericalEvidenceBinding.model_validate(payload | {"id": binding_identity(payload)})
