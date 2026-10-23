"""Decimal money helpers. Never use ``float`` for currency maths."""
from decimal import ROUND_HALF_UP, Decimal
from typing import Union

TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0.00")


def to_decimal(value: Union[int, float, str, Decimal, None]) -> Decimal:
    """Convert any numeric value to Decimal safely (via ``str`` for floats)."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def money(value: Union[int, float, str, Decimal, None]) -> Decimal:
    """Quantise to two decimal places using bankers-safe ROUND_HALF_UP."""
    return to_decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
