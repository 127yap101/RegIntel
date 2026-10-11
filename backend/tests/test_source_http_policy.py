"""Boundary cases for source byte ranges and conditional tag comparison."""

import pytest

from regintel.evidence.ranges import (
    ByteRange,
    InvalidSourceHeader,
    UnsatisfiableRange,
    bounded_header,
    if_none_match,
    if_range_matches,
    select_range,
)

ETAG = '"' + "a" * 64 + '"'


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("bytes=0-0", ByteRange(0, 0)),
        ("bytes=4-8", ByteRange(4, 8)),
        ("bytes=8-", ByteRange(8, 9)),
        ("bytes=-3", ByteRange(7, 9)),
        ("bytes=-99", ByteRange(0, 9)),
        ("bytes=0-999", ByteRange(0, 9)),
        ("bytes=0-1, 4-5", None),
        ("bytes=0-1,99-100", None),
        ("items=0-1", None),
        (" Bytes= 0-1 ", ByteRange(0, 1)),
    ],
)
def test_inclusive_range_and_explicit_full_fallbacks(
    value: str | None, expected: ByteRange | None
) -> None:
    assert select_range(value, size=10) == expected


@pytest.mark.parametrize("value", ["bytes=10-", "bytes=20-30", "bytes=-0", "bytes=5-4"])
def test_syntactic_single_range_without_selected_bytes(value: str) -> None:
    with pytest.raises(UnsatisfiableRange):
        select_range(value, size=10)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "bytes",
        "=0-1",
        "bytes=",
        "bytes=-",
        "bytes=+1-2",
        "bytes=１-2",
        "bytes=0 - 2",
        "bytes=0-2,",
        "bytes=0-2,broken",
        "bytes=" + "9" * 21 + "-",
        "bytes=0-" + "9" * 21,
        "bytes=0-2\r\nsecret",
        "bytes=" + "0-1," * 600,
    ],
)
def test_malformed_or_unbounded_ranges_fail_without_integer_expansion(value: str) -> None:
    with pytest.raises(InvalidSourceHeader):
        select_range(value, size=10)


@pytest.mark.parametrize("value", [None, ETAG, " " + ETAG + " "])
def test_only_matching_strong_if_range(value: str | None) -> None:
    assert if_range_matches(value, etag=ETAG)


@pytest.mark.parametrize("value", ["W/" + ETAG, '"different"', "Mon, 01 Jan 2024 00:00:00 GMT"])
def test_if_range_miss_returns_whole_representation(value: str) -> None:
    assert not if_range_matches(value, etag=ETAG)


@pytest.mark.parametrize("value", [ETAG, "W/" + ETAG, "*", '"other", W/' + ETAG])
def test_if_none_match_get_head_weak_comparison(value: str) -> None:
    assert if_none_match(value, etag=ETAG)


@pytest.mark.parametrize(
    "value",
    [
        None,
        '"other"',
        "W/garbage," + ETAG,
        ETAG + ",",
        "*," + ETAG,
        '"other,' + "a" * 64 + '"',
        ETAG + "secret",
        '"other",, ' + ETAG,
    ],
)
def test_malformed_none_match_never_short_circuits(value: str | None) -> None:
    assert not if_none_match(value, etag=ETAG)


def test_all_source_conditionals_share_bounded_header_policy() -> None:
    for operation in (if_none_match, if_range_matches):
        with pytest.raises(InvalidSourceHeader):
            operation("x" * 2049, etag=ETAG)
    with pytest.raises(InvalidSourceHeader):
        bounded_header("secret\x00header")
