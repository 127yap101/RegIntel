"""Exact raw-number and source-context interpretation, without inferred finance."""

from decimal import Decimal, localcontext

import pytest
from test_candidate_models import ALPHA, BETA, make_input, metric
from test_validation_models import money_policy, numeric_draft

from regintel.candidates.extraction import extract
from regintel.validation.quantity import normalize_quantity, parse_decimal, parse_source_date


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0", "0"),
        ("-0.00", "-0.00"),
        ("+12.50", "12.50"),
        ("(12.50)", "-12.50"),
        ("1,23,456.78", "123456.78"),
        ("1,234,567.890", "1234567.890"),
        ("123.000", "123.000"),
        ("00012.500", "12.500"),
    ],
)
def test_raw_values_preserve_sign_scale_and_exact_grouping(raw: str, expected: str) -> None:
    assert str(parse_decimal(raw)) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        " ",
        "-",
        "—",
        "NaN",
        "Infinity",
        "1e5",
        "1.2.3",
        "12,34",
        "1,234,56",
        "1,2,345",
        "1,00,00",
        "01,234",
        "(-12)",
        "(+12)",
        "12 ",
        " 12",
        "12%",
        "1" * 121,
        "0." + "1" * 121,
    ],
)
def test_unsupported_values_never_become_zero_or_guessed_numbers(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_decimal(raw)


def test_more_than_28_digits_are_never_rounded_by_default_decimal_context() -> None:
    raw = "1234567890123456789012345678901234567890.123456789012345678901234567890"
    with localcontext() as context:
        context.prec = 3
        assert str(parse_decimal(raw)) == raw
        assert str(parse_decimal("(" + raw + ")")) == "-" + raw


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("31 March 2026", "2026-03-31"),
        ("29 February 2024", "2024-02-29"),
        ("1 january 2001", "2001-01-01"),
    ],
)
def test_only_explicit_calendar_dates_are_interpreted(raw: str, expected: str) -> None:
    assert parse_source_date(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "29 February 2025",
        "31 April 2026",
        "0 March 2026",
        "31 Smarch 2026",
        "2026-03-31",
        "31/03/2026",
        "March 2026",
        "31 March 0000",
        "1 January +2026",
    ],
)
def test_ambiguous_or_invalid_date_not_guessed(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_source_date(raw)


def test_full_duration_money_is_exact_without_scale_conversion() -> None:
    source = make_input(
        f"{ALPHA} consolidated revenue INR 12.50 crore from 1 April 2025 to 31 March 2026.",
        start=84,
        metrics=(metric(),),
    )
    outcome = normalize_quantity(extract(source).numeric_facts[0], money_policy())
    assert outcome.quantity is not None
    quantity = outcome.quantity
    assert quantity.normalized_value == Decimal("12.50")
    assert quantity.normalized_unit == "crore" and quantity.currency == "INR"
    assert quantity.period.start_date == "2025-04-01"
    assert quantity.period.end_date == "2026-03-31"
    assert quantity.basis == "CONSOLIDATED"
    assert all(check.state == "PASS" for check in outcome.checks)
    assert all(item.span.start >= 84 for item in outcome.context_supports)


@pytest.mark.parametrize(
    ("currency", "unit", "invalid"),
    [
        ("INR", "rupees", False),
        ("USD", "rupees", True),
        ("USD", "crore", False),
        ("INR", "crore", False),
    ],
)
def test_explicit_currency_and_unit_must_jointly_support_the_amount(
    currency: str, unit: str, invalid: bool
) -> None:
    source = make_input(
        f"{ALPHA} consolidated revenue {currency} 12 {unit} from 1 April 2025 to 31 March 2026.",
        metrics=(metric(),),
    )
    outcome = normalize_quantity(
        numeric_draft(source, "12"), money_policy(allowed_unit_labels=(unit,))
    )
    assert outcome.quantity is not None
    assert outcome.quantity.raw_unit == unit and outcome.quantity.raw_currency == currency
    assert next(check for check in outcome.checks if check.code == "CURRENCY").state == (
        "FAIL" if invalid else "PASS"
    )


def test_year_ended_does_not_invent_duration_start() -> None:
    source = make_input(
        f"{ALPHA} consolidated revenue INR 12 crore for year ended 31 March 2026.",
        metrics=(metric(),),
    )
    outcome = normalize_quantity(extract(source).numeric_facts[0], money_policy())
    assert outcome.quantity is not None
    assert outcome.quantity.period.kind == "DURATION"
    assert outcome.quantity.period.start_date is None
    assert outcome.quantity.period.end_date == "2026-03-31"
    assert next(check for check in outcome.checks if check.code == "PERIOD").state == "REVIEW"


@pytest.mark.parametrize("currency", ["Rs.", "₹", "$"])
def test_currency_symbol_does_not_establish_country_currency(currency: str) -> None:
    source = make_input(
        f"{ALPHA} consolidated revenue {currency} 12 crore from 1 April 2025 to 31 March 2026.",
        metrics=(metric(),),
    )
    outcome = normalize_quantity(extract(source).numeric_facts[0], money_policy())
    assert outcome.quantity is not None and outcome.quantity.currency is None
    assert next(check for check in outcome.checks if check.code == "CURRENCY").state == "REVIEW"


@pytest.mark.parametrize("raw", ["-1", "101", "100.001"])
def test_ownership_percentage_range_is_checked(raw: str) -> None:
    source = make_input(
        f"{ALPHA} owns {raw}% of {BETA}, representing issued equity share capital, "
        "direct equity ownership as of 31 March 2026."
    )
    outcome = normalize_quantity(extract(source).relations[0], None)
    assert next(check for check in outcome.checks if check.code == "VALUE").state == "FAIL"


def test_dash_value_with_real_source_span_is_not_zero() -> None:
    source = make_input(f"{ALPHA} revenue - crore.", metrics=(metric(),))
    outcome = normalize_quantity(numeric_draft(source, "-"), money_policy())
    assert outcome.quantity is not None and outcome.quantity.normalized_value is None
    assert next(check for check in outcome.checks if check.code == "VALUE").state == "FAIL"


@pytest.mark.parametrize(
    ("kind", "raw", "unit", "invalid"),
    [
        ("COUNT", "0", "shares", False),
        ("COUNT", "1200", "shares", False),
        ("COUNT", "-1", "shares", True),
        ("COUNT", "12.5", "shares", True),
        ("POWER", "12.5", "MW", False),
        ("POWER", "1.25", "GW", False),
        ("POWER", "-0.1", "MW", True),
        ("PERCENTAGE", "0", "%", False),
        ("PERCENTAGE", "100.00", "%", False),
        ("PERCENTAGE", "101", "%", True),
        ("PERCENTAGE", "-1", "%", True),
    ],
)
def test_reviewed_quantity_kinds_enforce_range_and_count_integrality(
    kind: str,
    raw: str,
    unit: str,
    invalid: bool,
) -> None:
    source = make_input(
        f"{ALPHA} standalone capacity {raw} {unit} as of 31 March 2026.",
        metrics=(metric(cue="capacity"),),
    )
    policy = money_policy(quantity_kind=kind, period_kind="INSTANT", allowed_unit_labels=(unit,))
    outcome = normalize_quantity(extract(source).numeric_facts[0], policy)
    assert next(check for check in outcome.checks if check.code == "VALUE").state == (
        "FAIL" if invalid else "PASS"
    )
    assert outcome.quantity is not None
    assert outcome.quantity.period.instant_date == "2026-03-31"
    assert next(check for check in outcome.checks if check.code == "UNIT").state == "PASS"


@pytest.mark.parametrize("unit", ["lakh", "MW", "%"])
def test_reviewed_monetary_unit_policy_does_not_accept_other_units(unit: str) -> None:
    source = make_input(
        f"{ALPHA} consolidated revenue INR 12 {unit} from 1 April 2025 to 31 March 2026.",
        metrics=(metric(),),
    )
    outcome = normalize_quantity(extract(source).numeric_facts[0], money_policy())
    assert next(check for check in outcome.checks if check.code == "UNIT").state == "FAIL"
