"""Explicit experiment controls; citations are application-built exact source data."""

import hashlib
from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, Field, model_validator

from regintel.candidates.models import SourceSpan
from regintel.contracts.models import ContractModel, FinancialPeriod, QuantitativeValue
from regintel.contracts.primitives import (
    CanonicalId,
    DateString,
    Label,
    SafeInteger,
    Sha256Hash,
    integer_from_wire,
)
from regintel.entities.models import canonical_bytes
from regintel.ingestion.models import StoredText
from regintel.publication.models import PublishedObservation
from regintel.reads.models import ViewInfo

type Arm = Literal["B0", "B1", "B2", "B3"]
type Basis = Literal["STANDALONE", "CONSOLIDATED"]


class Filters(ContractModel):
    company_id: CanonicalId | None = None
    period: FinancialPeriod | None = None
    basis: Basis | None = None


class NumericLookup(ContractModel):
    metric_id: CanonicalId
    currency: Label
    unit: Label
    denominator: Label | None = None
    stake_kind: Label | None = None
    ownership_date: DateString | None = None


class RetrievalRequest(ContractModel):
    question: Annotated[StoredText, Field(min_length=1, max_length=1000)]
    corpus_version_id: CanonicalId | None = None
    as_of_date: DateString | None = None
    historical: bool = False
    arm: Arm = "B3"
    filters: Filters = Filters()
    top_k: Annotated[int, Field(strict=True, ge=1, le=10), BeforeValidator(integer_from_wire)] = 5
    context_budget: Annotated[
        int, Field(strict=True, ge=128, le=4096), BeforeValidator(integer_from_wire)
    ] = 2048
    graph_hops: Annotated[Literal[1, 2], BeforeValidator(integer_from_wire)] = 1
    numeric: NumericLookup | None = None

    @model_validator(mode="after")
    def nonempty_question(self) -> Self:
        if not self.question.strip():
            raise ValueError("A nonempty question is required.")
        return self


class RetrievalConfiguration(ContractModel):
    version: Literal["1.0.0"] = "1.0.0"
    code_sha256: Sha256Hash
    policy: Literal["extractive-exact-source-v1"] = "extractive-exact-source-v1"
    rrf_k: Literal[60] = 60
    bm25_k1: float = Field(default=1.2, ge=1.2, le=1.2)
    bm25_b: float = Field(default=0.75, ge=0.75, le=0.75)
    candidate_pool: Literal[100] = 100
    graph_relation_limit: Literal[1000] = 1000
    query_prefix: Literal["Represent this sentence for searching relevant passages: "] = (
        "Represent this sentence for searching relevant passages: "
    )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


class Citation(ContractModel):
    observation_id: CanonicalId
    filing_version_id: CanonicalId
    parse_version_id: CanonicalId
    source_sha256: Sha256Hash
    page_index: SafeInteger
    span: SourceSpan
    role: Literal[
        "DISCLOSURE",
        "VALUE",
        "UNIT",
        "CURRENCY",
        "PERIOD",
        "BASIS",
        "DENOMINATOR",
        "STAKE_KIND",
        "OWNERSHIP_DATE",
    ]


class RetrievalHit(ContractModel):
    chunk_id: CanonicalId
    observation: PublishedObservation
    dense_rank: SafeInteger | None
    lexical_rank: SafeInteger | None
    graph_hop: Literal[1, 2] | None
    citations: tuple[Citation, ...]
    context_tokens: SafeInteger


class ContextBundle(ContractModel):
    observation: PublishedObservation
    citations: tuple[Citation, ...]


class Trace(ContractModel):
    run_id: CanonicalId
    configuration_sha256: Sha256Hash
    question_sha256: Sha256Hash
    embedding_manifest_sha256: Sha256Hash
    embedding_model: Literal["BAAI/bge-small-en-v1.5"] = "BAAI/bge-small-en-v1.5"
    embedding_revision: Literal["5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"] = (
        "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
    )
    arm: Arm
    metadata_filters_applied: bool
    filters: Filters
    top_k: SafeInteger
    context_budget: SafeInteger
    context_tokens: SafeInteger
    budget_omitted: SafeInteger
    query_tokens: SafeInteger
    graph_hops: Literal[1, 2]
    duration_ms: float = Field(ge=0, allow_inf_nan=False)
    provider_calls: Literal[0] = 0
    provider_cost: Literal["0"] = "0"
    generation_model: None = None


class RetrievalResult(ContractModel):
    view: ViewInfo
    state: Literal["AVAILABLE", "TEMPORAL_SUPPORT_UNAVAILABLE"]
    hits: tuple[RetrievalHit, ...]
    trace: Trace


class ExtractiveClaim(ContractModel):
    text: StoredText
    observation_id: CanonicalId
    citations: tuple[Citation, ...]
    quantity: QuantitativeValue | None = None


class AnswerResult(ContractModel):
    retrieval: RetrievalResult
    state: Literal[
        "EXTRACTIVE_EVIDENCE",
        "NUMERIC_VALUE",
        "INSUFFICIENT_SUPPORT",
        "TEMPORAL_SUPPORT_UNAVAILABLE",
        "NUMERIC_CONTEXT_REQUIRED",
        "NUMERIC_UNAVAILABLE",
        "NUMERIC_INCOMPATIBLE",
        "NUMERIC_CONFLICT",
        "CONTEXT_BUDGET_UNAVAILABLE",
    ]
    claims: tuple[ExtractiveClaim, ...]
    explanation: str


class RetrievalWire(ContractModel):
    request: RetrievalRequest
    retrieval: RetrievalResult
    answer: AnswerResult
