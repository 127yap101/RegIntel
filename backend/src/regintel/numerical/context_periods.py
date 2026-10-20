"""Narrow explicit annual-period proposals; no default fiscal calendar or filing dates."""

import re
from datetime import date, timedelta
from typing import Literal

from regintel.contracts.models import FinancialPeriod

MONTHS = {
    name.casefold(): i
    for i, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        1,
    )
}
MONTH = "(?:" + "|".join(MONTHS) + ")"
SOURCE_DATE = rf"(?:{MONTH} [0-9]{{1,2}}, [0-9]{{4}}|[0-9]{{1,2}} {MONTH} [0-9]{{4}})"
ANNUAL = re.compile(rf"(?:as at and for the )?(?:financial )?year ended ({SOURCE_DATE})", re.I)
CALENDAR = rf"({MONTH}) ([0-9]{{1,2}})"
DEFINITION = re.compile(
    r"our company's financial year commences on "
    + CALENDAR
    + r" of the immediately preceding calendar year and ends on "
    + CALENDAR
    + r" of that particular calendar year(?P<tail>.*)",
    re.I,
)
TAIL = re.compile(
    r"(?:\. accordingly, | and accordingly, )all references to a particular "
    r"(?:fiscal or financial year|financial year or fiscal) are to the 12(?:-| )month period "
    r"commencing on "
    + CALENDAR
    + r" of the immediately preceding calendar year and ending on "
    + CALENDAR
    + r" of that particular calendar year\.",
    re.I,
)


def normalized_words(value: str) -> str:
    # Interpretation only; original word references and raw text remain unchanged.
    return " ".join(value.translate(str.maketrans("’“”", '\'""')).split())


def source_date(value: str) -> date:
    parts = value.replace(",", "").split()
    if len(parts) != 3:
        raise ValueError("An explicit supported calendar date is required.")
    if parts[0].casefold() in MONTHS:
        month, day = MONTHS[parts[0].casefold()], int(parts[1])
    else:
        month, day = MONTHS[parts[1].casefold()], int(parts[0])
    return date(int(parts[2]), month, day)


def fiscal_calendar(value: str) -> tuple[int, int, int, int] | None:
    """Accept only a complete issuer-scoped clause, optionally its matching annual restatement."""
    match = DEFINITION.fullmatch(normalized_words(value))
    if match is None:
        return None
    groups = match.groups()[:4]
    result = (
        MONTHS[groups[0].casefold()],
        int(groups[1]),
        MONTHS[groups[2].casefold()],
        int(groups[3]),
    )
    tail = match.group("tail")
    if tail != ".":
        second = TAIL.fullmatch(tail)
        if second is None:
            return None
        repeated = (
            MONTHS[second[1].casefold()],
            int(second[2]),
            MONTHS[second[3].casefold()],
            int(second[4]),
        )
        if result != repeated:
            return None
    # A leap year validates February29 as a source month/day. Check the actual year later.
    date(2000, result[0], result[1])
    date(2000, result[2], result[3])
    return result


def annual_period(
    header: str, definitions: tuple[str, ...]
) -> tuple[FinancialPeriod, Literal["PASS", "REVIEW", "FAIL"], str]:
    """Propose a complete duration only from a matching explicit preceding-year calendar."""
    unknown = FinancialPeriod(
        kind="UNKNOWN", start_date=None, end_date=None, instant_date=None, raw_label=header
    )
    match = ANNUAL.fullmatch(normalized_words(header))
    if match is None:
        return unknown, "REVIEW", "Only an explicit annual monetary column is supported here."
    try:
        end = source_date(match[1])
    except (ValueError, KeyError):
        return unknown, "FAIL", "The source column contains an invalid calendar date."
    incomplete = FinancialPeriod(
        kind="DURATION",
        start_date=None,
        end_date=end.isoformat(),
        instant_date=None,
        raw_label=header,
    )
    if not definitions:
        return incomplete, "REVIEW", "The annual end has no explicit applicable fiscal definition."
    try:
        calendars = tuple(fiscal_calendar(value) for value in definitions)
    except ValueError:
        return incomplete, "FAIL", "A fiscal definition contains an invalid calendar month/day."
    if any(value is None for value in calendars) or len(set(calendars)) != 1:
        return (
            incomplete,
            "REVIEW",
            "Fiscal definitions are unsupported or competing; no start is inferred.",
        )
    calendar = calendars[0]
    assert calendar is not None
    if (end.month, end.day) != calendar[2:]:
        return incomplete, "FAIL", "The annual end conflicts with its supplied fiscal definition."
    try:
        start = date(end.year - 1, calendar[0], calendar[1])
        anniversary = date(end.year, calendar[0], calendar[1])
        if anniversary - timedelta(days=1) != end:
            raise ValueError("The explicit boundaries do not describe one financial year.")
    except ValueError:
        return incomplete, "FAIL", "The fiscal definition does not yield a valid annual duration."
    return (
        FinancialPeriod(
            kind="DURATION",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            instant_date=None,
            raw_label=header,
        ),
        "PASS",
        "Both proposed boundaries retain explicit header and fiscal-definition support.",
    )
