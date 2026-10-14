"""Extraction shape/binding tests use explicit synthetic evidence, never gold scores."""

import hashlib

import pytest
from pydantic import ValidationError

from regintel.candidates.models import (
    CandidateBundle,
    DraftCandidate,
    ExtractionConfiguration,
    ExtractionInput,
    ExtractionIssue,
    MetricDefinition,
    RawQuantity,
    SourceSpan,
    effective_mentions,
)
from regintel.contracts.models import TextEvidence, TextSpan
from regintel.entities.models import (
    EntityMention,
    EntityReview,
    EntityRun,
    EvidenceAnchor,
    MentionResolution,
    ResolutionProposal,
    ResolverConfiguration,
    canonical_bytes,
)
from regintel.fixtures.sources import evidence_catalog, fixture_id

ALPHA = "Alpha Energy Limited"
BETA = "Beta Solar Limited"


def make_input(
    text: str = f"{ALPHA} owns {BETA}.",
    *,
    start: int = 0,
    alpha_state: str = "RESOLVED",
    beta_state: str = "RESOLVED",
    metrics: tuple[MetricDefinition, ...] = (),
) -> ExtractionInput:
    template = evidence_catalog()["owns_complete"]
    assert isinstance(template, TextEvidence)
    evidence = template.model_copy(
        update={
            "span": TextSpan(
                block_id=template.span.block_id, start=start, end=start + len(text), quote=text
            )
        }
    )
    mentions: list[EntityMention] = []
    for index, (name, state) in enumerate(((ALPHA, alpha_state), (BETA, beta_state))):
        offset = 0
        while (position := text.find(name, offset)) >= 0:
            entity_id = fixture_id(101 + index)
            proposals = (
                (
                    ResolutionProposal(
                        entity_id=entity_id,
                        method="FUZZY" if state == "REVIEW" else "EXACT_ALIAS",
                        score=91.0 if state == "REVIEW" else None,
                    ),
                )
                if state != "UNRESOLVED"
                else ()
            )
            mention = EntityMention(
                id=fixture_id(201 + index * 10000 + position),
                kind="NAME",
                support=EvidenceAnchor(
                    evidence_id=evidence.id,
                    start=start + position,
                    end=start + position + len(name),
                    quote=name,
                ),
                resolution=MentionResolution.model_validate(
                    {
                        "state": state,
                        "entity_id": entity_id if state == "RESOLVED" else None,
                        "method": "EXACT_ALIAS" if state == "RESOLVED" else None,
                        "reason": "SYNTHETIC_FIXTURE",
                        "proposals": proposals,
                    }
                ),
            )
            mentions.append(mention)
            offset = position + len(name)
    run = EntityRun(
        id=fixture_id(100),
        parse_version_id=evidence.source.parse_version_id,
        artifact_sha256="a" * 64,
        registry_revision=2,
        registry_sha256="b" * 64,
        configuration=ResolverConfiguration(
            spacy_version="fixture-only", rapidfuzz_version="fixture-only", code_sha256="c" * 64
        ),
        evidence_ids=(evidence.id,),
        mentions=tuple(mentions),
    )
    return ExtractionInput(
        parse_version_id=evidence.source.parse_version_id,
        entity_run=run,
        evidence=(evidence,),
        metrics=metrics,
    )


def support(source: ExtractionInput, quote: str | None = None) -> SourceSpan:
    evidence = source.evidence[0]
    quote = evidence.span.quote if quote is None else quote
    start = evidence.span.start + evidence.span.quote.index(quote)
    return SourceSpan(evidence_id=evidence.id, start=start, end=start + len(quote), quote=quote)


def metric(*, numeric: bool = True, number: int = 301, cue: str = "revenue") -> MetricDefinition:
    return MetricDefinition(
        id=fixture_id(number),
        key=f"metric_{number}",
        label=cue,
        kind="numeric_fact" if numeric else "narrative_fact",
        cue_phrases=(cue,),
    )


def relation(source: ExtractionInput) -> DraftCandidate:
    mentions = effective_mentions(source)
    alpha = next(item for item in mentions if item.entity_id == fixture_id(101))
    beta = next(item for item in mentions if item.entity_id == fixture_id(102))
    return DraftCandidate(
        kind="relation",
        subject_entity_id=alpha.entity_id,
        subject_mention_id=alpha.mention_id,
        object_entity_id=beta.entity_id,
        object_mention_id=beta.mention_id,
        relation_type="OWNS",
        supports=(support(source),),
        raw_text=source.evidence[0].span.quote,
    )


def review(source: ExtractionInput, *, reject: bool = False) -> EntityReview:
    mention = source.entity_run.mentions[0]
    return EntityReview(
        id=fixture_id(400),
        run_id=source.entity_run.id,
        mention_id=mention.id,
        decision="REJECT" if reject else "RESOLVE",
        entity_id=None if reject else fixture_id(101),
        support_evidence_ids=(source.evidence[0].id,),
        review_note="Explicit synthetic review, no real disclosure.",
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"quote": ""},
        {"quote": "x\x00", "end": 2},
        {"start": 1},
        {"end": 0},
        {"quote": "x" * 20001, "end": 20001},
        {"evidence_id": "fake"},
        {"page_index": 0},
        {"start": True},
    ],
)
def test_source_span_rejects_invalid_wire_bounds(updates: dict[str, object]) -> None:
    values: dict[str, object] = {"evidence_id": fixture_id(1), "start": 0, "end": 1, "quote": "x"}
    with pytest.raises(ValidationError):
        SourceSpan.model_validate(values | updates)


