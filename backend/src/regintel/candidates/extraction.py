"""Deterministic local proposals and provider-output membership checks.

These checks establish exact source/ID bindings. They do not establish financial
correctness, semantic support, acceptance, amendment effects or publication.
"""

import hashlib
import re
from pathlib import Path

from regintel.candidates.models import (
    CandidateBundle,
    DraftCandidate,
    EffectiveMention,
    ExtractionConfiguration,
    ExtractionInput,
    ExtractionIssue,
    RawQuantity,
    SourceSpan,
    _exact_span,
    effective_mentions,
)
from regintel.contracts.models import RelationType, TextEvidence
from regintel.entities.models import canonical_bytes

_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])|[\r\n]+")
_ABBREVIATION = re.compile(r"(?:Ltd|Pvt|Mr|Mrs|Ms|Dr|Co|Rs)\.$", re.IGNORECASE)
_NUMBER = re.compile(
    r"(?<![\w.,])(?:\([+-]?(?:[0-9]{1,3}(?:,[0-9]{2,3})+|[0-9]+)(?:\.[0-9]+)?\)"
    r"|[+-]?(?:[0-9]{1,3}(?:,[0-9]{2,3})+|[0-9]+)(?:\.[0-9]+)?)(?!\w|[.,][0-9])"
)
_RAW_DATE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}"
    r"|[0-9]{1,2} [A-Za-z]+ [0-9]{4}"
)
_VALUE_PREFIX = re.compile(r"\s*(?:was|were|is|of|:|=)?\s*(?:INR|USD|Rs\.|₹|\$)?\s*", re.I)
_UNIT = re.compile(r"(?<!\w)(?:crores?|lakhs?|millions?|billions?|MW|GW|shares)(?!\w)|%", re.I)
_CURRENCY = re.compile(r"(?<!\w)(?:INR|USD|Rs\.)(?!\w)|₹|\$", re.I)
_PERIOD = re.compile(
    r"\b(?:year|quarter|six months|nine months) ended [0-9]{1,2} [A-Za-z]+ [0-9]{4}\b"
    r"|\bas (?:at|of) [0-9]{1,2} [A-Za-z]+ [0-9]{4}\b",
    re.I,
)
_BASIS = re.compile(r"\b(?:standalone|consolidated)\b", re.I)
_DENOMINATOR = re.compile(r"\b(?:issued|paid-up) equity share capital\b", re.I)
_STAKE_KIND = re.compile(r"\b(?:equity|voting|economic) (?:stake|interest|ownership)\b", re.I)
_OWNERSHIP_DATE = re.compile(r"\bas (?:at|of) ([0-9]{1,2} [A-Za-z]+ [0-9]{4})\b", re.I)
_CONTEXT_PATTERNS = (_UNIT, _CURRENCY, _PERIOD, _BASIS, _DENOMINATOR, _STAKE_KIND, _OWNERSHIP_DATE)
_RELATIONS: tuple[tuple[RelationType, re.Pattern[str], bool], ...] = (
    ("OWNS", re.compile(r"\bowns\b", re.I), False),
    ("OWNS", re.compile(r"\bis owned by\b", re.I), True),
    ("PROMOTER_OF", re.compile(r"\bis (?:a |the )?promoter of\b", re.I), False),
    ("PROMOTER_OF", re.compile(r"\bhas (?:a |the )?promoter\b", re.I), True),
    ("SUBSIDIARY_OF", re.compile(r"\bis (?:a |the )?subsidiary of\b", re.I), False),
    ("SUBSIDIARY_OF", re.compile(r"\bhas (?:a |the )?subsidiary\b", re.I), True),
    ("SUPPLIES_TO", re.compile(r"\bsupplies to\b", re.I), False),
    ("SUPPLIES_TO", re.compile(r"\bis supplied by\b", re.I), True),
    ("AUDITS", re.compile(r"\baudits\b|\bis (?:a |the )?auditor of\b", re.I), False),
    ("AUDITS", re.compile(r"\bis audited by\b", re.I), True),
    ("LENDS_TO", re.compile(r"\blends to\b|\bis (?:a |the )?lender to\b", re.I), False),
    ("LENDS_TO", re.compile(r"\bborrows from\b", re.I), True),
)


