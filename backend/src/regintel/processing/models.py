"""Typed workflow bookkeeping, frozen inputs and immutable result checkpoints."""

import hashlib
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from regintel.candidates.models import ExtractionConfiguration
from regintel.contracts.models import ContractModel, TextEvidence
from regintel.contracts.primitives import CanonicalId, SafeInteger, Sha256Hash
from regintel.entities.models import RegistrySnapshot, ResolverConfiguration, canonical_bytes
from regintel.validation.models import ValidationConfiguration

type Stage = Literal["ENTITY", "CANDIDATE", "VALIDATION"]
type FailureCode = Literal[
    "CONFIGURATION_CHANGED",
    "AUTHORIZATION_CHANGED",
    "INPUT_CHANGED",
    "SOURCE_INVALID",
    "PROCESSING_FAILED",
]
STAGES: tuple[Stage, ...] = ("ENTITY", "CANDIDATE", "VALIDATION")


class ProcessingRequest(ContractModel):
    idempotency_key: CanonicalId
    parse_version_id: CanonicalId
    metric_ids: Annotated[tuple[CanonicalId, ...], Field(strict=False, max_length=100)]

    @model_validator(mode="after")
    def distinct_metrics(self) -> Self:
        if len(set(self.metric_ids)) != len(self.metric_ids):
            raise ValueError("Processing metrics must be distinct.")
        if tuple(sorted(self.metric_ids)) != self.metric_ids:
            raise ValueError("Processing metric IDs must be supplied in canonical sorted order.")
        return self


class ProcessingConfiguration(ContractModel):
    version: Literal["1.0.0"] = "1.0.0"
    code_sha256: Sha256Hash
    entity: ResolverConfiguration
    candidate: ExtractionConfiguration
    validation: ValidationConfiguration

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


class EntityStageInput(ContractModel):
    parse_version_id: CanonicalId
    artifact_sha256: Sha256Hash
    evidence: Annotated[
        tuple[TextEvidence, ...], Field(strict=False, min_length=1, max_length=10000)
    ]
    registry: RegistrySnapshot
    configuration: ResolverConfiguration

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @model_validator(mode="after")
    def one_source(self) -> Self:
        if len({record.id for record in self.evidence}) != len(self.evidence) or any(
            record.source.parse_version_id != self.parse_version_id for record in self.evidence
        ):
            raise ValueError("A stage requires distinct exact evidence from its sealed parse.")
        if sum(len(record.span.quote) for record in self.evidence) > 2000000:
            raise ValueError("The stage exceeds its complete source-text bound.")
        return self


class StageCheckpoint(ContractModel):
    stage: Stage
    output_id: CanonicalId
    input_sha256: Sha256Hash
    configuration_sha256: Sha256Hash
    generation: Annotated[SafeInteger, Field(ge=1)]


class ProcessingEvent(ContractModel):
    sequence: Annotated[SafeInteger, Field(ge=1)]
    generation: Annotated[SafeInteger, Field(ge=1, le=10000)]
    kind: Literal["STARTED", "INPUT_FROZEN", "CHECKPOINT", "RETRY", "FAILED", "COMPLETED"]
    stage: Stage | None
    failure_code: FailureCode | Literal["STORAGE_UNAVAILABLE"] | None

    @model_validator(mode="after")
    def coherent_event(self) -> Self:
        if (self.kind in {"INPUT_FROZEN", "CHECKPOINT"}) != (self.stage is not None):
            raise ValueError("Only a stage event identifies a stage.")
        if self.kind == "RETRY":
            if self.failure_code != "STORAGE_UNAVAILABLE":
                raise ValueError("Retry events identify temporary storage failure.")
        elif (self.kind == "FAILED") != (self.failure_code is not None):
            raise ValueError("Only failure or retry events carry a failure code.")
        elif self.failure_code == "STORAGE_UNAVAILABLE":
            raise ValueError("Storage failure is retryable.")
        return self


class ProcessingJob(ContractModel):
    id: CanonicalId
    request: ProcessingRequest
    configuration: ProcessingConfiguration
    submitted_by: CanonicalId
    submitted_auth_version: Annotated[SafeInteger, Field(ge=1)]
    state: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED"]
    generation: SafeInteger
    failure_code: FailureCode | None
    checkpoints: Annotated[tuple[StageCheckpoint, ...], Field(strict=False, max_length=3)]
    events: Annotated[tuple[ProcessingEvent, ...], Field(strict=False, max_length=10000)]

    @model_validator(mode="after")
    def coherent_progress(self) -> Self:
        stages = tuple(item.stage for item in self.checkpoints)
        if stages != STAGES[: len(stages)] or any(
            item.generation > self.generation for item in self.checkpoints
        ):
            raise ValueError("Checkpoints must complete a contiguous ordered stage prefix.")
        if (self.state == "FAILED") != (self.failure_code is not None):
            raise ValueError("Only a failed workflow has a terminal failure code.")
        if (self.state == "QUEUED") != (self.generation == 0):
            raise ValueError("A workflow starts queued without attempts.")
        if self.state == "SUCCEEDED" and stages != STAGES:
            raise ValueError("Processing success requires all three stage checkpoints.")
        if tuple(event.sequence for event in self.events) != tuple(range(1, len(self.events) + 1)):
            raise ValueError("Workflow events must retain their contiguous audit sequence.")
        if any(event.generation > self.generation for event in self.events):
            raise ValueError("An event cannot describe a future attempt.")
        return self
