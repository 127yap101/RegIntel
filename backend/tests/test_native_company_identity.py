"""Exact native identity contracts and sealed order, never financial/gold approval."""

import hashlib
import json
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from backend.tests.native_company_fixtures import company_registration
from backend.tests.native_context_fixtures import native_case
from regintel.entities.models import (
    EntityRegistration,
    NativeCompanyRegistration,
    RegisteredEntity,
    RegistrySnapshot,
    canonical_bytes,
)
from regintel.entities.native_support import verify_native_company
from regintel.parsing.native_context import project_native_context


@pytest.fixture
def case(tmp_path):
    fixture = native_case(tmp_path)
    body = company_registration(fixture.result, fixture.record.source_input.draft)
    return fixture, body


def test_exact_separate_word_identity_round_trips_and_does_not_create_evidence(case):
    fixture, body = case
    evidence = project_native_context(
        fixture.result.artifact, fixture.result.configuration
    ).evidence
    before = canonical_bytes(fixture.result.artifact)
    verify_native_company(body, fixture.result.artifact, evidence)
    assert len(body.legal_name_support.spans) == 3
    assert body.legal_name == "Authored Solar Limited"
    assert "quote" not in body.legal_name_support.model_dump()
    assert TypeAdapter(RegisteredEntity).validate_json(canonical_bytes(body)) == body
    assert canonical_bytes(fixture.result.artifact) == before


@pytest.mark.parametrize(
    "change",
    [
        "name",
        "cin",
        "name_order",
        "name_gap",
        "header_gap",
        "header_order",
        "name_parse",
        "partial",
        "foreign",
        "alias",
        "extra_identifier",
        "kind",
        "schema",
        "extra_quote",
        "short_name",
        "blank_note",
    ],
)
def test_invalid_profile_or_membership_cannot_register(case, change):
    fixture, body = case
    raw = body.model_dump(mode="json")
    if change == "blank_note":
        raw["review_note"] = " \n\t"
    elif change == "short_name":
        raw["legal_name"] = "Authored"
        raw["legal_name_support"]["spans"] = raw["legal_name_support"]["spans"][:1]
    elif change == "name":
        raw["legal_name"] = "Other Solar Limited"
    elif change == "cin":
        raw["identifiers"][0]["value"] = "U12345MH2020PLC999999"
    elif change == "name_order":
        raw["legal_name_support"]["spans"].reverse()
    elif change == "name_gap":
        raw["legal_name_support"]["spans"].pop(1)
    elif change == "header_gap":
        raw["issuer_header"]["spans"].pop(3)
    elif change == "header_order":
        raw["issuer_header"]["spans"][3:5] = reversed(raw["issuer_header"]["spans"][3:5])
    elif change == "name_parse":
        raw["legal_name_support"]["parse_version_id"] = str(uuid4())
    elif change == "partial":
        for role in ("issuer_header", "legal_name_support"):
            span = raw[role]["spans"][0]
            span.update(quote=span["quote"][1:], start=1)
        raw["legal_name"] = raw["legal_name"][1:]
    elif change == "foreign":
        for role in ("issuer_header", "legal_name_support"):
            raw[role]["spans"][0]["evidence_id"] = str(uuid4())
    elif change == "alias":
        raw["aliases"] = [{"name": "Authored", "support": raw["issuer_header"]["spans"][0]}]
    elif change == "extra_identifier":
        raw["identifiers"] *= 2
    elif change in {"kind", "schema"}:
        raw["kind" if change == "kind" else "schema_version"] = "UNSUPPORTED"
    else:
        raw["legal_name_support"]["quote"] = body.legal_name
    evidence = project_native_context(
        fixture.result.artifact, fixture.result.configuration
    ).evidence
    with pytest.raises(ValueError):
        checked = NativeCompanyRegistration.model_validate(raw)
        verify_native_company(checked, fixture.result.artifact, evidence)


def test_correct_text_cannot_hide_missing_or_changed_native_positions(case):
    fixture, body = case
    evidence = project_native_context(
        fixture.result.artifact, fixture.result.configuration
    ).evidence
    original = fixture.result.artifact
    block_id = next(
        e.span.block_id for e in evidence if e.id == body.legal_name_support.spans[1].evidence_id
    )
    blocks = tuple(
        b.model_copy(update={"source_ref": "unverified-native-position"}) if b.id == block_id else b
        for b in original.blocks
    )
    with pytest.raises(ValueError):
        verify_native_company(body, original.model_copy(update={"blocks": blocks}), evidence)


def test_legacy_registration_and_registry_bytes_keep_the_original_shape():
    raw = {
        "id": str(uuid4()),
        "kind": "COMPANY",
        "legal_name": "Legacy Solar Limited",
        "legal_name_support": {
            "evidence_id": str(uuid4()),
            "start": 0,
            "end": 20,
            "quote": "Legacy Solar Limited",
        },
        "aliases": [],
        "identifiers": [],
        "review_note": "Authored legacy byte regression.",
    }
    encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    legacy = TypeAdapter(RegisteredEntity).validate_json(encoded)
    assert isinstance(legacy, EntityRegistration) and canonical_bytes(legacy) == encoded
    packet = {"entities": [raw]}
    digest = hashlib.sha256(
        json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    registry = RegistrySnapshot(revision=1, sha256=digest, entities=(legacy,))
    assert registry.sha256 == digest and "schema_version" not in registry.entities[0].model_dump()


def test_registry_retains_native_support_without_inventing_a_combined_span(case):
    _, body = case
    digest = hashlib.sha256(
        json.dumps(
            {"entities": [body.model_dump(mode="json")]},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    registry = RegistrySnapshot(revision=1, sha256=digest, entities=(body,))
    restored = RegistrySnapshot.model_validate_json(canonical_bytes(registry))
    assert restored == registry and isinstance(restored.entities[0], NativeCompanyRegistration)
    with pytest.raises(ValidationError):
        EntityRegistration.model_validate(body.model_dump(mode="python"))