def current_configuration() -> ExtractionConfiguration:
    digest = hashlib.sha256()
    for name in ("models.py", "extraction.py", "records.py"):
        contents = Path(__file__).with_name(name).read_bytes()
        digest.update(name.encode("ascii") + b"\0" + len(contents).to_bytes(8, "big") + contents)
    return ExtractionConfiguration(code_sha256=digest.hexdigest())


def _statement_ranges(text: str) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    start = 0
    for boundary in _BOUNDARY.finditer(text):
        if _ABBREVIATION.search(text[max(start, boundary.start() - 5) : boundary.start()]):
            continue
        ranges.append((start, boundary.start()))
        start = boundary.end()
    ranges.append((start, len(text)))
    return tuple((start, end) for start, end in ranges if start < end and text[start:end].strip())


def _contained(inner: SourceSpan, outer: SourceSpan) -> bool:
    return (
        inner.evidence_id == outer.evidence_id
        and outer.start <= inner.start < inner.end <= outer.end
    )


def validate_bundle(source: ExtractionInput, bundle: CandidateBundle) -> CandidateBundle:
    """Revalidate schema and exact bindings; passing does not accept any proposal."""
    source = ExtractionInput.model_validate(source.model_dump(mode="python"))
    bundle = CandidateBundle.model_validate(bundle.model_dump(mode="python"))
    evidence = {record.id: record for record in source.evidence}
    mentions = {mention.mention_id: mention for mention in effective_mentions(source)}
    metrics = {metric.id: metric for metric in source.metrics}
    candidates = (*bundle.numeric_facts, *bundle.narrative_facts, *bundle.relations)
    for candidate in candidates:
        primary = candidate.supports[0]
        record = evidence.get(primary.evidence_id)
        if (
            record is None
            or not _exact_span(primary, record)
            or primary.quote != candidate.raw_text
        ):
            raise ValueError("Candidate primary text must exactly match a supplied source span.")
        if not any(
            record.span.start + start <= primary.start < primary.end <= record.span.start + end
            for start, end in _statement_ranges(record.span.quote)
        ):
            raise ValueError("Candidate support must occupy one bounded source statement.")
        spans: list[SourceSpan] = list(candidate.supports)
        if candidate.raw_quantity is not None:
            spans.extend(
                span
                for span in (
                    candidate.raw_quantity.value,
                    candidate.raw_quantity.unit,
                    candidate.raw_quantity.currency,
                    candidate.raw_quantity.period,
                    candidate.raw_quantity.basis,
                    candidate.raw_quantity.denominator,
                    candidate.raw_quantity.stake_kind,
                    candidate.raw_quantity.ownership_date,
                )
                if span is not None
            )
        if any(not _contained(span, primary) or not _exact_span(span, record) for span in spans):
            raise ValueError("Every candidate context span must belong to its exact statement.")
        subject = mentions.get(candidate.subject_mention_id)
        if (
            subject is None
            or subject.entity_id != candidate.subject_entity_id
            or not _contained(subject.support, primary)
        ):
            raise ValueError("Candidate subject must bind to a supplied effective source mention.")
        if candidate.kind == "relation":
            object_mention = mentions.get(candidate.object_mention_id or "")
            if (
                object_mention is None
                or object_mention.entity_id != candidate.object_entity_id
                or not _contained(object_mention.support, primary)
            ):
                raise ValueError(
                    "Candidate object must bind to a supplied effective source mention."
                )
        else:
            metric = metrics.get(candidate.metric_id or "")
            if metric is None or metric.kind != candidate.kind:
                raise ValueError("Candidate metric must be supplied with the matching fact kind.")
    if any(not set(issue.evidence_ids).issubset(evidence) for issue in bundle.issues):
        raise ValueError("Extraction issue evidence must belong to the supplied source collection.")
    return bundle


def _span(record: TextEvidence, start: int, end: int) -> SourceSpan:
    return SourceSpan(
        evidence_id=record.id,
        start=record.span.start + start,
        end=record.span.start + end,
        quote=record.span.quote[start:end],
    )


def _matching_span(pattern: re.Pattern[str], primary: SourceSpan) -> SourceSpan | None:
    matches = tuple(pattern.finditer(primary.quote))
    if len(matches) != 1:
        # Multiple source labels cannot be silently reconciled into one context.
        return None
    match = matches[0]
    return SourceSpan(
        evidence_id=primary.evidence_id,
        start=primary.start + match.start(),
        end=primary.start + match.end(),
        quote=match.group(),
    )


