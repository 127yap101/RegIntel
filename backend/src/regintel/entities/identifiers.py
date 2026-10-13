"""Bounded company/security identifier syntax; identifiers do not prove ownership."""

import re
from typing import Literal

CIN_PATTERN = re.compile(r"[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}\Z", re.ASCII)
ISIN_PATTERN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]\Z", re.ASCII)


def valid_identifier(kind: Literal["CIN", "ISIN"], value: str) -> bool:
    if kind == "CIN":
        return CIN_PATTERN.fullmatch(value) is not None
    if ISIN_PATTERN.fullmatch(value) is None:
        return False
    expanded = "".join(str(ord(char) - 55) if char.isalpha() else char for char in value)
    total = 0
    for index, char in enumerate(reversed(expanded)):
        number = int(char) * (2 if index % 2 else 1)
        total += number // 10 + number % 10
    return total % 10 == 0
