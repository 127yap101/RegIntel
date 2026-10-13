"""Entity shape gates preserve exact support and separate fuzzy/review authority."""

import hashlib
import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from regintel.entities.models import (
    ApprovedAlias,
    ApprovedIdentifier,
    EntityMention,
    EntityRegistration,
    EntityReview,
    EntityRun,
    EvidenceAnchor,
    MentionResolution,
    RegistrySnapshot,
    ResolutionProposal,
    ResolverConfiguration,
    canonical_bytes,
)


def entity_test_id(number: int) -> str:
    return str(UUID(int=number, version=4))


def anchor(quote: str = "Alpha Energy Limited", *, number: int = 11) -> EvidenceAnchor:
    return EvidenceAnchor(
        evidence_id=entity_test_id(number), start=7, end=7 + len(quote), quote=quote
    )


def registration_data() -> dict[str, object]:
    return {
        "id": entity_test_id(1),
        "kind": "COMPANY",
        "legal_name": "Alpha Energy Limited",
        "legal_name_support": anchor(),
        "aliases": (),
        "identifiers": (),
        "review_note": "Synthetic reviewed-name fixture; no real entity assertion.",
    }


def configuration() -> ResolverConfiguration:
    return ResolverConfiguration(
        spacy_version="test-only", rapidfuzz_version="test-only", code_sha256="c" * 64
    )


def unresolved() -> MentionResolution:
    return MentionResolution(
        state="UNRESOLVED", entity_id=None, method=None, reason="NO_MATCH", proposals=()
    )


def run_data() -> dict[str, object]:
    return {
        "id": entity_test_id(101),
        "parse_version_id": entity_test_id(102),
        "artifact_sha256": "a" * 64,
        "registry_revision": 0,
        "registry_sha256": "b" * 64,
        "configuration": configuration(),
        "evidence_ids": (entity_test_id(11),),
        "mentions": (
            EntityMention(
                id=entity_test_id(103), kind="NAME", support=anchor(), resolution=unresolved()
            ),
        ),
    }


def test_unicode_anchor_offsets_are_code_points_and_round_trip_without_changes() -> None:
    quote = "A\u0301lpha ☀ Energy Limited"
    support = anchor(quote)
    assert support.end - support.start == len(quote)
    assert support.end - support.start != len(quote.encode("utf-8"))
    assert EvidenceAnchor.model_validate_json(support.model_dump_json()) == support
    with pytest.raises(ValidationError):
        support.quote = "Beta Energy Limited"


