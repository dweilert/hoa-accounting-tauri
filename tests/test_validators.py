"""Validator tests — common amount helpers only.

Most of the original suite covered ``JournalValidator`` (double-entry
debit/credit balancing) which was retired with the Chart of Accounts
removal in migration 0061. The remaining tests cover the small helpers
in ``validators.common`` that are still in active use.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from hoa_accounting.exceptions import ValidationError
from hoa_accounting.validators.common import q2, require_positive_amount


def test_q2_rounds_to_two_decimals() -> None:
    assert q2("12.345") == Decimal("12.35")
    assert q2("12.344") == Decimal("12.34")


def test_q2_accepts_decimal_input() -> None:
    assert q2(Decimal("0.005")) == Decimal("0.01")


def test_require_positive_amount_rejects_zero() -> None:
    with pytest.raises(ValidationError):
        require_positive_amount("0.00", "Amount")


def test_require_positive_amount_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        require_positive_amount("-1.00", "Amount")


def test_require_positive_amount_returns_decimal() -> None:
    assert require_positive_amount("125.50", "Amount") == Decimal("125.50")