def _raw_quantity(value: SourceSpan, primary: SourceSpan) -> RawQuantity:
    return RawQuantity(
        value=value,
        unit=_matching_span(_UNIT, primary),
        currency=_matching_span(_CURRENCY, primary),
        period=_matching_span(_PERIOD, primary),
        basis=_matching_span(_BASIS, primary),
        denominator=_matching_span(_DENOMINATOR, primary),
        stake_kind=_matching_span(_STAKE_KIND, primary),
        ownership_date=_matching_span(_OWNERSHIP_DATE, primary),
    )


def _cue_positions(text: str, cues: tuple[str, ...]) -> tuple[tuple[int, int], ...]:
    positions: set[tuple[int, int]] = set()
    for cue in cues:
        for match in re.finditer(r"(?<!\w)" + re.escape(cue) + r"(?!\w)", text, re.I):
            positions.add((match.start(), match.end()))
    return tuple(sorted(positions))


def _local_mentions(
    mentions: tuple[EffectiveMention, ...], primary: SourceSpan
) -> tuple[EffectiveMention, ...]:
    ordered = sorted(
        (mention for mention in mentions if _contained(mention.support, primary)),
        key=lambda mention: (mention.support.start, mention.support.end, mention.mention_id),
    )
    result: list[EffectiveMention] = []
    for mention in ordered:
        if result and mention.support.start < result[-1].support.end:
            # Overlapping mention representations are not separate relation endpoints.
            if mention.entity_id != result[-1].entity_id:
                return ()
            continue
        result.append(mention)
    return tuple(result)


