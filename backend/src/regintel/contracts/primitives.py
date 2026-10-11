"""Strict wire primitives without financial arithmetic or authority decisions."""

import math
import re
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, Field, PlainSerializer, StringConstraints

MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_DECIMAL_INTEGER_DIGITS = 120
MAX_DECIMAL_FRACTIONAL_DIGITS = 120
ID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
DATE_PATTERN = r"^(000[1-9]|00[1-9][0-9]|0[1-9][0-9]{2}|[1-9][0-9]{3})-[0-9]{2}-[0-9]{2}$"
DECIMAL_PATTERN = r"^-?(0|[1-9][0-9]{0,119})(\.[0-9]{1,120})?$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
USERNAME_PATTERN = r"^[a-z][a-z0-9._-]{2,63}$"
ERROR_CODE_PATTERN = r"^[A-Z][A-Z0-9_]{0,63}$"


def _validate_id(value: str) -> str:
    if re.fullmatch(ID_PATTERN, value) is None:
        raise ValueError("A canonical lowercase RFC-variant UUIDv4 is required.")
    return value


def _validate_date(value: str) -> str:
    if re.fullmatch(DATE_PATTERN, value) is None:
        raise ValueError("A valid ISO calendar date is required.")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError("A valid ISO calendar date is required.") from None
    return value


def _validate_username(value: str) -> str:
    if re.fullmatch(USERNAME_PATTERN, value) is None:
        raise ValueError("A canonical ASCII username is required.")
    return value


def _validate_error_code(value: str) -> str:
    if re.fullmatch(ERROR_CODE_PATTERN, value) is None:
        raise ValueError("A bounded uppercase error code is required.")
    return value


def _validate_unicode(value: str) -> str:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise ValueError("Valid Unicode text is required.") from None
    return value


def integer_from_wire(value: object) -> int:
    """Use JSON Schema integer semantics while rejecting booleans, strings and unsafe floats."""
    if type(value) is int:
        return value
    if (
        type(value) is float
        and math.isfinite(value)
        and value.is_integer()
        and abs(value) <= MAX_SAFE_INTEGER
    ):
        return int(value)
    raise ValueError("An exact safe integer value is required.")


def _bounded_decimal(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise ValueError("A finite bounded decimal is required.")
    parts = value.as_tuple()
    exponent = parts.exponent
    if not isinstance(exponent, int):
        raise ValueError("A finite bounded decimal is required.")
    # Check the fixed-point output size before formatting potentially enormous exponents.
    integer_digits = max(1, len(parts.digits) + exponent)
    fractional_digits = max(0, -exponent)
    if (
        integer_digits > MAX_DECIMAL_INTEGER_DIGITS
        or fractional_digits > MAX_DECIMAL_FRACTIONAL_DIGITS
    ):
        raise ValueError("A decimal with at most 120 integer and fractional digits is required.")
    return value


def decimal_from_wire(value: object) -> Decimal:
    """Accept internal Decimal or exact fixed-point wire strings, never numeric coercion."""
    if isinstance(value, Decimal):
        return _bounded_decimal(value)
    if not isinstance(value, str) or re.fullmatch(DECIMAL_PATTERN, value) is None:
        raise ValueError("A bounded fixed-point decimal string is required.")
    return _bounded_decimal(Decimal(value))


def decimal_to_wire(value: Decimal) -> str:
    """Preserve fractional scale without rounding or scientific notation."""
    rendered = format(_bounded_decimal(value), "f")
    if re.fullmatch(DECIMAL_PATTERN, rendered) is None:
        raise ValueError("A bounded fixed-point decimal string is required.")
    return rendered


CanonicalId = Annotated[
    str,
    StringConstraints(strict=True, min_length=36, max_length=36, pattern=ID_PATTERN),
    AfterValidator(_validate_id),
]
DateString = Annotated[
    str,
    StringConstraints(strict=True, min_length=10, max_length=10, pattern=DATE_PATTERN),
    AfterValidator(_validate_date),
    Field(json_schema_extra={"format": "date"}),
]
Sha256Hash = Annotated[
    str, StringConstraints(strict=True, min_length=64, max_length=64, pattern=SHA256_PATTERN)
]
Username = Annotated[
    str,
    StringConstraints(strict=True, min_length=3, max_length=64, pattern=USERNAME_PATTERN),
    AfterValidator(_validate_username),
]
ErrorCode = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=64, pattern=ERROR_CODE_PATTERN),
    AfterValidator(_validate_error_code),
]
RawText = Annotated[
    str,
    StringConstraints(strict=True, max_length=200_000),
    AfterValidator(_validate_unicode),
]
Label = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=256),
    AfterValidator(_validate_unicode),
]
LineageLabel = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=64),
    AfterValidator(_validate_unicode),
]
SafeInteger = Annotated[
    int, Field(strict=True, ge=0, le=MAX_SAFE_INTEGER), BeforeValidator(integer_from_wire)
]
PositiveSafeInteger = Annotated[
    int, Field(strict=True, ge=1, le=MAX_SAFE_INTEGER), BeforeValidator(integer_from_wire)
]
PageIndex = Annotated[
    int, Field(strict=True, ge=0, le=MAX_SAFE_INTEGER - 1), BeforeValidator(integer_from_wire)
]
FiniteCoordinate = Annotated[float, Field(strict=True, allow_inf_nan=False)]
PositiveDimension = Annotated[float, Field(strict=True, allow_inf_nan=False, gt=0)]
WireDecimalString = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=242, pattern=DECIMAL_PATTERN)
]
DecimalValue = Annotated[
    Decimal,
    Field(strict=True, allow_inf_nan=False),
    BeforeValidator(decimal_from_wire, json_schema_input_type=WireDecimalString),
    PlainSerializer(decimal_to_wire, return_type=WireDecimalString, when_used="json"),
]
