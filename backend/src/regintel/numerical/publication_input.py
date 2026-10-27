"""Reproduce numerical checks and retain typed proof; never create accepted state."""

import hashlib
from pathlib import Path
from typing import Literal, get_args

from regintel.entities.models import canonical_bytes
from regintel.numerical.bound_gate import bound_gate_configuration_sha256, validate_bound_numerical
from regintel.numerical.gate_models import GateCode, StoredBoundNumericalGate
from regintel.numerical.publication_models import (
    NumericalPublicationInput,
    NumericalPublicationPreparation,
    publication_input_identity,
)
from regintel.numerical.review_models import ReviewedNumericalContext, require_reviewable
from regintel.numerical.review_repository import review_configuration_sha256
from regintel.validation.models import CheckCode, ValidationCheck

type CheckState = Literal["PASS", "REVIEW", "FAIL"]


def publication_input_configuration_sha256() -> str:
    digest = hashlib.sha256(
        (bound_gate_configuration_sha256() + review_configuration_sha256()).encode("ascii")
    )
    package = Path(__file__).resolve().parent
    for name in (
        "publication_models.py",
        "publication_input.py",
        "publication_input_repository.py",
    ):
        body = (package / name).read_bytes()
        digest.update(name.encode("ascii") + b"\0" + len(body).to_bytes(8, "big") + body)
    return digest.hexdigest()


def prepare_numerical_publication(
    gate: StoredBoundNumericalGate, review: ReviewedNumericalContext | None
) -> NumericalPublicationPreparation:
    gate = StoredBoundNumericalGate.model_validate(gate.model_dump(mode="python"))
    if validate_bound_numerical(gate.source_input) != gate.result:
        raise ValueError("The installed numerical gate must reproduce the exact retained input.")
    if review is not None:
        review = ReviewedNumericalContext.model_validate(review.model_dump(mode="python"))
    result = gate.result
    result_sha = hashlib.sha256(canonical_bytes(result)).hexdigest()
    retained = gate.source_input.context.source_input
    mapped: dict[CheckCode, tuple[GateCode, ...]] = {
        "SOURCE": ("SOURCE", "EXACT_WORDS", "BOUND_EVIDENCE", "FRESH_CONTEXT"),
        "ENTITY": ("ISSUER",),
        "TABLE_CONTEXT": ("TABLE", "BOUND_EVIDENCE"),
        "SOURCE_SCOPE": ("CONTEXT_SCOPE", "SOURCE_LANGUAGE", "FRESH_CONTEXT"),
        "ATTRIBUTION": ("ISSUER", "METRIC", "CONTEXT_SCOPE"),
        "METRIC": ("METRIC",),
        "VALUE": ("VALUE",),
        "UNIT": ("UNIT",),
        "CURRENCY": ("CURRENCY",),
        "PERIOD": ("PERIOD",),
        "BASIS": ("BASIS",),
    }
    bound = {check.code: check for check in result.checks}
    checks: dict[CheckCode, ValidationCheck] = {}
    for code, dependencies in mapped.items():
        states = {bound[key].state for key in dependencies}
        state: CheckState = (
            "FAIL" if "FAIL" in states else "REVIEW" if "REVIEW" in states else "PASS"
        )
        checks[code] = ValidationCheck(
            code=code,
            state=state,
            message="Fresh exact table/word context: " + ", ".join(dependencies) + ".",
        )
    money = (
        retained.metric is not None
        and retained.metric.kind == "numeric_fact"
        and retained.policy is not None
        and retained.policy.metric_id == retained.metric.id
        and retained.policy.quantity_kind == "MONEY"
        and retained.policy.period_kind == "DURATION"
    )
    not_applicable: tuple[CheckCode, ...] = (
        "DIRECTION",
        "DENOMINATOR",
        "STAKE_KIND",
        "OWNERSHIP_DATE",
    )
    for code in not_applicable:
        checks[code] = ValidationCheck(
            code=code,
            state="PASS" if money else "FAIL",
            message="No relation or ownership is inferred for this monetary-duration metric."
            if money
            else "This adapter supports only reviewed monetary-duration metrics.",
        )
    if not money:
        checks["METRIC"] = ValidationCheck(
            code="METRIC",
            state="FAIL",
            message="A reviewed monetary-duration metric policy is required.",
        )
    reviewed: CheckState
    if review is None:
        reviewed = "REVIEW"
        explanation = "The selected gate needs its actual immutable context confirmation."
    else:
        require_reviewable(gate, review.request)
        if (
            review.gate_input_sha256 != result.input_sha256
            or review.gate_result_sha256 != result_sha
            or review.configuration_sha256 != review_configuration_sha256()
        ):
            raise ValueError(
                "Context confirmation must match the exact gate and installed review configuration."
            )
        reviewed = "PASS" if review.request.decision == "CONFIRM_CONTEXT" else "FAIL"
        explanation = (
            "Exact confirmed context retained; publication still needs its separate atomic adapter."
        )
        if reviewed == "FAIL":
            explanation = "The immutable context review rejects this proposed publication input."
    checks["EXTRACTIVE_REVIEW"] = ValidationCheck(
        code="EXTRACTIVE_REVIEW", state=reviewed, message=explanation
    )
    ordered = tuple(checks[code] for code in get_args(CheckCode))
    supported = all(check.state == "PASS" for check in ordered)
    configuration = publication_input_configuration_sha256()
    proposed = None
    if supported:
        assert review is not None and retained.metric is not None and retained.policy is not None
        assert result.quantity_proposal is not None
        proposed = NumericalPublicationInput(
            id=publication_input_identity(result.id, review.id, configuration),
            gate_run_id=result.id,
            gate_input_sha256=result.input_sha256,
            gate_result_sha256=result_sha,
            configuration_sha256=configuration,
            gate=result,
            subject_entity_id=retained.draft.subject_entity_id,
            metric=retained.metric,
            policy=retained.policy,
            quantity=result.quantity_proposal,
            proof=gate.source_input.binding,
            context_review=review,
        )
    return NumericalPublicationPreparation(
        gate_run_id=result.id,
        gate_input_sha256=result.input_sha256,
        gate_result_sha256=result_sha,
        configuration_sha256=configuration,
        state="READY_FOR_ADAPTER" if supported else "BLOCKED",
        checks=ordered,
        proposed_input=proposed,
    )
