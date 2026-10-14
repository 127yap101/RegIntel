"""Strict immutable contracts for prepublication validation and review."""

import hashlib
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from regintel.candidates.models import ExtractionInput, SourceSpan
from regintel.candidates.records import CandidateRun, stable_id
from regintel.contracts.models import ContractModel, QuantitativeValue
from regintel.contracts.primitives import CanonicalId, RawText, Sha256Hash
from regintel.entities.models import EntityReview, canonical_bytes

UnitLabel = Literal[
    "INR",
    "USD",
    "rupees",
    "crore",
    "crores",
    "lakh",
    "lakhs",
    "million",
    "millions",
    "billion",
    "billions",
    "shares",
    "MW",
    "GW",
    "%",
]
CheckCode = Literal[
    "SOURCE",
    "ENTITY",
    "TABLE_CONTEXT",
    "SOURCE_SCOPE",
    "ATTRIBUTION",
    "DIRECTION",
    "METRIC",
    "VALUE",
    "UNIT",
    "CURRENCY",
    "PERIOD",
    "BASIS",
    "DENOMINATOR",
    "STAKE_KIND",
    "OWNERSHIP_DATE",
    "EXTRACTIVE_REVIEW",
]


class NumericMetricPolicy(ContractModel):
    """Reviewed metric meaning, independent of frozen extraction cues."""

    id: CanonicalId
    metric_id: CanonicalId
    quantity_kind: Literal["MONEY", "COUNT", "POWER", "PERCENTAGE"]
    period_kind: Literal["INSTANT", "DURATION"]
    allowed_unit_labels: Annotated[
        tuple[UnitLabel, ...], Field(strict=False, min_length=1, max_length=16)
    ]
    required_reporting_basis: bool = True
    review_note: Annotated[RawText, Field(min_length=1, max_length=2000)]

    @model_validator(mode="after")
    def valid_units(self) -> Self:
        families: dict[str, set[str]] = {
            "MONEY": {
                "INR",
                "USD",
                "rupees",
                "crore",
                "crores",
                "lakh",
                "lakhs",
                "million",
                "millions",
                "billion",
                "billions",
            },
            "COUNT": {"shares"},
            "POWER": {"MW", "GW"},
            "PERCENTAGE": {"%"},
        }
        if len(set(self.allowed_unit_labels)) != len(self.allowed_unit_labels) or not set(
            self.allowed_unit_labels
        ).issubset(families[self.quantity_kind]):
            raise ValueError("Metric unit policy must be distinct and match its quantity kind.")
        if not self.review_note.strip() or "\x00" in self.review_note:
            raise ValueError("Metric policies require a storable review explanation.")
        return self


