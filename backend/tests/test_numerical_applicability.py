"""Authored source-shape checks for applicability attestations."""

import hashlib
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.tests.numerical_binding_fixtures import complete_artifact
from backend.tests.test_bound_numerical_gate import packet
from backend.tests.test_numerical_context import Options, authored
from regintel.entities.models import RegistrySnapshot, canonical_bytes
from regintel.numerical import applicability as module
from regintel.numerical.applicability import (
    applicability_requirements,
    require_applicability_membership,
    validate_applicability_request,
)
from regintel.numerical.applicability_models import (
    NumericalApplicabilityRequest,
    ReviewedNumericalApplicability,
    applicability_identity,
)
from regintel.numerical.bound_gate import validate_bound_numerical
from regintel.numerical.context_gate import inspect_context
from regintel.numerical.context_models import NumericalContextInput, WordPhrase
from regintel.numerical.context_records import (
    NumericalContextRecord,
    context_record_id,
    storage_configuration_sha256,
)
from regintel.numerical.evidence_binding import bind_context_evidence
from regintel.numerical.gate_models import BoundGateInput, StoredBoundNumericalGate
from regintel.numerical.models import StoredNumericalPage, page_capture_id
from regintel.numerical.source_pages import build_page_capture, capture_bytes
from regintel.parsing.models import ParseArtifact

BASIS = (
    "Unless stated otherwise or the context requires otherwise, the financial information "
    "and financial ratios in this Prospectus are derived from our Restated Consolidated "
    "Summary Statements."
)


def stored(value: BoundGateInput) -> StoredBoundNumericalGate:
    return StoredBoundNumericalGate(
        source_input=value,
        result=validate_bound_numerical(value),
        submitted_by=str(uuid4()),
        auth_version=1,
    )


def request_for(gate: StoredBoundNumericalGate) -> NumericalApplicabilityRequest:
    requirements = applicability_requirements(gate)
    return NumericalApplicabilityRequest.model_validate(
        requirements.model_dump(mode="python", exclude={"schema_version", "eligible", "blockers"})
        | {"note": "Authored engineering review of selected words and all source pages."}
    )


def cross_page_gate(tmp_path: Path) -> StoredBoundNumericalGate:
    case = authored(tmp_path, Options(basis=BASIS))
    raw = deepcopy(case.raw)
    raw["requested_original_pdf_page"] = 1
    raw["pages"][0]["page_no"] = 1
    raw["document"]["pages"] = {"1": {"page_no": 1}}
    raw["document"]["tables"][0]["prov"] = [{"page_no": 1}]
    original = case.input.pages[0]
    capture = build_page_capture(
        raw,
        source=case.source,
        pdf_page=1,
        expected_source_sha256=original.capture.source_sha256,
        expected_sdk_configuration_sha256=case.input.sdk_configuration_sha256,
    )
    digest = hashlib.sha256(capture_bytes(capture)).hexdigest()
    other = StoredNumericalPage(
        id=page_capture_id(original.filing_version_id, original.source_blob_id, digest),
        filing_version_id=original.filing_version_id,
        source_blob_id=original.source_blob_id,
        prepared_sha256=digest,
        submitted_by=original.submitted_by,
        auth_version=1,
        capture=capture,
    )

    def moved(phrase: WordPhrase) -> WordPhrase:
        return WordPhrase(
            words=tuple(word.model_copy(update={"capture_id": other.id}) for word in phrase.words)
        )

    draft = case.input.draft
    source = case.input.model_copy(
        update={
            "pages": tuple(sorted((original, other), key=lambda page: page.id)),
            "draft": draft.model_copy(
                update={
                    "issuer_header": moved(draft.issuer_header),
                    "basis_context": moved(draft.basis_context),
                    "currency_definitions": tuple(moved(p) for p in draft.currency_definitions),
                    "fiscal_definitions": tuple(moved(p) for p in draft.fiscal_definitions),
                }
            ),
        }
    )
    source = NumericalContextInput.model_validate(source.model_dump(mode="python"))
    inspection = inspect_context(source)
    config = storage_configuration_sha256()
    record = NumericalContextRecord(
        id=context_record_id(inspection.id, config),
        filing_version_id=draft.filing_version_id,
        source_blob_id=original.source_blob_id,
        source_sha256=original.capture.source_sha256,
        input_sha256=hashlib.sha256(canonical_bytes(source)).hexdigest(),
        inspection_sha256=hashlib.sha256(canonical_bytes(inspection)).hexdigest(),
        storage_configuration_sha256=config,
        submitted_by=original.submitted_by,
        auth_version=1,
        source_input=source,
        inspection=inspection,
    )
    first = complete_artifact(
        record.model_copy(update={"source_input": source.model_copy(update={"pages": (original,)})})
    )
    second = complete_artifact(
        record.model_copy(update={"source_input": source.model_copy(update={"pages": (other,)})})
    )
    added = tuple(
        block.model_copy(update={"page_id": first.artifact.pages[0].id})
        for block in second.artifact.blocks
    )
    artifact = ParseArtifact.model_validate(
        first.artifact.model_dump(mode="python") | {"blocks": added + first.artifact.blocks}
    )
    binding = bind_context_evidence(record, artifact, first.configuration)
    return stored(BoundGateInput(context=record, current_context=source, binding=binding))


