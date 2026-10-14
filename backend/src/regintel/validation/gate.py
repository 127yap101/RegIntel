"""Conservative mandatory gates over immutable filing proposals and source context."""

import hashlib
import re
from pathlib import Path
from typing import get_args

from regintel.candidates.extraction import _statement_ranges, validate_bundle
from regintel.candidates.models import (
    CandidateBundle,
    DraftCandidate,
    ExtractionInput,
    effective_mentions,
)
from regintel.candidates.records import drafts, stable_id
from regintel.contracts.models import TextEvidence
from regintel.validation.models import (
    CheckCode,
    ContextWitness,
    ValidationCheck,
    ValidationConfiguration,
    ValidationInput,
    ValidationResult,
    ValidationRun,
)
from regintel.validation.quantity import normalize_quantity

_INJECTION = re.compile(
    r"\b(?:ignore|override|disregard)\s+(?:(?:all|the|previous|prior|system|these)\s+)*"
    r"(?:instructions?|rules?|prompts?|gates?)\b"
    r"|\b(?:system prompt|developer message|publish all candidates|accept all candidates)\b"
    r"|<\s*/?\s*(?:system|developer|assistant)\s*>|\b(?:run|execute)\s+(?:this\s+)?(?:code|command)\b",
    re.I,
)
_EXAMPLE = re.compile(
    r"\b(?:hypothetical|illustrative|illustration|fictional|for example|suppose|"
    r"example only|sample sentence|test fixture)\b",
    re.I,
)
_QUALIFIER = re.compile(
    r"\b(?:not|never|no longer|may|might|could|would|will|reportedly|allegedly|"
    r"purportedly|according to|claims?|claimed|denies|denied|disputes|disputed|"
    r"expects?|expected|intends?|intended|plans?|planned|proposes?|proposed|if|unless|"
    r"subject to|conditional|previously|formerly|historically)\b",
    re.I,
)
_RELATIONS: tuple[tuple[str, str, bool], ...] = (
    ("OWNS", r"owns", False),
    ("OWNS", r"is owned by", True),
    ("PROMOTER_OF", r"is (?:a |the )?promoter of", False),
    ("PROMOTER_OF", r"has (?:a |the )?promoter", True),
    ("SUBSIDIARY_OF", r"is (?:a |the )?subsidiary of", False),
    ("SUBSIDIARY_OF", r"has (?:a |the )?subsidiary", True),
    ("SUPPLIES_TO", r"supplies to", False),
    ("SUPPLIES_TO", r"is supplied by", True),
    ("AUDITS", r"audits|is (?:a |the )?auditor of", False),
    ("AUDITS", r"is audited by", True),
    ("LENDS_TO", r"lends to|is (?:a |the )?lender to", False),
    ("LENDS_TO", r"borrows from", True),
)


def current_configuration() -> ValidationConfiguration:
    """Fingerprint gate logic and reused geometry logic, without changing frozen files."""
    digest = hashlib.sha256()
    package = Path(__file__).parent
    files = [package / name for name in ("models.py", "gate.py", "quantity.py", "scope.py")]
    files.extend(
        package.parent / relative
        for relative in (
            "parsing/adapter.py",
            "parsing/geometry.py",
            "evidence/projection.py",
            "candidates/models.py",
            "candidates/extraction.py",
            "candidates/records.py",
            "parsing/models.py",
            "contracts/models.py",
            "contracts/primitives.py",
            "entities/models.py",
            "ingestion/models.py",
        )
    )
    for path in files:
        contents = path.read_bytes()
        name = path.relative_to(package.parent).as_posix()
        digest.update(name.encode("ascii") + b"\0" + len(contents).to_bytes(8, "big") + contents)
    return ValidationConfiguration(code_sha256=digest.hexdigest())


def _whole_statement(draft: DraftCandidate, record: TextEvidence) -> bool:
    primary = draft.supports[0]
    for start, end in _statement_ranges(record.span.quote):
        text = record.span.quote[start:end]
        left = len(text) - len(text.lstrip())
        right = len(text.rstrip())
        if (primary.start, primary.end) in {
            (record.span.start + start, record.span.start + end),
            (record.span.start + start + left, record.span.start + start + right),
        }:
            return True
    return False


def _one_bundle(draft: DraftCandidate) -> CandidateBundle:
    return CandidateBundle.model_validate(
        {
            "numeric_facts": (draft,) if draft.kind == "numeric_fact" else (),
            "narrative_facts": (draft,) if draft.kind == "narrative_fact" else (),
            "relations": (draft,) if draft.kind == "relation" else (),
            "issues": (),
        }
    )


