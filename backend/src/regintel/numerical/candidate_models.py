"""Immutable numerical candidate proposals; never acceptance or corpus state."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from regintel.candidates.records import stable_id
from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, SafeInteger, Sha256Hash
from regintel.entities.models import canonical_bytes
from regintel.numerical.publication_models import NumericalPublicationPreparation

MAX_CANDIDATE_RECORD_BYTES = 65536


def numerical_candidate_identity(prepared_input_id: str) -> str:
    return stable_id("numerical-candidate:" + prepared_input_id)


class NumericalCandidateRequest(ContractModel):
    gate_run_id: CanonicalId
    prepared_input_id: CanonicalId


class NumericalCandidateRecord(ContractModel):
    schema_version: Literal["numerical-candidate-1"] = "numerical-candidate-1"
    id: CanonicalId
    request: NumericalCandidateRequest
    preparation_sha256: Sha256Hash
    storage_configuration_sha256: Sha256Hash
    submitted_by: CanonicalId
    auth_version: Annotated[SafeInteger, Field(ge=1)]
    state: Literal["CANDIDATE"] = "CANDIDATE"
    acceptance_eligible: Literal[False] = False
    mandatory_m1_validation_complete: Literal[False] = False
    publishes_fact: Literal[False] = False

    @model_validator(mode="after")
    def proposal_identity(self) -> Self:
        if self.id != numerical_candidate_identity(self.request.prepared_input_id):
            raise ValueError(
                "A numerical candidate must retain its backend prepared-input identity."
            )
        if len(canonical_bytes(self)) > MAX_CANDIDATE_RECORD_BYTES:
            raise ValueError("Numerical candidate metadata exceeds its byte budget.")
        return self


class StoredNumericalCandidate(ContractModel):
    record: NumericalCandidateRecord
    preparation: NumericalPublicationPreparation

    @model_validator(mode="after")
    def complete_prepared_candidate(self) -> Self:
        prepared = self.preparation.proposed_input
        if (
            self.preparation.state != "READY_FOR_ADAPTER"
            or prepared is None
            or self.record.request.gate_run_id != self.preparation.gate_run_id
            or self.record.request.prepared_input_id != prepared.id
            or self.record.preparation_sha256 != self.preparation.sha256
        ):
            raise ValueError("A candidate requires its complete selected ready preparation.")
        return self
