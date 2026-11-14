"""Bound applicability requirements and source-specific attestation validation."""

import hashlib
import re
from pathlib import Path

from regintel.entities.models import canonical_bytes
from regintel.numerical.applicability_models import (
    ApplicabilityKind,
    NumericalApplicabilityAssertion,
    NumericalApplicabilityRequest,
    NumericalApplicabilityRequirements,
)
from regintel.numerical.bound_gate import bound_gate_configuration_sha256, validate_bound_numerical
from regintel.numerical.context_gate import CAPTION, UNIT_HEADER
from regintel.numerical.context_periods import normalized_words
from regintel.numerical.evidence_binding_models import BoundNumericalPhrase
from regintel.numerical.gate_models import StoredBoundNumericalGate
from regintel.validation.gate import _EXAMPLE, _INJECTION, _QUALIFIER

_REVIEW_CODES = frozenset({"CONTEXT_SCOPE", "BASIS", "SOURCE_LANGUAGE"})
_KINDS: tuple[ApplicabilityKind, ...] = ("CROSS_PAGE", "BASIS", "QUALIFIED_DEFAULT")
_BASIS_CLAUSE = re.compile(
    r"(?:Unless (?:stated|specified) otherwise(?: or the context requires otherwise)?, )?"
    r"the financial information(?: and financial ratios)? in this Prospectus are derived from "
    r"our Restated (?:Consolidated|Standalone) (?:Summary Statements|Financial Information)\.",
    re.I,
)


def applicability_configuration_sha256() -> str:
    package = Path(__file__).resolve().parent
    digest = hashlib.sha256(bound_gate_configuration_sha256().encode("ascii"))
    for name, path in (
        ("numerical/applicability_models.py", package / "applicability_models.py"),
        ("numerical/applicability.py", package / "applicability.py"),
        ("numerical/applicability_repository.py", package / "applicability_repository.py"),
        (
            "infra/migrations/0024_numerical_applicability_reviews.sql",
            package.parents[3] / "infra/migrations/0024_numerical_applicability_reviews.sql",
        ),
    ):
        body = path.read_bytes()
        digest.update(name.encode("ascii") + b"\0" + len(body).to_bytes(8, "big") + body)
    return digest.hexdigest()


def _text(phrase: BoundNumericalPhrase) -> str:
    # Grammar input only. Exact original words remain in the immutable binding.
    return normalized_words(" ".join(word.reference.quote for word in phrase.words))


def _selection(gate: StoredBoundNumericalGate) -> dict[str, object]:
    binding = gate.source_input.binding
    return {
        "gate_run_id": gate.result.id,
        "gate_input_sha256": gate.result.input_sha256,
        "gate_result_sha256": hashlib.sha256(canonical_bytes(gate.result)).hexdigest(),
        "binding_id": binding.id,
        "value_cell_id": binding.cells[0].artifact_cell_id,
        "row_cell_id": binding.cells[1].artifact_cell_id,
        "period_cell_id": binding.cells[2].artifact_cell_id,
        "reviewed_page_indices": tuple(
            sorted({phrase.words[0].evidence.source.page_index for phrase in binding.phrases})
        ),
    }


def _assertion(
    phrase: BoundNumericalPhrase, kind: ApplicabilityKind
) -> NumericalApplicabilityAssertion:
    return NumericalApplicabilityAssertion(
        kind=kind,
        role=phrase.role,
        ordinal=phrase.ordinal,
        evidence_ids=tuple(word.evidence.id for word in phrase.words),
    )


def _qualified_default(phrase: BoundNumericalPhrase) -> bool:
    text = _text(phrase)
    if phrase.role == "unit_header":
        return (
            UNIT_HEADER.fullmatch(text) is not None
            and re.search(r"\bunless otherwise (?:specified|stated)\b", text, re.I) is not None
        )
    return phrase.role == "basis_context" and _BASIS_CLAUSE.fullmatch(text) is not None


