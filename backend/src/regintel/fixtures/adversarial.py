"""Authored synthetic cases; future gate outcomes are data, never executed gates."""

import json
from typing import Literal

from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError

from regintel.contracts.models import (
    PUBLIC_MODELS,
    AmendmentEffect,
    ContractModel,
    EvidenceSupport,
    FinancialPeriod,
    QuantitativeValue,
    RelationReference,
    RelationType,
    ReportingBasis,
)
from regintel.contracts.primitives import CanonicalId, decimal_from_wire
from regintel.fixtures.sources import evidence_catalog, fixture_id

Category = Literal[
    "positive_control",
    "prompt_injection",
    "fabricated_evidence_ids",
    "modified_quotes",
    "standalone_consolidated_columns",
    "lakh_crore_mismatch",
    "publication_date_without_period",
    "dash_blank",
    "cooccurrence_without_relation",
    "ownership_missing_denominator_date",
    "may_to_certainty",
    "wrong_year",
    "undisclosed_supplier",
    "unsupported_json_claim",
    "model_timeout_refusal",
    "direction_inversion",
    "ocr_corruption",
    "amendment_conflict",
    "unsupported_paraphrase",
    "explicit_amendment_effect",
    "invalid_financial_wire",
]
REQUIRED_ADVERSARIAL_CATEGORIES: frozenset[str] = frozenset(
    {
        "prompt_injection",
        "fabricated_evidence_ids",
        "modified_quotes",
        "standalone_consolidated_columns",
        "lakh_crore_mismatch",
        "publication_date_without_period",
        "dash_blank",
        "cooccurrence_without_relation",
        "ownership_missing_denominator_date",
        "may_to_certainty",
        "wrong_year",
        "undisclosed_supplier",
        "unsupported_json_claim",
        "model_timeout_refusal",
        "direction_inversion",
        "ocr_corruption",
        "amendment_conflict",
        "unsupported_paraphrase",
    }
)
FutureExpectation = Literal[
    "SUPPORTED_CANDIDATE",
    "IGNORE_SOURCE_INSTRUCTIONS",
    "REJECT",
    "REVIEW",
    "PRESERVE_UNKNOWN",
    "PRESERVE_NULL",
    "PRESERVE_QUALIFIER",
    "PRESERVE_NEGATION",
    "NO_ACCEPTED_OUTPUT",
    "KEEP_SEPARATE",
    "EXPLICIT_EFFECT",
]
JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class FixtureCase(ContractModel):
    name: str
    category: Category
    source_aliases: tuple[str, ...]
    contract_name: str | None
    payload: dict[str, JsonValue] | None
    structurally_valid: bool | None
    future_expectation: FutureExpectation
    reason: str
    provider_event: Literal["timeout", "refusal"] | None


class CaseSuite(ContractModel):
    fixture_version: Literal["1.0.0"]
    synthetic: Literal[True]
    description: str
    observation_sources: dict[CanonicalId, str]
    cases: tuple[FixtureCase, ...]


def _wire(model: BaseModel) -> dict[str, JsonValue]:
    return JSON_OBJECT.validate_json(model.model_dump_json())


