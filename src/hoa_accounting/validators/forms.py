"""Shared form-field validators.

These helpers encode the rules that have evolved across the page-level
form handlers: trim whitespace, raise ``ValidationError`` with a
consistent message format, and accept ``None`` so that
``request.form.get(...)`` results can be passed through directly.

Each pages module previously defined its own copies. They had subtly
drifted (one variant raised ``ValueError`` instead of
``ValidationError``); consolidating here is a one-source-of-truth move.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from hoa_accounting.exceptions import ValidationError


def require(raw: str | None, label: str) -> str:
    """Trim ``raw`` and require non-empty content.

    Raises ``ValidationError`` with ``"{label} is required."`` if blank.
    """
    value = (raw or "").strip()
    if not value:
        raise ValidationError(f"{label} is required.")
    return value


def opt(raw: str | None) -> str | None:
    """Trim ``raw`` and return ``None`` for blank input."""
    return (raw or "").strip() or None


def parse_int(raw: str | None, label: str) -> int:
    """Parse ``raw`` as an integer, treating blanks/non-ints as missing.

    Mirrors the historical behavior across page handlers: any failure
    surfaces as ``"{label} is required."`` rather than a parse error.
    """
    try:
        return int((raw or "").strip())
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} is required.") from exc


def parse_positive_decimal(raw: str | None, label: str) -> Decimal:
    """Parse ``raw`` as a positive Decimal.

    Two distinct error messages: a clear "must be a number" for a parse
    failure, and "must be greater than zero" when the value is non-positive.
    """
    try:
        value = Decimal((raw or "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"{label} must be a number.") from exc
    if value <= Decimal("0"):
        raise ValidationError(f"{label} must be greater than zero.")
    return value


def parse_nonzero_decimal(raw: str | None, label: str) -> Decimal:
    """Parse ``raw`` as a nonzero Decimal (positive *or* negative).

    Used for vendor credit memos where a negative amount is valid.
    Raises ``ValidationError`` if blank, unparseable, or zero.
    """
    try:
        value = Decimal((raw or "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"{label} must be a number.") from exc
    if value == Decimal("0"):
        raise ValidationError(f"{label} must not be zero.")
    return value
