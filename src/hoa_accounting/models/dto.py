"""Data transfer objects used by services."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


# ── Legacy journal types — kept for manual journal entries + opening balances ──

@dataclass(frozen=True)
class JournalLineInput:
    """One debit or credit line for a journal entry."""
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


# ── Single-entry transaction results ──────────────────────────────────────────


@dataclass(frozen=True)
class AssessmentResult:
    """Return information for a posted assessment."""
    assessment_id: int


@dataclass(frozen=True)
class PaymentResult:
    """Return information for a posted owner payment."""
    payment_id: int


@dataclass(frozen=True)
class VendorBillResult:
    """Return information for a posted vendor bill."""
    vendor_bill_id: int


@dataclass(frozen=True)
class VendorPaymentResult:
    """Return information for a posted vendor bill payment."""
    bill_payment_id: int


@dataclass(frozen=True)
class ReserveTransferResult:
    """Return information for a posted reserve transfer."""
    reserve_transfer_id: int


@dataclass(frozen=True)
class ReversalResult:
    """Return information for a posted reversal."""
    original_journal_entry_id: int
    reversal_journal_entry_id: int
    reversal_entry_number: str
