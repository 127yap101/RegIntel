"""Shared shape contracts; source support and acceptance remain later M1 responsibilities."""

import math
from typing import Annotated, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from regintel.contracts.primitives import (
    MAX_SAFE_INTEGER,
    CanonicalId,
    DateString,
    DecimalValue,
    ErrorCode,
    FiniteCoordinate,
    Label,
    LineageLabel,
    PageIndex,
    PositiveDimension,
    PositiveSafeInteger,
    RawText,
    SafeInteger,
    Username,
    integer_from_wire,
)

CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"
RelationType = Literal["OWNS", "PROMOTER_OF", "SUBSIDIARY_OF", "SUPPLIES_TO", "AUDITS", "LENDS_TO"]
EffectType = Literal["ADD", "CORRECT", "SUPPLEMENT", "SUPERSEDE", "REMOVE"]
ObservationState = Literal["CANDIDATE", "ACCEPTED", "REVIEW", "QUARANTINED"]
PeriodKind = Literal["INSTANT", "DURATION", "UNKNOWN"]
ReportingBasis = Literal["STANDALONE", "CONSOLIDATED", "UNKNOWN"]
Role = Literal["admin", "learner"]
RELATION_DIRECTIONS: dict[str, dict[str, str]] = {
    "OWNS": {"subject": "owner", "object": "owned"},
    "PROMOTER_OF": {"subject": "promoter", "object": "company"},
    "SUBSIDIARY_OF": {"subject": "subsidiary", "object": "parent"},
    "SUPPLIES_TO": {"subject": "supplier", "object": "customer"},
    "AUDITS": {"subject": "auditor", "object": "company"},
    "LENDS_TO": {"subject": "lender", "object": "borrower"},
}
MODULE_OWNERSHIP: dict[str, str] = {
    "company_lookup_backend": "M1",
    "company_search_backend": "M1",
    "company_search_experience": "M2",
    "company_profile_experience": "M2",
    "GET /v1/quotes": "M2",
    "immutable_quote_snapshots": "M4",
}


class ContractModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        validate_default=True,
        hide_input_in_errors=True,
    )


IdCollection = Annotated[tuple[CanonicalId, ...], Field(strict=False, max_length=10_000)]
EvidenceIds = Annotated[
    tuple[CanonicalId, ...], Field(strict=False, min_length=1, max_length=10_000)
]


def _require_unique(values: tuple[str, ...]) -> None:
    if len(set(values)) != len(values):
        raise ValueError("Reference IDs must be unique within each collection.")


def _validate_rotation(value: object) -> object:
    return integer_from_wire(value)


class VersionContext(ContractModel):
    corpus_version_id: CanonicalId | None
    filing_version_id: CanonicalId | None
    parse_version_id: CanonicalId | None
    glossary_version_id: CanonicalId | None
    quote_version_id: CanonicalId | None
    portfolio_version_id: CanonicalId | None


class ResponseMeta(ContractModel):
    request_id: CanonicalId
    contract_version: Literal["1.0.0"]
    versions: VersionContext


class UserIdentity(ContractModel):
    id: CanonicalId
    username: Username
    role: Role


class SuccessEnvelope[T](ContractModel):
    data: T
    meta: ResponseMeta


class UserEnvelope(SuccessEnvelope[UserIdentity]):
    pass


class ErrorDetail(ContractModel):
    location: Literal["body", "query", "path", "header", "cookie", "request"]
    code: ErrorCode


class ApiError(ContractModel):
    code: ErrorCode
    message: Annotated[RawText, Field(min_length=1, max_length=500)]
    details: Annotated[tuple[ErrorDetail, ...], Field(strict=False, max_length=100)]


class ErrorEnvelope(ContractModel):
    error: ApiError
    meta: ResponseMeta


class FinancialPeriod(ContractModel):
    kind: PeriodKind
    start_date: DateString | None
    end_date: DateString | None
    instant_date: DateString | None
    raw_label: RawText | None

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if self.kind == "INSTANT":
            if self.start_date is not None or self.end_date is not None:
                raise ValueError("An instant period cannot carry duration dates.")
        elif self.kind == "DURATION":
            if self.instant_date is not None:
                raise ValueError("A duration period cannot carry an instant date.")
            if (
                self.start_date is not None
                and self.end_date is not None
                and self.end_date < self.start_date
            ):
                raise ValueError("Duration dates must be chronologically ordered.")
        elif any(
            value is not None for value in (self.start_date, self.end_date, self.instant_date)
        ):
            raise ValueError("An unknown period cannot carry interpreted dates.")
        return self


class QuantitativeValue(ContractModel):
    raw_value: RawText
    normalized_value: DecimalValue | None
    raw_unit: RawText | None
    normalized_unit: Label | None
    raw_currency: RawText | None
    currency: Label | None
    period: FinancialPeriod
    basis: ReportingBasis
    raw_basis_label: RawText | None
    denominator: Label | None
    stake_kind: Label | None
    ownership_date: DateString | None
    evidence_ids: EvidenceIds

    @model_validator(mode="after")
    def validate_reference_ids(self) -> Self:
        _require_unique(self.evidence_ids)
        return self


class EvidenceSource(ContractModel):
    filing_id: CanonicalId
    filing_version_id: CanonicalId
    parse_version_id: CanonicalId
    page_id: CanonicalId
    page_index: PageIndex


