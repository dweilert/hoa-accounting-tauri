"""Shared validation and numeric helpers."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from hoa_accounting.exceptions import ValidationError

TWOPLACES = Decimal("0.01")


def q2(value: Decimal | str | int | float) -> Decimal:
    """Quantize a numeric value to two decimal places."""
    if isinstance(value, Decimal):
        dec = value
    else:
        dec = Decimal(str(value))
    return dec.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def q2_str(value: Decimal | str | int | float) -> str:
    """Money as a 2-dp string ('100.00', '-12.50') — safe to compare to
    ``printf('%.2f', col)`` in SQL without going through float.

    Use this when matching a Python amount against the TEXT-stored
    Decimal columns in SQLite — avoids the float-drift trap of
    ``CAST(amount AS REAL) = CAST(? AS REAL)`` for amounts that might
    grow past the float-safe range.
    """
    return f"{q2(value):f}"


def require_positive_amount(
    amount: Decimal | str | int | float,
    label: str,
) -> Decimal:
    """Require a positive monetary amount."""
    amount_dec = q2(amount)
    if amount_dec <= Decimal("0.00"):
        raise ValidationError(f"{label} must be greater than zero.")
    return amount_dec
