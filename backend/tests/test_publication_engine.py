"""Authored publication scenarios; these are engineering fixtures, not gold data."""

import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import SecretStr, ValidationError
from test_candidate_models import ALPHA, BETA, make_input, metric, support
from test_validation_models import money_policy, numeric_draft, validation_input

from regintel.auth.types import User
from regintel.candidates.models import CandidateBundle, ExtractionInput
from regintel.candidates.records import stable_id
from regintel.entities.models import EntityRegistration, EvidenceAnchor, RegistrySnapshot
from regintel.fixtures.sources import fixture_id
from regintel.publication.engine import (
    PublicationConflict,
    approve_candidate,
    build_manifest,
    corpus_view,
)
from regintel.publication.models import (
    CandidateSelection,
    CorpusManifest,
    EffectProposal,
    FilingSnapshot,
    LineageProposal,
    PublicationConfiguration,
    PublicationRequest,
    ReviewedApproval,
)
from regintel.validation.gate import current_configuration, validate
from regintel.validation.models import ReviewDecision, ValidationInput


def administrator() -> User:
    return User(UUID(fixture_id(901)), "admin", SecretStr("unused"), "admin", True, 1)


def configuration() -> PublicationConfiguration:
    return PublicationConfiguration(
        code_sha256="a" * 64,
        validator_configuration_sha256=current_configuration().sha256,
        embedding_manifest_sha256="b" * 64,
    )


def authored(text: str, version: int = 0, *, narrative: bool = False) -> ValidationInput:
    source = make_input(text, metrics=(metric(numeric=False, cue="business"),) if narrative else ())
    # A separate original document/parse/evidence/run, preserving the two canonical entities.
    owned = (
        *source.entity_run.evidence_ids,
        source.entity_run.id,
        source.entity_run.parse_version_id,
        source.evidence[0].source.filing_id,
        source.evidence[0].source.filing_version_id,
        source.evidence[0].source.page_id,
        source.evidence[0].span.block_id,
    )
    encoded = source.model_dump_json()
    for identity in set(owned):
        encoded = encoded.replace(identity, stable_id(f"authored:{version}:{identity}"))
    return validation_input(ExtractionInput.model_validate_json(encoded))


def filing(
    source: ValidationInput, *, child: bool = False, known_date: bool = True
) -> FilingSnapshot:
    ref = source.source.evidence[0].source
    return FilingSnapshot(
        filing_id=ref.filing_id,
        filing_version_id=ref.filing_version_id,
        parse_version_id=ref.parse_version_id,
        source_sha256="c" * 64,
        document_type="ADDENDUM" if child else "RHP",
        published_on=("2025-12-01" if child else "2025-01-01") if known_date else None,
    )


def selected(source: ValidationInput, review_id: str | None = None) -> CandidateSelection:
    return CandidateSelection(
        candidate_run_id=source.candidate_run.id,
        candidate_id=source.candidate_run.candidates[0].id,
        review_id=review_id,
    )


