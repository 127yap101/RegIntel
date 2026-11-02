"""Bounded historical queue contracts, outside frozen numerical gate fingerprints."""

import hashlib
from typing import Annotated, Final, Literal, Self

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId
from regintel.entities.models import canonical_bytes
from regintel.ingestion.models import DocumentType, StoredLabel
from regintel.numerical.gate_models import BoundNumericalGateRun
from regintel.numerical.review_models import ReviewedNumericalContext

MAX_QUEUE_OFFSET: Final = 10000
MAX_QUEUE_PAGE: Final = 20
MAX_QUEUE_BYTES: Final = 8 * 1024 * 1024
GateStateFilter = Literal["ALL", "READY_FOR_REVIEW", "REVIEW_REQUIRED", "QUARANTINED"]
ContextReviewFilter = Literal["ALL", "UNREVIEWED", "CONFIRM_CONTEXT", "REJECT"]
QueueOffset = Annotated[int, Field(strict=True, ge=0, le=MAX_QUEUE_OFFSET)]
QueueLimit = Annotated[int, Field(strict=True, ge=1, le=MAX_QUEUE_PAGE)]


def _query_unicode(value: str) -> str:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise ValueError("A queue search requires valid Unicode text.") from None
    return value


QueueQuery = Annotated[
    str,
    StringConstraints(strict=True, max_length=120, pattern=r"^[^\x00]*$"),
    AfterValidator(_query_unicode),
]


class NumericalGateQueueRequest(ContractModel):
    state: GateStateFilter
    review: ContextReviewFilter
    query: QueueQuery
    offset: QueueOffset
    limit: QueueLimit


class NumericalGateQueueItem(ContractModel):
    filing_version_id: CanonicalId
    company_name_raw: StoredLabel
    document_type: DocumentType
    gate: BoundNumericalGateRun
    review: ReviewedNumericalContext | None

    @model_validator(mode="after")
    def recorded_review_membership(self) -> Self:
        gate, review = self.gate, self.review
        if review is not None and (
            review.request.gate_run_id != gate.id
            or review.gate_input_sha256 != gate.input_sha256
            or review.gate_result_sha256 != hashlib.sha256(canonical_bytes(gate)).hexdigest()
            or review.request.evidence_ids != gate.evidence_ids
            or review.request.decision == "CONFIRM_CONTEXT"
            and (gate.state != "READY_FOR_REVIEW" or not gate.evidence_ids)
        ):
            raise ValueError("A queued review must retain its exact recorded gate membership.")
        return self


class NumericalGateQueuePage(ContractModel):
    scope: Literal["RETAINED_HISTORY_ONLY"]
    state_filter: GateStateFilter
    review_filter: ContextReviewFilter
    query: QueueQuery
    offset: QueueOffset
    limit: QueueLimit
    has_more: bool
    items: Annotated[
        tuple[NumericalGateQueueItem, ...], Field(strict=False, max_length=MAX_QUEUE_PAGE)
    ]

    @model_validator(mode="after")
    def bounded_membership(self) -> Self:
        ids = tuple(item.gate.id for item in self.items)
        if ids != tuple(sorted(set(ids))) or len(self.items) > self.limit:
            raise ValueError("The queue requires distinct ordered gates within its page limit.")
        if self.has_more and len(self.items) != self.limit:
            raise ValueError("A queue continuation requires a complete current page.")
        for item in self.items:
            review = item.review.request.decision if item.review is not None else "UNREVIEWED"
            if (self.state_filter != "ALL" and item.gate.state != self.state_filter) or (
                self.review_filter != "ALL" and review != self.review_filter
            ):
                raise ValueError("A queue row differs from its selected historical filters.")
        if len(canonical_bytes(self)) > MAX_QUEUE_BYTES:
            raise ValueError("The queue response exceeds its retained-payload budget.")
        return self
