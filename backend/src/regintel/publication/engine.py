"""Deterministic acceptance and explicit amendment effects; no I/O or model authority."""

import hashlib
import re
from datetime import date, datetime

from regintel.auth.types import User
from regintel.candidates.models import SourceSpan, _exact_span
from regintel.candidates.records import drafts, stable_id
from regintel.contracts.models import TextEvidence
from regintel.entities.models import RegistrySnapshot, canonical_bytes
from regintel.publication.models import (
    AcceptanceSnapshot,
    AuditedEffect,
    AuditedLineage,
    CandidateSelection,
    CorpusManifest,
    CorpusView,
    EffectProposal,
    FilingSnapshot,
    LineageProposal,
    PublicationConfiguration,
    PublicationRequest,
    PublishedObservation,
    ReviewedApproval,
)
from regintel.validation.gate import validate
from regintel.validation.models import ValidationInput


class PublicationConflict(ValueError):
    """A fresh gate, immutable decision, source or publication dependency conflicts."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PublicationConflict(message)


def approve_candidate(
    corpus_id: str,
    selection: CandidateSelection,
    source: ValidationInput,
    filing: FilingSnapshot,
    review: ReviewedApproval | None,
    configuration: PublicationConfiguration,
) -> AcceptanceSnapshot:
    require(
        source.candidate_run.id == selection.candidate_run_id,
        "The selected candidate must belong to its sealed run.",
    )
    require(
        source.candidate_run.parse_version_id == filing.parse_version_id,
        "The filing must own the complete sealed parse.",
    )
    actual = validate(source)
    require(
        actual.configuration.sha256 == configuration.validator_configuration_sha256,
        "The publication requires the installed validator configuration.",
    )
    pairs = tuple(
        zip(source.candidate_run.candidates, drafts(source.candidate_run.bundle), strict=True)
    )
    pair = next((pair for pair in pairs if pair[0].id == selection.candidate_id), None)
    require(pair is not None, "A selected owned candidate is required.")
    assert pair is not None
    record, draft = pair
    result = next(item for item in actual.results if item.candidate_id == record.id)
    require(
        result.reviewer_eligible and result.state != "QUARANTINED",
        "Mandatory failed or unresolved context checks cannot be overridden.",
    )
    if review is not None:
        decision = review.decision
        require(
            decision.id == selection.review_id
            and decision.candidate_id == record.id
            and decision.decision == "APPROVE_FOR_PUBLICATION",
            "The original final review must explicitly approve this candidate.",
        )
        evidence = {item.id: item for item in source.source.evidence}
        primary = draft.supports[0]
        require(
            primary in decision.supports
            and all(
                span.evidence_id in evidence
                and _exact_span(span, evidence[span.evidence_id])
                and span.evidence_id == primary.evidence_id
                and primary.start <= span.start < span.end <= primary.end
                for span in decision.supports
            ),
            "The original review must retain the complete exact statement.",
        )
    else:
        require(
            selection.review_id is None and result.state == "PASS",
            "Extractive confirmation requires the original supported approval.",
        )
    observation_id = stable_id("published-observation:" + record.id)
    observation = PublishedObservation(
        id=observation_id,
        acceptance_audit_id=stable_id("acceptance:" + observation_id),
        first_corpus_version_id=corpus_id,
        candidate_id=record.id,
        candidate_run_id=source.candidate_run.id,
        parse_version_id=record.parse_version_id,
        filing_version_id=filing.filing_version_id,
        validation_run_id=actual.id,
        validation_input_sha256=actual.input_sha256,
        validator_configuration_sha256=actual.configuration.sha256,
        review_id=review.decision.id if review is not None else None,
        kind=record.kind,
        subject_entity_id=record.subject_entity_id,
        object_entity_id=record.object_entity_id,
        relation_type=record.relation_type,
        metric_id=record.metric_id,
        raw_text=record.raw_text,
        quantity=result.quantity,
        supports=draft.supports,
        context_supports=result.context_supports,
        source_published_on=filing.published_on,
    )
    return AcceptanceSnapshot(
        observation=observation, fresh_validation=actual, original_review=review
    )


def exact_source(
    span: SourceSpan, filing_version_id: str, evidence: dict[str, TextEvidence]
) -> None:
    record = evidence.get(span.evidence_id)
    require(
        record is not None
        and record.source.filing_version_id == filing_version_id
        and _exact_span(span, record),
        "Amendment support must be exact and source-owned.",
    )


def validate_lineage(
    proposal: LineageProposal,
    filings: dict[str, FilingSnapshot],
    evidence: dict[str, TextEvidence],
    registry: RegistrySnapshot,
) -> None:
    parent = filings.get(proposal.parent_filing_version_id)
    child = filings.get(proposal.child_filing_version_id)
    require(parent is not None and child is not None, "Both original filing versions are required.")
    assert parent is not None and child is not None
    require(parent.filing_id != child.filing_id, "Lineage requires distinct filing identities.")
    allowed = {
        "ADDENDUM_TO": {"ADDENDUM"},
        "CORRIGENDUM_TO": {"CORRIGENDUM", "ADDENDUM"},
        "AMENDS": {"DRHP", "RHP", "PROSPECTUS", "ADDENDUM", "CORRIGENDUM"},
    }
    require(
        child.document_type in allowed[proposal.lineage_type],
        "Lineage type differs from the child source.",
    )
    entity = next(
        (item for item in registry.entities if item.id == proposal.issuer_entity_id), None
    )
    require(
        entity is not None and entity.kind == "COMPANY",
        "Lineage requires an approved issuer identity.",
    )
    assert entity is not None
    names = {
        entity.legal_name.casefold(),
        *(alias.name.casefold() for alias in entity.aliases),
        *(identifier.value.casefold() for identifier in entity.identifiers),
    }
    for span, version in (
        (proposal.parent_identity, parent.filing_version_id),
        (proposal.child_identity, child.filing_version_id),
    ):
        exact_source(span, version, evidence)
        require(
            span.quote.casefold() in names,
            "Both filing identities require an approved issuer name/identifier.",
        )
    exact_source(proposal.parent_reference, child.filing_version_id, evidence)
    reference = proposal.parent_reference.quote.casefold()
    parent_labels = {
        "DRHP": ("draft red herring prospectus", "drhp"),
        "RHP": ("red herring prospectus", "rhp"),
        "PROSPECTUS": ("prospectus",),
        "ADDENDUM": ("addendum",),
        "CORRIGENDUM": ("corrigendum",),
    }
    require(
        any(label in reference for label in parent_labels[parent.document_type]),
        "The child source must explicitly identify its reviewed parent document.",
    )


def source_date(span: SourceSpan) -> str | None:
    for format_string in ("%Y-%m-%d", "%d %B %Y", "%B %d, %Y", "%B %d %Y", "%d %b %Y"):
        try:
            return datetime.strptime(span.quote.strip(), format_string).date().isoformat()
        except ValueError:
            continue
    return None


def validate_effect(
    effect: EffectProposal,
    lineage: LineageProposal,
    previous: dict[str, PublishedObservation],
    new: dict[str, PublishedObservation],
    active: set[str],
    evidence: dict[str, TextEvidence],
) -> None:
    require(
        set(effect.affected_observation_ids).issubset(active),
        "Effects can address only active named parent observations.",
    )
    require(
        all(
            item in previous
            and previous[item].filing_version_id == lineage.parent_filing_version_id
            for item in effect.affected_observation_ids
        ),
        "Affected observations must belong to the explicit parent filing.",
    )
    require(
        all(
            item in new and new[item].filing_version_id == lineage.child_filing_version_id
            for item in effect.new_candidate_ids
        ),
        "New observations must belong to the explicit child filing.",
    )
    for span in effect.supports:
        exact_source(span, lineage.child_filing_version_id, evidence)
    wording = " ".join(span.quote.casefold() for span in effect.supports)
    cues = {
        "ADD": r"\b(add(?:ed|ition|itional)?|include[ds]?)\b",
        "CORRECT": r"\b(correct(?:ed|ion)?|amend(?:ed|ment)?|revis(?:ed|ion))\b",
        "SUPPLEMENT": r"\b(supplement(?:ed|al|ation)?|addition(?:al)?|also)\b",
        "SUPERSEDE": r"\b(supersed(?:e[ds]?|ing)|replac(?:e[ds]?|ement)|substitut(?:ed|ion))\b",
        "REMOVE": r"\b(remov(?:ed|al)|delet(?:ed|ion)|omitted|withdrawn)\b",
    }
    require(
        re.search(cues[effect.effect_type], wording) is not None,
        "The source must explicitly support the reviewed amendment operation.",
    )
    require(
        not re.search(r"\b(not|never|propos(?:e[ds]?|ing)|may|might)\b", wording),
        "Negated, proposed or uncertain effect wording requires further review.",
    )
    if effect.effective_date is not None:
        support = effect.effective_date_support
        assert support is not None
        exact_source(support, lineage.child_filing_version_id, evidence)
        require(
            source_date(support) == effect.effective_date
            and any(
                span.evidence_id == support.evidence_id
                and span.start <= support.start < support.end <= span.end
                for span in effect.supports
            ),
            "Effective dates require exact support inside the amendment statement.",
        )
    if effect.effect_type in {"CORRECT", "SUPERSEDE"}:
        old_keys = {
            (
                previous[item].kind,
                previous[item].subject_entity_id,
                previous[item].metric_id,
                previous[item].relation_type,
                previous[item].object_entity_id,
            )
            for item in effect.affected_observation_ids
        }
        new_keys = {
            (
                new[item].kind,
                new[item].subject_entity_id,
                new[item].metric_id,
                new[item].relation_type,
                new[item].object_entity_id,
            )
            for item in effect.new_candidate_ids
        }
        require(
            old_keys == new_keys,
            "Replacement requires matching typed disclosure subjects and metrics/endpoints.",
        )


def assert_acyclic(lineages: tuple[AuditedLineage, ...]) -> None:
    children: dict[str, set[str]] = {}
    for item in lineages:
        link = item.proposal
        children.setdefault(link.parent_filing_version_id, set()).add(link.child_filing_version_id)
    visited: set[str] = set()
    pending: set[str] = set()

    def visit(node: str) -> None:
        require(node not in pending, "Filing lineage cannot contain a cycle.")
        if node in visited:
            return
        pending.add(node)
        for child in sorted(children.get(node, ())):
            visit(child)
        pending.remove(node)
        visited.add(node)

    for node in sorted(children):
        visit(node)


def build_manifest(
    request: PublicationRequest,
    configuration: PublicationConfiguration,
    user: User,
    acceptances: tuple[AcceptanceSnapshot, ...],
    filings: tuple[FilingSnapshot, ...],
    evidence: tuple[TextEvidence, ...],
    registry: RegistrySnapshot,
    parent: CorpusManifest | None = None,
) -> CorpusManifest:
    require(
        user.role == "admin" and user.is_active, "Publication requires a current administrator."
    )
    require(
        request.parent_corpus_version_id == (parent.id if parent else None),
        "The explicitly selected published parent must match.",
    )
    request_sha = hashlib.sha256(canonical_bytes(request)).hexdigest()
    corpus_id = stable_id(
        "corpus:" + request.idempotency_key + ":" + request_sha + ":" + configuration.sha256
    )
    previous = {item.id: item for item in parent.observations} if parent else {}
    new = {item.observation.candidate_id: item.observation for item in acceptances}
    require(
        set(new) == {item.candidate_id for item in request.selections}
        and len(new) == len(acceptances),
        "Every selected candidate requires one fresh acceptance.",
    )
    require(
        all(
            item.first_corpus_version_id == corpus_id and item.id not in previous
            for item in new.values()
        ),
        "New accepted observations cannot replace or clone historical observations.",
    )
    all_filings = {item.filing_version_id: item for item in parent.filings} if parent else {}
    for filing in filings:
        require(
            filing.filing_version_id not in all_filings
            or all_filings[filing.filing_version_id] == filing,
            "An immutable filing snapshot conflicts.",
        )
        all_filings[filing.filing_version_id] = filing
    records = {item.id: item for item in evidence}
    old_lineages = parent.lineages if parent else ()
    lineages = list(old_lineages)
    for link in request.lineages:
        require(
            link.id not in {item.proposal.id for item in lineages},
            "A lineage decision is immutable.",
        )
        require(
            not any(
                (item.proposal.parent_filing_version_id, item.proposal.child_filing_version_id)
                == (link.parent_filing_version_id, link.child_filing_version_id)
                for item in lineages
            ),
            "A filing pair already has a final lineage decision.",
        )
        validate_lineage(link, all_filings, records, registry)
        lineages.append(
            AuditedLineage(
                proposal=link,
                approved_in_corpus_version_id=corpus_id,
                reviewed_by=str(user.id),
                auth_version=user.auth_version,
            )
        )
    assert_acyclic(tuple(lineages))
    by_lineage = {item.proposal.id: item.proposal for item in lineages}
    active = set(parent.active_observation_ids) if parent else set()
    effects = list(parent.effects) if parent else []
    touched: set[str] = set()
    for effect in request.effects:
        require(
            effect.id not in {item.proposal.id for item in effects},
            "An effect decision is immutable.",
        )
        effect_lineage = by_lineage.get(effect.lineage_id)
        require(
            effect_lineage is not None, "An effect requires a supported explicit filing lineage."
        )
        assert effect_lineage is not None
        require(
            not touched.intersection(effect.affected_observation_ids),
            "Competing effects on the same observation require a separate reviewed resolution.",
        )
        validate_effect(effect, effect_lineage, previous, new, active, records)
        for prior in effects:
            require(
                not (
                    set(prior.new_observation_ids).intersection(effect.affected_observation_ids)
                    and prior.proposal.effective_date is not None
                    and effect.effective_date is not None
                    and effect.effective_date < prior.proposal.effective_date
                ),
                "Conflicting temporal effect order requires an explicit reviewed resolution.",
            )
        touched.update(effect.affected_observation_ids)
        if effect.effect_type in {"CORRECT", "SUPERSEDE", "REMOVE"}:
            active.difference_update(effect.affected_observation_ids)
        effects.append(
            AuditedEffect(
                proposal=effect,
                new_observation_ids=tuple(new[item].id for item in effect.new_candidate_ids),
                approved_in_corpus_version_id=corpus_id,
                reviewed_by=str(user.id),
                auth_version=user.auth_version,
            )
        )
    active.update(item.id for item in new.values())
    all_decisions: tuple[AuditedLineage | AuditedEffect, ...] = (*lineages, *effects)
    decision_ids = tuple(item.proposal.id for item in all_decisions)
    occupied = {item.id for item in (*previous.values(), *new.values())}
    occupied.update(records)
    occupied.update(item.subject_entity_id for item in (*previous.values(), *new.values()))
    occupied.update(
        item.object_entity_id
        for item in (*previous.values(), *new.values())
        if item.object_entity_id is not None
    )
    require(
        len(set(decision_ids)) == len(decision_ids) and not occupied.intersection(decision_ids),
        "Amendment decisions require distinct IDs without observation/entity/evidence collisions.",
    )
    linked = {item.proposal.child_filing_version_id for item in lineages}
    unresolved = tuple(
        sorted(
            item.filing_version_id
            for item in all_filings.values()
            if item.document_type in {"ADDENDUM", "CORRIGENDUM"}
            and item.filing_version_id not in linked
        )
    )
    return CorpusManifest(
        id=corpus_id,
        parent_corpus_version_id=parent.id if parent else None,
        request_sha256=request_sha,
        configuration=configuration,
        approved_by=str(user.id),
        approved_auth_version=user.auth_version,
        filings=tuple(all_filings[key] for key in sorted(all_filings)),
        observations=tuple(sorted((*previous.values(), *new.values()), key=lambda item: item.id)),
        new_acceptances=tuple(sorted(acceptances, key=lambda item: item.observation.id)),
        lineages=tuple(sorted(lineages, key=lambda item: item.proposal.id)),
        effects=tuple(effects),
        active_observation_ids=tuple(sorted(active)),
        unresolved_parent_filing_version_ids=unresolved,
    )


def corpus_view(
    manifest: CorpusManifest, as_of_date: str | None = None, *, historical: bool = False
) -> CorpusView:
    if as_of_date is not None:
        date.fromisoformat(as_of_date)
    if as_of_date is None:
        selected = tuple(
            item
            for item in manifest.observations
            if historical or item.id in manifest.active_observation_ids
        )
    elif any(item.published_on is None for item in manifest.filings) or any(
        item.proposal.effective_date is None for item in manifest.effects
    ):
        return CorpusView(
            corpus_version_id=manifest.id,
            as_of_date=as_of_date,
            state="TEMPORAL_SUPPORT_UNAVAILABLE",
            observations=(),
            unresolved_parent_filing_version_ids=manifest.unresolved_parent_filing_version_ids,
        )
    else:
        visible = {
            item.id
            for item in manifest.observations
            if item.source_published_on is not None and item.source_published_on <= as_of_date
        }
        if not historical:
            filings = {item.filing_version_id: item for item in manifest.filings}
            lineages = {item.proposal.id: item.proposal for item in manifest.lineages}
            for item in manifest.effects:
                effect = item.proposal
                child = filings[lineages[effect.lineage_id].child_filing_version_id]
                applies = (
                    effect.effective_date is not None
                    and effect.effective_date <= as_of_date
                    and child.published_on is not None
                    and child.published_on <= as_of_date
                )
                if applies:
                    visible.difference_update(
                        effect.affected_observation_ids
                        if effect.effect_type in {"CORRECT", "SUPERSEDE", "REMOVE"}
                        else ()
                    )
                else:
                    visible.difference_update(item.new_observation_ids)
        selected = tuple(item for item in manifest.observations if item.id in visible)
    return CorpusView(
        corpus_version_id=manifest.id,
        as_of_date=as_of_date,
        state="AVAILABLE",
        observations=selected,
        unresolved_parent_filing_version_ids=manifest.unresolved_parent_filing_version_ids,
    )
