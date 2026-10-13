"""Bounded exact-source mention detection and conservative entity proposals."""

import hashlib
import re
import unicodedata
from importlib.metadata import version
from pathlib import Path
from typing import Literal
from uuid import UUID

import spacy
from rapidfuzz.fuzz import ratio
from spacy.pipeline import EntityRuler

from regintel.contracts.models import TextEvidence
from regintel.entities.identifiers import valid_identifier
from regintel.entities.models import (
    EntityMention,
    EntityRun,
    EvidenceAnchor,
    IdentifierKind,
    MentionResolution,
    RegistrySnapshot,
    ResolutionMethod,
    ResolutionProposal,
    ResolverConfiguration,
)

_CIN = re.compile(r"(?<![A-Za-z0-9])[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}(?![A-Za-z0-9])")
_ISIN = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}[A-Z0-9]{9}[0-9](?![A-Za-z0-9])")
_COMPANY = re.compile(r"(?<!\w)(?:[A-Z][\w&.'’\-]*[ \t]+){1,11}(?:Limited|Ltd\.?|LLP)(?!\w)")
MentionKind = Literal["NAME", "CIN", "ISIN"]


def normalized_name(value: str) -> str:
    """No suffix deletion, translation, stemming or inferred aliases."""
    text = unicodedata.normalize("NFKC", value).casefold()
    return " ".join("".join(char if char.isalnum() else " " for char in text).split())


def stable_id(value: str) -> str:
    # Canonical contracts require UUIDv4 shape; derive stable bytes then set v4 bits.
    return str(UUID(bytes=hashlib.sha256(value.encode("utf-8")).digest()[:16], version=4))


def current_configuration() -> ResolverConfiguration:
    digest = hashlib.sha256()
    for name in ("models.py", "identifiers.py", "resolution.py"):
        contents = Path(__file__).with_name(name).read_bytes()
        digest.update(name.encode("ascii") + b"\0" + len(contents).to_bytes(8, "big") + contents)
    return ResolverConfiguration(
        spacy_version=version("spacy"),
        rapidfuzz_version=version("rapidfuzz"),
        code_sha256=digest.hexdigest(),
    )


def _result(
    matches: dict[str, ResolutionMethod],
    *,
    reason: str,
    force_review: bool = False,
) -> MentionResolution:
    proposals = tuple(
        ResolutionProposal(entity_id=entity_id, method=method, score=None)
        for entity_id, method in sorted(matches.items())
    )
    if len(proposals) == 1 and not force_review:
        return MentionResolution(
            state="RESOLVED",
            entity_id=proposals[0].entity_id,
            method=proposals[0].method,
            reason=reason,
            proposals=proposals,
        )
    return MentionResolution(
        state="REVIEW" if proposals else "UNRESOLVED",
        entity_id=None,
        method=None,
        reason=reason,
        proposals=proposals,
    )


