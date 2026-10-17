"""Bounded Decimal scaling and comparison; no financial interpretation by label."""

from decimal import ROUND_HALF_EVEN, Context, Decimal, DecimalException, Inexact, localcontext

from regintel.analysis.models import ComparisonCell, NormalizedAmount, PairDifference
from regintel.contracts.models import FinancialPeriod, QuantitativeValue
from regintel.contracts.primitives import decimal_to_wire

_SCALES = {
    "INR": "1",
    "USD": "1",
    "rupees": "1",
    "lakh": "100000",
    "lakhs": "100000",
    "crore": "10000000",
    "crores": "10000000",
    "million": "1000000",
    "millions": "1000000",
    "billion": "1000000000",
    "billions": "1000000000",
}


class NormalizationRangeError(ValueError):
    """A supported exact scale cannot fit the shared wire limits."""


def period_key(period: FinancialPeriod) -> tuple[str, str | None, str | None, str | None]:
    return period.kind, period.start_date, period.end_date, period.instant_date


def complete_period(period: FinancialPeriod) -> bool:
    if period.kind == "INSTANT":
        return period.instant_date is not None
    return (
        period.kind == "DURATION" and period.start_date is not None and period.end_date is not None
    )


def ownership_key(quantity: QuantitativeValue) -> tuple[str | None, str | None, str | None]:
    return quantity.denominator, quantity.stake_kind, quantity.ownership_date


def normalize(quantity: QuantitativeValue) -> NormalizedAmount:
    value = quantity.normalized_value
    unit = quantity.normalized_unit
    if value is None or unit is None:
        raise ValueError("An accepted value and explicit supported unit are required.")
    currency = quantity.currency
    if unit in _SCALES:
        if (
            currency not in {"INR", "USD"}
            or (unit in {"INR", "USD"} and unit != currency)
            or (unit == "rupees" and currency != "INR")
        ):
            raise ValueError(
                "An explicit matching currency is required; no FX conversion is allowed."
            )
        multiplier, target = Decimal(_SCALES[unit]), currency
    elif currency is not None:
        raise ValueError("Currency is incompatible with this non-monetary unit.")
    elif unit in {"MW", "GW"} and value >= 0:
        multiplier, target = Decimal("1000" if unit == "GW" else "1"), "MW"
    elif unit == "shares" and value >= 0 and value == value.to_integral_value():
        multiplier, target = Decimal("1"), "shares"
    elif unit == "%" and Decimal("0") <= value <= Decimal("100"):
        multiplier, target = Decimal("1"), "%"
    else:
        raise ValueError("The unit or value has no supported deterministic normalization.")
    with localcontext(Context(prec=512)) as context:
        context.traps[Inexact] = True
        scaled = value * multiplier
    # Reuse the wire's exact limits, including retained fractional scale.
    try:
        decimal_to_wire(scaled)
    except ValueError:
        raise NormalizationRangeError("Exact scaling exceeds wire limits.") from None
    return NormalizedAmount(value=scaled, unit=target, currency=currency, multiplier=multiplier)


def difference(baseline: ComparisonCell, comparison: ComparisonCell) -> PairDifference:
    common: dict[str, object] = {
        "baseline_company_id": baseline.company_id,
        "company_id": comparison.company_id,
        "input_observation_ids": (),
        "unit": None,
        "currency": None,
        "difference": None,
        "percentage_state": "UNAVAILABLE",
        "percentage_difference": None,
    }

    def unavailable(state: str, reason: str) -> PairDifference:
        return PairDifference.model_validate({**common, "state": state, "explanation": reason})

    left, right = baseline.normalized, comparison.normalized
    if left is None or right is None:
        return unavailable("UNAVAILABLE", "Both companies require one compatible accepted input.")
    left_quantity = baseline.inputs[0].observation.quantity
    right_quantity = comparison.inputs[0].observation.quantity
    assert left_quantity is not None and right_quantity is not None
    common["input_observation_ids"] = (
        baseline.inputs[0].observation.id,
        comparison.inputs[0].observation.id,
    )
    if (
        left.unit,
        left.currency,
        ownership_key(left_quantity),
        period_key(left_quantity.period),
        left_quantity.basis,
        baseline.inputs[0].metric.id,
    ) != (
        right.unit,
        right.currency,
        ownership_key(right_quantity),
        period_key(right_quantity.period),
        right_quantity.basis,
        comparison.inputs[0].metric.id,
    ):
        return unavailable("INCOMPATIBLE", "Input metrics or financial contexts differ.")
    common.update(
        unit="percentage points" if left.unit == "%" else left.unit, currency=left.currency
    )
    try:
        with localcontext(Context(prec=512)) as context:
            context.traps[Inexact] = True
            delta = right.value - left.value
        decimal_to_wire(delta)
    except (ValueError, DecimalException):
        return unavailable("OUT_OF_RANGE", "The exact difference exceeds supported Decimal limits.")
    common.update(difference=delta, percentage_state="NON_POSITIVE_BASELINE")
    if left.value > 0:
        try:
            with localcontext(Context(prec=512)):
                percentage = (delta * Decimal("100") / left.value).quantize(
                    Decimal("0.000001"), rounding=ROUND_HALF_EVEN
                )
            decimal_to_wire(percentage)
            common.update(percentage_state="AVAILABLE", percentage_difference=percentage)
        except (ValueError, DecimalException):
            common["percentage_state"] = "OUT_OF_RANGE"
    return PairDifference.model_validate(
        {
            **common,
            "state": "AVAILABLE",
            "explanation": "Exact difference; percentage follows the disclosed rounding policy.",
        }
    )
