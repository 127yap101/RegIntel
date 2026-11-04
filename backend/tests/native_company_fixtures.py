"""Native company proposals on authored blank-PDF words; no real identity review."""

from regintel.entities.models import (
    ApprovedIdentifier,
    EvidenceAnchor,
    NativeCompanyRegistration,
    NativeEntityWords,
)
from regintel.numerical.context_models import NumericalContextDraft
from regintel.parsing.native_context import NativeContextParse, project_native_context


def company_registration(
    result: NativeContextParse, draft: NumericalContextDraft
) -> NativeCompanyRegistration:
    projection = project_native_context(result.artifact, result.configuration)
    blocks = {block.id: block for block in result.artifact.blocks}
    by_word = {
        (record.source.page_index, blocks[record.span.block_id].source_cell_index): record
        for record in projection.evidence
    }
    page = next(
        c.stored.capture.page_index
        for c in result.captures
        if c.stored.id == draft.issuer_header.capture_id
    )
    anchors = []
    for word in draft.issuer_header.words:
        record = by_word[page, word.word_index]
        anchors.append(
            EvidenceAnchor(
                evidence_id=record.id,
                start=record.span.start,
                end=record.span.end,
                quote=record.span.quote,
            )
        )
    marker = next(
        i for i, span in enumerate(anchors) if span.quote.casefold() in {"corporate", "cin:"}
    )
    header = NativeEntityWords(
        schema_version="native-entity-words-1",
        parse_version_id=result.artifact.id,
        spans=tuple(anchors),
    )
    name = header.model_copy(update={"spans": tuple(anchors[:marker])})
    return NativeCompanyRegistration(
        schema_version="native-company-registration-1",
        id=draft.subject_entity_id,
        kind="COMPANY",
        legal_name=name.inspection_text(),
        legal_name_support=name,
        issuer_header=header,
        identifiers=(
            ApprovedIdentifier(
                kind="CIN",
                value=anchors[-1].quote,
                support=anchors[-1],
            ),
        ),
        review_note="Authored native company engineering review; no real/human approval.",
    )
