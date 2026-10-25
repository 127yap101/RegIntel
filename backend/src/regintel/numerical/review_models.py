"""Staged numerical-context decisions; never legacy validation or fact acceptance."""

import hashlib
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, RawText, Sha256Hash
from regintel.entities.models import canonical_bytes
from regintel.numerical.gate_models import StoredBoundNumericalGate

MAX_REVIEW_BYTES = 65536


class NumericalContextReviewRequest(ContractModel):
    gate_run_id: CanonicalId
    decision: Literal["CONFIRM_CONTEXT", "REJECT"]
    evidence_ids: Annotated[tuple[CanonicalId, ...], Field(strict=False, max_length=1024)]
    note: Annotated[RawText, Field(min_length=1, max_length=2000)]

    @model_validator(mode="after")
    def exact_membership(self) -> Self:
        if self.evidence_ids != tuple(sorted(set(self.evidence_ids))):
            raise ValueError("A context review requires distinct sorted evidence IDs.")
        if not self.note.strip() or "\x00" in self.note:
            raise ValueError("A numerical review requires a storable nonblank explanation.")
        if len(canonical_bytes(self)) > MAX_REVIEW_BYTES:
            raise ValueError("Numerical review exceeds its explicit byte budget.")
        return self


def require_reviewable(
    gate: StoredBoundNumericalGate, request: NumericalContextReviewRequest
) -> None:
    if request.gate_run_id != gate.result.id or request.evidence_ids != gate.result.evidence_ids:
        raise ValueError(
            "Review must retain the complete selected gate's exact evidence membership."
        )
    if request.decision == "CONFIRM_CONTEXT" and (
        gate.result.state != "READY_FOR_REVIEW"
        or not gate.result.evidence_ids
        or any(item.state != "PASS" for item in gate.result.checks)
    ):
        raise ValueError(
            "Failed or unresolved mandatory context checks cannot be reviewer-overridden."
        )


def review_identity(
    request: NumericalContextReviewRequest, input_sha256: str, configuration_sha256: str
) -> str:
    payload = canonical_bytes(request) + input_sha256.encode() + configuration_sha256.encode()
    return str(
        UUID(bytes=hashlib.sha256(b"bound-numerical-review:" + payload).digest()[:16], version=4)
    )


class ReviewedNumericalContext(ContractModel):
    schema_version: Literal["bound-numerical-review-1"] = "bound-numerical-review-1"
    id: CanonicalId
    request: NumericalContextReviewRequest
    gate_input_sha256: Sha256Hash
    gate_result_sha256: Sha256Hash
    configuration_sha256: Sha256Hash
    reviewed_by: CanonicalId
    auth_version: Annotated[int, Field(strict=True, ge=1)]
    acceptance_eligible: Literal[False] = False
    mandatory_m1_validation_complete: Literal[False] = False
    publishes_fact: Literal[False] = False

    @model_validator(mode="after")
    def immutable_identity(self) -> Self:
        if self.id != review_identity(
            self.request, self.gate_input_sha256, self.configuration_sha256
        ):
            raise ValueError(
                "Numerical review identity must retain exact inputs and configuration."
            )
        if len(canonical_bytes(self)) > MAX_REVIEW_BYTES:
            raise ValueError("Numerical review exceeds its explicit byte budget.")
        return self