class TextSpan(ContractModel):
    block_id: CanonicalId
    start: SafeInteger
    end: SafeInteger
    quote: Annotated[RawText, Field(min_length=1)]

    @model_validator(mode="after")
    def validate_offsets(self) -> Self:
        if self.end <= self.start or self.end - self.start != len(self.quote):
            raise ValueError("A text span must be half-open with exact Unicode code-point length.")
        return self


class PdfRectangle(ContractModel):
    x0: FiniteCoordinate
    y0: FiniteCoordinate
    x1: FiniteCoordinate
    y1: FiniteCoordinate

    @model_validator(mode="after")
    def validate_area(self) -> Self:
        if (
            self.x1 <= self.x0
            or self.y1 <= self.y0
            or not math.isfinite(self.x1 - self.x0)
            or not math.isfinite(self.y1 - self.y0)
        ):
            raise ValueError("A PDF rectangle must have positive area.")
        return self


class PageGeometry(ContractModel):
    width: PositiveDimension
    height: PositiveDimension
    media_box: PdfRectangle
    crop_box: PdfRectangle
    rotation: Annotated[Literal[0, 90, 180, 270], BeforeValidator(_validate_rotation)]
    coordinate_space: Literal["UNROTATED_PDF_POINTS"]
    origin: Literal["BOTTOM_LEFT"]

    @model_validator(mode="after")
    def validate_media_dimensions(self) -> Self:
        if not math.isclose(
            self.width, self.media_box.x1 - self.media_box.x0, rel_tol=1e-12, abs_tol=1e-9
        ) or not math.isclose(
            self.height, self.media_box.y1 - self.media_box.y0, rel_tol=1e-12, abs_tol=1e-9
        ):
            raise ValueError("Page dimensions must agree with media-box extents.")
        return self


class CellReference(ContractModel):
    table_id: CanonicalId
    cell_id: CanonicalId
    row_index: SafeInteger
    column_index: SafeInteger
    row_span: PositiveSafeInteger
    column_span: PositiveSafeInteger
    row_label_cell_ids: IdCollection
    period_column_cell_ids: IdCollection
    unit_header_cell_ids: IdCollection
    basis_header_cell_ids: IdCollection

    @model_validator(mode="after")
    def validate_context_ids(self) -> Self:
        for values in (
            self.row_label_cell_ids,
            self.period_column_cell_ids,
            self.unit_header_cell_ids,
            self.basis_header_cell_ids,
        ):
            _require_unique(values)
        if (
            self.row_index + self.row_span > MAX_SAFE_INTEGER
            or self.column_index + self.column_span > MAX_SAFE_INTEGER
        ):
            raise ValueError("Cell span endpoints must remain exact safe integers.")
        return self


Boxes = Annotated[tuple[PdfRectangle, ...], Field(strict=False, min_length=1, max_length=10_000)]


class TextEvidence(ContractModel):
    id: CanonicalId
    kind: Literal["text"]
    source: EvidenceSource
    page_geometry: PageGeometry
    boxes: Boxes
    span: TextSpan


class CellEvidence(ContractModel):
    id: CanonicalId
    kind: Literal["table_cell"]
    source: EvidenceSource
    page_geometry: PageGeometry
    boxes: Boxes
    cell: CellReference


EvidenceRecord = Annotated[TextEvidence | CellEvidence, Field(discriminator="kind")]


class EvidenceSupport(ContractModel):
    records: Annotated[
        tuple[EvidenceRecord, ...], Field(strict=False, min_length=1, max_length=10_000)
    ]

    @model_validator(mode="after")
    def validate_record_ids(self) -> Self:
        _require_unique(tuple(record.id for record in self.records))
        return self


class RelationReference(ContractModel):
    id: CanonicalId
    relation_type: RelationType
    subject_entity_id: CanonicalId
    object_entity_id: CanonicalId
    state: ObservationState
    evidence_ids: EvidenceIds
    quantitative_context: QuantitativeValue | None

    @model_validator(mode="after")
    def validate_reference_ids(self) -> Self:
        _require_unique(self.evidence_ids)
        return self


class FilingLineage(ContractModel):
    parent_filing_id: CanonicalId
    child_filing_id: CanonicalId
    lineage_type: LineageLabel

    @model_validator(mode="after")
    def validate_distinct_filings(self) -> Self:
        if self.parent_filing_id == self.child_filing_id:
            raise ValueError("Parent and child filing IDs must be distinct.")
        return self


class AmendmentEffect(ContractModel):
    id: CanonicalId
    effect_type: EffectType
    affected_observation_ids: IdCollection
    new_observation_ids: IdCollection
    evidence_ids: EvidenceIds
    reviewed_decision_id: CanonicalId | None
    effective_date: DateString | None

    @model_validator(mode="after")
    def validate_reference_ids(self) -> Self:
        for values in (
            self.affected_observation_ids,
            self.new_observation_ids,
            self.evidence_ids,
        ):
            _require_unique(values)
        return self


PUBLIC_MODELS: dict[str, type[BaseModel]] = {
    model.__name__: model
    for model in (
        VersionContext,
        ResponseMeta,
        UserIdentity,
        UserEnvelope,
        ErrorDetail,
        ApiError,
        ErrorEnvelope,
        FinancialPeriod,
        QuantitativeValue,
        EvidenceSource,
        TextSpan,
        PdfRectangle,
        PageGeometry,
        CellReference,
        TextEvidence,
        CellEvidence,
        EvidenceSupport,
        RelationReference,
        FilingLineage,
        AmendmentEffect,
    )
}
