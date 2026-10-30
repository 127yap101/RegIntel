"""Bounded workspace contracts, separate from frozen validation/publication code."""

from typing import Annotated, Literal

from pydantic import Field

from regintel.candidates.models import DraftCandidate, MetricDefinition
from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, SafeInteger, Sha256Hash
from regintel.evidence.api import EvidenceData
from regintel.ingestion.jobs import FilingJob, UploadMetadata
from regintel.ingestion.models import CandidateRecord, StoredLabel
from regintel.numerical.acceptance_models import (
    NumericalAcceptanceRequest,
    StoredNumericalAcceptance,
)
from regintel.numerical.candidate_models import NumericalCandidateRequest, StoredNumericalCandidate
from regintel.numerical.publication_models import NumericalPublicationPreparation
from regintel.numerical.review_api import NumericalReviewPacket
from regintel.numerical.review_models import NumericalContextReviewRequest, ReviewedNumericalContext
from regintel.processing.api import DispatchReceipt
from regintel.processing.models import ProcessingJob, ProcessingRequest
from regintel.publication.models import CorpusManifest, PublicationRequest
from regintel.publication.support_models import NativeAmendmentWords
from regintel.validation.api import ReviewReceipt, ValidationData, ValidationRequest
from regintel.validation.models import ReviewDecision, ValidationResult

type QueueKind = Literal["filings", "processing", "validations", "publications"]
type ReviewFilter = Literal["ALL", "PASS", "REVIEW", "QUARANTINED"]


class QueueItem(ContractModel):
    id: CanonicalId
    label: StoredLabel
    state: StoredLabel
    parse_version_id: CanonicalId | None
    related_id: CanonicalId | None


class QueuePage(ContractModel):
    kind: QueueKind
    items: Annotated[tuple[QueueItem, ...], Field(strict=False, max_length=25)]
    offset: SafeInteger
    limit: SafeInteger
    has_more: bool
    published_corpus_id: CanonicalId | None


class ReviewItem(ContractModel):
    candidate: CandidateRecord
    draft: DraftCandidate
    result: ValidationResult
    review: ReviewDecision | None
    metric_label: StoredLabel | None
    accepted_observation_id: CanonicalId | None


class ReviewPage(ContractModel):
    run_id: CanonicalId
    candidate_run_id: CanonicalId
    parse_version_id: CanonicalId
    configuration_sha256: Sha256Hash
    approval_current: bool
    state_filter: ReviewFilter
    items: Annotated[tuple[ReviewItem, ...], Field(strict=False, max_length=25)]
    offset: SafeInteger
    limit: SafeInteger
    has_more: bool


class MetricPage(ContractModel):
    items: Annotated[tuple[MetricDefinition, ...], Field(strict=False, max_length=100)]


class AdminWire(ContractModel):
    queue: QueuePage
    review_page: ReviewPage
    metrics: MetricPage
    filing_job: FilingJob
    upload: UploadMetadata
    processing_job: ProcessingJob
    processing_request: ProcessingRequest
    dispatch: DispatchReceipt
    validation: ValidationData
    validation_request: ValidationRequest
    review_request: ReviewDecision
    review_receipt: ReviewReceipt
    manifest: CorpusManifest
    publication_request: PublicationRequest
    evidence: EvidenceData
    numerical_packet: NumericalReviewPacket
    numerical_review_request: NumericalContextReviewRequest
    numerical_review: ReviewedNumericalContext
    numerical_preparation: NumericalPublicationPreparation
    numerical_candidate_request: NumericalCandidateRequest
    numerical_candidate: StoredNumericalCandidate
    numerical_acceptance_request: NumericalAcceptanceRequest
    numerical_acceptance: StoredNumericalAcceptance
    native_amendment_words: NativeAmendmentWords