def _numeric_context_scoped(
    draft: DraftCandidate, source: ExtractionInput, witnesses: tuple[ContextWitness, ...]
) -> bool:
    """Require one complete subject/metric/value claim with only its explicit context."""
    raw = draft.raw_quantity
    if raw is None:
        return False
    primary = draft.supports[0]
    mentions = [
        item
        for item in effective_mentions(source)
        if (
            item.support.evidence_id == primary.evidence_id
            and primary.start <= item.support.start < item.support.end <= primary.end
        )
    ]
    subject = next((item for item in mentions if item.mention_id == draft.subject_mention_id), None)
    metric = next((item for item in source.metrics if item.id == draft.metric_id), None)
    if (
        subject is None
        or metric is None
        or len(mentions) != 1
        or primary.quote[: subject.support.start - primary.start].strip()
    ):
        return False
    head = primary.quote[subject.support.end - primary.start : raw.value.start - primary.start]
    if not any(
        re.fullmatch(
            r"\s*(?:(?:standalone|consolidated)\s+)?"
            + re.escape(cue)
            + r"\s*(?:was|were|is|of|:|=)?\s*(?:INR|USD|Rs\.|₹|\$)?\s*",
            head,
            re.I,
        )
        for cue in metric.cue_phrases
    ):
        return False
    tail_start = raw.value.end - primary.start
    tail = list(primary.quote[tail_start:])
    for witness in witnesses:
        span = witness.span
        if witness.role != "VALUE" and span.start >= raw.value.end:
            start, end = (
                span.start - primary.start - tail_start,
                span.end - primary.start - tail_start,
            )
            tail[start:end] = " " * (end - start)
    remainder = "".join(tail)
    # These linking words add no additional value, entity, metric or condition.
    return (
        re.fullmatch(r"(?:\s|[.,:;()]|\b(?:for|the|period|on|a|basis)\b)*", remainder, re.I)
        is not None
    )