def _object(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ValueError("Fixture object required.")
    return value


def _sequence(value: JsonValue) -> list[JsonValue]:
    if not isinstance(value, list):
        raise ValueError("Fixture sequence required.")
    return value


def _quantity(
    alias: str,
    value: str | None = "100.00",
    *,
    basis: ReportingBasis = "STANDALONE",
    unit: str | None = "lakh",
    raw_unit: str = "INR lakh",
    unknown_period: bool = False,
    ownership: bool = False,
) -> QuantitativeValue:
    from regintel.fixtures.sources import source_text_catalog

    return QuantitativeValue(
        raw_value=source_text_catalog()[alias],
        normalized_value=decimal_from_wire(value) if value is not None else None,
        raw_unit="percent" if ownership else raw_unit,
        normalized_unit=unit,
        raw_currency=None if ownership else "INR",
        currency=None if ownership else "INR",
        period=FinancialPeriod(
            kind="UNKNOWN" if unknown_period else "INSTANT" if ownership else "DURATION",
            start_date=None if unknown_period or ownership else "2025-04-01",
            end_date=None if unknown_period or ownership else "2026-03-31",
            instant_date="2026-03-31" if ownership else None,
            raw_label=None,
        ),
        basis="UNKNOWN" if ownership else basis,
        raw_basis_label="direct equity" if ownership else None,
        denominator="issued equity share capital" if ownership else None,
        stake_kind="direct equity" if ownership else None,
        ownership_date="2026-03-31" if ownership else None,
        evidence_ids=(evidence_catalog()[alias].id,),
    )


def _relation(
    alias: str,
    *,
    kind: RelationType = "OWNS",
    subject: int = 1,
    target: int = 2,
    quantity: QuantitativeValue | None = None,
) -> RelationReference:
    return RelationReference(
        id=fixture_id(9001),
        relation_type=kind,
        subject_entity_id=fixture_id(subject),
        object_entity_id=fixture_id(target),
        state="CANDIDATE",
        evidence_ids=(evidence_catalog()[alias].id,),
        quantitative_context=quantity,
    )


def _support(*aliases: str) -> EvidenceSupport:
    catalog = evidence_catalog()
    return EvidenceSupport(records=tuple(catalog[alias] for alias in aliases))


def fixture_cases() -> CaseSuite:
    cases: list[FixtureCase] = []
    # Authored source anchors for future observation/effect tests; nothing is persisted.
    observation_sources = {
        fixture_id(9001): "owns_complete",
        fixture_id(9301): "corrected_ownership",
        fixture_id(9302): "subsidiary_complete",
        fixture_id(9303): "supplement_only",
        fixture_id(9304): "lender_complete",
        fixture_id(9305): "explicit_supersede",
        fixture_id(9306): "auditor_complete",
        fixture_id(9307): "explicit_addition",
        fixture_id(9308): "conflict_ownership",
    }

    def add(
        name: str,
        category: Category,
        aliases: tuple[str, ...],
        model: BaseModel,
        expectation: FutureExpectation,
        reason: str,
        *,
        payload: dict[str, JsonValue] | None = None,
        valid: bool = True,
    ) -> None:
        cases.append(
            FixtureCase(
                name=name,
                category=category,
                source_aliases=aliases,
                contract_name=type(model).__name__,
                payload=payload if payload is not None else _wire(model),
                structurally_valid=valid,
                future_expectation=expectation,
                reason=reason,
                provider_event=None,
            )
        )

    complete = _relation(
        "owns_complete",
        quantity=_quantity(
            "owns_complete",
            "51.00",
            unit="percent",
            ownership=True,
        ),
    )
    add(
        "supported ownership candidate",
        "positive_control",
        ("owns_complete",),
        complete,
        "SUPPORTED_CANDIDATE",
        "Exact disclosure includes direction, stake, denominator and date.",
    )
    add(
        "cross-page support",
        "positive_control",
        ("cross_page_first", "cross_page_second"),
        _support("cross_page_first", "cross_page_second"),
        "SUPPORTED_CANDIDATE",
        "Page-local evidence records remain separate for a bounded cross-page statement.",
    )
    add(
        "source injection is literal",
        "prompt_injection",
        ("prompt_injection",),
        _support("prompt_injection"),
        "IGNORE_SOURCE_INSTRUCTIONS",
        "The source command is untrusted text; no permissions or acceptance may follow it.",
    )
    invented = _wire(complete)
    invented["evidence_ids"] = [fixture_id(999999)]
    add(
        "well-shaped fabricated ID",
        "fabricated_evidence_ids",
        ("owns_complete",),
        complete,
        "REJECT",
        "UUID shape is valid, but the supplied evidence ID is absent from these sources.",
        payload=invented,
    )
    modified = _wire(_support("owns_complete"))
    record = _object(_sequence(modified["records"])[0])
    span = _object(record["span"])
    quote = span["quote"]
    if not isinstance(quote, str) or not quote:
        raise ValueError("Exact source quote required.")
    span["quote"] = "X" + quote[1:]
    add(
        "modified quote same length",
        "modified_quotes",
        ("owns_complete",),
        _support("owns_complete"),
        "REJECT",
        "Offsets match length but the quote differs from source.",
        payload=modified,
    )
    add(
        "same value wrong basis column",
        "standalone_consolidated_columns",
        ("revenue_standalone",),
        _quantity("revenue_standalone", basis="CONSOLIDATED"),
        "REJECT",
        "The same numeric value does not license changing the standalone column basis.",
    )
    add(
        "same value correct consolidated column",
        "positive_control",
        ("revenue_consolidated",),
        _quantity("revenue_consolidated", basis="CONSOLIDATED"),
        "SUPPORTED_CANDIDATE",
        "Column and reporting basis retain the disclosed consolidated context.",
    )
    add(
        "lakh interpreted as crore",
        "lakh_crore_mismatch",
        ("revenue_standalone",),
        _quantity("revenue_standalone", unit="crore"),
        "REJECT",
        "The lakh header does not support crore without deterministic normalization.",
    )
    add(
        "publication is not a period",
        "publication_date_without_period",
        ("publication_unknown",),
        _quantity(
            "publication_unknown",
            "20",
            unit="crore",
            raw_unit="INR crore",
            basis="UNKNOWN",
            unknown_period=True,
        ),
        "PRESERVE_UNKNOWN",
        "The source publication date supplies no financial-period evidence.",
    )
    for alias in ("dash_value", "blank_value"):
        add(
            alias + " stays unavailable",
            "dash_blank",
            (alias,),
            _quantity(alias, None),
            "PRESERVE_NULL",
            "A dash or blank supplies no authoritative zero.",
        )
    add(
        "co-occurrence proposed as ownership",
        "cooccurrence_without_relation",
        ("cooccurrence",),
        _relation("cooccurrence"),
        "REJECT",
        "Mentioning two companies is not relationship proof.",
    )
    missing = _wire(_quantity("owns_missing_context", "30", unit="percent", ownership=True))
    missing.update(
        denominator=None,
        ownership_date=None,
        basis="UNKNOWN",
        raw_basis_label=None,
        stake_kind=None,
    )
    missing["period"] = _wire(
        FinancialPeriod(
            kind="UNKNOWN",
            start_date=None,
            end_date=None,
            instant_date=None,
            raw_label=None,
        )
    )
    add(
        "ownership needs context review",
        "ownership_missing_denominator_date",
        ("owns_missing_context",),
        _quantity("owns_missing_context"),
        "REVIEW",
        "Missing denominator/date/basis prevents automatic acceptance.",
        payload=missing,
    )
    add(
        "may preserved in evidence",
        "may_to_certainty",
        ("supplier_may",),
        _support("supplier_may"),
        "PRESERVE_QUALIFIER",
        "May is retained as uncertainty.",
    )
    add(
        "may converted to certain supplier",
        "may_to_certainty",
        ("supplier_may",),
        _relation("supplier_may", kind="SUPPLIES_TO", subject=3),
        "REJECT",
        "A proposed future supply arrangement does not support a certain current relation.",
    )
    add(
        "negated supplier preserved",
        "positive_control",
        ("supplier_negated",),
        _support("supplier_negated"),
        "PRESERVE_NEGATION",
        "No supply is preserved as negation.",
    )
    add(
        "prior-year value proposed for current year",
        "wrong_year",
        ("revenue_prior_year",),
        _quantity("revenue_prior_year", "90.00"),
        "REJECT",
        "The source column belongs to FY2024-25.",
    )
    add(
        "undisclosed supplier",
        "undisclosed_supplier",
        ("cooccurrence",),
        _relation("cooccurrence", kind="SUPPLIES_TO", subject=3),
        "REJECT",
        "No supplier disclosure supports the proposed direction or entities.",
    )
    add(
        "schema-valid unsupported lender",
        "unsupported_json_claim",
        ("owns_complete",),
        _relation("owns_complete", kind="LENDS_TO"),
        "REJECT",
        "Valid JSON and entity IDs do not establish lending from ownership evidence.",
    )
    for event in ("timeout", "refusal"):
        cases.append(
            FixtureCase(
                name="mock provider " + event,
                category="model_timeout_refusal",
                source_aliases=(),
                contract_name=None,
                payload=None,
                structurally_valid=None,
                future_expectation="NO_ACCEPTED_OUTPUT",
                reason="Mock event has no accepted output.",
                provider_event="timeout" if event == "timeout" else "refusal",
            )
        )
    add(
        "ownership direction inverted",
        "direction_inversion",
        ("owns_complete",),
        _relation("owns_complete", subject=2, target=1),
        "REJECT",
        "Prism owning Helio reverses the disclosed Helio-to-Prism direction.",
    )
    corrupted = _wire(_support("ocr_region"))
    ocr_span = _object(_object(_sequence(corrupted["records"])[0])["span"])
    ocr_quote = ocr_span["quote"]
    if not isinstance(ocr_quote, str) or "10 crore" not in ocr_quote:
        raise ValueError("Expected authored OCR transcription is missing.")
    ocr_span["quote"] = ocr_quote.replace("10 crore", "1O crore")
    add(
        "ambiguous image transcription",
        "ocr_corruption",
        ("ocr_region",),
        _support("ocr_region"),
        "REVIEW",
        "Mock OCR changes 10 to 1O; preserve the image and route ambiguity to review.",
        payload=corrupted,
    )
    add(
        "conflicting later disclosure",
        "amendment_conflict",
        ("owns_complete", "conflict_ownership"),
        _support("owns_complete", "conflict_ownership"),
        "KEEP_SEPARATE",
        "A later date alone does not replace the earlier immutable observation.",
    )
    add(
        "paraphrase adds supply claim",
        "unsupported_paraphrase",
        ("owns_complete",),
        _relation("owns_complete", kind="SUPPLIES_TO"),
        "REJECT",
        "The proposed paraphrase adds an unsupported supply relationship.",
    )
    for effect_type, alias, affected_ids, new_ids in (
        ("ADD", "explicit_addition", [], [fixture_id(9307)]),
        ("CORRECT", "corrected_ownership", [fixture_id(9001)], [fixture_id(9301)]),
        ("SUPPLEMENT", "supplement_only", [fixture_id(9302)], [fixture_id(9303)]),
        ("SUPERSEDE", "explicit_supersede", [fixture_id(9304)], [fixture_id(9305)]),
        ("REMOVE", "explicit_removal", [fixture_id(9306)], []),
    ):
        effect = AmendmentEffect.model_validate(
            {
                "id": fixture_id(9100 + len(cases)),
                "effect_type": effect_type,
                "affected_observation_ids": affected_ids,
                "new_observation_ids": new_ids,
                "evidence_ids": [evidence_catalog()[alias].id],
                "reviewed_decision_id": None,
                "effective_date": None,
            }
        )
        add(
            "explicit " + effect_type.lower(),
            "explicit_amendment_effect",
            (alias,),
            effect,
            "EXPLICIT_EFFECT",
            "Only the named affected disclosure receives the supported effect.",
        )
    numeric = _wire(_quantity("revenue_standalone"))
    numeric["normalized_value"] = 100.0
    add(
        "financial JSON number rejected",
        "invalid_financial_wire",
        ("revenue_standalone",),
        _quantity("revenue_standalone"),
        "REJECT",
        "Financial wire values require decimal strings.",
        payload=numeric,
        valid=False,
    )
    return CaseSuite(
        fixture_version="1.0.0",
        synthetic=True,
        description="Synthetic structural cases and authored future expectations; no model runs.",
        observation_sources=observation_sources,
        cases=tuple(cases),
    )


def verify_case_suite(suite: CaseSuite) -> None:
    """Verify fixture integrity and current shape decisions; do not execute future expectations."""
    names = [case.name for case in suite.cases]
    if len(set(names)) != len(names):
        raise ValueError("Fixture case names must be unique.")
    categories = {case.category for case in suite.cases}
    if not REQUIRED_ADVERSARIAL_CATEGORIES <= categories:
        raise ValueError("Required adversarial coverage is incomplete.")
    catalog = evidence_catalog()
    if not set(suite.observation_sources.values()) <= catalog.keys():
        raise ValueError("Fixture observation anchor refers to an unknown source alias.")
    for case in suite.cases:
        if not set(case.source_aliases) <= catalog.keys():
            raise ValueError("Fixture refers to an unknown source alias.")
        if case.contract_name is None:
            if (
                case.payload is not None
                or case.structurally_valid is not None
                or case.provider_event is None
            ):
                raise ValueError("Mock provider events must not contain accepted contract output.")
            continue
        if case.contract_name not in PUBLIC_MODELS or case.payload is None:
            raise ValueError("Fixture contract reference is incomplete.")
        try:
            PUBLIC_MODELS[case.contract_name].model_validate_json(json.dumps(case.payload))
            valid = True
        except ValidationError:
            valid = False
        if valid != case.structurally_valid:
            raise ValueError("Fixture structural decision differs from the current contract.")
        if case.contract_name == "AmendmentEffect":
            effect = AmendmentEffect.model_validate_json(json.dumps(case.payload))
            declared_evidence = {catalog[alias].id for alias in case.source_aliases}
            if set(effect.evidence_ids) != declared_evidence:
                raise ValueError(
                    "Fixture effect evidence differs from its declared source aliases."
                )
            if not set(effect.affected_observation_ids + effect.new_observation_ids) <= (
                suite.observation_sources.keys()
            ):
                raise ValueError("Fixture effect refers to an unknown observation anchor.")
