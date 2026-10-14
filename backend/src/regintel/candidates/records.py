"""Backend-assigned proposal IDs and raw quantitative storage; no acceptance."""

import hashlib
from typing import Annotated, Self

from pydantic import Field, model_validator

from regintel.candidates.models import (
    CandidateBundle,
    DraftCandidate,
    ExtractionConfiguration,
    ExtractionInput,
)
from regintel.contracts.models import ContractModel, FinancialPeriod, QuantitativeValue
from regintel.contracts.primitives import CanonicalId, Sha256Hash
from regintel.entities.models import canonical_bytes
from regintel.ingestion.models import CandidateRecord, QuantitativeContextRecord


def stable_id(value: str) -> str:
    """Assign a reproducible UUID-shaped application ID without loading NLP."""
    from uuid import UUID

    return str(UUID(bytes=hashlib.sha256(value.encode()).digest()[:16], version=4))


def drafts(bundle: CandidateBundle) -> tuple[DraftCandidate, ...]:
    return (*bundle.numeric_facts, *bundle.narrative_facts, *bundle.relations)


class CandidateRun(ContractModel):
    id: CanonicalId
    parse_version_id: CanonicalId
    entity_run_id: CanonicalId
    input_sha256: Sha256Hash
    configuration: ExtractionConfiguration
    bundle: CandidateBundle
    candidates: Annotated[tuple[CandidateRecord, ...], Field(strict=False, max_length=1000)]
    quantities: Annotated[
        tuple[QuantitativeContextRecord, ...], Field(strict=False, max_length=1000)
    ]

    @model_validator(mode="after")
    def validate_records(self) -> Self:
        expected_id = stable_id(
            "candidate-run:" + self.input_sha256 + ":" + self.configuration.sha256
        )
        expected_candidates, expected_quantities = _records(
            self.parse_version_id, self.id, self.bundle
        )
        if (
            self.id != expected_id
            or self.candidates != expected_candidates
            or self.quantities != expected_quantities
        ):
            raise ValueError("Stored proposal identities and raw values must match their drafts.")
        if len(self.candidates) != len(drafts(self.bundle)):
            raise ValueError("Every draft needs exactly one stored candidate.")
        ids = [item.id for item in self.candidates]
        quantity_ids = [item.id for item in self.quantities]
        references = [
            item.quantitative_context_id
            for item in self.candidates
            if item.quantitative_context_id is not None
        ]
        if len(set(ids)) != len(ids) or len(set(quantity_ids)) != len(quantity_ids):
            raise ValueError("Stored proposal IDs must be unique.")
        if sorted(references) != sorted(quantity_ids):
            raise ValueError("Raw quantities must have exactly one proposal owner.")
        if any(item.parse_version_id != self.parse_version_id for item in self.candidates) or any(
            item.parse_version_id != self.parse_version_id for item in self.quantities
        ):
            raise ValueError("Stored proposals must occupy one immutable parse.")
        return self


def _records(
    parse_version_id: str, run_id: str, bundle: CandidateBundle
) -> tuple[tuple[CandidateRecord, ...], tuple[QuantitativeContextRecord, ...]]:
    candidates: list[CandidateRecord] = []
    quantities: list[QuantitativeContextRecord] = []
    for draft in drafts(bundle):
        draft_sha = hashlib.sha256(canonical_bytes(draft)).hexdigest()
        candidate_id = stable_id("candidate:" + run_id + ":" + draft_sha)
        evidence_ids = tuple(dict.fromkeys(span.evidence_id for span in draft.supports))
        context_id: str | None = None
        raw = draft.raw_quantity
        if raw is not None:
            context_id = stable_id("candidate-quantity:" + candidate_id)
            quantities.append(
                QuantitativeContextRecord(
                    id=context_id,
                    parse_version_id=parse_version_id,
                    quantity=QuantitativeValue(
                        raw_value=raw.value.quote,
                        normalized_value=None,
                        raw_unit=raw.unit.quote if raw.unit is not None else None,
                        normalized_unit=None,
                        raw_currency=raw.currency.quote if raw.currency is not None else None,
                        currency=None,
                        period=FinancialPeriod(
                            kind="UNKNOWN",
                            start_date=None,
                            end_date=None,
                            instant_date=None,
                            raw_label=raw.period.quote if raw.period is not None else None,
                        ),
                        basis="UNKNOWN",
                        raw_basis_label=raw.basis.quote if raw.basis is not None else None,
                        denominator=raw.denominator.quote if raw.denominator is not None else None,
                        stake_kind=raw.stake_kind.quote if raw.stake_kind is not None else None,
                        ownership_date=None,
                        evidence_ids=evidence_ids,
                    ),
                )
            )
        candidates.append(
            CandidateRecord(
                id=candidate_id,
                parse_version_id=parse_version_id,
                kind=draft.kind,
                state="CANDIDATE",
                subject_entity_id=draft.subject_entity_id,
                object_entity_id=draft.object_entity_id,
                metric_id=draft.metric_id,
                relation_type=draft.relation_type,
                raw_text=draft.raw_text,
                quantitative_context_id=context_id,
                evidence_ids=evidence_ids,
            )
        )
    return tuple(candidates), tuple(quantities)


def materialize(
    source: ExtractionInput,
    configuration: ExtractionConfiguration,
    bundle: CandidateBundle,
    *,
    input_sha256: str | None = None,
) -> CandidateRun:
    """Keep all extracted context raw until the M1.7 semantic gate interprets it."""
    # Stored runs fingerprint the actual immutable bytes. Re-serialization of an
    # equivalent historical input must not change its recorded storage identity.
    source_sha = source.sha256 if input_sha256 is None else input_sha256
    run_id = stable_id("candidate-run:" + source_sha + ":" + configuration.sha256)
    candidates, quantities = _records(source.parse_version_id, run_id, bundle)
    return CandidateRun(
        id=run_id,
        parse_version_id=source.parse_version_id,
        entity_run_id=source.entity_run.id,
        input_sha256=source_sha,
        configuration=configuration,
        bundle=bundle,
        candidates=candidates,
        quantities=quantities,
    )
