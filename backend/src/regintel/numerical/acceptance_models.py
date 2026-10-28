"""Explicit audited numerical decisions; accepted proposals remain unpublished."""

import hashlib
from typing import Annotated, Literal, Self, get_args

from pydantic import Field, model_validator

from regintel.candidates.records import stable_id
from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, RawText, SafeInteger, Sha256Hash
from regintel.entities.models import canonical_bytes
from regintel.numerical.candidate_models import StoredNumericalCandidate
from regintel.validation.models import CheckCode, ValidationCheck

MAX_ACCEPTANCE_BYTES = 65536


def numerical_acceptance_identity(candidate_id: str) -> str:
    return stable_id("numerical-acceptance:" + candidate_id)


class NumericalAcceptanceRequest(ContractModel):
    candidate_id: CanonicalId
    decision: Literal["ACCEPT", "REJECT"]
    evidence_ids: Annotated[tuple[CanonicalId, ...], Field(strict=False, max_length=1024)]
    note: Annotated[RawText, Field(min_length=1, max_length=2000)]

    @model_validator(mode="after")
    def explicit_membership(self) -> Self:
        if not self.evidence_ids or self.evidence_ids != tuple(sorted(set(self.evidence_ids))):
            raise ValueError("A decision retains the complete distinct sorted evidence IDs.")
        if not self.note.strip() or "\x00" in self.note:
            raise ValueError("A numerical decision requires a storable nonblank explanation.")
        return self


class NumericalAcceptanceRecord(ContractModel):
    schema_version: Literal["numerical-acceptance-1"] = "numerical-acceptance-1"
    id: CanonicalId
    request: NumericalAcceptanceRequest
    candidate_record_sha256: Sha256Hash
    candidate_preparation_sha256: Sha256Hash
    configuration_sha256: Sha256Hash
    reviewed_by: CanonicalId
    auth_version: Annotated[SafeInteger, Field(ge=1)]
    checks: Annotated[tuple[ValidationCheck, ...], Field(strict=False, max_length=16)]
    state: Literal["ACCEPTED_UNPUBLISHED", "REJECTED"]
    mandatory_m1_validation_complete: bool
    publishes_fact: Literal[False] = False
    published_corpus_version_id: None = None

    @model_validator(mode="after")
    def complete_decision(self) -> Self:
        accepted = self.request.decision == "ACCEPT"
        if (
            self.id != numerical_acceptance_identity(self.request.candidate_id)
            or self.state != ("ACCEPTED_UNPUBLISHED" if accepted else "REJECTED")
            or self.mandatory_m1_validation_complete != accepted
            or (
                accepted
                and (
                    tuple(check.code for check in self.checks) != get_args(CheckCode)
                    or any(check.state != "PASS" for check in self.checks)
                )
            )
            or (not accepted and self.checks)
        ):
            raise ValueError("Acceptance requires every mandatory check; rejection claims none.")
        if len(canonical_bytes(self)) > MAX_ACCEPTANCE_BYTES:
            raise ValueError("Numerical decision exceeds its explicit byte budget.")
        return self


class StoredNumericalAcceptance(ContractModel):
    record: NumericalAcceptanceRecord
    candidate: StoredNumericalCandidate

    @model_validator(mode="after")
    def selected_candidate(self) -> Self:
        proposed = self.candidate.preparation.proposed_input
        assert proposed is not None
        if (
            self.record.request.candidate_id != self.candidate.record.id
            or self.record.request.evidence_ids != proposed.gate.evidence_ids
            or self.record.candidate_record_sha256
            != hashlib.sha256(canonical_bytes(self.candidate.record)).hexdigest()
            or self.record.candidate_preparation_sha256 != self.candidate.preparation.sha256
            or (
                self.record.request.decision == "ACCEPT"
                and self.record.checks != self.candidate.preparation.checks
            )
        ):
            raise ValueError("A decision must retain its selected exact candidate and checks.")
        return self
