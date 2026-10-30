"""Ordered amendment word proofs over authored blank-PDF declarations, not research gold."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.tests.evidence_fixtures import synthetic_artifact, synthetic_configuration
from backend.tests.native_context_fixtures import native_case
from backend.tests.test_numerical_context import Options
from regintel.candidates.models import SourceSpan
from regintel.evidence.projection import project_parse
from regintel.parsing.native_context import project_native_context
from regintel.publication.engine import source_date
from regintel.publication.support import (
    AmendmentSupportError,
    native_word_index,
    support_contains,
    support_text,
    uncertain_effect_wording,
)
from regintel.publication.support_models import NativeAmendmentWords

REFERENCE = "Red Herring Prospectus."
STATEMENT = "The earlier disclosure is corrected effective 1 January 2026."


def ordered_support(index, text):
    words = sorted(index.values(), key=lambda item: (item.evidence.source.page_index, item.index))
    tokens = text.split()
    matches = [
        words[start : start + len(tokens)]
        for start in range(len(words))
        if [value.evidence.span.quote for value in words[start : start + len(tokens)]] == tokens
    ]
    assert len(matches) == 1
    return NativeAmendmentWords(
        schema_version="native-amendment-words-1",
        parse_version_id=matches[0][0].evidence.source.parse_version_id,
        spans=tuple(
            SourceSpan(
                evidence_id=item.evidence.id,
                start=0,
                end=item.evidence.span.end,
                quote=item.evidence.span.quote,
            )
            for item in matches[0]
        ),
    )


@pytest.fixture
def support_case(tmp_path):
    case = native_case(
        tmp_path,
        Options(
            unit="(INR in million)",
            currency=(),
            amendment_reference=REFERENCE,
            amendment_statement=STATEMENT,
        ),
    )
    projection = project_native_context(case.result.artifact, case.result.configuration)
    index = native_word_index(case.result.artifact, projection.evidence)
    records = {item.id: item for item in projection.evidence}
    return case, index, records


def inspect(case, support, index, records, *, statement=False):
    return support_text(
        support,
        case.result.artifact.filing_version_id,
        case.result.artifact.id,
        records,
        index,
        statement=statement,
    )


def test_exact_ordered_words_and_date_preserve_raw_separate_support(support_case):
    case, index, records = support_case
    value = ordered_support(index, STATEMENT)
    before = value.model_dump_json()
    assert inspect(case, value, index, records, statement=True) == STATEMENT
    assert "quote" not in value.model_dump(mode="json")
    date = ordered_support(index, "1 January 2026.")
    assert support_contains(value, date)
    assert source_date(inspect(case, date, index, records)) == "2026-01-01"
    assert value.model_dump_json() == before


@pytest.mark.parametrize(
    "change",
    [
        "gap",
        "reverse",
        "foreign-parse",
        "missing-index",
        "wrong-position",
        "changed-record",
        "foreign-page",
    ],
)
def test_source_order_cannot_be_supplied_or_forged_by_a_request(support_case, change):
    case, index, records = support_case
    value = ordered_support(index, STATEMENT)
    if change == "gap":
        value = value.model_copy(update={"spans": value.spans[:2] + value.spans[3:]})
    elif change == "reverse":
        value = value.model_copy(update={"spans": tuple(reversed(value.spans))})
    elif change == "foreign-parse":
        value = value.model_copy(update={"parse_version_id": str(uuid4())})
    elif change == "missing-index":
        index = {}
    elif change == "wrong-position":
        index = {
            **index,
            value.spans[1].evidence_id: replace(index[value.spans[1].evidence_id], index=999),
        }
    else:
        item = records[value.spans[1].evidence_id]
        altered = item.model_copy(
            update={"source": item.source.model_copy(update={"page_id": str(uuid4())})}
        )
        records = {**records, item.id: altered}
        if change == "foreign-page":
            index = {**index, item.id: replace(index[item.id], evidence=altered)}
    with pytest.raises(AmendmentSupportError):
        inspect(case, value, index, records, statement=True)


@pytest.mark.parametrize(
    "text",
    [
        "earlier disclosure is corrected effective 1 January 2026.",
        "The earlier disclosure is corrected",
        "corrected",
    ],
)
def test_native_effect_cannot_drop_leading_or_trailing_statement_context(support_case, text):
    case, index, records = support_case
    value = ordered_support(index, text)
    with pytest.raises(AmendmentSupportError):
        inspect(case, value, index, records, statement=True)


def test_a_legacy_span_cannot_disguise_an_isolated_native_cue(support_case):
    case, index, records = support_case
    isolated = ordered_support(index, "corrected").spans[0]
    with pytest.raises(AmendmentSupportError):
        inspect(case, isolated, index, records, statement=True)


def test_date_membership_requires_contiguous_support_and_same_parse(support_case):
    _, index, _ = support_case
    whole = ordered_support(index, STATEMENT)
    date = ordered_support(index, "1 January 2026.")
    assert not support_contains(
        whole, date.model_copy(update={"spans": tuple(reversed(date.spans))})
    )
    assert not support_contains(whole, date.model_copy(update={"parse_version_id": str(uuid4())}))
    assert not support_contains(whole.spans[0], date)
    assert support_contains(whole, date.spans[0])


@pytest.mark.parametrize(
    "change", ["duplicate", "partial", "extra-quote", "unknown-version", "empty"]
)
def test_versioned_word_support_has_no_combined_quote_or_partial_word(support_case, change):
    _, index, _ = support_case
    value = ordered_support(index, STATEMENT).model_dump(mode="json")
    if change == "duplicate":
        value["spans"].append(value["spans"][0])
    if change == "partial":
        value["spans"][0]["start"] = 1
    if change == "extra-quote":
        value["quote"] = STATEMENT
    if change == "unknown-version":
        value["schema_version"] = "unknown"
    if change == "empty":
        value["spans"] = []
    with pytest.raises(ValidationError):
        NativeAmendmentWords.model_validate(value)


def test_unavailable_predecessor_does_not_become_a_sentence_boundary(support_case):
    case, index, records = support_case
    value = ordered_support(index, STATEMENT)
    index = {
        **index,
        value.spans[0].evidence_id: replace(index[value.spans[0].evidence_id], previous=None),
    }
    with pytest.raises(AmendmentSupportError):
        inspect(case, value, index, records, statement=True)


def test_incomplete_native_projection_cannot_fall_back_to_a_legacy_effect_span(support_case):
    case, index, records = support_case
    value = ordered_support(index, "corrected").spans[0]
    record = records[value.evidence_id]
    partial = record.model_copy(
        update={
            "span": record.span.model_copy(
                update={
                    "start": 1,
                    "quote": record.span.quote[1:],
                }
            )
        }
    )
    altered = {**records, partial.id: partial}
    positions = native_word_index(case.result.artifact, tuple(altered.values()))
    assert not positions[partial.id].complete
    clipped = value.model_copy(update={"start": 1, "quote": value.quote[1:]})
    with pytest.raises(AmendmentSupportError, match="isolated native"):
        inspect(case, clipped, positions, altered, statement=True)


def test_duplicate_original_positions_are_not_resolved_by_timestamp(support_case):
    case, _, records = support_case
    block = case.result.artifact.blocks[0]
    artifact = case.result.artifact.model_copy(
        update={"blocks": (*case.result.artifact.blocks, block)}
    )
    with pytest.raises(AmendmentSupportError):
        native_word_index(artifact, tuple(records.values()))


def test_legacy_multiline_text_cell_retains_its_complete_original_statement():
    original = "Alpha Solar Limited.\nRed Herring Prospectus.\n" + STATEMENT
    configuration = synthetic_configuration()
    artifact = synthetic_artifact(configuration=configuration, original=original)
    records = project_parse(artifact, configuration).evidence
    index = native_word_index(artifact, records)
    assert index == {} and artifact.blocks[0].source_ref == "page/0/text-cell/0"
    record = next(item for item in records if item.span.quote == original)
    start = original.index(STATEMENT)
    support = SourceSpan(
        evidence_id=record.id, start=start, end=start + len(STATEMENT), quote=STATEMENT
    )
    assert (
        support_text(
            support,
            artifact.filing_version_id,
            artifact.id,
            {item.id: item for item in records},
            index,
            statement=True,
        )
        == STATEMENT
    )
    words = NativeAmendmentWords(
        schema_version="native-amendment-words-1",
        parse_version_id=artifact.id,
        spans=(SourceSpan(evidence_id=record.id, start=0, end=len(original), quote=original),),
    )
    with pytest.raises(AmendmentSupportError, match="sealed original order"):
        support_text(
            words,
            artifact.filing_version_id,
            artifact.id,
            {item.id: item for item in records},
            index,
        )


@pytest.mark.parametrize(
    "text",
    [
        "The disclosure is not corrected.",
        "It may be corrected.",
        "The correction is subject to approval.",
        "It is corrected if approval arrives.",
        "It is corrected unless the proposal changes.",
        "It is expected to be corrected.",
        "The proposal could replace this disclosure.",
        "It is corrected except the named figures.",
    ],
)
def test_conditional_or_proposed_operations_are_not_supported_effects(text):
    assert uncertain_effect_wording(text)


def test_migration_keeps_every_unrelated_publication_build_guard_byte_for_byte():
    root = Path(__file__).resolve().parents[2]
    legacy = (root / "infra/migrations/0011_publication.sql").read_text(encoding="utf-8")
    native = (root / "infra/migrations/0022_native_amendment_support.sql").read_text(
        encoding="utf-8"
    )

    def function(source, prefix):
        start = source.index(prefix)
        end = source.index("\nEND; $$;", start) + len("\nEND; $$;")
        return source[start:end]

    expected = function(legacy, "CREATE FUNCTION regintel.validate_publication_build()")
    expected = expected.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    for fragment in (
        "regintel.candidate_span(item -> 'parent_identity'",
        "regintel.candidate_span(selected, (SELECT id",
        "regintel.candidate_span(selected,(SELECT p.id",
    ):
        assert expected.count(fragment) == 1
        expected = expected.replace(
            fragment, fragment.replace("candidate_span", "publication_support_text")
        )
    assert (
        function(native, "CREATE OR REPLACE FUNCTION regintel.validate_publication_build()")
        == expected
    )
    assert "CREATE TRIGGER" not in native and "DROP " not in native