class ValidationCheck(ContractModel):
    code: CheckCode
    state: Literal["PASS", "REVIEW", "FAIL"]
    message: Annotated[RawText, Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def storable_message(self) -> Self:
        if "\x00" in self.message:
            raise ValueError("Validation messages must be storable Unicode.")
        return self


class ContextWitness(ContractModel):
    role: Literal[
        "VALUE",
        "UNIT",
        "CURRENCY",
        "PERIOD",
        "BASIS",
        "DENOMINATOR",
        "STAKE_KIND",
        "OWNERSHIP_DATE",
    ]
    span: SourceSpan


class ValidationConfiguration(ContractModel):
    version: Literal["1.0.0"] = "1.0.0"
    code_sha256: Sha256Hash

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


class ValidationInput(ContractModel):
    candidate_run: CandidateRun
    source: ExtractionInput
    source_input_sha256: Sha256Hash
    entity_reviews: Annotated[tuple[EntityReview, ...], Field(strict=False, max_length=25000)] = ()
    policies: Annotated[tuple[NumericMetricPolicy, ...], Field(strict=False, max_length=100)] = ()
    table_evidence_ids: Annotated[
        tuple[CanonicalId, ...], Field(strict=False, max_length=10000)
    ] = ()
    transcription_evidence_ids: Annotated[
        tuple[CanonicalId, ...], Field(strict=False, max_length=10000)
    ] = ()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()

    @model_validator(mode="after")
    def linked_inputs(self) -> Self:
        from regintel.candidates.extraction import validate_bundle
        from regintel.candidates.records import materialize

        run = self.candidate_run
        if (
            run.parse_version_id != self.source.parse_version_id
            or run.entity_run_id != self.source.entity_run.id
            or run.input_sha256 != self.source_input_sha256
        ):
            raise ValueError("Validation requires the sealed proposal and its frozen source input.")
        validate_bundle(self.source, run.bundle)
        if (
            materialize(
                self.source, run.configuration, run.bundle, input_sha256=self.source_input_sha256
            )
            != run
        ):
            raise ValueError(
                "Validation source and candidate records must reproduce the frozen run."
            )
        metrics = {metric.id: metric for metric in self.source.metrics}
        if (
            len({policy.id for policy in self.policies}) != len(self.policies)
            or len({policy.metric_id for policy in self.policies}) != len(self.policies)
            or any(
                policy.metric_id not in metrics or metrics[policy.metric_id].kind != "numeric_fact"
                for policy in self.policies
            )
        ):
            raise ValueError(
                "Validation metric policies must bind distinct supplied numeric metrics."
            )
        if len(set(self.table_evidence_ids)) != len(self.table_evidence_ids) or not set(
            self.table_evidence_ids
        ).issubset(self.source.entity_run.evidence_ids):
            raise ValueError("Table risk references must be distinct source evidence IDs.")
        if len(set(self.transcription_evidence_ids)) != len(
            self.transcription_evidence_ids
        ) or not set(self.transcription_evidence_ids).issubset(self.source.entity_run.evidence_ids):
            raise ValueError("Transcription risks must be distinct source evidence IDs.")
        refreshed = ExtractionInput.model_validate(
            self.source.model_dump(mode="python") | {"reviews": self.entity_reviews}
        )
        if not set(self.source.reviews).issubset(refreshed.reviews):
            raise ValueError("Current entity decisions must preserve immutable historical reviews.")
        return self


class ValidationResult(ContractModel):
    candidate_id: CanonicalId
    state: Literal["PASS", "REVIEW", "QUARANTINED"]
    checks: Annotated[tuple[ValidationCheck, ...], Field(strict=False, min_length=1, max_length=32)]
    quantity: QuantitativeValue | None
    context_supports: Annotated[tuple[ContextWitness, ...], Field(strict=False, max_length=16)]
    reviewer_eligible: bool

    @model_validator(mode="after")
    def state_matches_checks(self) -> Self:
        states = {check.state for check in self.checks}
        expected = "QUARANTINED" if "FAIL" in states else "REVIEW" if "REVIEW" in states else "PASS"
        if self.state != expected or len({check.code for check in self.checks}) != len(self.checks):
            raise ValueError("Validation state must match its distinct mandatory checks.")
        if len(self.checks) != 16:
            raise ValueError("Every result requires all sixteen mandatory check categories.")
        reviews = {check.code for check in self.checks if check.state == "REVIEW"}
        eligible = "FAIL" not in states and (not reviews or reviews == {"EXTRACTIVE_REVIEW"})
        if self.reviewer_eligible != eligible:
            raise ValueError("Mandatory failed or unresolved checks cannot be reviewer-overridden.")
        keys = [
            (item.role, item.span.evidence_id, item.span.start, item.span.end)
            for item in self.context_supports
        ]
        if len(set(keys)) != len(keys):
            raise ValueError("Context witnesses must be distinct.")
        return self


class ValidationRun(ContractModel):
    id: CanonicalId
    candidate_run_id: CanonicalId
    parse_version_id: CanonicalId
    input_sha256: Sha256Hash
    configuration: ValidationConfiguration
    results: Annotated[tuple[ValidationResult, ...], Field(strict=False, max_length=1000)]

    @model_validator(mode="after")
    def stable_identity(self) -> Self:
        expected = stable_id(
            "validation-run:" + self.input_sha256 + ":" + self.configuration.sha256
        )
        if self.id != expected or len({result.candidate_id for result in self.results}) != len(
            self.results
        ):
            raise ValueError(
                "Validation run identity and candidate results must be distinct and frozen."
            )
        return self


class ReviewDecision(ContractModel):
    """Stage eligibility for later publication; this is not acceptance or a corpus."""

    id: CanonicalId
    validation_run_id: CanonicalId
    candidate_id: CanonicalId
    decision: Literal["APPROVE_FOR_PUBLICATION", "REJECT"]
    supports: Annotated[tuple[SourceSpan, ...], Field(strict=False, min_length=1, max_length=16)]
    review_note: Annotated[RawText, Field(min_length=1, max_length=2000)]

    @model_validator(mode="after")
    def bounded_review(self) -> Self:
        keys = [(span.evidence_id, span.start, span.end) for span in self.supports]
        if (
            len(set(keys)) != len(keys)
            or not self.review_note.strip()
            or "\x00" in self.review_note
        ):
            raise ValueError(
                "Review decisions require distinct support and a storable explanation."
            )
        return self