def _evaluate(
    source: ValidationInput, candidate_id: str, draft: DraftCandidate
) -> ValidationResult:
    checks: dict[str, ValidationCheck] = {
        code: ValidationCheck.model_validate(
            {"code": code, "state": "PASS", "message": "Not applicable to this candidate kind."}
        )
        for code in get_args(CheckCode)
    }

    def check(code: CheckCode, state: str, message: str) -> None:
        checks[code] = ValidationCheck.model_validate(
            {"code": code, "state": state, "message": message}
        )

    try:
        validate_bundle(source.source, _one_bundle(draft))
        check("SOURCE", "PASS", "All source IDs, spans and frozen candidate bindings are exact.")
    except ValueError:
        check(
            "SOURCE",
            "FAIL",
            "The candidate does not match its supplied immutable source and bindings.",
        )
    fresh = ExtractionInput.model_validate(
        source.source.model_dump(mode="python") | {"reviews": source.entity_reviews}
    )
    mentions = {item.mention_id: item for item in effective_mentions(fresh)}
    subject = mentions.get(draft.subject_mention_id)
    object_mention = mentions.get(draft.object_mention_id or "")
    if (
        subject is None
        or subject.entity_id != draft.subject_entity_id
        or (
            draft.kind == "relation"
            and (object_mention is None or object_mention.entity_id != draft.object_entity_id)
        )
    ):
        check(
            "ENTITY", "FAIL", "A current source entity decision no longer supports this candidate."
        )
    else:
        check(
            "ENTITY",
            "PASS",
            "Current effective source mentions support the supplied canonical IDs.",
        )
    primary = draft.supports[0]
    record = next((item for item in source.source.evidence if item.id == primary.evidence_id), None)
    if primary.evidence_id in source.table_evidence_ids:
        check(
            "TABLE_CONTEXT",
            "REVIEW",
            "Table geometry overlaps this text; original row/header/cell support is unavailable.",
        )
    else:
        check(
            "TABLE_CONTEXT", "PASS", "This source has no server-detected processed-table overlap."
        )
    if record is None or not _whole_statement(draft, record):
        check(
            "SOURCE_SCOPE",
            "FAIL",
            "A candidate must preserve its complete source statement and qualifications.",
        )
    elif _INJECTION.search(record.span.quote):
        check(
            "SOURCE_SCOPE",
            "FAIL",
            "Instruction-like source content cannot authorize a filing claim.",
        )
    elif primary.evidence_id in source.transcription_evidence_ids:
        check(
            "SOURCE_SCOPE",
            "REVIEW",
            "OCR or unknown transcription provenance needs original-source verification.",
        )
    elif _EXAMPLE.search(record.span.quote):
        check(
            "SOURCE_SCOPE",
            "REVIEW",
            "Illustrative or hypothetical source scope cannot establish an actual claim.",
        )
    elif draft.kind != "narrative_fact" and (
        _QUALIFIER.search(record.span.quote)
        or any(char in record.span.quote for char in ('"', "“", "”"))
    ):
        check(
            "SOURCE_SCOPE",
            "REVIEW",
            "Negation, conditions, temporal scope, quotation or attribution require resolution.",
        )
    else:
        check(
            "SOURCE_SCOPE",
            "PASS",
            "Complete source context preserves the claim's applicable qualifications.",
        )

    policies = {policy.metric_id: policy for policy in source.policies}
    policy = policies.get(draft.metric_id or "")
    if draft.kind == "relation":
        if subject is not None and object_mention is not None:
            endpoints = sorted((subject, object_mention), key=lambda item: item.support.start)
            left, right = endpoints
            before = primary.quote[: left.support.start - primary.start]
            between = primary.quote[
                left.support.end - primary.start : right.support.start - primary.start
            ]
            after = primary.quote[right.support.end - primary.start :]
            valid = []
            for relation, pattern, inverse in _RELATIONS:
                if re.fullmatch(r"\s*(?:" + pattern + r")\s*", between, re.I):
                    valid.append(
                        (
                            relation,
                            right.entity_id if inverse else left.entity_id,
                            left.entity_id if inverse else right.entity_id,
                        )
                    )
            if (
                draft.relation_type == "OWNS"
                and draft.raw_quantity is not None
                and re.fullmatch(
                    r"\s*owns\s+" + re.escape(draft.raw_quantity.value.quote) + r"\s*%\s+of\s*",
                    between,
                    re.I,
                )
            ):
                valid.append(("OWNS", left.entity_id, right.entity_id))
            # Quantified ownership context is checked separately; other suffixes need review.
            suffix_ok = re.fullmatch(r"\s*\.?\s*", after) is not None or (
                draft.relation_type == "OWNS"
                and draft.raw_quantity is not None
                and re.fullmatch(
                    r"\s*,?\s*(?:representing |with )?(?:issued|paid-up) equity share capital"
                    r"(?:[,;]?\s+)(?:direct|indirect|aggregate) (?:equity|voting|economic) "
                    r"(?:ownership|stake|interest)(?:[,;]?\s+)as (?:at|of) "
                    r"[0-9]{1,2} [A-Za-z]+ [0-9]{4}\.?\s*",
                    after,
                    re.I,
                )
                is not None
            )
            expected = (draft.relation_type, draft.subject_entity_id, draft.object_entity_id)
            if valid and expected not in valid:
                check(
                    "DIRECTION",
                    "FAIL",
                    "The candidate reverses or changes the explicitly supported relation.",
                )
            elif expected not in valid or before.strip() or not suffix_ok:
                check(
                    "DIRECTION",
                    "REVIEW",
                    "The source is outside the narrow fully directed affirmative relation grammar.",
                )
            else:
                check(
                    "DIRECTION",
                    "PASS",
                    "A complete explicit source grammar supports the typed relation and direction.",
                )
            local = [
                mention
                for mention in effective_mentions(fresh)
                if mention.support.evidence_id == primary.evidence_id
                and primary.start <= mention.support.start < mention.support.end <= primary.end
            ]
            if {mention.entity_id for mention in local} != {
                draft.subject_entity_id,
                draft.object_entity_id,
            }:
                check(
                    "ATTRIBUTION",
                    "REVIEW",
                    "Additional source entities make relation attribution ambiguous.",
                )
            else:
                check(
                    "ATTRIBUTION",
                    "PASS",
                    "The source relation binds only the supplied local endpoints.",
                )
        if draft.relation_type == "OWNS" and draft.raw_quantity is None:
            for code in (
                "VALUE",
                "UNIT",
                "PERIOD",
                "BASIS",
                "DENOMINATOR",
                "STAKE_KIND",
                "OWNERSHIP_DATE",
            ):
                check(
                    code,
                    "REVIEW",
                    "Ownership needs explicit percentage, denominator, date and ownership basis.",
                )
        elif draft.relation_type != "OWNS" and draft.raw_quantity is not None:
            check(
                "VALUE",
                "REVIEW",
                "Quantitative interpretation is not implemented for this relation type.",
            )
    else:
        metric = next((item for item in source.source.metrics if item.id == draft.metric_id), None)
        cues = (
            tuple(
                match
                for cue in metric.cue_phrases
                for match in re.finditer(
                    r"(?<!\w)" + re.escape(cue) + r"(?!\w)", primary.quote, re.I
                )
            )
            if metric
            else ()
        )
        local = [
            mention
            for mention in effective_mentions(fresh)
            if mention.support.evidence_id == primary.evidence_id
            and primary.start <= mention.support.start < mention.support.end <= primary.end
        ]
        if metric is None or metric.kind != draft.kind or not cues:
            check(
                "METRIC", "FAIL", "The supplied metric cue does not occur in this source statement."
            )
        elif draft.kind == "numeric_fact" and policy is None:
            check(
                "METRIC",
                "REVIEW",
                "Extraction cues do not establish metric semantics; a reviewed policy is required.",
            )
        else:
            check(
                "METRIC",
                "PASS",
                "The supplied metric and applicable reviewed policy match this exact source.",
            )
        if len({mention.entity_id for mention in local}) != 1:
            check(
                "ATTRIBUTION", "REVIEW", "The source fact has ambiguous local entity attribution."
            )
        elif draft.kind == "numeric_fact" and draft.raw_quantity is not None:
            value = draft.raw_quantity.value
            immediate = [
                match
                for match in cues
                if match.end() <= value.start - primary.start
                and re.fullmatch(
                    r"\s*(?:was|were|is|of|:|=)?\s*(?:INR|USD|Rs\.|₹|\$)?\s*",
                    primary.quote[match.end() : value.start - primary.start],
                    re.I,
                )
            ]
            if len(immediate) != 1:
                check(
                    "ATTRIBUTION",
                    "FAIL",
                    "The value is not directly and uniquely attributed to the supplied metric cue.",
                )
            else:
                check(
                    "ATTRIBUTION",
                    "PASS",
                    "One metric cue directly attributes this exact raw value.",
                )
        else:
            check(
                "ATTRIBUTION",
                "PASS",
                "One supplied local entity binds the unchanged extractive narrative.",
            )
        if draft.kind == "narrative_fact":
            check(
                "EXTRACTIVE_REVIEW",
                "REVIEW",
                "A reviewer must confirm the unchanged narrative and its source qualifications.",
            )

    effective = tuple(effective_mentions(fresh))
    effective_ids = {item.mention_id for item in effective}
    unavailable = [
        mention
        for mention in fresh.entity_run.mentions
        if mention.id not in effective_ids
        and mention.support.evidence_id == primary.evidence_id
        and primary.start <= mention.support.start < mention.support.end <= primary.end
        and not any(
            mention.support.start < item.support.end and item.support.start < mention.support.end
            for item in effective
        )
    ]
    if unavailable:
        check(
            "ATTRIBUTION", "REVIEW", "Unresolved source entities prevent unique claim attribution."
        )
    quantity = normalize_quantity(draft, policy)
    if (
        draft.kind == "numeric_fact"
        and checks["ATTRIBUTION"].state != "FAIL"
        and not _numeric_context_scoped(draft, fresh, quantity.context_supports)
    ):
        check(
            "ATTRIBUTION",
            "REVIEW",
            "Additional claim text or numbers prevent exact subject/metric/context attribution.",
        )
    for item in quantity.checks:
        # Unsupported quantitative non-ownership relation interpretations remain blocking.
        if (
            checks[item.code].state != "REVIEW"
            or draft.kind != "relation"
            or draft.relation_type == "OWNS"
        ):
            checks[item.code] = item
    states = {item.state for item in checks.values()}
    reviews = {item.code for item in checks.values() if item.state == "REVIEW"}
    return ValidationResult(
        candidate_id=candidate_id,
        state="QUARANTINED" if "FAIL" in states else "REVIEW" if "REVIEW" in states else "PASS",
        checks=tuple(checks[code] for code in get_args(CheckCode)),
        quantity=quantity.quantity,
        context_supports=quantity.context_supports,
        reviewer_eligible="FAIL" not in states
        and (not reviews or reviews == {"EXTRACTIVE_REVIEW"}),
    )


def validate(source: ValidationInput, *, input_sha256: str | None = None) -> ValidationRun:
    """Create a complete immutable gate result; never accept or publish a candidate."""
    source = ValidationInput.model_validate(source.model_dump(mode="python"))
    configuration = current_configuration()
    input_sha = source.sha256 if input_sha256 is None else input_sha256
    results = tuple(
        _evaluate(source, candidate.id, draft)
        for candidate, draft in zip(
            source.candidate_run.candidates, drafts(source.candidate_run.bundle), strict=True
        )
    )
    return ValidationRun(
        id=stable_id("validation-run:" + input_sha + ":" + configuration.sha256),
        candidate_run_id=source.candidate_run.id,
        parse_version_id=source.candidate_run.parse_version_id,
        input_sha256=input_sha,
        configuration=configuration,
        results=results,
    )
