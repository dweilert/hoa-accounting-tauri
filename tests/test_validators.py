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
    """Minimal validator used for journal validator unit tests.

    Stubs both ``require_active_account`` (legacy) and
    ``require_active_account_with_fund`` (used by the fund-balance check).
    By default every account is reported as OPERATING; tests that need
    mixed-fund behavior should pass a ``fund_code_map``.
    """

    def __init__(self, fund_code_map: dict[int, str] | None = None) -> None:
        self.fund_code_map = fund_code_map or {}

    def require_active_account(self, account_id: int) -> None:
        return None

    def require_active_account_with_fund(self, account_id: int) -> str:
        return self.fund_code_map.get(account_id, "OPERATING")


def test_journal_line_needs_debit_or_credit() -> None:
    import pytest
    pytest.skip("JournalValidator retired with Chart of Accounts removal")
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
    import pytest
    pytest.skip("JournalValidator retired with Chart of Accounts removal")
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


def test_cross_fund_entry_rejected_by_default() -> None:
    import pytest
    pytest.skip("JournalValidator retired with Chart of Accounts removal")
    """Overall balanced but per-fund unbalanced entry is rejected."""
    from hoa_accounting.validators.journal_validator import JournalValidator

    # Debit $10 to an OPERATING account, credit $10 to a RESERVE account.
    # Overall balances, but neither fund balances on its own.
    validator = JournalValidator(
        DummyAccountValidator(fund_code_map={1: "OPERATING", 2: "RESERVE"})
    )
    with pytest.raises(UnbalancedJournalError, match="within fund"):
        validator.validate_lines(
            [
                JournalLineInput(account_id=1, description="d",
                                 debit_amount=Decimal("10.00")),
                JournalLineInput(account_id=2, description="c",
                                 credit_amount=Decimal("10.00")),
            ]
        )


def test_cross_fund_entry_allowed_when_opted_in() -> None:
    import pytest
    pytest.skip("JournalValidator retired with Chart of Accounts removal")
    """A reserve-transfer style entry succeeds only with inter_fund_allowed=True."""
    from hoa_accounting.validators.journal_validator import JournalValidator

    validator = JournalValidator(
        DummyAccountValidator(fund_code_map={1: "OPERATING", 2: "RESERVE"})
    )
    # Same cross-fund lines as above, but this time explicitly allowed.
    validator.validate_lines(
        [
            JournalLineInput(account_id=1, description="d",
                             debit_amount=Decimal("10.00")),
            JournalLineInput(account_id=2, description="c",
                             credit_amount=Decimal("10.00")),
        ],
        inter_fund_allowed=True,
    )


def test_multi_fund_entry_with_each_fund_balanced_is_accepted() -> None:
    import pytest
    pytest.skip("JournalValidator retired with Chart of Accounts removal")
    """Multiple funds are fine as long as each balances on its own."""
    from hoa_accounting.validators.journal_validator import JournalValidator

    # OPERATING: +10 debit / +10 credit.  RESERVE: +5 debit / +5 credit.
    validator = JournalValidator(
        DummyAccountValidator(
            fund_code_map={
                1: "OPERATING",
                2: "OPERATING",
                3: "RESERVE",
                4: "RESERVE",
            }
        )
    )
    validator.validate_lines(
        [
            JournalLineInput(account_id=1, description="op-d",
                             debit_amount=Decimal("10.00")),
            JournalLineInput(account_id=2, description="op-c",
                             credit_amount=Decimal("10.00")),
            JournalLineInput(account_id=3, description="rs-d",
                             debit_amount=Decimal("5.00")),
            JournalLineInput(account_id=4, description="rs-c",
                             credit_amount=Decimal("5.00")),
        ]
    )
