"""Versioned bound numerical gate records, separate from legacy M1 acceptance."""

import hashlib
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, RawText, Sha256Hash
from regintel.entities.models import canonical_bytes
from regintel.numerical.context_models import NumericalContextInput, NumericalQuantityProposal
from regintel.numerical.context_records import NumericalContextRecord
from regintel.numerical.evidence_binding_models import NumericalEvidenceBinding

MAX_GATE_INPUT_BYTES = 40 * 1024 * 1024
MAX_GATE_RESULT_BYTES = 256 * 1024
GATE_CODES = (
    "SOURCE",
    "EXACT_WORDS",
    "TABLE",
    "ISSUER",
    "METRIC",
    "VALUE",
    "UNIT",
    "CURRENCY",
    "PERIOD",
    "BASIS",
    "CONTEXT_SCOPE",
    "FRESH_CONTEXT",
    "BOUND_EVIDENCE",
    "SOURCE_LANGUAGE",
)
GateCode = Literal[
    "SOURCE",
    "EXACT_WORDS",
    "TABLE",
    "ISSUER",
    "METRIC",
    "VALUE",
    "UNIT",
    "CURRENCY",
    "PERIOD",
    "BASIS",
    "CONTEXT_SCOPE",
    "FRESH_CONTEXT",
    "BOUND_EVIDENCE",
    "SOURCE_LANGUAGE",
]


def gate_identity(input_sha256: str, configuration_sha256: str) -> str:
    body = ("bound-numerical-gate:" + input_sha256 + ":" + configuration_sha256).encode("ascii")
    return str(UUID(bytes=hashlib.sha256(body).digest()[:16], version=4))


class BoundGateInput(ContractModel):
    context: NumericalContextRecord
    current_context: NumericalContextInput
    binding: NumericalEvidenceBinding

    @model_validator(mode="after")
    def bounded_input(self) -> Self:
        if len(canonical_bytes(self)) > MAX_GATE_INPUT_BYTES:
            raise ValueError("Bound numerical gate input exceeds its byte budget.")
        return self


class BoundGateCheck(ContractModel):
    code: GateCode
    state: Literal["PASS", "REVIEW", "FAIL"]
    message: Annotated[RawText, Field(min_length=1, max_length=500)]


class BoundNumericalGateRun(ContractModel):
    schema_version: Literal["bound-numerical-gate-1"] = "bound-numerical-gate-1"
    id: CanonicalId
    context_record_id: CanonicalId
    parse_version_id: CanonicalId
    evidence_binding_id: CanonicalId
    source_sha256: Sha256Hash
    input_sha256: Sha256Hash
    configuration_sha256: Sha256Hash
    state: Literal["READY_FOR_REVIEW", "REVIEW_REQUIRED", "QUARANTINED"]
    checks: Annotated[tuple[BoundGateCheck, ...], Field(strict=False, min_length=14, max_length=14)]
    quantity_proposal: NumericalQuantityProposal | None
    evidence_ids: Annotated[tuple[CanonicalId, ...], Field(strict=False, max_length=1024)]
    review_required: Literal[True] = True
    acceptance_eligible: Literal[False] = False
    mandatory_m1_validation_complete: Literal[False] = False

    @model_validator(mode="after")
    def result_identity(self) -> Self:
        if tuple(check.code for check in self.checks) != GATE_CODES:
            raise ValueError("Bound numerical validation requires every ordered gate.")
        expected = (
            "QUARANTINED"
            if any(c.state == "FAIL" for c in self.checks)
            else "REVIEW_REQUIRED"
            if any(c.state == "REVIEW" for c in self.checks)
            else "READY_FOR_REVIEW"
        )
        if self.state != expected or (
            self.state == "QUARANTINED" and self.quantity_proposal is not None
        ):
            raise ValueError("Numerical gate status cannot conceal failures or unresolved context.")
        if self.state == "READY_FOR_REVIEW" and self.quantity_proposal is None:
            raise ValueError("A supported numerical review needs its exact proposed quantity.")
        if self.evidence_ids != tuple(sorted(set(self.evidence_ids))):
            raise ValueError("Bound source IDs must retain distinct canonical membership.")
        if self.id != gate_identity(self.input_sha256, self.configuration_sha256):
            raise ValueError(
                "Numerical gate identity must bind the exact inputs and configuration."
            )
        if len(canonical_bytes(self)) > MAX_GATE_RESULT_BYTES:
            raise ValueError("Numerical gate result exceeds its byte budget.")
        return self


class StoredBoundNumericalGate(ContractModel):
    source_input: BoundGateInput
    result: BoundNumericalGateRun
    submitted_by: CanonicalId
    auth_version: Annotated[int, Field(strict=True, ge=1)]

    @model_validator(mode="after")
    def exact_input(self) -> Self:
        packet, result = self.source_input, self.result
        if (
            hashlib.sha256(canonical_bytes(packet)).hexdigest() != result.input_sha256
            or packet.context.id != result.context_record_id
            or packet.binding.id != result.evidence_binding_id
            or packet.binding.parse_version_id != result.parse_version_id
            or packet.context.source_sha256 != result.source_sha256
        ):
            raise ValueError("Stored numerical gate must retain its exact input membership.")
        return self
