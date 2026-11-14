"""Exact, versioned applicability attestations for retained numerical support."""

import hashlib
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, RawText, SafeInteger, Sha256Hash
from regintel.entities.models import canonical_bytes
from regintel.numerical.evidence_binding_models import PhraseRole

MAX_APPLICABILITY_BYTES = 256 * 1024
ApplicabilityKind = Literal["CROSS_PAGE", "BASIS", "QUALIFIED_DEFAULT"]


class NumericalApplicabilityAssertion(ContractModel):
    kind: ApplicabilityKind
    role: PhraseRole
    ordinal: Annotated[SafeInteger, Field(le=3)]
    evidence_ids: Annotated[
        tuple[CanonicalId, ...], Field(strict=False, min_length=1, max_length=256)
    ]

    @model_validator(mode="after")
    def distinct_words(self) -> Self:
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("An applicability assertion requires distinct ordered source words.")
        return self


class _ApplicabilitySelection(ContractModel):
    gate_run_id: CanonicalId
    gate_input_sha256: Sha256Hash
    gate_result_sha256: Sha256Hash
    binding_id: CanonicalId
    value_cell_id: CanonicalId
    row_cell_id: CanonicalId
    period_cell_id: CanonicalId
    assertions: Annotated[
        tuple[NumericalApplicabilityAssertion, ...], Field(strict=False, max_length=45)
    ]
    reviewed_page_indices: Annotated[
        tuple[SafeInteger, ...], Field(strict=False, min_length=1, max_length=4)
    ]

    @model_validator(mode="after")
    def bounded_membership(self) -> Self:
        keys = [(item.role, item.ordinal, item.kind) for item in self.assertions]
        if len(set(keys)) != len(keys):
            raise ValueError("Applicability assertions must be distinct.")
        if self.reviewed_page_indices != tuple(sorted(set(self.reviewed_page_indices))):
            raise ValueError("Reviewed source pages must be distinct and sorted.")
        if len(canonical_bytes(self)) > MAX_APPLICABILITY_BYTES:
            raise ValueError("Applicability selection exceeds its explicit byte budget.")
        return self


class NumericalApplicabilityRequirements(_ApplicabilitySelection):
    schema_version: Literal["numerical-applicability-requirements-1"] = (
        "numerical-applicability-requirements-1"
    )
    eligible: bool
    blockers: Annotated[
        tuple[Annotated[RawText, Field(min_length=1, max_length=500)], ...],
        Field(strict=False, max_length=24),
    ]

    @model_validator(mode="after")
    def eligibility_matches_requirements(self) -> Self:
        if self.eligible != (not self.blockers and bool(self.assertions)):
            raise ValueError("Applicability eligibility must retain all blockers and assertions.")
        return self


class NumericalApplicabilityRequest(_ApplicabilitySelection):
    schema_version: Literal["numerical-applicability-request-1"] = (
        "numerical-applicability-request-1"
    )
    decision: Literal["APPLIES"] = "APPLIES"
    assertions: Annotated[
        tuple[NumericalApplicabilityAssertion, ...],
        Field(strict=False, min_length=1, max_length=45),
    ]
    note: Annotated[RawText, Field(min_length=1, max_length=2000)]

    @model_validator(mode="after")
    def meaningful_note(self) -> Self:
        if not self.note.strip() or "\x00" in self.note:
            raise ValueError("Applicability review requires a storable nonblank explanation.")
        return self


def applicability_identity(
    request: NumericalApplicabilityRequest, configuration_sha256: str
) -> str:
    body = canonical_bytes(request) + configuration_sha256.encode("ascii")
    digest = hashlib.sha256(b"numerical-applicability-review:" + body).digest()
    return str(UUID(bytes=digest[:16], version=4))


class ReviewedNumericalApplicability(ContractModel):
    schema_version: Literal["numerical-applicability-review-1"] = "numerical-applicability-review-1"
    id: CanonicalId
    request: NumericalApplicabilityRequest
    configuration_sha256: Sha256Hash
    reviewed_by: CanonicalId
    auth_version: Annotated[int, Field(strict=True, ge=1)]
    acceptance_eligible: Literal[False] = False
    mandatory_m1_validation_complete: Literal[False] = False
    publishes_fact: Literal[False] = False

    @model_validator(mode="after")
    def immutable_identity(self) -> Self:
        if self.id != applicability_identity(self.request, self.configuration_sha256):
            raise ValueError(
                "Applicability review identity must retain its exact request/configuration."
            )
        if len(canonical_bytes(self)) > MAX_APPLICABILITY_BYTES:
            raise ValueError("Applicability review exceeds its explicit byte budget.")
        return self