@pytest.mark.parametrize(
    "changes",
    [
        {"start": -1},
        {"start": True},
        {"start": "7"},
        {"end": 7},
        {"end": 9007199254740992},
        {"quote": ""},
        {"quote": "A" * 257, "end": 264},
        {"quote": "\ud800", "end": 8},
        {"quote": "Altered quote"},
        {"evidence_id": "00000000-0000-0000-0000-000000000011"},
        {"page_index": 0},
    ],
)
def test_anchor_rejects_forged_offsets_unbounded_quotes_and_unknown_source_fields(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        EvidenceAnchor.model_validate(anchor().model_dump(mode="python") | changes)


def test_alias_and_identifier_require_exact_supplied_support() -> None:
    alias = ApprovedAlias(name="Alpha Energy", support=anchor("Alpha Energy"))
    assert alias.name == alias.support.quote
    with pytest.raises(ValidationError):
        ApprovedAlias(name="Alpha Energy Limited", support=anchor("Alpha Energy"))
    valid = "U12345MH2020PLC123456"
    identifier = ApprovedIdentifier(kind="CIN", value=valid, support=anchor(valid))
    assert identifier.value == valid
    with pytest.raises(ValidationError):
        ApprovedIdentifier(kind="CIN", value=valid, support=anchor("L54321DL2021PLC654321"))
    with pytest.raises(ValidationError):
        ApprovedIdentifier(kind="ISIN", value="US0378331006", support=anchor("US0378331006"))


@pytest.mark.parametrize("name", ["   ", "--", "☀"])
def test_approved_names_require_a_real_name_token_even_with_matching_source(name: str) -> None:
    with pytest.raises(ValidationError):
        ApprovedAlias(name=name, support=anchor(name))
    with pytest.raises(ValidationError):
        EntityRegistration.model_validate(
            registration_data() | {"legal_name": name, "legal_name_support": anchor(name)}
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"legal_name": "Beta Energy Limited"},
        {"kind": "METRIC"},
        {"id": entity_test_id(0xABCD).upper()},
        {"review_note": ""},
        {"review_note": "A" * 2001},
        {"aliases": (ApprovedAlias(name="Alpha Energy Limited", support=anchor()),)},
        {
            "aliases": (
                ApprovedAlias(name="Alpha Energy", support=anchor("Alpha Energy")),
                ApprovedAlias(name="Alpha Energy", support=anchor("Alpha Energy")),
            )
        },
        {"accepted_financial_fact": True},
    ],
)
def test_registration_cannot_invent_name_duplicate_terms_or_financial_authority(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        EntityRegistration.model_validate(registration_data() | changes)


@pytest.mark.parametrize("kind", ["PERSON", "ORGANIZATION"])
def test_cin_registration_is_limited_to_companies(kind: str) -> None:
    value = "U12345MH2020PLC123456"
    with pytest.raises(ValidationError):
        EntityRegistration.model_validate(
            registration_data()
            | {
                "kind": kind,
                "identifiers": (
                    ApprovedIdentifier(kind="CIN", value=value, support=anchor(value)),
                ),
            }
        )


def test_duplicate_identifier_in_one_registration_is_rejected() -> None:
    value = "U12345MH2020PLC123456"
    identifier = ApprovedIdentifier(kind="CIN", value=value, support=anchor(value))
    with pytest.raises(ValidationError):
        EntityRegistration.model_validate(registration_data() | {"identifiers": (identifier,) * 2})


@pytest.mark.parametrize(
    "method,score",
    [
        ("FUZZY", None),
        ("FUZZY", -0.1),
        ("FUZZY", 100.1),
        ("FUZZY", float("nan")),
        ("FUZZY", float("inf")),
        ("EXACT_CIN", 99.0),
        ("NORMALIZED_NAME", 100.0),
    ],
)
def test_scores_are_bounded_fuzzy_proposals_only(method: str, score: float | None) -> None:
    with pytest.raises(ValidationError):
        ResolutionProposal.model_validate(
            {"entity_id": entity_test_id(1), "method": method, "score": score}
        )


def test_even_perfect_fuzzy_similarity_cannot_be_resolved_state() -> None:
    proposal = ResolutionProposal(entity_id=entity_test_id(1), method="FUZZY", score=100.0)
    with pytest.raises(ValidationError):
        MentionResolution(
            state="RESOLVED",
            entity_id=entity_test_id(1),
            method="FUZZY",
            reason="FUZZY_PROPOSAL",
            proposals=(proposal,),
        )
    review = MentionResolution(
        state="REVIEW", entity_id=None, method=None, reason="FUZZY_PROPOSAL", proposals=(proposal,)
    )
    assert review.entity_id is None


@pytest.mark.parametrize("mutation", ["different_id", "different_method", "duplicate", "none"])
def test_resolved_shape_requires_the_sole_matching_exact_proposal(mutation: str) -> None:
    proposal = ResolutionProposal(entity_id=entity_test_id(1), method="EXACT_ALIAS", score=None)
    data: dict[str, object] = {
        "state": "RESOLVED",
        "entity_id": entity_test_id(1),
        "method": "EXACT_ALIAS",
        "reason": "APPROVED_NAME",
        "proposals": (proposal,),
    }
    if mutation == "different_id":
        data["entity_id"] = entity_test_id(2)
    elif mutation == "different_method":
        data["method"] = "NORMALIZED_NAME"
    elif mutation == "duplicate":
        data["proposals"] = (proposal, proposal)
    else:
        data["proposals"] = ()
    with pytest.raises(ValidationError):
        MentionResolution.model_validate(data)


@pytest.mark.parametrize("state", ["REVIEW", "UNRESOLVED"])
def test_pending_mentions_cannot_carry_a_canonical_identity(state: str) -> None:
    with pytest.raises(ValidationError):
        MentionResolution.model_validate(
            {
                "state": state,
                "entity_id": entity_test_id(1),
                "method": None,
                "reason": "NO_MATCH",
                "proposals": (),
            }
        )


def test_unresolved_shape_cannot_hide_an_existing_proposal() -> None:
    proposal = ResolutionProposal(entity_id=entity_test_id(1), method="EXACT_ALIAS", score=None)
    with pytest.raises(ValidationError):
        MentionResolution(
            state="UNRESOLVED",
            entity_id=None,
            method=None,
            reason="NO_MATCH",
            proposals=(proposal,),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"fuzzy_threshold": -1.0},
        {"fuzzy_threshold": 101.0},
        {"fuzzy_threshold": float("nan")},
        {"max_proposals": 0},
        {"max_proposals": 101},
        {"max_proposals": True},
        {"max_proposals": "5"},
        {"code_sha256": "A" * 64},
        {"version": "2.0.0"},
    ],
)
def test_resolver_configuration_is_explicit_bounded_and_strict(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ResolverConfiguration.model_validate(configuration().model_dump(mode="python") | changes)


def test_configuration_hash_is_canonical_and_changes_with_policy() -> None:
    selected = configuration()
    assert selected.sha256 == hashlib.sha256(canonical_bytes(selected)).hexdigest()
    rebuilt = ResolverConfiguration.model_validate_json(selected.model_dump_json())
    assert rebuilt.sha256 == selected.sha256
    altered = selected.model_copy(update={"fuzzy_threshold": 90.0})
    assert altered.sha256 != selected.sha256


@pytest.mark.parametrize(
    "mutation", ["foreign_evidence", "duplicate_evidence", "duplicate_mention"]
)
def test_run_requires_unique_mentions_within_its_supplied_evidence(mutation: str) -> None:
    data = run_data()
    if mutation == "foreign_evidence":
        data["evidence_ids"] = (entity_test_id(12),)
    elif mutation == "duplicate_evidence":
        data["evidence_ids"] = (entity_test_id(11),) * 2
    else:
        mentions = data["mentions"]
        assert isinstance(mentions, tuple)
        data["mentions"] = mentions * 2
    with pytest.raises(ValidationError):
        EntityRun.model_validate(data)


def test_entity_run_is_frozen_and_retains_exact_registry_and_parse_identity() -> None:
    run = EntityRun.model_validate(run_data())
    assert EntityRun.model_validate_json(run.model_dump_json()) == run
    assert run.mentions[0].support.quote == "Alpha Energy Limited"
    assert run.mentions[0].resolution.state == "UNRESOLVED"
    with pytest.raises(ValidationError):
        run.registry_revision = 1


@pytest.mark.parametrize("changes", [{"revision": -1}, {"sha256": "bad"}])
def test_registry_snapshot_has_explicit_revision_and_digest_shape(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RegistrySnapshot.model_validate(
            {"revision": 0, "sha256": "b" * 64, "entities": ()} | changes
        )


def snapshot_data() -> dict[str, object]:
    first = EntityRegistration.model_validate(registration_data())
    second = EntityRegistration.model_validate(registration_data() | {"id": entity_test_id(2)})
    entities = (first, second)
    content = json.dumps(
        {"entities": [entity.model_dump(mode="json") for entity in entities]},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return {"revision": 2, "sha256": hashlib.sha256(content).hexdigest(), "entities": entities}


def test_snapshot_canonical_digest_binds_the_actual_approval_content() -> None:
    selected = RegistrySnapshot.model_validate(snapshot_data())
    assert RegistrySnapshot.model_validate_json(selected.model_dump_json()) == selected
    assert selected.revision == len(selected.entities) == 2


@pytest.mark.parametrize("mutation", ["hash", "revision", "duplicate", "unsorted", "content"])
def test_snapshot_rejects_forged_hash_revision_duplicate_or_reordered_entities(
    mutation: str,
) -> None:
    data = snapshot_data()
    entities = data["entities"]
    assert isinstance(entities, tuple)
    if mutation == "hash":
        data["sha256"] = "f" * 64
    elif mutation == "revision":
        data["revision"] = 1
    elif mutation == "duplicate":
        data["entities"] = (entities[0], entities[0])
    elif mutation == "unsorted":
        data["entities"] = tuple(reversed(entities))
    else:
        changed = entities[0].model_copy(update={"review_note": "A different approval record."})
        data["entities"] = (changed, entities[1])
    with pytest.raises(ValidationError):
        RegistrySnapshot.model_validate(data)


@pytest.mark.parametrize(
    "decision,entity_id,support",
    [
        ("RESOLVE", None, (entity_test_id(11),)),
        ("REJECT", entity_test_id(1), (entity_test_id(11),)),
        ("REJECT", None, ()),
        ("REJECT", None, (entity_test_id(11),) * 2),
    ],
)
def test_review_decision_requires_consistent_identity_and_unique_exact_support(
    decision: str,
    entity_id: str | None,
    support: tuple[str, ...],
) -> None:
    with pytest.raises(ValidationError):
        EntityReview.model_validate(
            {
                "id": entity_test_id(201),
                "run_id": entity_test_id(101),
                "mention_id": entity_test_id(103),
                "decision": decision,
                "entity_id": entity_id,
                "support_evidence_ids": support,
                "review_note": "Synthetic reviewed decision.",
            }
        )
