"""Bounded joint-support proposals; these are never accepted M1 evidence or facts."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from regintel.candidates.models import MetricDefinition
from regintel.contracts.models import ContractModel, FinancialPeriod, ReportingBasis
from regintel.contracts.primitives import (
    CanonicalId,
    DecimalValue,
    RawText,
    SafeInteger,
    Sha256Hash,
)
from regintel.entities.models import RegistrySnapshot
from regintel.numerical.models import NumericalWordRef, StoredNumericalPage
from regintel.validation.models import NumericMetricPolicy

ContextCode = Literal[
    "SOURCE",
    "EXACT_WORDS",
    "TABLE",
    "ISSUER",
    "METRIC",
    "VALUE",
    "UNIT",
    "CURRENCY",
    "PERIOD",
    "BASIS",
    "CONTEXT_SCOPE",
]
CONTEXT_CODES: tuple[ContextCode, ...] = (
    "SOURCE",
    "EXACT_WORDS",
    "TABLE",
    "ISSUER",
    "METRIC",
    "VALUE",
    "UNIT",
    "CURRENCY",
    "PERIOD",
    "BASIS",
    "CONTEXT_SCOPE",
)


class WordPhrase(ContractModel):
    """Ordered whole-word references, without claiming a combined exact PDF span."""

    words: Annotated[
        tuple[NumericalWordRef, ...], Field(strict=False, min_length=1, max_length=256)
    ]

    @model_validator(mode="after")
    def one_ordered_page(self) -> Self:
        first = self.words[0]
        if any(
            word.capture_id != first.capture_id
            or word.word_index != first.word_index + offset
            or word.start != 0
            or "\x00" in word.quote
            for offset, word in enumerate(self.words)
        ):
            raise ValueError("A phrase must retain ordered whole words from one original page.")
        return self

    @property
    def capture_id(self) -> str:
        return self.words[0].capture_id


class TableCellSupport(ContractModel):
    table_index: Annotated[SafeInteger, Field(le=7)]
    cell_index: Annotated[SafeInteger, Field(le=1_999)]
    phrase: WordPhrase


class NumericalContextDraft(ContractModel):
    schema_version: Literal["numerical-context-draft-1"] = "numerical-context-draft-1"
    filing_version_id: CanonicalId
    subject_entity_id: CanonicalId
    metric_id: CanonicalId
    value: TableCellSupport
    row_label: TableCellSupport
    period_header: TableCellSupport
    issuer_header: WordPhrase
    table_scope: WordPhrase
    unit_header: WordPhrase
    basis_context: WordPhrase | None = None
    currency_definitions: Annotated[tuple[WordPhrase, ...], Field(strict=False, max_length=4)] = ()
    fiscal_definitions: Annotated[tuple[WordPhrase, ...], Field(strict=False, max_length=4)] = ()

    def phrases(self) -> tuple[WordPhrase, ...]:
        return (
            self.value.phrase,
            self.row_label.phrase,
            self.period_header.phrase,
            self.issuer_header,
            self.table_scope,
            self.unit_header,
            *((self.basis_context,) if self.basis_context is not None else ()),
            *self.currency_definitions,
            *self.fiscal_definitions,
        )

    @property
    def capture_ids(self) -> tuple[str, ...]:
        return tuple(sorted({phrase.capture_id for phrase in self.phrases()}))

    @model_validator(mode="after")
    def bounded_support(self) -> Self:
        words = [word for phrase in self.phrases() for word in phrase.words]
        if (
            len(self.capture_ids) > 4
            or len(words) > 1_024
            or sum(len(w.quote) for w in words) > 64_000
        ):
            raise ValueError("Joint context exceeds its explicit page/word/text budget.")
        return self


class NumericalContextInput(ContractModel):
    """Trusted producer input; repositories load snapshots rather than accepting model state."""

    draft: NumericalContextDraft
    pages: Annotated[
        tuple[StoredNumericalPage, ...], Field(strict=False, min_length=1, max_length=4)
    ]
    registry: RegistrySnapshot
    metric: MetricDefinition | None
    policy: NumericMetricPolicy | None
    sdk_configuration_sha256: Sha256Hash
    preparation_code_sha256: Sha256Hash

    @model_validator(mode="after")
    def bounded_pages(self) -> Self:
        ids = [page.id for page in self.pages]
        if (
            len(ids) != len(set(ids))
            or sum(len(word.orig or "") for page in self.pages for word in page.capture.words)
            > 500_000
        ):
            raise ValueError("Context pages must be unique and fit the source-text budget.")
        return self


class ContextCheck(ContractModel):
    code: ContextCode
    state: Literal["PASS", "REVIEW", "FAIL"]
    message: Annotated[RawText, Field(min_length=1, max_length=300)]


class NumericalQuantityProposal(ContractModel):
    raw_value: Annotated[RawText, Field(min_length=1, max_length=500)]
    normalized_value: DecimalValue
    normalized_unit: Annotated[RawText, Field(max_length=32)] | None
    currency: Literal["INR", "USD"] | None
    period: FinancialPeriod
    basis: ReportingBasis


class NumericalContextInspection(ContractModel):
    schema_version: Literal["numerical-context-inspection-1"] = "numerical-context-inspection-1"
    id: CanonicalId
    draft: NumericalContextDraft
    draft_sha256: Sha256Hash
    source_input_sha256: Sha256Hash
    configuration_sha256: Sha256Hash
    state: Literal["SUPPORTED_PROPOSAL", "REVIEW_REQUIRED", "QUARANTINED"]
    checks: Annotated[tuple[ContextCheck, ...], Field(strict=False, min_length=11, max_length=11)]
    quantity: NumericalQuantityProposal | None
    acceptance_eligible: Literal[False] = False
    review_required: Literal[True] = True
    mandatory_m1_validation_complete: Literal[False] = False

    @model_validator(mode="after")
    def state_matches_checks(self) -> Self:
        if tuple(check.code for check in self.checks) != CONTEXT_CODES:
            raise ValueError("Every joint context check must be present in canonical order.")
        expected = (
            "QUARANTINED"
            if any(c.state == "FAIL" for c in self.checks)
            else "REVIEW_REQUIRED"
            if any(c.state == "REVIEW" for c in self.checks)
            else "SUPPORTED_PROPOSAL"
        )
        if self.state != expected or (expected == "QUARANTINED" and self.quantity is not None):
            raise ValueError("Inspection state must retain failures and mandatory review.")
        if expected == "SUPPORTED_PROPOSAL" and (
            self.quantity is None
            or self.quantity.normalized_unit is None
            or self.quantity.currency is None
            or self.quantity.basis == "UNKNOWN"
            or self.quantity.period.kind != "DURATION"
            or self.quantity.period.start_date is None
            or self.quantity.period.end_date is None
        ):
            raise ValueError("A supported proposal requires complete proposed monetary context.")
        return self
