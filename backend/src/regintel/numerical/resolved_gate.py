"""Replay exact reviewed applicability without changing source quantity or history."""

import hashlib
from pathlib import Path

from regintel.entities.models import canonical_bytes
from regintel.numerical.applicability import (
    applicability_configuration_sha256,
    validate_applicability_request,
)
from regintel.numerical.gate_models import (
    ApplicabilityGateInput,
    BoundGateCheck,
    BoundNumericalGateRun,
    gate_identity,
)

_REVIEW_CODES = frozenset({"CONTEXT_SCOPE", "BASIS", "SOURCE_LANGUAGE"})
_REVIEWED_MESSAGE = (
    "Exact reviewed source applicability supports this check; original qualifications "
    "remain in the retained evidence binding."
)


def resolved_gate_configuration_sha256() -> str:
    package = Path(__file__).resolve().parent
    digest = hashlib.sha256(applicability_configuration_sha256().encode("ascii"))
    for name, path in (
        ("numerical/resolved_gate.py", package / "resolved_gate.py"),
        ("numerical/resolved_gate_repository.py", package / "resolved_gate_repository.py"),
        (
            "infra/migrations/0025_numerical_applicability_gates.sql",
            package.parents[3] / "infra/migrations/0025_numerical_applicability_gates.sql",
        ),
    ):
        body = path.read_bytes()
        digest.update(name.encode("ascii") + b"\0" + len(body).to_bytes(8, "big") + body)
    return digest.hexdigest()


def validate_resolved_numerical(value: ApplicabilityGateInput) -> BoundNumericalGateRun:
    """The repository separately proves that both immutable inputs are actually stored."""
    value = ApplicabilityGateInput.model_validate(value.model_dump(mode="python"))
    review = value.applicability
    if review.configuration_sha256 != applicability_configuration_sha256():
        raise ValueError("Applicability must be reviewed under the installed configuration.")
    # This replays the base gate with current policy, rejects unsupported language and
    # other missing prerequisites, and requires every exact phrase/cell/page assertion.
    validate_applicability_request(value.base_gate(), review.request)
    checks: list[BoundGateCheck] = []
    for check in value.base_result.checks:
        if check.state == "PASS":
            checks.append(check)
        elif check.state == "REVIEW" and check.code in _REVIEW_CODES:
            checks.append(BoundGateCheck(code=check.code, state="PASS", message=_REVIEWED_MESSAGE))
        else:
            raise ValueError("Applicability cannot override another numerical gate or failure.")
    input_sha = hashlib.sha256(canonical_bytes(value)).hexdigest()
    config_sha = resolved_gate_configuration_sha256()
    return BoundNumericalGateRun.model_validate(
        value.base_result.model_dump(mode="python")
        | {
            "id": gate_identity(input_sha, config_sha),
            "input_sha256": input_sha,
            "configuration_sha256": config_sha,
            "state": "READY_FOR_REVIEW",
            "checks": tuple(checks),
        }
    )
