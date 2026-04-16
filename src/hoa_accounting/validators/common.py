"""Shared validation and numeric helpers."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from hoa_accounting.exceptions import ValidationError

TWOPLACES = Decimal("0.01")


def q2(value: Decimal | str | int | float) -> Decimal:
    """Quantize a numeric value to two decimal places."""
    if isinstance(value, Decimal):
        dec = value
    else:
        dec = Decimal(str(value))
    return dec.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def require_positive_amount(
    amount: Decimal | str | int | float,
    label: str,
) -> Decimal:
    """Require a positive monetary amount."""
    amount_dec = q2(amount)
    if amount_dec <= Decimal("0.00"):
        raise ValidationError(f"{label} must be greater than zero.")
    return amount_dec
