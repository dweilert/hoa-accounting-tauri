"""Validation for journal entry lines."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Sequence

from hoa_accounting.exceptions import UnbalancedJournalError, ValidationError
from hoa_accounting.models.dto import JournalLineInput

from .account_validator import AccountValidator
from .common import q2


class JournalValidator:
    """Validation of journal structure and balance.

    Enforces three rules:
      1. At least two lines, each with a single non-zero debit or credit.
      2. Total debits equal total credits across the whole entry.
      3. Total debits equal total credits *within each fund* (fund-balance
         invariant). HOA fund accounting requires that the OPERATING,
         RESERVE, and SPECIAL funds each stay in balance on their own —
         otherwise a single entry can silently move money between funds.

    The fund-balance rule is skipped only when the caller sets
    ``inter_fund_allowed=True``. The only legitimate use today is the
    reserve transfer service; a proper long-term fix is to introduce
    due-to/due-from inter-fund accounts so every entry balances in every
    fund without exception.
    """

    def __init__(self, account_validator: AccountValidator) -> None:
        self.account_validator = account_validator

    def validate_lines(
        self,
        lines: Sequence[JournalLineInput],
        *,
        inter_fund_allowed: bool = False,
    ) -> None:
        """Require valid, balanced journal lines."""
        if len(lines) < 2:
            raise ValidationError("A journal entry must have at least two lines.")

        debit_total = Decimal("0.00")
        credit_total = Decimal("0.00")
        fund_debits: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
        fund_credits: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))

        for line in lines:
            fund_code = self.account_validator.require_active_account_with_fund(
                line.account_id
            )
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
            fund_debits[fund_code] += debit
            fund_credits[fund_code] += credit

        if debit_total != credit_total:
            raise UnbalancedJournalError(
                f"Journal entry is unbalanced. Debits={debit_total} Credits={credit_total}"
            )

        if inter_fund_allowed:
            return

        for fund_code in sorted(set(fund_debits) | set(fund_credits)):
            fd = fund_debits[fund_code]
            fc = fund_credits[fund_code]
            if fd != fc:
                raise UnbalancedJournalError(
                    f"Journal entry does not balance within fund {fund_code}. "
                    f"Debits={fd} Credits={fc}. "
                    "Cross-fund entries require a reserve transfer or "
                    "inter-fund due-to/due-from accounts."
                )