def create(
    source: ValidationInput,
    *,
    parent: CorpusManifest | None = None,
    child: bool = False,
    known_date: bool = True,
    review: ReviewedApproval | None = None,
    lineages: tuple[LineageProposal, ...] = (),
    effects: tuple[EffectProposal, ...] = (),
) -> CorpusManifest:
    selection = selected(source, review.decision.id if review else None)
    request = PublicationRequest(
        idempotency_key=stable_id("request:" + source.candidate_run.id),
        parent_corpus_version_id=parent.id if parent else None,
        selections=(selection,),
        lineages=lineages,
        effects=effects,
    )
    config = configuration()
    from regintel.entities.models import canonical_bytes

    corpus_id = stable_id(
        "corpus:"
        + request.idempotency_key
        + ":"
        + hashlib.sha256(canonical_bytes(request)).hexdigest()
        + ":"
        + config.sha256
    )
    snapshot = filing(source, child=child, known_date=known_date)
    accepted = approve_candidate(corpus_id, selection, source, snapshot, review, config)
    original = authored(f"{ALPHA} supplies to {BETA}.")
    anchor = support(original.source, ALPHA)
    entity = EntityRegistration(
        id=fixture_id(101),
        kind="COMPANY",
        legal_name=ALPHA,
        legal_name_support=EvidenceAnchor.model_validate(anchor.model_dump(mode="python")),
        aliases=(),
        identifiers=(),
        review_note="Authored issuer identity.",
    )
    registry_bytes = json.dumps(
        {"entities": [entity.model_dump(mode="json")]},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    registry = RegistrySnapshot(
        revision=1, sha256=hashlib.sha256(registry_bytes).hexdigest(), entities=(entity,)
    )
    return build_manifest(
        request,
        config,
        administrator(),
        (accepted,),
        (snapshot,),
        (*original.source.evidence, *source.source.evidence),
        registry,
        parent,
    )


def amendment(
    effect_type: str = "SUPERSEDE",
) -> tuple[CorpusManifest, ValidationInput, LineageProposal, EffectProposal]:
    parent_source = authored(f"{ALPHA} supplies to {BETA}.")
    parent = create(parent_source)
    cue = {
        "SUPERSEDE": "superseded",
        "CORRECT": "corrected",
        "SUPPLEMENT": "supplemented",
        "ADD": "additional",
        "REMOVE": "removed",
    }[effect_type]
    child = authored(
        f"{ALPHA} supplies to {BETA}. Red Herring Prospectus. "
        f"The earlier disclosure is {cue} effective 1 January 2026.",
        1,
    )
    lineage = LineageProposal(
        id=fixture_id(910),
        parent_filing_version_id=parent.filings[0].filing_version_id,
        child_filing_version_id=filing(child, child=True).filing_version_id,
        lineage_type="ADDENDUM_TO",
        issuer_entity_id=fixture_id(101),
        parent_identity=support(parent_source.source, ALPHA),
        child_identity=support(child.source, ALPHA),
        parent_reference=support(child.source, "Red Herring Prospectus"),
        review_note="Authored same-issuer reviewed parent reference.",
    )
    effect = EffectProposal.model_validate(
        {
            "id": fixture_id(911),
            "lineage_id": lineage.id,
            "effect_type": effect_type,
            "affected_observation_ids": ()
            if effect_type == "ADD"
            else parent.active_observation_ids,
            "new_candidate_ids": () if effect_type == "REMOVE" else (selected(child).candidate_id,),
            "supports": (
                support(child.source, f"The earlier disclosure is {cue} effective 1 January 2026."),
            ),
            "effective_date": "2026-01-01",
            "effective_date_support": support(child.source, "1 January 2026"),
            "review_note": "Authored explicit effect decision; no real amendment claim.",
        }
    )
    return parent, child, lineage, effect


def test_passed_relation_keeps_exact_evidence_and_fresh_gate() -> None:
    source = authored(f"{ALPHA} supplies to {BETA}.")
    manifest = create(source)
    observation = manifest.observations[0]
    assert observation.relation_type == "SUPPLIES_TO"
    assert observation.supports[0].quote == source.source.evidence[0].span.quote
    assert observation.validation_run_id == validate(source).id
    assert corpus_view(manifest).observations == manifest.observations
    assert corpus_view(manifest, "2024-12-31").observations == ()


def test_review_retains_older_validation_identity_and_requires_complete_statement() -> None:
    source = authored(f"{ALPHA} business is manufacture of solar modules.", narrative=True)
    review = ReviewedApproval(
        decision=ReviewDecision(
            id=fixture_id(920),
            validation_run_id=fixture_id(921),
            candidate_id=selected(source).candidate_id,
            decision="APPROVE_FOR_PUBLICATION",
            supports=(support(source.source),),
            review_note="Authored older review, independently revalidated.",
        ),
        reviewed_by=str(administrator().id),
        auth_version=1,
    )
    manifest = create(source, review=review)
    assert manifest.new_acceptances[0].original_review == review
    assert manifest.observations[0].validation_run_id != review.decision.validation_run_id
    with pytest.raises(PublicationConflict):
        create(source)
    with pytest.raises(PublicationConflict):
        create(
            source,
            review=review.model_copy(
                update={
                    "decision": review.decision.model_copy(
                        update={"supports": (support(source.source, "business"),)}
                    )
                }
            ),
        )


@pytest.mark.parametrize("change", ["rejected", "candidate", "configuration", "source"])
def test_approval_cannot_bypass_current_gate_or_owned_membership(change: str) -> None:
    source = authored(f"{ALPHA} supplies to {BETA}.")
    selection = selected(source)
    config = configuration()
    review = None
    if change == "candidate":
        selection = selection.model_copy(update={"candidate_id": fixture_id(999)})
    elif change == "configuration":
        config = config.model_copy(update={"validator_configuration_sha256": "f" * 64})
    elif change == "source":
        source = source.model_copy(
            update={"table_evidence_ids": source.source.entity_run.evidence_ids}
        )
    else:
        review = ReviewedApproval(
            decision=ReviewDecision(
                id=fixture_id(920),
                validation_run_id=fixture_id(921),
                candidate_id=selection.candidate_id,
                decision="REJECT",
                supports=(support(source.source),),
                review_note="Rejected.",
            ),
            reviewed_by=str(administrator().id),
            auth_version=1,
        )
        selection = selection.model_copy(update={"review_id": review.decision.id})
    with pytest.raises(PublicationConflict):
        approve_candidate(fixture_id(930), selection, source, filing(source), review, config)


def test_decimal_quantity_is_normalized_without_mutating_raw_candidate() -> None:
    raw = make_input(
        f"{ALPHA} consolidated revenue INR 12 crore from 1 April 2025 to 31 March 2026.",
        metrics=(metric(),),
    )
    source = validation_input(
        raw,
        bundle=CandidateBundle(
            numeric_facts=(numeric_draft(raw, "12"),), narrative_facts=(), relations=(), issues=()
        ),
        policies=(money_policy(allowed_unit_labels=("crore",)),),
    )
    before = source.model_dump_json()
    accepted = approve_candidate(
        fixture_id(930), selected(source), source, filing(source), None, configuration()
    )
    assert accepted.observation.quantity is not None
    assert accepted.observation.quantity.normalized_value == Decimal("12")
    assert accepted.observation.quantity.normalized_unit == "crore"
    assert source.model_dump_json() == before


@pytest.mark.parametrize("effect_type", ["SUPERSEDE", "CORRECT", "SUPPLEMENT", "ADD"])
def test_scoped_effects_preserve_history_and_obey_effective_dates(effect_type: str) -> None:
    parent, child, lineage, effect = amendment(effect_type)
    manifest = create(child, parent=parent, child=True, lineages=(lineage,), effects=(effect,))
    assert len(corpus_view(manifest, historical=True).observations) == 2
    replacing = effect_type in {"CORRECT", "SUPERSEDE"}
    assert len(corpus_view(manifest).observations) == (1 if replacing else 2)
    assert corpus_view(manifest, "2025-12-31").observations == parent.observations
    assert len(corpus_view(manifest, "2026-01-01").observations) == (1 if replacing else 2)
    assert len(corpus_view(manifest, "2025-12-31", historical=True).observations) == 2
    assert manifest.observations[0] in (
        *parent.observations,
        manifest.new_acceptances[0].observation,
    )


def test_missing_source_or_effect_dates_abstain_without_latest_wins() -> None:
    source = authored(f"{ALPHA} supplies to {BETA}.")
    manifest = create(source, child=True, known_date=False)
    assert manifest.unresolved_parent_filing_version_ids == (filing(source).filing_version_id,)
    assert corpus_view(manifest).observations == manifest.observations
    assert corpus_view(manifest, "2026-01-01").state == "TEMPORAL_SUPPORT_UNAVAILABLE"
    parent, child, lineage, effect = amendment()
    undated = effect.model_copy(update={"effective_date": None, "effective_date_support": None})
    manifest = create(child, parent=parent, child=True, lineages=(lineage,), effects=(undated,))
    assert corpus_view(manifest, "2026-01-01").observations == ()


@pytest.mark.parametrize(
    "change", ["unsupported", "wrong_parent", "cross_issuer", "foreign_span", "date", "overlap"]
)
def test_effects_and_lineage_fail_closed(change: str) -> None:
    parent, child, lineage, effect = amendment()
    effects = (effect,)
    if change == "unsupported":
        effect = effect.model_copy(update={"supports": (support(child.source, ALPHA),)})
    elif change == "wrong_parent":
        lineage = lineage.model_copy(update={"parent_filing_version_id": fixture_id(999)})
    elif change == "cross_issuer":
        lineage = lineage.model_copy(update={"issuer_entity_id": fixture_id(102)})
    elif change == "foreign_span":
        lineage = lineage.model_copy(update={"child_identity": lineage.parent_identity})
    elif change == "date":
        effect = effect.model_copy(update={"effective_date": "2026-01-02"})
    else:
        effects = (effect, effect.model_copy(update={"id": fixture_id(912)}))
    if change != "overlap":
        effects = (effect,)
    with pytest.raises(PublicationConflict):
        create(child, parent=parent, child=True, lineages=(lineage,), effects=effects)


def test_authority_is_not_granted_by_learner_or_extra_payload() -> None:
    source = authored(f"{ALPHA} supplies to {BETA}.")
    manifest = create(source)
    with pytest.raises(ValidationError):
        PublicationRequest.model_validate(
            {
                "idempotency_key": fixture_id(940),
                "parent_corpus_version_id": manifest.id,
                "selections": (),
                "accepted": True,
            }
        )
    request = PublicationRequest(
        idempotency_key=fixture_id(941),
        parent_corpus_version_id=None,
        selections=(selected(source),),
    )
    with pytest.raises(PublicationConflict):
        build_manifest(
            request,
            configuration(),
            replace(administrator(), role="learner"),
            manifest.new_acceptances,
            manifest.filings,
            source.source.evidence,
            RegistrySnapshot(
                revision=0, sha256=hashlib.sha256(b'{"entities":[]}').hexdigest(), entities=()
            ),
        )


def test_transitive_lineage_cycle_is_rejected_but_shared_ancestor_is_allowed() -> None:
    from regintel.publication.engine import assert_acyclic
    from regintel.publication.models import AuditedLineage

    parent, _, link, _ = amendment()

    def audited(identity: int, source: str, target: str) -> AuditedLineage:
        return AuditedLineage(
            proposal=link.model_copy(
                update={
                    "id": fixture_id(identity),
                    "parent_filing_version_id": source,
                    "child_filing_version_id": target,
                }
            ),
            approved_in_corpus_version_id=parent.id,
            reviewed_by=str(administrator().id),
            auth_version=1,
        )

    first, second, third = fixture_id(951), fixture_id(952), fixture_id(953)
    chain = (audited(961, first, second), audited(962, second, third))
    assert_acyclic(chain + (audited(963, first, third),))
    with pytest.raises(PublicationConflict):
        assert_acyclic(chain + (audited(964, third, first),))


def test_effect_cannot_activate_before_its_child_source_is_published() -> None:
    parent, child, lineage, effect = amendment()
    manifest = create(child, parent=parent, child=True, lineages=(lineage,), effects=(effect,))
    # Authored immutable snapshots of a later published child: source availability
    # and amendment effective date are independent of the financial period.
    filings = tuple(
        item.model_copy(update={"published_on": "2026-02-01"})
        if item.filing_version_id == lineage.child_filing_version_id
        else item
        for item in manifest.filings
    )
    observations = tuple(
        item.model_copy(update={"source_published_on": "2026-02-01"})
        if item.filing_version_id == lineage.child_filing_version_id
        else item
        for item in manifest.observations
    )
    delayed = manifest.model_copy(update={"filings": filings, "observations": observations})
    assert corpus_view(delayed, "2026-01-15").observations == parent.observations
    assert corpus_view(delayed, "2026-02-01").observations == tuple(
        item for item in delayed.observations if item.id in delayed.active_observation_ids
    )
