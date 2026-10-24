"""Deterministic illustrative calculations; never calculations over invented filing facts."""

from decimal import ROUND_HALF_EVEN, Decimal, DecimalException, localcontext

from pydantic import TypeAdapter, ValidationError

from regintel.contracts.primitives import DecimalValue
from regintel.learning.models import ExampleCalculation, ExampleInput


def calculate_example(source: ExampleInput) -> ExampleCalculation:
    source = ExampleInput.model_validate(source.model_dump(mode="python"))
    formula = {
        "ADD": "left + right",
        "SUBTRACT": "left - right",
        "MULTIPLY": "left * right",
        "DIVIDE": "left / right",
        "PERCENT_CHANGE": "(right - left) / left * 100",
    }[source.operation]
    rounding = (
        "HALF_EVEN_12_DECIMAL_PLACES"
        if source.operation in {"DIVIDE", "PERCENT_CHANGE"}
        else "EXACT"
    )

    def result(state: str, value: Decimal | None = None) -> ExampleCalculation:
        return ExampleCalculation.model_validate(
            {
                "input": source,
                "state": state,
                "result": value,
                "result_unit": "%" if source.operation == "PERCENT_CHANGE" else source.unit,
                "formula": formula,
                "rounding": rounding,
            }
        )

    if source.operation == "DIVIDE" and source.right == 0:
        return result("ZERO_DIVISOR")
    if source.operation == "PERCENT_CHANGE" and source.left <= 0:
        return result("NON_POSITIVE_BASELINE")
    try:
        with localcontext() as context:
            context.prec = 512
            if source.operation == "ADD":
                value = source.left + source.right
            elif source.operation == "SUBTRACT":
                value = source.left - source.right
            elif source.operation == "MULTIPLY":
                value = source.left * source.right
            elif source.operation == "DIVIDE":
                value = source.left / source.right
            else:
                value = (source.right - source.left) / source.left * Decimal(100)
            if rounding != "EXACT":
                value = value.quantize(Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN)
        TypeAdapter(DecimalValue).validate_python(value)
        return result("AVAILABLE", value)
    except (DecimalException, ValidationError):
        return result("OUT_OF_RANGE")
