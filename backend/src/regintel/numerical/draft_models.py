"""Versioned unpublished numerical corpus input retaining complete native proof."""

import hashlib
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from regintel.candidates.records import stable_id
from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, SafeInteger, Sha256Hash
from regintel.entities.models import canonical_bytes
from regintel.numerical.acceptance_models import StoredNumericalAcceptance
from regintel.publication.models import CorpusManifest, FilingSnapshot

MAX_DRAFT_BYTES = 64 * 1024 * 1024


class NumericalPublicationDraftRequest(ContractModel):
    idempotency_key: CanonicalId
    parent_corpus_version_id: CanonicalId | None
    candidate_ids: Annotated[
        tuple[CanonicalId, ...], Field(strict=False, min_length=1, max_length=20)
    ]

    @model_validator(mode="after")
    def explicit_selection(self) -> Self:
        if self.candidate_ids != tuple(sorted(set(self.candidate_ids))):
            raise ValueError("Draft candidate IDs must be distinct and canonically ordered.")
        return self


def numerical_observation_identity(candidate_id: str) -> str:
    return stable_id("numerical-observation:" + candidate_id)


def numerical_draft_identity(
    request: NumericalPublicationDraftRequest, configuration: str, actor: str, auth_version: int
) -> str:
    return stable_id(
        "numerical-publication-draft:"
        + hashlib.sha256(canonical_bytes(request)).hexdigest()
        + ":"
        + configuration
        + ":"
        + actor
        + ":"
        + str(auth_version)
    )


class NumericalPublicationEntry(ContractModel):
    """Proposed observation identity, not a published/committed observation."""

    id: CanonicalId
    acceptance: StoredNumericalAcceptance
    filing: FilingSnapshot

    @model_validator(mode="after")
    def complete_accepted_source(self) -> Self:
        accepted = self.acceptance.record
        prepared = self.acceptance.candidate.preparation.proposed_input
        assert prepared is not None
        proof = prepared.proof
        if (
            self.id != numerical_observation_identity(accepted.request.candidate_id)
            or accepted.state != "ACCEPTED_UNPUBLISHED"
            or not accepted.mandatory_m1_validation_complete
            or (
                self.filing.filing_id,
                self.filing.filing_version_id,
                self.filing.parse_version_id,
                self.filing.source_sha256,
            )
            != (
                proof.filing_id,
                proof.filing_version_id,
                proof.parse_version_id,
                proof.source_sha256,
            )
            or self.filing.document_type in {"ADDENDUM", "CORRIGENDUM"}
        ):
            raise ValueError("A draft entry requires its accepted, supported original filing.")
        return self


class NumericalPublicationDraft(ContractModel):
    schema_version: Literal["numerical-publication-draft-1"] = "numerical-publication-draft-1"
    id: CanonicalId
    request: NumericalPublicationDraftRequest
    configuration_sha256: Sha256Hash
    prepared_by: CanonicalId
    auth_version: Annotated[SafeInteger, Field(ge=1)]
    parent: CorpusManifest | None
    entries: Annotated[
        tuple[NumericalPublicationEntry, ...], Field(strict=False, min_length=1, max_length=20)
    ]
    state: Literal["UNPUBLISHED_DRAFT"] = "UNPUBLISHED_DRAFT"
    publishes_fact: Literal[False] = False
    corpus_committed: Literal[False] = False

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @model_validator(mode="after")
    def complete_draft(self) -> Self:
        candidates = tuple(entry.acceptance.record.request.candidate_id for entry in self.entries)
        old = self.parent.observations if self.parent is not None else ()
        ids = {entry.id for entry in self.entries}
        if (
            self.id
            != numerical_draft_identity(
                self.request, self.configuration_sha256, self.prepared_by, self.auth_version
            )
            or self.request.parent_corpus_version_id != (self.parent.id if self.parent else None)
            or candidates != self.request.candidate_ids
            or len(ids) != len(self.entries)
            or ids.intersection(item.id for item in old)
            or set(candidates).intersection(item.candidate_id for item in old)
        ):
            raise ValueError(
                "A draft must retain its selected parent, candidates and stable identity."
            )
        filings = (
            {item.filing_version_id: item for item in self.parent.filings} if self.parent else {}
        )
        for entry in self.entries:
            if (
                entry.filing.filing_version_id in filings
                and filings[entry.filing.filing_version_id] != entry.filing
            ):
                raise ValueError("A draft cannot alter an immutable inherited filing snapshot.")
            filings[entry.filing.filing_version_id] = entry.filing
        if len(canonical_bytes(self)) > MAX_DRAFT_BYTES:
            raise ValueError("The complete publication draft exceeds its explicit byte budget.")
        return self
