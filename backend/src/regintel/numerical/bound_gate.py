"""Bound word/context checks; this gate never creates a legacy acceptance or review."""

import hashlib
from pathlib import Path

from regintel.entities.models import canonical_bytes
from regintel.numerical.context_gate import inspect_context
from regintel.numerical.context_models import WordPhrase
from regintel.numerical.evidence_binding import binding_configuration_sha256
from regintel.numerical.gate_models import (
    GATE_CODES,
    BoundGateCheck,
    BoundGateInput,
    BoundNumericalGateRun,
    gate_identity,
)
from regintel.validation.gate import _EXAMPLE, _INJECTION, _QUALIFIER


def bound_gate_configuration_sha256() -> str:
    package = Path(__file__).resolve().parents[1]
    names = (
        "numerical/gate_models.py",
        "numerical/bound_gate.py",
        "numerical/gate_repository.py",
        "numerical/context_models.py",
        "numerical/context_gate.py",
        "numerical/context_periods.py",
        "numerical/context_records.py",
        "numerical/context_inputs.py",
        "numerical/context_storage.py",
        "numerical/evidence_binding.py",
        "numerical/evidence_binding_models.py",
        "numerical/evidence_binding_repository.py",
        "numerical/models.py",
        "entities/models.py",
        "contracts/models.py",
        "contracts/primitives.py",
        "validation/models.py",
        "validation/quantity.py",
        "validation/gate.py",
    )
    digest = hashlib.sha256()
    for name in names:
        body = (package / name).read_bytes()
        digest.update(name.encode("ascii") + b"\0" + len(body).to_bytes(8, "big") + body)
    migration = package.parents[2] / "infra/migrations/0017_bound_numerical_gates.sql"
    body = migration.read_bytes()
    digest.update(
        b"infra/migrations/0017_bound_numerical_gates.sql\0" + len(body).to_bytes(8, "big") + body
    )
    return digest.hexdigest()


def _phrases(value: BoundGateInput) -> tuple[tuple[str, int, WordPhrase], ...]:
    draft = value.context.source_input.draft
    result: list[tuple[str, int, WordPhrase]] = [
        ("value", 0, draft.value.phrase),
        ("row_label", 0, draft.row_label.phrase),
        ("period_header", 0, draft.period_header.phrase),
        ("issuer_header", 0, draft.issuer_header),
        ("table_scope", 0, draft.table_scope),
        ("unit_header", 0, draft.unit_header),
    ]
    if draft.basis_context is not None:
        result.append(("basis_context", 0, draft.basis_context))
    result.extend(
        ("currency_definition", i, phrase) for i, phrase in enumerate(draft.currency_definitions)
    )
    result.extend(
        ("fiscal_definition", i, phrase) for i, phrase in enumerate(draft.fiscal_definitions)
    )
    return tuple(result)


def _bound(value: BoundGateInput) -> bool:
    record, binding = value.context, value.binding
    if (
        binding.context_record_id != record.id
        or binding.context_input_sha256 != record.input_sha256
        or binding.context_inspection_sha256 != record.inspection_sha256
        or binding.filing_version_id != record.filing_version_id
        or binding.source_blob_id != record.source_blob_id
        or binding.source_sha256 != record.source_sha256
        or binding.binding_configuration_sha256 != binding_configuration_sha256()
    ):
        return False
    expected = _phrases(value)
    if tuple((p.role, p.ordinal) for p in binding.phrases) != tuple(
        (role, index) for role, index, _ in expected
    ):
        return False
    pages = {page.id: page for page in record.source_input.pages}
    draft = record.source_input.draft
    for cell, support in zip(
        binding.cells, (draft.value, draft.row_label, draft.period_header), strict=True
    ):
        page = pages.get(support.phrase.capture_id)
        if page is None:
            return False
        previews = [
            item
            for item in page.capture.cells
            if (item.table_index, item.cell_index) == (support.table_index, support.cell_index)
        ]
        if len(previews) != 1:
            return False
        preview = previews[0]
        if (cell.row_index, cell.column_index, cell.row_span, cell.column_span) != (
            preview.row_index,
            preview.column_index,
            preview.row_span,
            preview.column_span,
        ):
            return False
    for supplied, (_, _, phrase) in zip(binding.phrases, expected, strict=True):
        if tuple(word.reference for word in supplied.words) != phrase.words:
            return False
        page = pages.get(phrase.capture_id)
        if page is None:
            return False
        for word in supplied.words:
            reference, evidence = word.reference, word.evidence
            if reference.word_index >= len(page.capture.words):
                return False
            native = page.capture.words[reference.word_index]
            if (
                native.orig != reference.quote
                or native.box is None
                or evidence.boxes != (native.box,)
                or evidence.source.page_index != page.capture.page_index
                or evidence.page_geometry != page.capture.page_geometry
                or evidence.source.filing_id != binding.filing_id
                or evidence.source.filing_version_id != record.filing_version_id
                or evidence.source.parse_version_id != binding.parse_version_id
            ):
                return False
    return True


