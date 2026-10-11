"""M1.1 immutable storage shapes, without authority to accept or publish observations."""

from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import AfterValidator, Field, model_validator

from regintel.contracts.models import (
    ContractModel,
    EvidenceIds,
    EvidenceRecord,
    PageGeometry,
    QuantitativeValue,
    RelationType,
    TextEvidence,
)
from regintel.contracts.primitives import (
    MAX_SAFE_INTEGER,
    CanonicalId,
    DateString,
    Label,
    PageIndex,
    PositiveSafeInteger,
    RawText,
    SafeInteger,
    Sha256Hash,
)

DocumentType = Literal["DRHP", "RHP", "PROSPECTUS", "ADDENDUM", "CORRIGENDUM"]
CandidateKind = Literal["numeric_fact", "narrative_fact", "relation"]
ContextRole = Literal["ROW_LABEL", "PERIOD_COLUMN", "UNIT_HEADER", "BASIS_HEADER"]


def _stored_text(value: str) -> str:
    if "\x00" in value:
        raise ValueError("Stored PostgreSQL text cannot contain a null code point.")
    return value


def _source_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
            and not any(character.isspace() or ord(character) < 32 for character in value)
        )
        _ = parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("A bounded HTTPS source URL without credentials or fragment is required.")
    return value


StoredText = Annotated[RawText, AfterValidator(_stored_text)]
StoredLabel = Annotated[Label, AfterValidator(_stored_text)]
SourceUrl = Annotated[StoredText, Field(min_length=1, max_length=4096), AfterValidator(_source_url)]


class SourceBlob(ContractModel):
    id: CanonicalId
    sha256: Sha256Hash
    byte_size: PositiveSafeInteger
    storage_key: StoredLabel

    @model_validator(mode="after")
    def validate_content_key(self) -> Self:
        if self.storage_key != f"sha256/{self.sha256}.pdf":
            raise ValueError("A source storage key must be derived from its exact SHA-256.")
        return self


class FilingRecord(ContractModel):
    id: CanonicalId
    company_name_raw: StoredLabel
    company_entity_id: CanonicalId | None


class FilingVersionRecord(ContractModel):
    id: CanonicalId
    filing_id: CanonicalId
    source_blob_id: CanonicalId
    document_type: DocumentType
    source_url: SourceUrl | None
    published_on: DateString | None
    declared_parent_filing_version_id: CanonicalId | None

    @model_validator(mode="after")
    def validate_parent(self) -> Self:
        if self.declared_parent_filing_version_id == self.id:
            raise ValueError("A filing version cannot declare itself as its parent.")
        return self


class ParseVersionRecord(ContractModel):
    id: CanonicalId
    filing_version_id: CanonicalId
    source_blob_id: CanonicalId
    adapter_name: StoredLabel
    adapter_version: StoredLabel
    configuration_sha256: Sha256Hash
    artifact_sha256: Sha256Hash
    page_count: PositiveSafeInteger
    block_count: SafeInteger
    table_count: SafeInteger
    cell_count: SafeInteger
    evidence_count: SafeInteger


class PageRecord(ContractModel):
    id: CanonicalId
    parse_version_id: CanonicalId
    filing_version_id: CanonicalId
    page_index: PageIndex
    geometry: PageGeometry


class BlockRecord(ContractModel):
    id: CanonicalId
    parse_version_id: CanonicalId
    page_id: CanonicalId
    text: StoredText


class TableRecord(ContractModel):
    id: CanonicalId
    parse_version_id: CanonicalId
    first_page_id: CanonicalId
    row_count: PositiveSafeInteger
    column_count: PositiveSafeInteger


class CellRecord(ContractModel):
    id: CanonicalId
    parse_version_id: CanonicalId
    table_id: CanonicalId
    page_id: CanonicalId
    row_index: SafeInteger
    column_index: SafeInteger
    row_span: PositiveSafeInteger
    column_span: PositiveSafeInteger
    raw_text: StoredText

    @model_validator(mode="after")
    def validate_endpoints(self) -> Self:
        if (
            self.row_index + self.row_span > MAX_SAFE_INTEGER
            or self.column_index + self.column_span > MAX_SAFE_INTEGER
        ):
            raise ValueError("Cell endpoints must remain exact safe integers.")
        return self


class CellContextRecord(ContractModel):
    cell_id: CanonicalId
    parse_version_id: CanonicalId
    table_id: CanonicalId
    context_cell_id: CanonicalId
    role: ContextRole