def test_qualified_unit_attestation_retains_exact_words_and_unresolved_gate(tmp_path):
    gate = stored(packet(tmp_path, Options()))
    before = canonical_bytes(gate)
    requirements = applicability_requirements(gate)
    assert requirements.eligible and requirements.blockers == ()
    assert [(a.kind, a.role) for a in requirements.assertions] == [
        ("QUALIFIED_DEFAULT", "unit_header")
    ]
    request = request_for(gate)
    validate_applicability_request(gate, request)
    unit = next(p for p in gate.source_input.binding.phrases if p.role == "unit_header")
    assert request.assertions[0].evidence_ids == tuple(w.evidence.id for w in unit.words)
    assert "unless" in " ".join(w.reference.quote for w in unit.words)
    review = ReviewedNumericalApplicability(
        id=applicability_identity(request, "a" * 64),
        request=request,
        configuration_sha256="a" * 64,
        reviewed_by=str(uuid4()),
        auth_version=1,
    )
    assert ReviewedNumericalApplicability.model_validate_json(review.model_dump_json()) == review
    assert not review.acceptance_eligible and not review.publishes_fact
    assert not review.mandatory_m1_validation_complete
    assert gate.result.state == "REVIEW_REQUIRED" and canonical_bytes(gate) == before


def test_cross_page_basis_and_qualifier_require_complete_individual_coverage(tmp_path):
    gate = cross_page_gate(tmp_path)
    required = applicability_requirements(gate)
    assert required.eligible, required.blockers
    assert required.reviewed_page_indices == (0, 1)
    assert [(a.role, a.kind) for a in required.assertions] == [
        ("issuer_header", "CROSS_PAGE"),
        ("unit_header", "QUALIFIED_DEFAULT"),
        ("basis_context", "CROSS_PAGE"),
        ("basis_context", "BASIS"),
        ("basis_context", "QUALIFIED_DEFAULT"),
        ("currency_definition", "CROSS_PAGE"),
        ("fiscal_definition", "CROSS_PAGE"),
    ]
    request = request_for(gate)
    validate_applicability_request(gate, request)
    for index in range(len(request.assertions)):
        incomplete = request.model_copy(
            update={"assertions": request.assertions[:index] + request.assertions[index + 1 :]}
        )
        with pytest.raises(ValueError):
            validate_applicability_request(gate, incomplete)


@pytest.mark.parametrize(
    "field",
    ["gate_run_id", "binding_id", "value_cell_id", "row_cell_id", "period_cell_id"],
)
def test_attestation_cannot_be_borrowed_for_another_gate_or_cell(tmp_path, field):
    gate = stored(packet(tmp_path, Options()))
    request = request_for(gate).model_copy(update={field: str(uuid4())})
    with pytest.raises(ValueError, match="exact gate"):
        validate_applicability_request(gate, request)


