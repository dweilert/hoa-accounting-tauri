"""Money-formatting helpers.

Three patterns for rendering money values had drifted across the
codebase:

- ``f"{Decimal(str(x)):.2f}"`` — form-field hydration ("12.34")
- ``f"${total:,.2f}"`` — display, but assumes ``total`` is float-formattable
- ``f"{Decimal(str(x)):,.2f}"`` — display, Decimal-safe

A few sites also fed ``float()`` results into ``:.2f``, which silently
truncates trailing precision.

Two helpers, both Decimal-safe and tolerant of ``None`` / blank input:

- :py:func:`format_money` — ``"12.34"`` (no symbol, no separators).
  Use for form ``value=`` attributes that need to round-trip.
- :py:func:`format_currency` — ``"$12,345.67"`` (with thousands
  separators and ``$`` prefix). Use for human-facing display.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def _to_decimal(value: object) -> Decimal:
    """Coerce arbitrary input to ``Decimal``, returning ``Decimal('0')``
    for ``None`` / empty / unparseable values rather than raising.

    Going through ``str()`` is intentional: ``float`` values would
    otherwise carry their binary-rounding artifacts straight into the
    Decimal (``Decimal(0.1)`` ≠ ``Decimal('0.1')``).
    """
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def format_money(value: object) -> str:
    """Render a money value as ``"12.34"`` for form fields.

    No currency symbol, no thousands separators — just the numeric
    string an HTML input expects. Always exactly two decimal places.
    """
    return f"{_to_decimal(value):.2f}"


def format_currency(value: object) -> str:
    """Render a money value as ``"$12,345.67"`` for display.

    Always includes the ``$`` prefix and thousands separators. Always
    exactly two decimal places.
    """
    return f"${_to_decimal(value):,.2f}"