class StoredEvidence(ContractModel):
    record: EvidenceRecord

    @model_validator(mode="after")
    def validate_storage_bounds(self) -> Self:
        if isinstance(self.record, TextEvidence):
            _stored_text(self.record.span.quote)
        media = self.record.page_geometry.media_box
        for box in self.record.boxes:
            if (
                box.x0 < media.x0 - 1e-7
                or box.y0 < media.y0 - 1e-7
                or box.x1 > media.x1 + 1e-7
                or box.y1 > media.y1 + 1e-7
            ):
                raise ValueError("Stored evidence boxes must occupy their source media box.")
        return self


class QuantitativeContextRecord(ContractModel):
    id: CanonicalId
    parse_version_id: CanonicalId
    quantity: QuantitativeValue

    @model_validator(mode="after")
    def validate_stored_text(self) -> Self:
        for value in (
            self.quantity.raw_value,
            self.quantity.raw_unit,
            self.quantity.normalized_unit,
            self.quantity.raw_currency,
            self.quantity.currency,
            self.quantity.period.raw_label,
            self.quantity.raw_basis_label,
            self.quantity.denominator,
            self.quantity.stake_kind,
        ):
            if value is not None:
                _stored_text(value)
        return self


class CandidateRecord(ContractModel):
    id: CanonicalId
    parse_version_id: CanonicalId
    kind: CandidateKind
    state: Literal["CANDIDATE"]
    subject_entity_id: CanonicalId
    object_entity_id: CanonicalId | None
    metric_id: CanonicalId | None
    relation_type: RelationType | None
    raw_text: StoredText
    quantitative_context_id: CanonicalId | None
    evidence_ids: EvidenceIds

    @model_validator(mode="after")
    def validate_candidate_shape(self) -> Self:
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("Candidate evidence IDs must be unique.")
        if self.kind == "relation":
            if self.object_entity_id is None or self.relation_type is None or self.metric_id:
                raise ValueError("Relations require directed entity endpoints/type and no metric.")
            if self.subject_entity_id == self.object_entity_id:
                raise ValueError("Relation endpoints must be distinct.")
        elif self.metric_id is None or self.object_entity_id is not None or self.relation_type:
            raise ValueError("Facts require a metric and no relation endpoint/type.")
        if self.kind == "numeric_fact" and self.quantitative_context_id is None:
            raise ValueError("Numeric candidates require a quantitative-context reference.")
        return self


class AcceptanceAuditRecord(ContractModel):
    """Reserved audit shape; its storage insertion is disabled until M1B gates exist."""

    id: CanonicalId
    candidate_id: CanonicalId
    parse_version_id: CanonicalId
    actor_user_id: CanonicalId
    decision: Literal["ACCEPTED"]
    validator_configuration_sha256: Sha256Hash


class FactObservationRecord(ContractModel):
    """Future accepted immutable observation; shape does not confer acceptance."""

    id: CanonicalId
    candidate_id: CanonicalId
    parse_version_id: CanonicalId
    acceptance_audit_id: CanonicalId
    corpus_version_id: CanonicalId
    kind: Literal["numeric_fact", "narrative_fact"]
    subject_entity_id: CanonicalId
    metric_id: CanonicalId
    quantitative_context_id: CanonicalId | None
    raw_text: StoredText

    @model_validator(mode="after")
    def validate_context(self) -> Self:
        if self.kind == "numeric_fact" and self.quantitative_context_id is None:
            raise ValueError("Accepted numeric fact shapes require quantitative context.")
        return self


class RelationObservationRecord(ContractModel):
    """Reserved accepted relation with explicit candidate/audit/corpus anchors."""

    id: CanonicalId
    candidate_id: CanonicalId
    parse_version_id: CanonicalId
    acceptance_audit_id: CanonicalId
    corpus_version_id: CanonicalId
    subject_entity_id: CanonicalId
    object_entity_id: CanonicalId
    relation_type: RelationType
    quantitative_context_id: CanonicalId | None

    @model_validator(mode="after")
    def validate_direction(self) -> Self:
        if self.subject_entity_id == self.object_entity_id:
            raise ValueError("Relation endpoints must be distinct.")
        return self


class CorpusVersionRecord(ContractModel):
    """Reserved corpus shape; building/publication operations arrive in M1B."""

    id: CanonicalId
    parent_corpus_version_id: CanonicalId | None
    state: Literal["BUILDING", "PUBLISHED"]
    configuration_sha256: Sha256Hash

    @model_validator(mode="after")
    def validate_parent(self) -> Self:
        if self.parent_corpus_version_id == self.id:
            raise ValueError("A corpus version cannot be its own parent.")
        return self
