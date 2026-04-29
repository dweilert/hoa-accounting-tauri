"""Edge-case tests for the money-formatting helpers.

The helpers in :mod:`hoa_accounting.validators.format` advertise
None-tolerance, blank-tolerance, and Decimal-safety. The audit
flagged these contracts as untested.
"""

from __future__ import annotations

from decimal import Decimal

from hoa_accounting.validators.format import format_currency, format_money

# ── format_money ──────────────────────────────────────────────────────


def test_format_money_none_returns_zero():
    """``None`` is the common case for "no value yet" — must not raise."""
    assert format_money(None) == "0.00"


def test_format_money_empty_string_returns_zero():
    """Empty string from a blank form field collapses to zero."""
    assert format_money("") == "0.00"


def test_format_money_zero():
    assert format_money(0) == "0.00"
    assert format_money(Decimal("0")) == "0.00"


def test_format_money_decimal_no_separator():
    """Numeric form-field shape: no thousands separators, no symbol."""
    assert format_money(Decimal("12.34")) == "12.34"
    assert format_money(Decimal("1234.56")) == "1234.56"
    assert format_money(Decimal("1234567.89")) == "1234567.89"


def test_format_money_str_input():
    """Accepting ``str`` lets templates pass raw DB values without
    pre-converting."""
    assert format_money("12.34") == "12.34"
    assert format_money("1234.5") == "1234.50"


def test_format_money_rounds_extra_precision():
    """``Decimal`` arithmetic can leave trailing precision; the helper
    formats to exactly two places via ``f"{:.2f}"`` which uses
    banker's rounding (round-half-to-even)."""
    # 12.345 → ties at the 5; rounds to even (4 is even) → 12.34
    assert format_money(Decimal("12.345")) == "12.34"
    # 12.355 → rounds to even (6 is even) → 12.36
    assert format_money(Decimal("12.355")) == "12.36"
    # Not a tie → straightforward half-up / half-down.
    assert format_money(Decimal("12.349")) == "12.35"
    assert format_money(Decimal("12.341")) == "12.34"


def test_format_money_negative():
    """Negative values keep their sign — no sign manipulation."""
    assert format_money(Decimal("-12.34")) == "-12.34"
    assert format_money(-1234.5) == "-1234.50"


def test_format_money_unparseable_returns_zero():
    """A bare-bones safety net: hand it garbage, get zero (don't raise)."""
    assert format_money("not a number") == "0.00"
    assert format_money({"weird": "input"}) == "0.00"


# ── format_currency ──────────────────────────────────────────────────


def test_format_currency_none_returns_zero():
    assert format_currency(None) == "$0.00"


def test_format_currency_empty_string_returns_zero():
    assert format_currency("") == "$0.00"


def test_format_currency_basic():
    assert format_currency(Decimal("12.34")) == "$12.34"
    assert format_currency(0) == "$0.00"


def test_format_currency_thousands_separator():
    """Display form: thousands separators always present."""
    assert format_currency(Decimal("1234.56")) == "$1,234.56"
    assert format_currency(Decimal("1234567.89")) == "$1,234,567.89"


def test_format_currency_negative_keeps_sign_after_dollar():
    """Convention: ``$-12.34`` (sign inside the symbol). Documented so
    a future change to ``-$12.34`` is a deliberate UX decision."""
    assert format_currency(Decimal("-12.34")) == "$-12.34"
    assert format_currency(-1234.5) == "$-1,234.50"


def test_format_currency_rounds_extra_precision():
    assert format_currency(Decimal("12.349")) == "$12.35"
    assert format_currency(Decimal("12.341")) == "$12.34"


def test_format_currency_str_input():
    assert format_currency("99.99") == "$99.99"


def test_format_currency_unparseable_returns_zero():
    assert format_currency("garbage") == "$0.00"
    assert format_currency([]) == "$0.00"
