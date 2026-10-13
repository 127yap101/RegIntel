"""Strict entity-resolution contracts; entity mapping is not fact acceptance."""

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, Label, RawText, SafeInteger, Sha256Hash

EntityKind = Literal["COMPANY", "PERSON", "ORGANIZATION"]
IdentifierKind = Literal["CIN", "ISIN"]
ResolutionMethod = Literal["EXACT_CIN", "EXACT_ISIN", "EXACT_ALIAS", "NORMALIZED_NAME", "FUZZY"]
EntityName = Annotated[Label, Field(max_length=256)]
ReviewNote = Annotated[RawText, Field(min_length=1, max_length=2000)]


def canonical_bytes(value: ContractModel) -> bytes:
    return json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


class EvidenceAnchor(ContractModel):
    evidence_id: CanonicalId
    start: SafeInteger
    end: SafeInteger
    quote: Annotated[RawText, Field(min_length=1, max_length=256)]

    @model_validator(mode="after")
    def exact_length(self) -> Self:
        if self.end <= self.start or self.end - self.start != len(self.quote):
            raise ValueError("Entity support requires an exact Unicode subspan.")
        return self


class ApprovedAlias(ContractModel):
    name: EntityName
    support: EvidenceAnchor

    @model_validator(mode="after")
    def exact_name(self) -> Self:
        if self.name != self.support.quote or not any(char.isalnum() for char in self.name):
            raise ValueError("An approved name must exactly match its source span.")
        return self


class ApprovedIdentifier(ContractModel):
    kind: IdentifierKind
    value: Annotated[Label, Field(max_length=21)]
    support: EvidenceAnchor

    @model_validator(mode="after")
    def exact_identifier(self) -> Self:
        # Import the lightweight validator without importing the NLP runtime.
        from regintel.entities.identifiers import valid_identifier

        if self.value != self.support.quote or not valid_identifier(self.kind, self.value):
            raise ValueError("Identifier support and syntax/check digit must be valid.")
        return self


class EntityRegistration(ContractModel):
    id: CanonicalId
    kind: EntityKind
    legal_name: EntityName
    legal_name_support: EvidenceAnchor
    aliases: Annotated[tuple[ApprovedAlias, ...], Field(strict=False, max_length=100)] = ()
    identifiers: Annotated[tuple[ApprovedIdentifier, ...], Field(strict=False, max_length=100)] = ()
    review_note: ReviewNote

    @model_validator(mode="after")
    def validate_support(self) -> Self:
        if self.legal_name != self.legal_name_support.quote or not any(
            char.isalnum() for char in self.legal_name
        ):
            raise ValueError("The legal name must exactly match its supporting span.")
        names = [self.legal_name, *(alias.name for alias in self.aliases)]
        keys = [(identifier.kind, identifier.value) for identifier in self.identifiers]
        if len(set(names)) != len(names) or len(set(keys)) != len(keys):
            raise ValueError("Registry terms must be unique within an entity.")
        if self.kind != "COMPANY" and any(x.kind == "CIN" for x in self.identifiers):
            raise ValueError("CIN identifies a company.")
        return self


class RegistrySnapshot(ContractModel):
    revision: SafeInteger
    sha256: Sha256Hash
    entities: Annotated[tuple[EntityRegistration, ...], Field(strict=False, max_length=10000)]

    @model_validator(mode="after")
    def validate_fingerprint(self) -> Self:
        ids = [entity.id for entity in self.entities]
        if self.revision != len(ids) or ids != sorted(set(ids)):
            raise ValueError(
                "A registry snapshot must have sorted unique entities and exact revision."
            )
        contents = json.dumps(
            {"entities": [entity.model_dump(mode="json") for entity in self.entities]},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if hashlib.sha256(contents).hexdigest() != self.sha256:
            raise ValueError("Registry fingerprint must identify the supplied approval snapshot.")
        return self


class ResolutionProposal(ContractModel):
    entity_id: CanonicalId
    method: ResolutionMethod
    score: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)] | None

    @model_validator(mode="after")
    def validate_score(self) -> Self:
        if (self.method == "FUZZY") != (self.score is not None):
            raise ValueError("Only fuzzy proposals carry similarity scores.")
        return self


class MentionResolution(ContractModel):
    state: Literal["RESOLVED", "REVIEW", "UNRESOLVED"]
    entity_id: CanonicalId | None
    method: ResolutionMethod | None
    reason: Label
    proposals: Annotated[tuple[ResolutionProposal, ...], Field(strict=False, max_length=100)]

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        ids = [proposal.entity_id for proposal in self.proposals]
        if len(set(ids)) != len(ids):
            raise ValueError("Resolution proposals must reference distinct entities.")
        if self.state == "RESOLVED":
            if self.entity_id is None or self.method is None or self.method == "FUZZY":
                raise ValueError("Fuzzy similarity cannot resolve a canonical entity.")
            if ids != [self.entity_id] or self.proposals[0].method != self.method:
                raise ValueError("Resolved identity must match the sole exact proposal.")
        elif self.entity_id is not None or self.method is not None:
            raise ValueError("Unresolved/review mentions have no authoritative identity.")
        if self.state == "UNRESOLVED" and self.proposals:
            raise ValueError("Unresolved mentions must not have matching proposals.")
        return self


class EntityMention(ContractModel):
    id: CanonicalId
    kind: Literal["NAME", "CIN", "ISIN"]
    support: EvidenceAnchor
    resolution: MentionResolution


class ResolverConfiguration(ContractModel):
    version: Literal["1.0.0"] = "1.0.0"
    spacy_version: Label
    rapidfuzz_version: Label
    code_sha256: Sha256Hash
    fuzzy_threshold: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)] = 85.0
    max_proposals: Annotated[int, Field(ge=1, le=100)] = 5

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


class EntityRun(ContractModel):
    id: CanonicalId
    parse_version_id: CanonicalId
    artifact_sha256: Sha256Hash
    registry_revision: SafeInteger
    registry_sha256: Sha256Hash
    configuration: ResolverConfiguration
    evidence_ids: Annotated[
        tuple[CanonicalId, ...], Field(strict=False, min_length=1, max_length=10000)
    ]
    mentions: Annotated[tuple[EntityMention, ...], Field(strict=False, max_length=25000)]

    @model_validator(mode="after")
    def validate_membership(self) -> Self:
        evidence = set(self.evidence_ids)
        ids = [mention.id for mention in self.mentions]
        if len(evidence) != len(self.evidence_ids) or len(set(ids)) != len(ids):
            raise ValueError("Run evidence and mention IDs must be unique.")
        if any(mention.support.evidence_id not in evidence for mention in self.mentions):
            raise ValueError("Mentions must belong to the supplied evidence collection.")
        return self


class EntityReview(ContractModel):
    id: CanonicalId
    run_id: CanonicalId
    mention_id: CanonicalId
    decision: Literal["RESOLVE", "REJECT"]
    entity_id: CanonicalId | None
    support_evidence_ids: Annotated[
        tuple[CanonicalId, ...], Field(strict=False, min_length=1, max_length=16)
    ]
    review_note: ReviewNote

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if (self.decision == "RESOLVE") != (self.entity_id is not None):
            raise ValueError("Only a resolving review selects an existing entity.")
        if len(set(self.support_evidence_ids)) != len(self.support_evidence_ids):
            raise ValueError("Review evidence IDs must be unique.")
        return self
