"""Exact links to existing M1 evidence; no new evidence identity or acceptance authority."""

import hashlib
import json
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from regintel.contracts.models import ContractModel, EvidenceSource, TextEvidence
from regintel.contracts.primitives import CanonicalId, SafeInteger, Sha256Hash
from regintel.numerical.models import NumericalWordRef

MAX_BINDING_BYTES = 4 * 1024 * 1024
PhraseRole = Literal[
    "value",
    "row_label",
    "period_header",
    "issuer_header",
    "table_scope",
    "unit_header",
    "basis_context",
    "currency_definition",
    "fiscal_definition",
]
CellRole = Literal["value", "row_label", "period_header"]


def binding_identity(payload: dict[str, object]) -> str:
    body = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return str(
        UUID(bytes=hashlib.sha256(b"numerical-evidence-binding:" + body).digest()[:16], version=4)
    )


class BoundNumericalWord(ContractModel):
    reference: NumericalWordRef
    evidence: TextEvidence

    @model_validator(mode="after")
    def whole_original_word(self) -> Self:
        if (
            self.reference.start != 0
            or self.evidence.span.start != 0
            or self.reference.end != self.evidence.span.end
            or self.reference.quote != self.evidence.span.quote
        ):
            raise ValueError("A binding must retain one complete exact original word.")
        return self


class BoundNumericalPhrase(ContractModel):
    role: PhraseRole
    ordinal: Annotated[SafeInteger, Field(le=3)]
    words: Annotated[
        tuple[BoundNumericalWord, ...], Field(strict=False, min_length=1, max_length=256)
    ]

    @model_validator(mode="after")
    def ordered_source_words(self) -> Self:
        first = self.words[0]
        if any(
            word.reference.capture_id != first.reference.capture_id
            or word.reference.word_index != first.reference.word_index + offset
            or word.evidence.source != first.evidence.source
            for offset, word in enumerate(self.words)
        ):
            raise ValueError("A phrase must retain ordered words from one exact source page.")
        return self


class BoundNumericalCell(ContractModel):
    """Retained processed-grid membership supported by separate existing native-word evidence."""

    role: CellRole
    artifact_table_id: CanonicalId
    artifact_cell_id: CanonicalId
    source: EvidenceSource
    row_index: SafeInteger
    column_index: SafeInteger
    row_span: Annotated[SafeInteger, Field(ge=1)]
    column_span: Annotated[SafeInteger, Field(ge=1)]
    word_evidence_ids: Annotated[
        tuple[CanonicalId, ...], Field(strict=False, min_length=1, max_length=256)
    ]


class NumericalEvidenceBinding(ContractModel):
    schema_version: Literal["numerical-context-evidence-binding-1"] = (
        "numerical-context-evidence-binding-1"
    )
    scope: Literal["EXISTING_M1_WORD_EVIDENCE_ONLY"] = "EXISTING_M1_WORD_EVIDENCE_ONLY"
    id: CanonicalId
    context_record_id: CanonicalId
    context_input_sha256: Sha256Hash
    context_inspection_sha256: Sha256Hash
    filing_id: CanonicalId
    filing_version_id: CanonicalId
    source_blob_id: CanonicalId
    source_sha256: Sha256Hash
    parse_version_id: CanonicalId
    parse_artifact_sha256: Sha256Hash
    processing_configuration_sha256: Sha256Hash
    binding_configuration_sha256: Sha256Hash
    phrases: Annotated[
        tuple[BoundNumericalPhrase, ...], Field(strict=False, min_length=6, max_length=15)
    ]
    cells: Annotated[
        tuple[BoundNumericalCell, ...], Field(strict=False, min_length=3, max_length=3)
    ]
    acceptance_eligible: Literal[False] = False
    mandatory_m1_validation_complete: Literal[False] = False
    review_required: Literal[True] = True

    @model_validator(mode="after")
    def exact_membership(self) -> Self:
        keys = [(phrase.role, phrase.ordinal) for phrase in self.phrases]
        required = [
            (role, 0)
            for role in (
                "value",
                "row_label",
                "period_header",
                "issuer_header",
                "table_scope",
                "unit_header",
            )
        ]
        words = [word for phrase in self.phrases for word in phrase.words]
        if (
            keys[:6] != required
            or len(keys) != len(set(keys))
            or len(words) > 1024
            or any(
                (
                    word.evidence.source.filing_id,
                    word.evidence.source.filing_version_id,
                    word.evidence.source.parse_version_id,
                )
                != (self.filing_id, self.filing_version_id, self.parse_version_id)
                for word in words
            )
        ):
            raise ValueError("Every exact binding must retain its bounded source membership.")
        if tuple(cell.role for cell in self.cells) != ("value", "row_label", "period_header"):
            raise ValueError("Every binding needs its value, row and period grid membership.")
        for cell, phrase in zip(self.cells, self.phrases[:3], strict=True):
            if cell.source != phrase.words[0].evidence.source or cell.word_evidence_ids != tuple(
                word.evidence.id for word in phrase.words
            ):
                raise ValueError("Grid membership must retain the exact linked source words.")
        if len({cell.artifact_table_id for cell in self.cells}) != 1:
            raise ValueError("Value, row and period support must occupy one retained table.")
        payload = self.model_dump(mode="json", exclude={"id"})
        if self.id != binding_identity(payload):
            raise ValueError(
                "Binding identity must retain exact context, evidence and configuration."
            )
        if len(self.model_dump_json().encode("utf-8")) > MAX_BINDING_BYTES:
            raise ValueError("Exact evidence binding exceeds its explicit byte budget.")
        return self
