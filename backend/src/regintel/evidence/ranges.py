"""Bounded single-range and entity-tag HTTP policy for immutable original PDFs."""

import re
from dataclasses import dataclass

MAX_CONDITIONAL_HEADER = 2048
MAX_RANGE_NUMERAL = 20
_RANGE = re.compile(r"([0-9]*)-([0-9]*)\Z", re.ASCII)
_ETAG = re.compile(r'(?:W/)?"[\x21\x23-\x7e\x80-\xff]*"', re.ASCII)


class InvalidSourceHeader(ValueError):
    """A bounded malformed source header; its text is never returned to clients."""


class UnsatisfiableRange(ValueError):
    """A syntactically valid single byte range cannot select this representation."""


@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int


def bounded_header(value: str | None) -> str | None:
    if value is not None and (
        len(value) > MAX_CONDITIONAL_HEADER
        or any(ord(character) < 32 and character != "\t" for character in value)
    ):
        raise InvalidSourceHeader()
    return value


def select_range(value: str | None, *, size: int) -> ByteRange | None:
    """Select one inclusive range; ignore unknown units or valid multipart ranges."""
    value = bounded_header(value)
    if value is None:
        return None
    unit, separator, raw_members = value.strip().partition("=")
    if not separator or not unit:
        raise InvalidSourceHeader()
    if unit.casefold() != "bytes":
        return None
    members = raw_members.split(",")
    parsed: list[tuple[str, str]] = []
    for member in members:
        match = _RANGE.fullmatch(member.strip())
        if match is None:
            raise InvalidSourceHeader()
        first, last = match.groups()
        if (not first and not last) or max(len(first), len(last)) > MAX_RANGE_NUMERAL:
            raise InvalidSourceHeader()
        parsed.append((first, last))
    if len(parsed) != 1:
        return None
    first, last = parsed[0]
    if not first:
        suffix = int(last)
        if suffix == 0:
            raise UnsatisfiableRange()
        return ByteRange(max(0, size - suffix), size - 1)
    start = int(first)
    end = min(int(last), size - 1) if last else size - 1
    if start >= size or end < start:
        raise UnsatisfiableRange()
    return ByteRange(start, end)


def if_range_matches(value: str | None, *, etag: str) -> bool:
    """Only the identical strong tag enables partial output; dates/weak tags do not."""
    value = bounded_header(value)
    return value is None or value.strip() == etag


def if_none_match(value: str | None, *, etag: str) -> bool:
    """Use weak comparison for GET/HEAD; ignore malformed bounded tag lists."""
    value = bounded_header(value)
    if value is None:
        return False
    value = value.strip()
    if value == "*":
        return True
    offset = 0
    matches: list[str] = []
    while offset < len(value):
        match = _ETAG.match(value, offset)
        if match is None:
            return False
        matches.append(match.group().removeprefix("W/"))
        offset = match.end()
        while offset < len(value) and value[offset] in " \t":
            offset += 1
        if offset == len(value):
            return etag in matches
        if value[offset] != ",":
            return False
        offset += 1
        while offset < len(value) and value[offset] in " \t":
            offset += 1
    return False
