"""Deterministic semantic inspection of exact supports from a complete sealed parse."""

import re
from dataclasses import dataclass

from regintel.candidates.models import SourceSpan, _exact_span
from regintel.contracts.models import TextEvidence
from regintel.parsing.models import ParseArtifact, ParsedBlock
from regintel.publication.support_models import AmendmentSupport, NativeAmendmentWords


class AmendmentSupportError(ValueError):
    """Original source membership, order or bounded statement context is unverified."""


@dataclass(frozen=True)
class NativeWordPosition:
    evidence: TextEvidence
    index: int
    previous: str | None
    complete: bool = True


type NativeWordIndex = dict[str, NativeWordPosition]


def uncertain_effect_wording(text: str) -> bool:
    return (
        re.search(
            r"\b(not|never|no|propos(?:e[ds]?|ing)|may|might|could|would|expects?|expected|"
            r"intends?|intended|plans?|planned|if|unless|subject to|conditional|provided|except)\b",
            text,
            re.I,
        )
        is not None
    )


def _native_position(block: ParsedBlock) -> tuple[str, int] | None:
    if (
        block.page_id is None
        or block.page_index is None
        or block.source_cell_index is None
        or block.source_ref != f"page/{block.page_index}/text-cell/{block.source_cell_index}"
    ):
        return None
    return block.page_id, block.source_cell_index


def native_word_index(
    artifact: ParseArtifact, evidence: tuple[TextEvidence, ...]
) -> NativeWordIndex:
    """Positions come only from verified native provenance, including index gaps."""
    if artifact.provenance.adapter_name != "regintel-native-context":
        # Legacy Docling text cells can contain whole paragraphs, not native words.
        return {}
    blocks = {block.id: block for block in artifact.blocks}
    original: dict[tuple[str, int], ParsedBlock] = {}
    for original_block in artifact.blocks:
        position = _native_position(original_block)
        if position is not None:
            if position in original:
                raise AmendmentSupportError("Native original-word positions must be unambiguous.")
            original[position] = original_block
    result: NativeWordIndex = {}
    for record in evidence:
        block = blocks.get(record.span.block_id)
        if block is None:
            raise AmendmentSupportError("Evidence must belong to its sealed original block.")
        position = _native_position(block)
        if position is None:
            continue
        complete = (
            block.from_ocr is False
            and record.source.parse_version_id == artifact.id
            and record.source.filing_version_id == artifact.filing_version_id
            and record.source.page_id == position[0]
            and record.span.start == 0
            and record.span.quote == block.orig
            and record.span.end == len(record.span.quote)
        )
        previous = original.get((position[0], position[1] - 1))
        result[record.id] = NativeWordPosition(
            record,
            position[1],
            previous.orig if previous and previous.from_ocr is False else None,
            complete,
        )
    return result


def support_spans(support: AmendmentSupport) -> tuple[SourceSpan, ...]:
    return support.spans if isinstance(support, NativeAmendmentWords) else (support,)


def _sentence_end(text: str) -> bool:
    terminal = text.rstrip().rstrip("\"'”’)]")
    return bool(re.search(r"[.!?]$", terminal)) and terminal.casefold() not in {
        "rs.",
        "mr.",
        "mrs.",
        "dr.",
        "no.",
        "nos.",
        "ltd.",
        "co.",
        "e.g.",
        "i.e.",
    }


def _word_statement(first: NativeWordPosition, last: TextEvidence) -> bool:
    return (
        first.index == 0 or first.previous is not None and _sentence_end(first.previous)
    ) and _sentence_end(last.span.quote)


def support_text(
    support: AmendmentSupport,
    filing_version_id: str,
    parse_version_id: str,
    evidence: dict[str, TextEvidence],
    words: NativeWordIndex,
    *,
    statement: bool = False,
) -> str:
    """Return semantic inspection text; the caller must never persist it as an exact quote."""
    spans = support_spans(support)
    records = []
    for span in spans:
        record = evidence.get(span.evidence_id)
        if (
            record is None
            or record.source.filing_version_id != filing_version_id
            or record.source.parse_version_id != parse_version_id
            or not _exact_span(span, record)
        ):
            raise AmendmentSupportError("Amendment support must be exact and source/parse-owned.")
        records.append(record)
    first = records[0]
    if isinstance(support, NativeAmendmentWords):
        initial = words.get(first.id)
        if support.parse_version_id != parse_version_id or initial is None:
            raise AmendmentSupportError(
                "Native amendment words require their sealed original order."
            )
        for offset, (span, record) in enumerate(zip(spans, records, strict=True)):
            position = words.get(record.id)
            if (
                position is None
                or not position.complete
                or position.evidence != record
                or position.index != initial.index + offset
                or record.source != first.source
                or span.start != 0
                or span.end != record.span.end
                or span.quote != record.span.quote
            ):
                raise AmendmentSupportError(
                    "Native amendment words cannot omit or reorder context."
                )
        if statement and not _word_statement(initial, records[-1]):
            raise AmendmentSupportError("Native effect support needs complete sentence boundaries.")
        return " ".join(span.quote for span in spans)
    if statement:
        native = words.get(first.id)
        if native is not None:
            if (
                not native.complete
                or support.start != 0
                or support.end != first.span.end
                or not _word_statement(native, first)
            ):
                raise AmendmentSupportError(
                    "An isolated native word cannot conceal effect context."
                )
        else:
            before = first.span.quote[: support.start - first.span.start].rstrip()
            after = first.span.quote[support.end - first.span.start :]
            if (before and not _sentence_end(before.split()[-1])) or (
                after.strip() and not (_sentence_end(support.quote) and after[0].isspace())
            ):
                raise AmendmentSupportError("Effect support cannot omit its sentence context.")
    return support.quote


def support_contains(whole: AmendmentSupport, part: AmendmentSupport) -> bool:
    """A word date is an exact contiguous subsequence; a single span stays inside one word/block."""
    outer, inner = support_spans(whole), support_spans(part)
    if isinstance(part, NativeAmendmentWords):
        return (
            isinstance(whole, NativeAmendmentWords)
            and whole.parse_version_id == part.parse_version_id
            and any(outer[start : start + len(inner)] == inner for start in range(len(outer)))
        )
    return any(
        span.evidence_id == part.evidence_id and span.start <= part.start < part.end <= span.end
        for span in outer
    )
