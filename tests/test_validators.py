"""Validator tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from hoa_accounting.exceptions import UnbalancedJournalError, ValidationError
from hoa_accounting.models.dto import JournalLineInput
from hoa_accounting.validators.common import q2, require_positive_amount


def test_q2_rounding() -> None:
    """q2 rounds to two decimals."""
    assert q2("12.345") == Decimal("12.35")


def test_require_positive_amount_rejects_zero() -> None:
    """Zero is rejected for positive amount validations."""
    with pytest.raises(ValidationError):
        require_positive_amount("0.00", "Amount")


class DummyAccountValidator:
    """Minimal validator used for journal validator unit tests."""

    def require_active_account(self, account_id: int) -> None:
        return None


def test_journal_line_needs_debit_or_credit() -> None:
    """A line with neither debit nor credit is rejected."""
    from hoa_accounting.validators.journal_validator import JournalValidator

    validator = JournalValidator(DummyAccountValidator())
    with pytest.raises(ValidationError):
        validator.validate_lines(
            [
                JournalLineInput(account_id=1, description="bad"),
                JournalLineInput(account_id=2, description="bad", credit_amount=Decimal("1.00")),
            ]
        )


def test_unbalanced_journal_rejected() -> None:
    """An unbalanced journal raises an error."""
    from hoa_accounting.validators.journal_validator import JournalValidator

    validator = JournalValidator(DummyAccountValidator())
    with pytest.raises(UnbalancedJournalError):
        validator.validate_lines(
            [
                JournalLineInput(
                    account_id=1,
                    description="d",
                    debit_amount=Decimal("10.00"),
                ),
                JournalLineInput(
                    account_id=2,
                    description="c",
                    credit_amount=Decimal("9.00"),
                ),
            ]
        )