def validate_bound_numerical(value: BoundGateInput) -> BoundNumericalGateRun:
    value = BoundGateInput.model_validate(value.model_dump(mode="python"))
    inspection = inspect_context(value.current_context)
    checks: dict[str, BoundGateCheck] = {
        check.code: BoundGateCheck.model_validate(check.model_dump(mode="python"))
        for check in inspection.checks
    }
    fresh = canonical_bytes(value.current_context) == canonical_bytes(value.context.source_input)
    retained = value.context.source_input
    same_source = (
        value.current_context.draft == retained.draft
        and value.current_context.pages == retained.pages
        and value.current_context.sdk_configuration_sha256 == retained.sdk_configuration_sha256
        and value.current_context.preparation_code_sha256 == retained.preparation_code_sha256
    )
    checks["FRESH_CONTEXT"] = BoundGateCheck(
        code="FRESH_CONTEXT",
        state="PASS" if fresh else "REVIEW" if same_source else "FAIL",
        message="Current registry, metric, policy and source snapshots match retained context."
        if fresh
        else "Context changed; create and bind a new inspection without grafting history.",
    )
    bound = _bound(value)
    checks["BOUND_EVIDENCE"] = BoundGateCheck(
        code="BOUND_EVIDENCE",
        state="PASS" if bound else "FAIL",
        message="Existing M1 words retain exact original context membership."
        if bound
        else "The bound evidence differs from its retained source/context.",
    )
    # Grammar scanning only: this joined text is never stored as a source quote/span.
    text = "\n".join(
        " ".join(word.quote for word in phrase.words) for _, _, phrase in _phrases(value)
    )
    language_state = (
        "FAIL"
        if _INJECTION.search(text)
        else "REVIEW"
        if _EXAMPLE.search(text) or _QUALIFIER.search(text)
        else "PASS"
    )
    checks["SOURCE_LANGUAGE"] = BoundGateCheck.model_validate(
        {
            "code": "SOURCE_LANGUAGE",
            "state": language_state,
            "message": "Instructions fail; illustrative or qualified context needs review."
            if language_state != "PASS"
            else "Bound context has no recognized instruction, illustrative or qualification cue.",
        }
    )
    ordered = tuple(checks[code] for code in GATE_CODES)
    state = (
        "QUARANTINED"
        if any(c.state == "FAIL" for c in ordered)
        else "REVIEW_REQUIRED"
        if any(c.state == "REVIEW" for c in ordered)
        else "READY_FOR_REVIEW"
    )
    input_sha = hashlib.sha256(canonical_bytes(value)).hexdigest()
    config_sha = bound_gate_configuration_sha256()
    return BoundNumericalGateRun.model_validate(
        {
            "id": gate_identity(input_sha, config_sha),
            "context_record_id": value.context.id,
            "parse_version_id": value.binding.parse_version_id,
            "evidence_binding_id": value.binding.id,
            "source_sha256": value.context.source_sha256,
            "input_sha256": input_sha,
            "configuration_sha256": config_sha,
            "state": state,
            "checks": ordered,
            "quantity_proposal": inspection.quantity if fresh and state != "QUARANTINED" else None,
            "evidence_ids": tuple(
                sorted({w.evidence.id for p in value.binding.phrases for w in p.words})
            )
            if bound
            else (),
        }
    )
