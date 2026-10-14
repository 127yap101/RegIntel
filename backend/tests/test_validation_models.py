"""Strict staged contracts use controlled evidence; no research score is implied."""

from typing import get_args

import pytest
from pydantic import ValidationError
from test_candidate_models import ALPHA, make_input, metric, support

from regintel.candidates.extraction import current_configuration, extract
from regintel.candidates.models import CandidateBundle, DraftCandidate, ExtractionInput
from regintel.candidates.records import materialize
from regintel.entities.models import EntityReview
from regintel.fixtures.sources import fixture_id
from regintel.validation.models import (
    CheckCode,
    NumericMetricPolicy,
    ReviewDecision,
    ValidationCheck,
    ValidationInput,
    ValidationResult,
)


def money_policy(**updates: object) -> NumericMetricPolicy:
    return NumericMetricPolicy.model_validate(
        {
            "id": fixture_id(801),
            "metric_id": fixture_id(301),
            "quantity_kind": "MONEY",
            "period_kind": "DURATION",
            "allowed_unit_labels": ("crore", "INR"),
            "required_reporting_basis": True,
            "review_note": "Synthetic reviewed metric semantics.",
        }
        | updates
    )


def validation_input(
    source: ExtractionInput | None = None,
    *,
    bundle: CandidateBundle | None = None,
    policies: tuple[NumericMetricPolicy, ...] = (),
    reviews: tuple[EntityReview, ...] | None = None,
    table: bool = False,
) -> ValidationInput:
    source = make_input() if source is None else source
    bundle = extract(source) if bundle is None else bundle
    run = materialize(source, current_configuration(), bundle)
    return ValidationInput(
        candidate_run=run,
        source=source,
        source_input_sha256=run.input_sha256,
        entity_reviews=source.reviews if reviews is None else reviews,
        policies=policies,
        table_evidence_ids=(source.evidence[0].id,) if table else (),
    )


def numeric_draft(source: ExtractionInput, raw: str) -> DraftCandidate:
    from regintel.candidates.models import RawQuantity, effective_mentions

    subject = effective_mentions(source)[0]
    return DraftCandidate(
        kind="numeric_fact",
        subject_entity_id=subject.entity_id,
        subject_mention_id=subject.mention_id,
        metric_id=source.metrics[0].id,
        supports=(support(source),),
        raw_text=source.evidence[0].span.quote,
        raw_quantity=RawQuantity(value=support(source, raw)),
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"allowed_unit_labels": ("MW",)},
        {"allowed_unit_labels": ("crore", "crore")},
        {"allowed_unit_labels": ()},
        {"allowed_unit_labels": ("crores?",)},
        {"quantity_kind": "ARBITRARY"},
        {"period_kind": "UNKNOWN"},
        {"review_note": " "},
        {"review_note": "x\x00y"},
        {"extra": True},
        {"required_reporting_basis": "true"},
    ],
)
def test_invalid_metric_policies_are_not_accepted(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        money_policy(**updates)


@pytest.mark.parametrize(
    "updates",
    [
        {"source_input_sha256": "d" * 64},
        {"table_evidence_ids": (fixture_id(999),)},
        {"table_evidence_ids": (fixture_id(10), fixture_id(10))},
        {"policies": (money_policy(),)},
        {"transcription_evidence_ids": (fixture_id(999),)},
    ],
)
def test_input_cannot_forge_linked_membership(updates: dict[str, object]) -> None:
    value = validation_input()
    with pytest.raises(ValidationError):
        ValidationInput.model_validate(value.model_dump(mode="python") | updates)


def test_frozen_source_cannot_replace_candidate_text_or_metric() -> None:
    source = make_input(f"{ALPHA} revenue 12 crore.", metrics=(metric(),))
    value = validation_input(source)
    modified = make_input(f"{ALPHA} revenue 13 crore.", metrics=(metric(),))
    with pytest.raises(ValidationError):
        ValidationInput.model_validate(value.model_dump(mode="python") | {"source": modified})


@pytest.mark.parametrize("change", ["missing", "duplicate", "false_review", "false_quarantine"])
def test_result_cannot_bypass_the_complete_check_matrix(change: str) -> None:
    checks = tuple(
        ValidationCheck.model_validate(
            {"code": code, "state": "PASS", "message": "Synthetic pass."}
        )
        for code in get_args(CheckCode)
    )
    value: dict[str, object] = {
        "candidate_id": fixture_id(900),
        "state": "PASS",
        "checks": checks,
        "quantity": None,
        "context_supports": (),
        "reviewer_eligible": True,
    }
    if change == "missing":
        value["checks"] = checks[:1]
    elif change == "duplicate":
        value["checks"] = (checks[0],) * 16
    elif change == "false_review":
        value["checks"] = (checks[0].model_copy(update={"state": "REVIEW"}), *checks[1:])
        value["state"] = "REVIEW"
    else:
        value["checks"] = (checks[0].model_copy(update={"state": "FAIL"}), *checks[1:])
        value["state"] = "QUARANTINED"
    with pytest.raises(ValidationError):
        ValidationResult.model_validate(value)


@pytest.mark.parametrize("decision", ["ACCEPT", "ACCEPTED", "PUBLISHED"])
def test_review_cannot_claim_current_acceptance_or_publication(decision: str) -> None:
    source = make_input()
    with pytest.raises(ValidationError):
        ReviewDecision(
            id=fixture_id(990),
            validation_run_id=fixture_id(991),
            candidate_id=fixture_id(992),
            decision=decision,
            supports=(support(source),),
            review_note="Synthetic review.",
        )


def test_staged_review_keeps_exact_support_and_is_frozen() -> None:
    source = make_input()
    review = ReviewDecision(
        id=fixture_id(990),
        validation_run_id=fixture_id(991),
        candidate_id=fixture_id(992),
        decision="APPROVE_FOR_PUBLICATION",
        supports=(support(source),),
        review_note="Synthetic review with exact evidence.",
    )
    assert ReviewDecision.model_validate_json(review.model_dump_json()) == review
    with pytest.raises(ValidationError):
        review.decision = "REJECT"  # type: ignore[misc]
