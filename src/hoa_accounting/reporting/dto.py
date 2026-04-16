"""DTOs for reporting output."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class TrialBalanceRow:
    """One row in a trial balance report."""
    account_id: int
    account_number: str
    account_name: str
    account_type_id: int
    fund_code: str
    debit_total: Decimal
    credit_total: Decimal
    net_debit: Decimal
    net_credit: Decimal


@dataclass(frozen=True)
class TrialBalanceReport:
    """Full trial balance report."""
    as_of_date: str
    rows: list[TrialBalanceRow]
    total_debits: Decimal
    total_credits: Decimal


@dataclass(frozen=True)
class GeneralLedgerRow:
    """One row in a general ledger detail report."""
    entry_date: str
    entry_number: str
    source_type: str
    memo: str
    line_description: str
    debit_amount: Decimal
    credit_amount: Decimal
    running_balance: Decimal
    lot_id: int | None
    owner_id: int | None
    vendor_id: int | None


@dataclass(frozen=True)
class GeneralLedgerReport:
    """General ledger detail for one account."""
    account_id: int
    account_number: str
    account_name: str
    from_date: str | None
    to_date: str | None
    rows: list[GeneralLedgerRow]


@dataclass(frozen=True)
class OwnerLedgerRow:
    """One owner-ledger detail row for the owner receivable subledger."""
    entry_date: str
    entry_number: str
    source_type: str
    source_id: int | None
    memo: str
    line_description: str
    debit_amount: Decimal
    credit_amount: Decimal
    running_balance: Decimal
    lot_id: int | None
    lot_number: str | None
    due_date: str | None
    assessment_id: int | None
    payment_id: int | None
    receipt_number: str | None
    payment_method: str | None
    owner_adjustment_id: int | None
    adjustment_type: str | None


@dataclass(frozen=True)
class OwnerLedgerReport:
    """Owner receivable subledger report for one owner and one receivable account."""
    owner_id: int
    owner_name: str
    receivable_account_id: int
    receivable_account_number: str
    receivable_account_name: str
    from_date: str | None
    to_date: str | None
    opening_balance: Decimal
    closing_balance: Decimal
    rows: list[OwnerLedgerRow]


@dataclass(frozen=True)
class ARAgingDetailRow:
    """One open assessment item included in AR aging."""
    owner_id: int
    owner_name: str
    lot_id: int | None
    lot_number: str | None
    assessment_id: int
    assessment_date: str
    due_date: str
    description: str
    original_amount: Decimal
    applied_amount: Decimal
    remaining_amount: Decimal
    days_past_due: int
    aging_bucket: str


@dataclass(frozen=True)
class ARAgingOwnerSummary:
    """Owner-level AR aging totals."""
    owner_id: int
    owner_name: str
    current_amount: Decimal
    amount_1_30: Decimal
    amount_31_60: Decimal
    amount_61_90: Decimal
    amount_90_plus: Decimal
    total_open_amount: Decimal
    credit_balance: Decimal
    ledger_balance: Decimal


@dataclass(frozen=True)
class ARAgingReport:
    """Accounts receivable aging report."""
    as_of_date: str
    receivable_account_id: int
    receivable_account_number: str
    receivable_account_name: str
    detail_rows: list[ARAgingDetailRow]
    owner_summaries: list[ARAgingOwnerSummary]
    total_current_amount: Decimal
    total_amount_1_30: Decimal
    total_amount_31_60: Decimal
    total_amount_61_90: Decimal
    total_amount_90_plus: Decimal
    total_open_amount: Decimal
    total_credit_balance: Decimal
    total_ledger_balance: Decimal


@dataclass(frozen=True)
class BalanceSheetRow:
    """One line item on a balance sheet section."""
    account_id: int | None
    account_number: str | None
    account_name: str
    fund_code: str | None
    amount: Decimal
    is_system: bool = False


@dataclass(frozen=True)
class BalanceSheetSection:
    """One balance sheet section such as assets, liabilities, or equity."""
    section_name: str
    rows: list[BalanceSheetRow]
    total_amount: Decimal


@dataclass(frozen=True)
class BalanceSheetReport:
    """Balance sheet as of a date."""
    as_of_date: str
    assets: BalanceSheetSection
    liabilities: BalanceSheetSection
    equity: BalanceSheetSection
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    total_liabilities_and_equity: Decimal
    balancing_difference: Decimal


@dataclass(frozen=True)
class IncomeStatementRow:
    """One line item in an income statement section."""
    account_id: int
    account_number: str
    account_name: str
    fund_code: str
    amount: Decimal


@dataclass(frozen=True)
class IncomeStatementSection:
    """One income statement section such as income or expenses."""
    section_name: str
    rows: list[IncomeStatementRow]
    total_amount: Decimal


@dataclass(frozen=True)
class IncomeStatementReport:
    """Income statement for a date range."""
    from_date: str
    to_date: str
    income: IncomeStatementSection
    expenses: IncomeStatementSection
    total_income: Decimal
    total_expenses: Decimal
    net_income: Decimal