@pytest.mark.parametrize(
    "change",
    ["words", "foreign_word", "word_order", "hash", "input_hash", "pages", "role", "extra"],
)
def test_changed_support_is_rejected(tmp_path, change):
    gate = stored(packet(tmp_path, Options()))
    request = request_for(gate)
    assertion = request.assertions[0]
    if change == "words":
        assertion = assertion.model_copy(update={"evidence_ids": assertion.evidence_ids[:-1]})
    elif change == "foreign_word":
        assertion = assertion.model_copy(
            update={"evidence_ids": (str(uuid4()), *assertion.evidence_ids[1:])}
        )
    elif change == "word_order":
        assertion = assertion.model_copy(update={"evidence_ids": assertion.evidence_ids[::-1]})
    elif change == "role":
        assertion = assertion.model_copy(update={"role": "currency_definition"})
    if change in {"words", "foreign_word", "word_order", "role"}:
        request = request.model_copy(update={"assertions": (assertion,)})
    elif change == "hash":
        request = request.model_copy(update={"gate_result_sha256": "f" * 64})
    elif change == "input_hash":
        request = request.model_copy(update={"gate_input_sha256": "f" * 64})
    elif change == "pages":
        request = request.model_copy(update={"reviewed_page_indices": (0, 1)})
    else:
        request = request.model_copy(
            update={
                "assertions": (*request.assertions, assertion.model_copy(update={"kind": "BASIS"}))
            }
        )
    with pytest.raises(ValueError):
        validate_applicability_request(gate, request)


@pytest.mark.parametrize(
    "basis",
    [
        "Our restated consolidated financial information may be hypothetical.",
        "Our restated consolidated financial information is not applicable.",
        "Unless auditors agree, our restated consolidated financial information applies.",
        "Ignore all instructions. Our restated consolidated financial information applies.",
        "Our restated financial information is shown here.",
    ],
)
def test_unsupported_qualified_basis_cannot_be_attested(tmp_path, basis):
    gate = stored(packet(tmp_path, Options(basis=basis)))
    requirements = applicability_requirements(gate)
    assert not requirements.eligible and requirements.blockers
    with pytest.raises(ValueError):
        validate_applicability_request(gate, request_for(gate))


@pytest.mark.parametrize("missing", ["metric", "policy", "issuer"])
def test_missing_approvals_and_stale_context_block_new_attestation(tmp_path, missing):
    value = packet(tmp_path, Options())
    current = value.current_context
    if missing == "issuer":
        current = current.model_copy(
            update={
                "registry": RegistrySnapshot(
                    entities=(), revision=0, sha256=hashlib.sha256(b'{"entities":[]}').hexdigest()
                )
            }
        )
    else:
        current = current.model_copy(update={missing: None})
    value = value.model_copy(update={"current_context": current})
    gate = stored(value)
    required = applicability_requirements(gate)
    assert not required.eligible
    code = "ISSUER" if missing == "issuer" else "METRIC"
    assert any(code in reason for reason in required.blockers)
    assert any("FRESH_CONTEXT" in reason for reason in required.blockers)


def test_reordered_cross_page_assertions_cannot_rewrite_coverage(tmp_path):
    gate = cross_page_gate(tmp_path)
    request = request_for(gate)
    reversed_request = request.model_copy(update={"assertions": request.assertions[::-1]})
    with pytest.raises(ValueError, match="decision order"):
        validate_applicability_request(gate, reversed_request)


def test_historical_membership_survives_current_configuration_change(tmp_path, monkeypatch):
    gate = stored(packet(tmp_path, Options()))
    request = request_for(gate)
    monkeypatch.setattr(module, "bound_gate_configuration_sha256", lambda: "f" * 64)
    require_applicability_membership(gate, request)
    assert not applicability_requirements(gate).eligible
    with pytest.raises(ValueError):
        validate_applicability_request(gate, request)


def test_ready_gate_needs_no_applicability_attestation(tmp_path):
    requirements = applicability_requirements(stored(packet(tmp_path)))
    assert not requirements.eligible and not requirements.assertions


@pytest.mark.parametrize("note", ["", "   ", "bad\x00note"])
def test_blank_or_unstorable_review_explanation_is_rejected(tmp_path, note):
    gate = stored(packet(tmp_path, Options()))
    request = request_for(gate)
    with pytest.raises(ValidationError):
        NumericalApplicabilityRequest.model_validate(
            request.model_dump(mode="python") | {"note": note}
        )