def extract(source: ExtractionInput) -> CandidateBundle:
    """Generate conservative same-statement baselines with exact unaltered text."""
    source = ExtractionInput.model_validate(source.model_dump(mode="python"))
    mentions = effective_mentions(source)
    effective_ids = {mention.mention_id for mention in mentions}
    unavailable = tuple(
        SourceSpan.model_validate(mention.support.model_dump(mode="python"))
        for mention in source.entity_run.mentions
        if mention.id not in effective_ids
    )
    numeric: list[DraftCandidate] = []
    narrative: list[DraftCandidate] = []
    relations: list[DraftCandidate] = []
    issues: list[ExtractionIssue] = []

    def issue(code: str, record: TextEvidence, message: str) -> None:
        item = ExtractionIssue.model_validate(
            {"code": code, "evidence_ids": (record.id,), "message": message}
        )
        if item not in issues:
            issues.append(item)
        if len(issues) > 1000:
            raise ValueError("Extraction issue limit exceeded; no partial bundle is returned.")

    for record in sorted(source.evidence, key=lambda item: item.id):
        for start, end in _statement_ranges(record.span.quote):
            text = record.span.quote[start:end]
            if len(text) > 20000:
                raise ValueError("A source statement exceeds the explicit window limit.")
            primary = _span(record, start, end)
            local = _local_mentions(mentions, primary)
            entities = {mention.entity_id for mention in local}
            unresolved = tuple(
                anchor
                for anchor in unavailable
                if _contained(anchor, primary)
                and not any(
                    anchor.start < mention.support.end and mention.support.start < anchor.end
                    for mention in local
                )
            )
            has_cue = any(_cue_positions(text, metric.cue_phrases) for metric in source.metrics)
            has_trigger = any(pattern.search(text) for _, pattern, _ in _RELATIONS)
            if not local and (has_cue or has_trigger):
                issue(
                    "UNRESOLVED_ENTITY", record, "No effective entity mention binds this statement."
                )
                continue
            if unresolved and (has_cue or has_trigger):
                issue(
                    "UNRESOLVED_ENTITY", record, "Unresolved source mentions require entity review."
                )
            for left, right in zip(local, local[1:], strict=False):
                if left.entity_id == right.entity_id:
                    continue
                if any(
                    left.support.end <= anchor.start < anchor.end <= right.support.start
                    for anchor in unresolved
                ):
                    continue
                gap = record.span.quote[
                    left.support.end - record.span.start : right.support.start - record.span.start
                ]
                triggers = [
                    (kind, inverse) for kind, pattern, inverse in _RELATIONS if pattern.search(gap)
                ]
                if len(triggers) != 1:
                    if triggers:
                        issue(
                            "AMBIGUOUS_CONTEXT",
                            record,
                            "Multiple directed triggers require review.",
                        )
                    continue
                kind, inverse = triggers[0]
                subject, object_mention = (right, left) if inverse else (left, right)
                ownership_values = tuple(
                    match
                    for match in _NUMBER.finditer(primary.quote)
                    if re.match(r"\s*%", primary.quote[match.end() :])
                )
                quantity = None
                if kind == "OWNS" and len(ownership_values) == 1:
                    match = ownership_values[0]
                    quantity = _raw_quantity(
                        _span(record, start + match.start(), start + match.end()), primary
                    )
                    if any(len(tuple(pattern.finditer(text))) > 1 for pattern in _CONTEXT_PATTERNS):
                        issue(
                            "AMBIGUOUS_CONTEXT",
                            record,
                            "Multiple raw context labels require review.",
                        )
                relations.append(
                    DraftCandidate(
                        kind="relation",
                        subject_entity_id=subject.entity_id,
                        subject_mention_id=subject.mention_id,
                        object_entity_id=object_mention.entity_id,
                        object_mention_id=object_mention.mention_id,
                        relation_type=kind,
                        supports=(primary,),
                        raw_text=primary.quote,
                        raw_quantity=quantity,
                    )
                )
            for metric in sorted(source.metrics, key=lambda item: item.id):
                positions = _cue_positions(text, metric.cue_phrases)
                if not positions:
                    continue
                if unresolved:
                    continue
                if len(entities) != 1:
                    issue("AMBIGUOUS_CONTEXT", record, "A fact cue has multiple entity bindings.")
                    continue
                subject = local[0]
                if metric.kind == "narrative_fact":
                    narrative.append(
                        DraftCandidate(
                            kind="narrative_fact",
                            subject_entity_id=subject.entity_id,
                            subject_mention_id=subject.mention_id,
                            metric_id=metric.id,
                            supports=(primary,),
                            raw_text=primary.quote,
                        )
                    )
                    continue
                if len(positions) != 1:
                    issue("AMBIGUOUS_CONTEXT", record, "Repeated metric cues require review.")
                    continue
                values = tuple(_NUMBER.finditer(text, positions[0][1]))
                # Only an immediately following value can be attributed to a literal cue.
                # Period/date values and distant numbers are never selected by proximity.
                immediate = tuple(
                    match
                    for match in values
                    if _VALUE_PREFIX.fullmatch(text[positions[0][1] : match.start()])
                    and not _RAW_DATE.match(text, match.start())
                )
                if len(immediate) != 1:
                    issue(
                        "MISSING_VALUE",
                        record,
                        "No single directly attributed raw value is available.",
                    )
                    continue
                match = immediate[0]
                later = tuple(other for other in values if other.start() > match.start())
                if later and re.fullmatch(
                    r"\s*(?:and|or|to|,|/|-)?\s*", text[match.end() : later[0].start()], re.I
                ):
                    issue("AMBIGUOUS_CONTEXT", record, "Multiple nearby raw values require review.")
                    continue
                value = _span(record, start + match.start(), start + match.end())
                if any(len(tuple(pattern.finditer(text))) > 1 for pattern in _CONTEXT_PATTERNS):
                    issue(
                        "AMBIGUOUS_CONTEXT", record, "Multiple raw context labels require review."
                    )
                numeric.append(
                    DraftCandidate(
                        kind="numeric_fact",
                        subject_entity_id=subject.entity_id,
                        subject_mention_id=subject.mention_id,
                        metric_id=metric.id,
                        supports=(primary,),
                        raw_text=primary.quote,
                        raw_quantity=_raw_quantity(value, primary),
                    )
                )
            if len(numeric) + len(narrative) + len(relations) > 1000:
                raise ValueError("Candidate limit exceeded; no partial bundle is returned.")

    if not (numeric or narrative or relations):
        issues.append(
            ExtractionIssue(
                code="NO_SUPPORTED_CANDIDATE",
                message="The bounded deterministic rules produced no source-linked proposals.",
            )
        )

    # Stable sorting and duplicate collapse remove repeated representations, not distinct facts.
    def ordered(items: list[DraftCandidate]) -> tuple[DraftCandidate, ...]:
        unique = {canonical_bytes(item): item for item in items}
        return tuple(unique[key] for key in sorted(unique))

    return validate_bundle(
        source,
        CandidateBundle(
            numeric_facts=ordered(numeric),
            narrative_facts=ordered(narrative),
            relations=ordered(relations),
            issues=tuple(issues),
        ),
    )
