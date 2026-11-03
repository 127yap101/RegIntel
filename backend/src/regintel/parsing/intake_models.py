"""Explicit local file selection and preparation-only native import receipts."""

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, Sha256Hash
from regintel.ingestion.jobs import FilingJob, UploadMetadata


class IntakeFile(ContractModel):
    path: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=4096)]
    sha256: Sha256Hash


class IntakePage(ContractModel):
    pdf_page: Annotated[int, Field(strict=True, ge=1, le=2000)]
    raw_capture: IntakeFile


class NativeIntakePlan(ContractModel):
    schema_version: Literal["native-intake-plan-1"] = "native-intake-plan-1"
    source: IntakeFile
    parser_configuration: IntakeFile
    native_manifest: IntakeFile
    metadata: UploadMetadata
    context_pages: Annotated[
        tuple[IntakePage, ...], Field(strict=False, min_length=1, max_length=32)
    ]

    @model_validator(mode="after")
    def ordered_pages(self) -> Self:
        pages = tuple(item.pdf_page for item in self.context_pages)
        if pages != tuple(sorted(set(pages))):
            raise ValueError("Select unique original pages in increasing physical page order.")
        return self


class NativeIntakeCheck(ContractModel):
    status: Literal["PREPARATION_ONLY"] = "PREPARATION_ONLY"
    source_sha256: Sha256Hash
    source_pages: Annotated[int, Field(strict=True, ge=1, le=2000)]
    native_manifest_sha256: Sha256Hash
    processing_configuration_sha256: Sha256Hash
    evidence_pdf_pages: Annotated[tuple[int, ...], Field(strict=False, min_length=1, max_length=32)]
    prepared_sha256: Annotated[
        tuple[Sha256Hash, ...], Field(strict=False, min_length=1, max_length=32)
    ]
    acceptance_eligible: Literal[False] = False


class NativeIntakeResult(ContractModel):
    status: Literal["SOURCE_EVIDENCE_SEALED"] = "SOURCE_EVIDENCE_SEALED"
    job: FilingJob
    capture_ids: Annotated[
        tuple[CanonicalId, ...], Field(strict=False, min_length=1, max_length=32)
    ]
    acceptance_eligible: Literal[False] = False

    @model_validator(mode="after")
    def sealed_job(self) -> Self:
        if self.job.state != "PARSED" or self.job.parse_version_id is None:
            raise ValueError("Only a verified sealed source parse has a successful receipt.")
        return self
