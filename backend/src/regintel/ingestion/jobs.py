"""Typed upload metadata and PostgreSQL-owned job responses."""

import hashlib
from typing import Literal

from regintel.contracts.models import ContractModel, ResponseMeta
from regintel.contracts.primitives import CanonicalId, DateString, SafeInteger, Sha256Hash
from regintel.ingestion.models import DocumentType, SourceUrl, StoredLabel

JobState = Literal["QUEUED", "RUNNING", "SOURCE_VERIFIED", "PARSED", "FAILED"]

ParserFailureCode = Literal["PARSE_FAILED", "ARTIFACT_INVALID", "PARSER_CONFIGURATION_MISMATCH"]


class ParserFailure(Exception):
    """Sanitized, terminal parser outcome; never contain source or SDK diagnostics."""

    def __init__(self, code: ParserFailureCode) -> None:
        self.code = code
        super().__init__(code)


class UploadMetadata(ContractModel):
    company_name_raw: StoredLabel
    document_type: DocumentType
    source_url: SourceUrl | None = None
    published_on: DateString | None = None
    declared_parent_filing_version_id: CanonicalId | None = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class FilingJob(ContractModel):
    id: CanonicalId
    filing_version_id: CanonicalId
    source_blob_id: CanonicalId
    source_sha256: Sha256Hash
    configuration_sha256: Sha256Hash
    state: JobState
    attempts: SafeInteger
    page_count: SafeInteger | None
    parse_version_id: CanonicalId | None = None
    failure_code: (
        Literal[
            "SOURCE_HASH_MISMATCH",
            "INVALID_PDF",
            "PAGE_LIMIT",
            "ENCRYPTED_PDF",
            "SOURCE_UNAVAILABLE",
            "WORKER_CONFIGURATION_MISMATCH",
            "PARSE_FAILED",
            "ARTIFACT_INVALID",
            "PARSER_CONFIGURATION_MISMATCH",
        ]
        | None
    )


class FilingJobEnvelope(ContractModel):
    data: FilingJob
    meta: ResponseMeta
