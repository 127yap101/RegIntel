"""Immutable preparation records and exact word references, without fact authority."""

import hashlib
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from regintel.contracts.models import ContractModel, PageGeometry, PdfRectangle
from regintel.contracts.primitives import CanonicalId, RawText, SafeInteger, Sha256Hash
from regintel.numerical.source_pages import NumericalPageCapture, capture_bytes
from regintel.parsing.models import ReportedRectangle


def page_capture_id(filing_version_id: str, source_blob_id: str, prepared_sha256: str) -> str:
    key = f"numerical-page:{filing_version_id}:{source_blob_id}:{prepared_sha256}"
    return str(UUID(bytes=hashlib.sha256(key.encode("utf-8")).digest()[:16], version=4))


class StoredNumericalPage(ContractModel):
    schema_version: Literal["stored-numerical-page-1"] = "stored-numerical-page-1"
    id: CanonicalId
    filing_version_id: CanonicalId
    source_blob_id: CanonicalId
    prepared_sha256: Sha256Hash
    submitted_by: UUID
    auth_version: Annotated[int, Field(strict=True, ge=1)]
    capture: NumericalPageCapture

    @model_validator(mode="after")
    def immutable_identity(self) -> Self:
        if hashlib.sha256(capture_bytes(self.capture)).hexdigest() != self.prepared_sha256:
            raise ValueError("Prepared page bytes must match their immutable fingerprint.")
        if self.id != page_capture_id(
            self.filing_version_id, self.source_blob_id, self.prepared_sha256
        ):
            raise ValueError("Stored preparation identity must bind its uploaded source version.")
        return self


class NumericalWordRef(ContractModel):
    schema_version: Literal["numerical-word-reference-1"] = "numerical-word-reference-1"
    capture_id: CanonicalId
    word_index: Annotated[SafeInteger, Field(le=19_999)]
    start: Annotated[SafeInteger, Field(le=20_000)]
    end: Annotated[SafeInteger, Field(le=20_000)]
    quote: Annotated[RawText, Field(min_length=1, max_length=20_000)]

    @model_validator(mode="after")
    def exact_unicode_length(self) -> Self:
        if self.end <= self.start or self.end - self.start != len(self.quote):
            raise ValueError("A source-word reference needs exact half-open Unicode offsets.")
        return self


class ResolvedNumericalWord(ContractModel):
    reference: NumericalWordRef
    filing_version_id: CanonicalId
    source_blob_id: CanonicalId
    source_sha256: Sha256Hash
    page_index: SafeInteger
    page_geometry: PageGeometry
    raw_rectangle: ReportedRectangle
    box: PdfRectangle
    geometry_scope: Literal["ORIGINAL_WORD_ENVELOPE"] = "ORIGINAL_WORD_ENVELOPE"
    acceptance_eligible: Literal[False] = False
    review_required: Literal[True] = True