def test_unicode_offsets_are_codepoints_and_absolute() -> None:
    source = make_input("🙂 " + ALPHA + " owns " + BETA + ".", start=79)
    span = support(source, ALPHA)
    assert span.start == 81
    assert span.end - span.start == len(ALPHA)
    assert SourceSpan.model_validate_json(span.model_dump_json()) == span


@pytest.mark.parametrize(
    "updates",
    [
        {"cue_phrases": ()},
        {"cue_phrases": ("revenue", "revenue")},
        {"cue_phrases": (" revenue",)},
        {"cue_phrases": ("revenue\x00",)},
        {"cue_phrases": ("x" * 129,)},
        {"cue_phrases": ("%",)},
        {"label": "Revenue\x00"},
        {"key": "Revenue"},
        {"kind": "relation"},
        {"formula": "a/b"},
    ],
)
def test_metric_configuration_rejects_unbounded_or_interpreted_fields(
    updates: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        MetricDefinition.model_validate(metric().model_dump(mode="python") | updates)


def test_literal_unicode_metric_cues_are_preserved_without_regex_execution() -> None:
    value = metric().model_copy(update={"cue_phrases": ("Straße", "STRASSE", "revenue.*")})
    assert MetricDefinition.model_validate(value.model_dump(mode="python")) == value


@pytest.mark.parametrize(
    "updates",
    [
        {"state": "ACCEPTED"},
        {"subject_entity_id": "fake"},
        {"metric_id": fixture_id(301)},
        {"object_entity_id": None},
        {"object_mention_id": None},
        {"relation_type": "KNOWS"},
        {"object_entity_id": fixture_id(101)},
        {"supports": ()},
        {"raw_text": ""},
        {"raw_text": "\x00"},
    ],
)
def test_draft_cannot_change_authority_or_endpoint_shape(updates: dict[str, object]) -> None:
    candidate = relation(make_input())
    with pytest.raises(ValidationError):
        DraftCandidate.model_validate(candidate.model_dump(mode="python") | updates)


def test_raw_quantity_forbids_model_interpretation_fields() -> None:
    source = make_input(f"{ALPHA} revenue 12.", metrics=(metric(),))
    quantity = RawQuantity(value=support(source, "12"))
    for field in ("normalized_value", "normalized_unit", "instant_date", "effective_date"):
        with pytest.raises(ValidationError):
            RawQuantity.model_validate(quantity.model_dump(mode="python") | {field: "12"})


def test_bundle_collection_and_duplicate_gates() -> None:
    candidate = relation(make_input())
    with pytest.raises(ValidationError):
        CandidateBundle(numeric_facts=(candidate,))
    with pytest.raises(ValidationError):
        CandidateBundle(relations=(candidate, candidate))
    assert CandidateBundle().model_dump(mode="json") == {
        "numeric_facts": [],
        "narrative_facts": [],
        "relations": [],
        "issues": [],
    }


def test_effective_review_resolves_fuzzy_but_rejection_suppresses_exact() -> None:
    fuzzy = make_input(alpha_state="REVIEW")
    assert [item.entity_id for item in effective_mentions(fuzzy)] == [fixture_id(102)]
    decision = review(fuzzy)
    resolved = fuzzy.model_copy(update={"reviews": (decision,)})
    effective = effective_mentions(
        ExtractionInput.model_validate(resolved.model_dump(mode="python"))
    )
    assert {item.entity_id for item in effective} == {fixture_id(101), fixture_id(102)}
    assert (
        next(item for item in effective if item.entity_id == fixture_id(101)).review_id
        == decision.id
    )
    exact = make_input()
    rejected = exact.model_copy(update={"reviews": (review(exact, reject=True),)})
    assert [item.entity_id for item in effective_mentions(rejected)] == [fixture_id(102)]


@pytest.mark.parametrize("field", ["run_id", "mention_id", "entity_id"])
def test_reviews_cannot_supply_new_ids_outside_frozen_run(field: str) -> None:
    source = make_input(alpha_state="REVIEW")
    decision = review(source).model_copy(update={field: fixture_id(999)})
    with pytest.raises(ValidationError):
        ExtractionInput.model_validate(source.model_dump(mode="python") | {"reviews": (decision,)})


def test_input_detects_missing_duplicate_foreign_or_modified_sources() -> None:
    source = make_input()
    evidence = source.evidence[0]
    variants: tuple[dict[str, object], ...] = (
        {"evidence": ()},
        {"evidence": (evidence, evidence)},
        {"parse_version_id": fixture_id(999)},
        {"metrics": (metric(), metric())},
        {
            "evidence": (
                evidence.model_copy(
                    update={
                        "span": evidence.span.model_copy(
                            update={"quote": evidence.span.quote.replace(ALPHA, "X" * len(ALPHA))}
                        )
                    }
                ),
            )
        },
    )
    for variant in variants:
        with pytest.raises(ValidationError):
            ExtractionInput.model_validate(source.model_dump(mode="python") | variant)


def test_input_and_configuration_hashes_bind_exact_source_and_metric_config() -> None:
    source = make_input()
    assert source.sha256 == hashlib.sha256(canonical_bytes(source)).hexdigest()
    assert make_input(metrics=(metric(),)).sha256 != source.sha256
    config = ExtractionConfiguration(code_sha256="a" * 64)
    assert config.sha256 == hashlib.sha256(canonical_bytes(config)).hexdigest()


def test_issue_source_ids_and_storable_boundaries() -> None:
    with pytest.raises(ValidationError):
        ExtractionIssue(code="MISSING_VALUE", evidence_ids=(fixture_id(1),) * 2, message="x")
    with pytest.raises(ValidationError):
        ExtractionIssue(code="MISSING_VALUE", message="x" * 501)
    with pytest.raises(ValidationError):
        ExtractionIssue.model_validate({"code": "ACCEPTED", "message": "x"})
