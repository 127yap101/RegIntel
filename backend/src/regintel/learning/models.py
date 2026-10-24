"""Reviewed glossary drafts, independent versions and explicitly educational examples."""

from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import AfterValidator, Field, model_validator

from regintel.contracts.models import ContractModel
from regintel.contracts.primitives import CanonicalId, DecimalValue, Label, RawText, Sha256Hash


def _source_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("An ordinary HTTP source link without credentials is required.")
    return value


class LearningSource(ContractModel):
    title: Annotated[Label, Field(max_length=200)]
    url: Annotated[str, Field(strict=True, max_length=2048), AfterValidator(_source_url)]
    location: Annotated[Label, Field(max_length=200)] | None = None


class ExampleInput(ContractModel):
    kind: Literal["AUTHORED_EDUCATIONAL_EXAMPLE"] = "AUTHORED_EDUCATIONAL_EXAMPLE"
    operation: Literal["ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "PERCENT_CHANGE"]
    left: DecimalValue
    right: DecimalValue
    unit: Annotated[Label, Field(max_length=80)]
    explanation: Annotated[RawText, Field(min_length=1, max_length=1000)]


class ExampleCalculation(ContractModel):
    input: ExampleInput
    state: Literal["AVAILABLE", "ZERO_DIVISOR", "NON_POSITIVE_BASELINE", "OUT_OF_RANGE"]
    result: DecimalValue | None
    result_unit: Annotated[Label, Field(max_length=80)]
    formula: Literal[
        "left + right",
        "left - right",
        "left * right",
        "left / right",
        "(right - left) / left * 100",
    ]
    rounding: Literal["EXACT", "HALF_EVEN_12_DECIMAL_PLACES"]

    @model_validator(mode="after")
    def available_result(self) -> Self:
        if (self.result is not None) != (self.state == "AVAILABLE"):
            raise ValueError("Only an available educational calculation carries a result.")
        return self


class DefinitionDraft(ContractModel):
    term: Annotated[Label, Field(max_length=120)]
    definition: Annotated[RawText, Field(min_length=1, max_length=4000)]
    sources: Annotated[tuple[LearningSource, ...], Field(strict=False, min_length=1, max_length=5)]
    metric_ids: Annotated[tuple[CanonicalId, ...], Field(strict=False, max_length=8)] = ()
    example: ExampleInput | None = None

    @model_validator(mode="after")
    def distinct_context(self) -> Self:
        if not self.term.strip() or not self.definition.strip():
            raise ValueError("A definition requires a nonblank term and explanation.")
        if len(set(self.metric_ids)) != len(self.metric_ids):
            raise ValueError("Definition metric links must be distinct.")
        return self


class StoredDefinition(ContractModel):
    id: CanonicalId
    content_sha256: Sha256Hash
    draft: DefinitionDraft
    calculation: ExampleCalculation | None
    submitted_by: CanonicalId


class LearningReview(ContractModel):
    decision: Literal["APPROVE", "REJECT"]
    note: Annotated[RawText, Field(min_length=1, max_length=1000)]

    @model_validator(mode="after")
    def explained_review(self) -> Self:
        if not self.note.strip():
            raise ValueError("A learning review needs a nonblank explanation.")
        return self


class ReviewedDefinition(ContractModel):
    definition: StoredDefinition
    review_id: CanonicalId
    reviewed_by: CanonicalId
    review: LearningReview


class PublishLearning(ContractModel):
    parent_glossary_version_id: CanonicalId | None = None
    definition_ids: Annotated[
        tuple[CanonicalId, ...], Field(strict=False, min_length=1, max_length=100)
    ]

    @model_validator(mode="after")
    def distinct_definitions(self) -> Self:
        if len(set(self.definition_ids)) != len(self.definition_ids):
            raise ValueError("Publish each approved definition once.")
        return self


class GlossaryVersion(ContractModel):
    glossary_version_id: CanonicalId
    parent_glossary_version_id: CanonicalId | None = None
    definitions: Annotated[
        tuple[ReviewedDefinition, ...], Field(strict=False, min_length=1, max_length=100)
    ]

    @model_validator(mode="after")
    def approved_terms(self) -> Self:
        if any(item.review.decision != "APPROVE" for item in self.definitions):
            raise ValueError("Published glossary content requires explicit approval.")
        terms = [item.definition.draft.term.casefold() for item in self.definitions]
        if len(set(terms)) != len(terms):
            raise ValueError(
                "A glossary version cannot contain conflicting definitions of one term."
            )
        return self


class LearningOverview(ContractModel):
    state: Literal["AVAILABLE", "NO_PUBLISHED_GLOSSARY"]
    glossary_version_id: CanonicalId | None

    @model_validator(mode="after")
    def explicit_version(self) -> Self:
        if (self.glossary_version_id is not None) != (self.state == "AVAILABLE"):
            raise ValueError("Learning availability requires its independent published version.")
        return self
