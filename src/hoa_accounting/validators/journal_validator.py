"""Validation for journal entry lines."""

from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from hoa_accounting.exceptions import UnbalancedJournalError, ValidationError
from hoa_accounting.models.dto import JournalLineInput

from .account_validator import AccountValidator
from .common import q2


class JournalValidator:
    """Validation of journal structure and balance."""

    def __init__(self, account_validator: AccountValidator) -> None:
        self.account_validator = account_validator

    def validate_lines(self, lines: Sequence[JournalLineInput]) -> None:
        """Require valid, balanced journal lines."""
        if len(lines) < 2:
            raise ValidationError("A journal entry must have at least two lines.")

        debit_total = Decimal("0.00")
        credit_total = Decimal("0.00")

        for line in lines:
            self.account_validator.require_active_account(line.account_id)
            debit = q2(line.debit_amount)
            credit = q2(line.credit_amount)

            if debit < 0 or credit < 0:
                raise ValidationError("Debit and credit amounts cannot be negative.")
            if (debit > 0 and credit > 0) or (debit == 0 and credit == 0):
                raise ValidationError(
                    "Each journal line must have either a debit amount or a credit amount."
                )

            debit_total += debit
            credit_total += credit

        if debit_total != credit_total:
            raise UnbalancedJournalError(
                f"Journal entry is unbalanced. Debits={debit_total} Credits={credit_total}"
            )