def applicability_requirements(
    gate: StoredBoundNumericalGate,
) -> NumericalApplicabilityRequirements:
    gate = StoredBoundNumericalGate.model_validate(gate.model_dump(mode="python"))
    result = gate.result
    binding = gate.source_input.binding
    blockers: list[str] = []
    if result.state != "REVIEW_REQUIRED":
        blockers.append("Applicability review requires an unresolved review gate.")
    if result.configuration_sha256 != bound_gate_configuration_sha256():
        blockers.append("Run the installed numerical gates before applicability review.")
    elif validate_bound_numerical(gate.source_input) != result:
        blockers.append("The retained gate differs from exact deterministic replay.")
    for check in result.checks:
        if check.state == "FAIL" or (check.state == "REVIEW" and check.code not in _REVIEW_CODES):
            blockers.append(f"{check.code} requires resolution before applicability review.")
    quantity = result.quantity_proposal
    if (
        quantity is None
        or quantity.basis == "UNKNOWN"
        or quantity.currency is None
        or quantity.normalized_unit is None
        or quantity.period.kind != "DURATION"
        or quantity.period.start_date is None
        or quantity.period.end_date is None
    ):
        blockers.append("A complete source-supported monetary duration and basis are required.")
    checks = {check.code: check.state for check in result.checks}
    scope = next(phrase for phrase in binding.phrases if phrase.role == "table_scope")
    if CAPTION.fullmatch(_text(scope)) is None:
        blockers.append("The table caption requires an independently supported issuer statement.")
    value_page = binding.cells[0].source.page_index
    assertions: list[NumericalApplicabilityAssertion] = []
    language_blocked = False
    for phrase in binding.phrases:
        if phrase.words[0].evidence.source.page_index != value_page:
            assertions.append(_assertion(phrase, "CROSS_PAGE"))
        if phrase.role == "basis_context" and checks["BASIS"] == "REVIEW":
            if _BASIS_CLAUSE.fullmatch(_text(phrase)) is None:
                blockers.append("The separate basis clause has unsupported applicability wording.")
            assertions.append(_assertion(phrase, "BASIS"))
        text = _text(phrase)
        if _INJECTION.search(text) or _EXAMPLE.search(text):
            language_blocked = True
        if _QUALIFIER.search(text):
            if _qualified_default(phrase):
                assertions.append(_assertion(phrase, "QUALIFIED_DEFAULT"))
            else:
                language_blocked = True
    if language_blocked:
        blockers.append(
            "Instruction, illustrative, negated or unsupported qualified context is blocked."
        )
    if checks["CONTEXT_SCOPE"] == "REVIEW" and not any(
        item.kind == "CROSS_PAGE" for item in assertions
    ):
        blockers.append(
            "The unresolved statement scope is outside supported cross-page applicability."
        )
    if checks["BASIS"] == "REVIEW" and not any(item.kind == "BASIS" for item in assertions):
        blockers.append("The unresolved basis lacks a supported separate statement clause.")
    if not assertions:
        blockers.append("This gate has no supported applicability assertions to review.")
    return NumericalApplicabilityRequirements.model_validate(
        _selection(gate)
        | {"assertions": tuple(assertions), "eligible": not blockers, "blockers": tuple(blockers)}
    )


def require_applicability_membership(
    gate: StoredBoundNumericalGate, request: NumericalApplicabilityRequest
) -> None:
    """Validate immutable historical references without applying current gate policy."""
    gate = StoredBoundNumericalGate.model_validate(gate.model_dump(mode="python"))
    request = NumericalApplicabilityRequest.model_validate(request.model_dump(mode="python"))
    supplied = request.model_dump(mode="python")
    if any(supplied[key] != value for key, value in _selection(gate).items()):
        raise ValueError("Applicability review must retain the exact gate, source cells and pages.")
    phrases = gate.source_input.binding.phrases
    order = {(phrase.role, phrase.ordinal): index for index, phrase in enumerate(phrases)}
    keys: list[tuple[int, int]] = []
    for assertion in request.assertions:
        index = order.get((assertion.role, assertion.ordinal))
        if index is None or assertion.evidence_ids != tuple(
            word.evidence.id for word in phrases[index].words
        ):
            raise ValueError(
                "Applicability assertions require complete ordered source phrase words."
            )
        keys.append((index, _KINDS.index(assertion.kind)))
    if keys != sorted(keys):
        raise ValueError("Applicability assertions must retain source phrase and decision order.")


def validate_applicability_request(
    gate: StoredBoundNumericalGate, request: NumericalApplicabilityRequest
) -> None:
    require_applicability_membership(gate, request)
    required = applicability_requirements(gate)
    if not required.eligible or request.assertions != required.assertions:
        raise ValueError(
            "Applicability review requires every supported assertion and resolved prerequisite."
        )
