"""Versioned bound numerical gate records, separate from legacy M1 acceptance."""

import hashlib
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, TypeAdapter, model_validator

from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, RawText, Sha256Hash
from regintel.entities.models import canonical_bytes
from regintel.numerical.applicability_models import ReviewedNumericalApplicability
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


class ApplicabilityGateInput(BoundGateInput):
    """A new gate retains the unresolved result and its exact applicability decision."""

    schema_version: Literal["bound-numerical-applicability-input-1"] = (
        "bound-numerical-applicability-input-1"
    )
    base_result: BoundNumericalGateRun
    base_submitted_by: CanonicalId
    base_auth_version: Annotated[int, Field(strict=True, ge=1)]
    applicability: ReviewedNumericalApplicability

    def base_input(self) -> BoundGateInput:
        return BoundGateInput(
            context=self.context, current_context=self.current_context, binding=self.binding
        )

    def base_gate(self) -> "StoredBoundNumericalGate":
        return StoredBoundNumericalGate(
            source_input=self.base_input(),
            result=self.base_result,
            submitted_by=self.base_submitted_by,
            auth_version=self.base_auth_version,
        )

    @model_validator(mode="after")
    def exact_applicability_source(self) -> Self:
        base, request = self.base_result, self.applicability.request
        if (
            base.state != "REVIEW_REQUIRED"
            or hashlib.sha256(canonical_bytes(self.base_input())).hexdigest() != base.input_sha256
            or base.context_record_id != self.context.id
            or base.parse_version_id != self.binding.parse_version_id
            or base.evidence_binding_id != self.binding.id
            or base.source_sha256 != self.context.source_sha256
            or request.gate_run_id != base.id
            or request.gate_input_sha256 != base.input_sha256
            or request.gate_result_sha256 != hashlib.sha256(canonical_bytes(base)).hexdigest()
            or request.binding_id != self.binding.id
        ):
            raise ValueError("Applicability gate must retain the exact unresolved base gate.")
        return self


GateInput = Annotated[ApplicabilityGateInput | BoundGateInput, Field(union_mode="left_to_right")]
_GATE_INPUT_ADAPTER: TypeAdapter[ApplicabilityGateInput | BoundGateInput] = TypeAdapter(GateInput)


def parse_gate_input_json(body: bytes) -> ApplicabilityGateInput | BoundGateInput:
    """Read both historical packets and the explicit applicability input version."""
    return _GATE_INPUT_ADAPTER.validate_json(body)


class StoredBoundNumericalGate(ContractModel):
    source_input: GateInput
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
