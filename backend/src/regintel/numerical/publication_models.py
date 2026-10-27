"""Versioned, non-authoritative input for the numerical publication adapter."""

import hashlib
from typing import Annotated, Literal, Self, get_args

from pydantic import Field, model_validator

from regintel.candidates.models import MetricDefinition
from regintel.candidates.records import stable_id
from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, Sha256Hash
from regintel.entities.models import canonical_bytes
from regintel.numerical.context_models import NumericalQuantityProposal
from regintel.numerical.evidence_binding_models import NumericalEvidenceBinding
from regintel.numerical.gate_models import BoundNumericalGateRun
from regintel.numerical.review_models import ReviewedNumericalContext
from regintel.validation.models import CheckCode, NumericMetricPolicy, ValidationCheck

MAX_PUBLICATION_INPUT_BYTES = 4 * 1024 * 1024


def publication_input_identity(gate_id: str, review_id: str, configuration: str) -> str:
    return stable_id(
        "numerical-publication-input:" + gate_id + ":" + review_id + ":" + configuration
    )


class NumericalPublicationInput(ContractModel):
    schema_version: Literal["numerical-publication-input-1"] = "numerical-publication-input-1"
    id: CanonicalId
    gate_run_id: CanonicalId
    gate_input_sha256: Sha256Hash
    gate_result_sha256: Sha256Hash
    configuration_sha256: Sha256Hash
    gate: BoundNumericalGateRun
    subject_entity_id: CanonicalId
    metric: MetricDefinition
    policy: NumericMetricPolicy
    quantity: NumericalQuantityProposal
    proof: NumericalEvidenceBinding
    context_review: ReviewedNumericalContext
    acceptance_eligible: Literal[False] = False
    mandatory_m1_validation_complete: Literal[False] = False
    publishes_fact: Literal[False] = False

    @model_validator(mode="after")
    def complete_reviewed_input(self) -> Self:
        review, quantity = self.context_review, self.quantity
        evidence = tuple(sorted({word.evidence.id for p in self.proof.phrases for word in p.words}))
        if (
            self.id
            != publication_input_identity(self.gate_run_id, review.id, self.configuration_sha256)
            or review.request.gate_run_id != self.gate_run_id
            or review.request.decision != "CONFIRM_CONTEXT"
            or review.request.evidence_ids != evidence
            or review.gate_input_sha256 != self.gate_input_sha256
            or review.gate_result_sha256 != self.gate_result_sha256
            or self.gate.id != self.gate_run_id
            or self.gate.input_sha256 != self.gate_input_sha256
            or hashlib.sha256(canonical_bytes(self.gate)).hexdigest() != self.gate_result_sha256
            or self.gate.state != "READY_FOR_REVIEW"
            or self.gate.quantity_proposal != quantity
            or self.gate.evidence_ids != evidence
            or self.gate.evidence_binding_id != self.proof.id
            or self.gate.context_record_id != self.proof.context_record_id
            or self.gate.parse_version_id != self.proof.parse_version_id
            or self.gate.source_sha256 != self.proof.source_sha256
            or self.metric.id != self.policy.metric_id
            or self.metric.kind != "numeric_fact"
            or self.policy.quantity_kind != "MONEY"
            or self.policy.period_kind != "DURATION"
            or quantity.currency not in {"INR", "USD"}
            or quantity.normalized_unit is None
            or quantity.basis == "UNKNOWN"
            or quantity.period.kind != "DURATION"
            or quantity.period.start_date is None
            or quantity.period.end_date is None
        ):
            raise ValueError(
                "Publication input requires complete monetary context and exact confirmed proof."
            )
        if len(canonical_bytes(self)) > MAX_PUBLICATION_INPUT_BYTES:
            raise ValueError("Numerical publication input exceeds its explicit proof byte budget.")
        return self


class NumericalPublicationPreparation(ContractModel):
    schema_version: Literal["numerical-publication-preparation-1"] = (
        "numerical-publication-preparation-1"
    )
    gate_run_id: CanonicalId
    gate_input_sha256: Sha256Hash
    gate_result_sha256: Sha256Hash
    configuration_sha256: Sha256Hash
    state: Literal["READY_FOR_ADAPTER", "BLOCKED"]
    checks: Annotated[
        tuple[ValidationCheck, ...], Field(strict=False, min_length=16, max_length=16)
    ]
    proposed_input: NumericalPublicationInput | None
    acceptance_eligible: Literal[False] = False
    mandatory_m1_validation_complete: Literal[False] = False
    publishes_fact: Literal[False] = False

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @model_validator(mode="after")
    def exact_preparation(self) -> Self:
        passed = all(check.state == "PASS" for check in self.checks)
        if tuple(check.code for check in self.checks) != get_args(CheckCode):
            raise ValueError(
                "Publication preparation retains all sixteen ordered mandatory categories."
            )
        if (self.state == "READY_FOR_ADAPTER") != passed or (
            self.proposed_input is not None
        ) != passed:
            raise ValueError(
                "Blocked preparation cannot expose a publishable input or hide a check."
            )
        if self.proposed_input is not None and any(
            getattr(self, key) != getattr(self.proposed_input, key)
            for key in (
                "gate_run_id",
                "gate_input_sha256",
                "gate_result_sha256",
                "configuration_sha256",
            )
        ):
            raise ValueError(
                "The prepared input must belong to the selected gate and configuration."
            )
        if len(canonical_bytes(self)) > MAX_PUBLICATION_INPUT_BYTES:
            raise ValueError("Numerical publication preparation exceeds its byte budget.")
        return self
