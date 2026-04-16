"""Data transfer objects used by services."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class JournalLineInput:
    """One debit or credit line for a journal entry.

    ``expense_classification`` carries the per-transaction operating-vs-
    improvement tag used by expense reporting. It is optional on the input
    — lines targeting non-expense accounts (asset, liability, income,
    equity) leave it ``None``, which stores as SQL NULL. Expense-account
    lines should supply either ``"OPERATING"`` or ``"IMPROVEMENT"``;
    callers that omit it on an expense line get ``"OPERATING"`` as a safe
    default applied at the validator layer.
    """
    account_id: int
    description: str
    debit_amount: Decimal = Decimal("0.00")
    credit_amount: Decimal = Decimal("0.00")
    lot_id: Optional[int] = None
    owner_id: Optional[int] = None
    vendor_id: Optional[int] = None
    expense_classification: Optional[str] = None


@dataclass(frozen=True)
class JournalEntryResult:
    """Return information for a newly created journal entry."""
    journal_entry_id: int
    entry_number: str
    source_type: str


@dataclass(frozen=True)
class AssessmentResult:
    """Return information for a posted assessment."""
    assessment_id: int
    journal_entry_id: int
    entry_number: str


@dataclass(frozen=True)
class PaymentResult:
    """Return information for a posted owner payment."""
    payment_id: int
    journal_entry_id: int
    entry_number: str


@dataclass(frozen=True)
class VendorBillResult:
    """Return information for a posted vendor bill."""
    vendor_bill_id: int
    journal_entry_id: int
    entry_number: str


@dataclass(frozen=True)
class VendorPaymentResult:
    """Return information for a posted vendor bill payment."""
    bill_payment_id: int
    journal_entry_id: int
    entry_number: str


@dataclass(frozen=True)
class ReserveTransferResult:
    """Return information for a posted reserve transfer."""
    reserve_transfer_id: int
    journal_entry_id: int
    entry_number: str


@dataclass(frozen=True)
class ReversalResult:
    """Return information for a posted reversal.

    ``original_journal_entry_id`` is the entry being reversed (now marked
    REVERSED). ``reversal_journal_entry_id`` is the new entry that swaps
    the original's debits and credits.
    """
    original_journal_entry_id: int
    reversal_journal_entry_id: int
    reversal_entry_number: str
