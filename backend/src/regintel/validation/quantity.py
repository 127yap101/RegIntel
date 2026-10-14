"""Exact Decimal/context interpretation, without scale arithmetic or inferred dates."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from regintel.candidates.models import DraftCandidate, SourceSpan
from regintel.contracts.models import FinancialPeriod, QuantitativeValue, ReportingBasis
from regintel.validation.models import (
    CheckCode,
    ContextWitness,
    NumericMetricPolicy,
    ValidationCheck,
)

_DATE = r"[0-9]{1,2} [A-Za-z]+ [0-9]{4}"
_MONTHS = {
    name.casefold(): index
    for index, name in enumerate(
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
_INSTANT = re.compile(r"\bas (?:at|of) (" + _DATE + r")\b", re.I)
_DURATION = re.compile(r"\bfrom (" + _DATE + r") to (" + _DATE + r")\b", re.I)
_ENDED = re.compile(r"\b(?:year|quarter|six months|nine months) ended (" + _DATE + r")\b", re.I)
_UNIT = re.compile(
    r"(?<!\w)(?:crores?|lakhs?|millions?|billions?|rupees|shares|MW|GW)(?!\w)|%", re.I
)
_CURRENCY = re.compile(r"(?<!\w)(?:INR|USD)(?!\w)", re.I)
_BASIS = re.compile(r"\b(?:standalone|consolidated)\b", re.I)
_OWNERSHIP_BASIS = re.compile(
    r"\b(?:direct|indirect|aggregate) (?:equity|voting|economic) "
    r"(?:ownership|interest|stake)\b",
    re.I,
)
_DENOMINATOR = re.compile(r"\b(?:issued|paid-up) equity share capital\b", re.I)
_STAKE = re.compile(r"\b(?:equity|voting|economic) (?:stake|interest|ownership)\b", re.I)


@dataclass(frozen=True)
class QuantityOutcome:
    quantity: QuantitativeValue | None
    checks: tuple[ValidationCheck, ...]
    context_supports: tuple[ContextWitness, ...]


def parse_decimal(raw: str) -> Decimal:
    """Recognize explicit Indian/Western grouping and preserve decimal scale exactly."""
    if len(raw) > 500 or raw != raw.strip():
        raise ValueError("A bounded raw number is required.")
    negative = raw.startswith("(") and raw.endswith(")")
    value = raw[1:-1] if negative else raw
    if negative and value.startswith(("+", "-")):
        raise ValueError("Parenthesized numbers cannot also supply a sign.")
    if re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", value) is None:
        if (
            re.fullmatch(
                r"[+-]?(?:[1-9][0-9]{0,2}(?:,[0-9]{3})+|[1-9][0-9]?(?:,[0-9]{2})*,[0-9]{3})"
                r"(?:\.[0-9]+)?",
                value,
            )
            is None
        ):
            raise ValueError("The raw value has unsupported or malformed numeric notation.")
    unsigned = value.lstrip("+-").replace(",", "")
    integer, _, fractional = unsigned.partition(".")
    if len(integer.lstrip("0")) > 120 or len(fractional) > 120:
        raise ValueError("The raw value exceeds exact decimal storage limits.")
    try:
        result = Decimal(value.replace(",", ""))
    except InvalidOperation:
        raise ValueError("The raw value is not a finite decimal.") from None
    return result.copy_negate() if negative else result


def parse_source_date(raw: str) -> str:
    if re.fullmatch(_DATE, raw) is None:
        raise ValueError("A supported explicit source calendar date is required.")
    parts = raw.split(" ")
    if len(parts) != 3 or parts[1].casefold() not in _MONTHS:
        raise ValueError("A supported explicit source calendar date is required.")
    try:
        return date(int(parts[2]), _MONTHS[parts[1].casefold()], int(parts[0])).isoformat()
    except ValueError:
        raise ValueError("The source calendar date is invalid.") from None


def _span(primary: SourceSpan, match: re.Match[str]) -> SourceSpan:
    return SourceSpan(
        evidence_id=primary.evidence_id,
        start=primary.start + match.start(),
        end=primary.start + match.end(),
        quote=match.group(),
    )


def normalize_quantity(
    draft: DraftCandidate, policy: NumericMetricPolicy | None
) -> QuantityOutcome:
    """Produce a proposed interpretation and checks; never write authoritative state."""
    raw = draft.raw_quantity
    if raw is None:
        return QuantityOutcome(None, (), ())
    primary = draft.supports[0]
    checks: list[ValidationCheck] = []
    witnesses: list[ContextWitness] = [
        ContextWitness.model_validate({"role": role, "span": span})
        for role, span in (
            ("VALUE", raw.value),
            ("UNIT", raw.unit),
            ("CURRENCY", raw.currency),
            ("PERIOD", raw.period),
            ("BASIS", raw.basis),
            ("DENOMINATOR", raw.denominator),
            ("STAKE_KIND", raw.stake_kind),
            ("OWNERSHIP_DATE", raw.ownership_date),
        )
        if span is not None
    ]

    def witness(role: CheckCode, span: SourceSpan) -> None:
        item = ContextWitness.model_validate({"role": role, "span": span})
        if item not in witnesses:
            witnesses.append(item)

    def check(code: CheckCode, state: str, message: str) -> None:
        checks.append(
            ValidationCheck.model_validate({"code": code, "state": state, "message": message})
        )

    def context(
        role: CheckCode,
        pattern: re.Pattern[str],
        supplied: SourceSpan | None,
        *,
        required: bool = True,
    ) -> tuple[SourceSpan | None, re.Match[str] | None]:
        matches = tuple(pattern.finditer(primary.quote))
        if len(matches) != 1:
            if supplied is not None and not any(
                _span(primary, match) == supplied for match in matches
            ):
                check(role, "FAIL", "Supplied context has an unsupported semantic label.")
            elif required or len(matches) > 1:
                check(role, "REVIEW", "A single explicit applicable context label is required.")
            else:
                check(role, "PASS", "This context is not required by the reviewed metric policy.")
            return None, None
        match = matches[0]
        span = _span(primary, match)
        if supplied is not None and supplied != span:
            check(role, "FAIL", "Supplied context does not match its complete source label.")
            return None, None
        witness(role, span)
        check(role, "PASS", "One exact source label supports this context.")
        return span, match

    value: Decimal | None = None
    try:
        value = parse_decimal(raw.value.quote)
        check("VALUE", "PASS", "The raw value has an exact bounded Decimal interpretation.")
    except ValueError:
        check("VALUE", "FAIL", "The raw value lacks a supported exact Decimal interpretation.")

    ownership = draft.kind == "relation" and draft.relation_type == "OWNS"
    kind = "PERCENTAGE" if ownership else policy.quantity_kind if policy else None
    if value is not None and (
        (kind == "PERCENTAGE" and not Decimal("0") <= value <= Decimal("100"))
        or (kind in {"COUNT", "POWER"} and value < 0)
        or (kind == "COUNT" and value != value.to_integral_value())
    ):
        checks[0] = ValidationCheck(
            code="VALUE",
            state="FAIL",
            message="The value is incompatible with the reviewed quantity kind.",
        )

    unit_pattern = _UNIT
    if kind == "MONEY" and not _UNIT.search(primary.quote):
        unit_pattern = _CURRENCY
    unit, _ = context("UNIT", unit_pattern, raw.unit)
    unit_label: str | None = None
    if unit is not None:
        unit_label = (
            unit.quote.upper()
            if unit.quote.casefold() in {"mw", "gw", "inr", "usd"}
            else unit.quote.casefold()
        )
        allowed = ("%",) if ownership else policy.allowed_unit_labels if policy else ()
        if unit_label not in allowed:
            checks[-1] = ValidationCheck(
                code="UNIT",
                state="FAIL" if policy or ownership else "REVIEW",
                message="The source unit is outside the reviewed metric policy.",
            )

    currency: SourceSpan | None = None
    if kind == "MONEY":
        if (
            raw.currency is not None
            and raw.currency.quote in {"Rs.", "₹", "$"}
            and not _CURRENCY.search(primary.quote)
        ):
            check(
                "CURRENCY",
                "REVIEW",
                "An ambiguous currency symbol cannot establish an ISO currency.",
            )
        else:
            currency, _ = context("CURRENCY", _CURRENCY, raw.currency)
            if unit_label == "rupees" and currency is not None and currency.quote.upper() == "USD":
                checks[-1] = ValidationCheck(
                    code="CURRENCY",
                    state="FAIL",
                    message="The explicit currency conflicts with the source's rupee unit.",
                )
    elif raw.currency is not None or _CURRENCY.search(primary.quote):
        check(
            "CURRENCY",
            "FAIL" if kind is not None else "REVIEW",
            "Currency is incompatible with a non-monetary or unspecified metric.",
        )

    period = FinancialPeriod(
        kind="UNKNOWN",
        start_date=None,
        end_date=None,
        instant_date=None,
        raw_label=raw.period.quote if raw.period else None,
    )
    expected_period = "INSTANT" if ownership else policy.period_kind if policy else None
    matches = (
        [("INSTANT", match) for match in _INSTANT.finditer(primary.quote)]
        + [("DURATION", match) for match in _DURATION.finditer(primary.quote)]
        + [("DURATION", match) for match in _ENDED.finditer(primary.quote)]
    )
    period_span: SourceSpan | None = None
    if len(matches) != 1:
        check(
            "PERIOD",
            "REVIEW",
            "One explicit financial period is required; publication dates are not periods.",
        )
    else:
        period_kind, match = matches[0]
        period_span = _span(primary, match)
        if raw.period is not None and raw.period != period_span:
            check(
                "PERIOD",
                "FAIL",
                "The supplied period label does not match the complete explicit source period.",
            )
        elif expected_period is None or period_kind != expected_period:
            check(
                "PERIOD",
                "REVIEW",
                "The explicit period does not match a reviewed metric interpretation.",
            )
        else:
            witness("PERIOD", period_span)
            try:
                first_date = parse_source_date(match.group(1))
                if period_kind == "INSTANT":
                    period = FinancialPeriod(
                        kind="INSTANT",
                        start_date=None,
                        end_date=None,
                        instant_date=first_date,
                        raw_label=period_span.quote,
                    )
                    check("PERIOD", "PASS", "The instant date is explicitly supported.")
                elif match.re is _DURATION:
                    end_date = parse_source_date(match.group(2))
                    if end_date < first_date:
                        raise ValueError("The source duration is reversed.")
                    period = FinancialPeriod(
                        kind="DURATION",
                        start_date=first_date,
                        end_date=end_date,
                        instant_date=None,
                        raw_label=period_span.quote,
                    )
                    check("PERIOD", "PASS", "Both duration boundaries are explicitly supported.")
                else:
                    period = FinancialPeriod(
                        kind="DURATION",
                        start_date=None,
                        end_date=first_date,
                        instant_date=None,
                        raw_label=period_span.quote,
                    )
                    check(
                        "PERIOD",
                        "REVIEW",
                        "The source supplies an end date but no duration start; none is inferred.",
                    )
            except ValueError:
                check(
                    "PERIOD",
                    "FAIL",
                    "The explicit financial period contains an invalid or reversed calendar date.",
                )

    basis, _ = context(
        "BASIS",
        _OWNERSHIP_BASIS if ownership else _BASIS,
        raw.basis,
        required=ownership or policy is None or policy.required_reporting_basis,
    )
    denominator: SourceSpan | None = None
    stake: SourceSpan | None = None
    ownership_date: str | None = None
    if ownership:
        denominator, _ = context("DENOMINATOR", _DENOMINATOR, raw.denominator)
        stake, _ = context("STAKE_KIND", _STAKE, raw.stake_kind)
        ownership_span, ownership_match = context("OWNERSHIP_DATE", _INSTANT, raw.ownership_date)
        if ownership_span is not None and ownership_match is not None:
            try:
                ownership_date = parse_source_date(ownership_match.group(1))
                if period.instant_date != ownership_date:
                    checks[-1] = ValidationCheck(
                        code="OWNERSHIP_DATE",
                        state="FAIL",
                        message="Ownership date must match its explicit instant period.",
                    )
            except ValueError:
                checks[-1] = ValidationCheck(
                    code="OWNERSHIP_DATE",
                    state="FAIL",
                    message="The ownership calendar date is invalid.",
                )
    elif (
        raw.denominator is not None
        or raw.stake_kind is not None
        or (raw.ownership_date is not None and raw.ownership_date != period_span)
    ):
        check(
            "DENOMINATOR", "REVIEW", "Ownership context is not supported for this ordinary metric."
        )

    reporting_basis: ReportingBasis = "UNKNOWN"
    if basis is not None and not ownership:
        reporting_basis = "STANDALONE" if basis.quote.casefold() == "standalone" else "CONSOLIDATED"
    quantity = QuantitativeValue(
        raw_value=raw.value.quote,
        normalized_value=value,
        raw_unit=unit.quote if unit else raw.unit.quote if raw.unit else None,
        normalized_unit=unit_label,
        raw_currency=currency.quote if currency else raw.currency.quote if raw.currency else None,
        currency=currency.quote.upper() if currency else None,
        period=period,
        basis=reporting_basis,
        raw_basis_label=basis.quote if basis else raw.basis.quote if raw.basis else None,
        denominator=denominator.quote
        if denominator
        else raw.denominator.quote
        if raw.denominator
        else None,
        stake_kind=stake.quote if stake else raw.stake_kind.quote if raw.stake_kind else None,
        ownership_date=ownership_date,
        evidence_ids=tuple(dict.fromkeys(span.evidence_id for span in draft.supports)),
    )
    return QuantityOutcome(quantity, tuple(checks), tuple(witnesses))
