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


@dataclass(frozen=True)
class YtdExpenseCategoryRow:
    """One expense category (GL account) row on the YTD summary."""
    account_id: int
    account_number: str
    account_name: str
    group_code: str
    fund_code: str
    ytd_amount: Decimal
    record_count: int
    comment: str = ""


@dataclass(frozen=True)
class YtdExpenseGroup:
    """One group bucket (Landscape, Entrance, …) with its categories."""
    group_code: str
    rows: list[YtdExpenseCategoryRow]
    group_total: Decimal
    group_record_count: int


@dataclass(frozen=True)
class YtdExpenseSummaryReport:
    """YTD expense summary grouped by expense group, matching the
    user's spreadsheet summary view."""
    from_date: str
    to_date: str
    groups: list[YtdExpenseGroup]
    grand_total: Decimal
    total_record_count: int


# ── Lot Statement (Owner Ledger — lot-based, source-table view) ───────────────

@dataclass(frozen=True)
class OpeningBalanceLine:
    """One line in the beginning-balance breakdown."""
    charge_type: str   # DUES | LATE_FEE | LEGAL_FEE | ADJUSTMENT
    label: str         # human-readable label
    amount: Decimal    # positive = owed to HOA; negative = credit


@dataclass(frozen=True)
class LotOwnerInfo:
    """Contact details for one owner of a lot."""
    display_name: str
    first_name: str
    last_name: str
    email: str
    phone: str


@dataclass(frozen=True)
class LotStatementRow:
    """One line in a lot statement — a charge, payment, or adjustment."""
    entry_date: str
    entry_type: str      # CHARGE | PAYMENT | ADJUSTMENT
    charge_type: str     # DUES, LATE_FEE, LEGAL_FEE, PAYMENT, CREDIT_MEMO, WRITE_OFF, OTHER
    description: str
    due_date: str        # populated for charges; blank for payments/adjustments
    debit_amount: Decimal
    credit_amount: Decimal
    running_balance: Decimal
    status: str          # assessment status for charges; blank otherwise
    receipt_number: str  # populated for payments; blank otherwise


@dataclass(frozen=True)
class LotStatementReport:
    """Full lot statement for one lot for a full year."""
    lot_id: int
    lot_number: str
    lot_address: str
    owners: list[LotOwnerInfo]
    year: int
    from_date: str
    to_date: str
    opening_balance: Decimal
    opening_balance_lines: list[OpeningBalanceLine]
    closing_balance: Decimal
    rows: list[LotStatementRow]


# ── Expenses by Date ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ExpensesByDateRow:
    """One row in the expenses-by-date report."""
    entry_date: str
    entry_number: str
    account_number: str
    account_name: str
    group_code: str
    fund_code: str
    memo: str
    amount: Decimal


@dataclass(frozen=True)
class ExpensesByDateReport:
    """All expense journal lines in date order."""
    from_date: str
    to_date: str
    rows: list[ExpensesByDateRow]
    grand_total: Decimal


# ── Income by Date ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class IncomeByDateRow:
    """One row in the income-by-date report."""
    entry_date: str
    source: str         # homeowner name, or blank for non-owner income
    lot_number: str     # lot identifier, or blank when not applicable
    account_code: str   # short code e.g. DUES, RESALE_FEE, 4010
    account_name: str   # full name for tooltip
    memo: str
    comment: str        # notes/additional annotation, may be blank
    amount: Decimal


@dataclass(frozen=True)
class IncomeByDateReport:
    """All income journal lines in date order."""
    from_date: str
    to_date: str
    rows: list[IncomeByDateRow]
    grand_total: Decimal


# ── Vendor Expenses ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class VendorExpensesRow:
    """One row in the vendor expenses report."""
    vendor_name: str
    entry_date: str
    entry_number: str
    account_number: str
    account_name: str
    group_code: str
    memo: str
    amount: Decimal


@dataclass(frozen=True)
class VendorExpensesReport:
    """Expense journal lines grouped by vendor."""
    from_date: str
    to_date: str
    vendor_id: int | None
    vendor_name: str | None
    rows: list[VendorExpensesRow]
    grand_total: Decimal


# ── Homeowner Contact List ────────────────────────────────────────────────────

@dataclass(frozen=True)
class HomeownerContactRow:
    """One contact row (owner or renter) in the homeowner contact list."""
    role: str          # "OWNER" | "RENTER"
    first_name: str
    last_name: str
    address: str
    cell_phone: str
    home_phone: str
    email: str


@dataclass(frozen=True)
class HomeownerContactListReport:
    """Directory of all active owners with contact information."""
    rows: list[HomeownerContactRow]


# ── Expenses vs Budget ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ExpenseVsBudgetRow:
    """One category row comparing budget to actual."""
    category_name: str
    group_code: str
    budget_amount: Decimal
    actual_amount: Decimal
    variance: Decimal


@dataclass(frozen=True)
class ExpenseVsBudgetGroup:
    """One expense group bucket with its category rows."""
    group_code: str
    rows: list[ExpenseVsBudgetRow]
    group_budget: Decimal
    group_actual: Decimal
    group_variance: Decimal


@dataclass(frozen=True)
class ExpenseVsBudgetReport:
    """Actual expenses vs approved budget for a fiscal year."""
    fiscal_year: int
    fund_code: str
    from_date: str
    to_date: str
    groups: list[ExpenseVsBudgetGroup]
    total_budget: Decimal
    total_actual: Decimal
    total_variance: Decimal


# ── Budget Summary ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BudgetSummaryRow:
    """One category row in the budget summary, with amounts for 1–3 years."""
    category_name: str
    group_code: str
    year_amounts: list[Decimal]   # one entry per year in display order
    pct_changes: list[str]        # one fewer than year_amounts; empty for single year


@dataclass(frozen=True)
class BudgetSummaryGroup:
    """One group bucket with its category rows and subtotals."""
    group_code: str
    rows: list[BudgetSummaryRow]
    subtotal_amounts: list[Decimal]
    subtotal_pct_changes: list[str]


@dataclass(frozen=True)
class BudgetSummaryReport:
    """Budget amounts across 1, 2, or 3 fiscal years."""
    years: list[int]
    groups: list[BudgetSummaryGroup]
    total_amounts: list[Decimal]
    total_pct_changes: list[str]