class EntityResolver:
    def __init__(self, snapshot: RegistrySnapshot, configuration: ResolverConfiguration) -> None:
        if (
            configuration.spacy_version != version("spacy")
            or (configuration.rapidfuzz_version != version("rapidfuzz"))
            or configuration.code_sha256 != current_configuration().code_sha256
        ):
            raise ValueError("Resolver configuration does not identify the installed runtime.")
        self.snapshot = snapshot
        self.configuration = configuration
        self.names: dict[str, set[str]] = {}
        self.normalized: dict[str, set[str]] = {}
        self.identifiers: dict[tuple[str, str], str] = {}
        for entity in snapshot.entities:
            for name in (entity.legal_name, *(alias.name for alias in entity.aliases)):
                self.names.setdefault(name, set()).add(entity.id)
                self.normalized.setdefault(normalized_name(name), set()).add(entity.id)
            for identifier in entity.identifiers:
                key = (identifier.kind, identifier.value)
                if key in self.identifiers and self.identifiers[key] != entity.id:
                    raise ValueError("A registry identifier cannot identify different entities.")
                self.identifiers[key] = entity.id
        self.nlp = spacy.blank("en")
        self.nlp.max_length = 200001
        ruler = self.nlp.add_pipe("entity_ruler", config={"phrase_matcher_attr": "LOWER"})
        if not isinstance(ruler, EntityRuler):
            raise ValueError("EntityRuler pipeline is unavailable.")
        # Patterns carry a mention label, never a canonical entity ID. Collisions
        # stay in the independent alias index even when EntityRuler picks a span.
        ruler.add_patterns(
            [{"label": "REGINTEL_NAME", "pattern": name} for name in sorted(self.names)]
        )

    def resolve(
        self,
        kind: str,
        quote: str,
        *,
        context_identifiers: dict[str, ResolutionMethod] | None = None,
    ) -> MentionResolution:
        identifiers = context_identifiers or {}
        if kind in {"CIN", "ISIN"}:
            identifier_kind: IdentifierKind = "CIN" if kind == "CIN" else "ISIN"
            if not valid_identifier(identifier_kind, quote):
                return _result({}, reason="INVALID_IDENTIFIER")
            entity_id = self.identifiers.get((kind, quote))
            if entity_id is None:
                return _result({}, reason="UNKNOWN_IDENTIFIER")
            identifier_method: ResolutionMethod = "EXACT_CIN" if kind == "CIN" else "EXACT_ISIN"
            matches = {entity_id: identifier_method}
            if any(candidate != entity_id for candidate in identifiers):
                return _result(
                    identifiers | matches,
                    reason="CONFLICTING_IDENTIFIER_CONTEXT",
                    force_review=True,
                )
            return _result(matches, reason="EXACT_IDENTIFIER")
        exact = self.names.get(quote)
        normalized = self.normalized.get(normalized_name(quote))
        method: ResolutionMethod = "EXACT_ALIAS" if exact else "NORMALIZED_NAME"
        ids = exact or normalized or set()
        if ids:
            matches = {entity_id: method for entity_id in ids}
            if identifiers and not set(identifiers).issubset(ids):
                return _result(
                    identifiers | matches,
                    reason="CONFLICTING_IDENTIFIER_CONTEXT",
                    force_review=True,
                )
            return _result(matches, reason="APPROVED_NAME" if len(ids) == 1 else "AMBIGUOUS_NAME")
        scores: dict[str, float] = {}
        key = normalized_name(quote)
        if key:
            for name, entity_ids in self.normalized.items():
                score = float(ratio(key, name))
                if score >= self.configuration.fuzzy_threshold:
                    for entity_id in entity_ids:
                        scores[entity_id] = max(score, scores.get(entity_id, 0.0))
        proposed = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        # This is an explicitly bounded proposal list, not accepted state.
        proposed = proposed[: self.configuration.max_proposals]
        return MentionResolution(
            state="REVIEW" if proposed else "UNRESOLVED",
            entity_id=None,
            method=None,
            reason="FUZZY_PROPOSAL" if proposed else "NO_MATCH",
            proposals=tuple(
                ResolutionProposal(entity_id=entity_id, method="FUZZY", score=score)
                for entity_id, score in proposed
            ),
        )

    def run(self, evidence: tuple[TextEvidence, ...], artifact_sha256: str) -> EntityRun:
        if not evidence or len(evidence) > 10000:
            raise ValueError(
                "Resolver requires one to 10000 exact evidence records; no truncation."
            )
        parse_id = evidence[0].source.parse_version_id
        if any(record.source.parse_version_id != parse_id for record in evidence):
            raise ValueError("Resolver sources must belong to one sealed parse.")
        run_id = stable_id(
            f"entity-run:{parse_id}:{artifact_sha256}:{self.snapshot.sha256}:{self.configuration.sha256}"
        )
        mentions: list[EntityMention] = []
        for record in sorted(evidence, key=lambda item: item.id):
            text = record.span.quote
            spans: set[tuple[int, int, MentionKind]] = set()
            if self.names:
                for item in self.nlp(text).ents:
                    spans.add((item.start_char, item.end_char, "NAME"))
            patterns: tuple[tuple[re.Pattern[str], MentionKind], ...] = (
                (_CIN, "CIN"),
                (_ISIN, "ISIN"),
                (_COMPANY, "NAME"),
            )
            for pattern, kind in patterns:
                for match in pattern.finditer(text):
                    spans.add((match.start(), match.end(), kind))
            context: dict[str, ResolutionMethod] = {}
            for start, end, kind in sorted(spans, key=lambda item: (item[2], item[0], item[1])):
                entity_id = self.identifiers.get((kind, text[start:end]))
                if entity_id is not None:
                    context.setdefault(entity_id, "EXACT_CIN" if kind == "CIN" else "EXACT_ISIN")
            for start, end, kind in sorted(spans):
                quote = text[start:end]
                if len(quote) > 256:
                    raise ValueError("Entity mention exceeds the explicit source-span bound.")
                anchor = EvidenceAnchor(
                    evidence_id=record.id,
                    start=record.span.start + start,
                    end=record.span.start + end,
                    quote=quote,
                )
                mentions.append(
                    EntityMention(
                        id=stable_id(f"entity-mention:{run_id}:{record.id}:{start}:{end}:{kind}"),
                        kind=kind,
                        support=anchor,
                        resolution=self.resolve(kind, quote, context_identifiers=context),
                    )
                )
                if len(mentions) > 25000:
                    raise ValueError(
                        "Resolver mention limit exceeded; no partial run is persisted."
                    )
        return EntityRun(
            id=run_id,
            parse_version_id=parse_id,
            artifact_sha256=artifact_sha256,
            registry_revision=self.snapshot.revision,
            registry_sha256=self.snapshot.sha256,
            configuration=self.configuration,
            evidence_ids=tuple(record.id for record in sorted(evidence, key=lambda item: item.id)),
            mentions=tuple(mentions),
        )
