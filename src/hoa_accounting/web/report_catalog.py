"""Metadata for report-console UI rendering."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReportField:
    """Metadata describing one report input field."""
    name: str
    label: str
    placeholder: str
    required: bool
    field_type: str = "text"    # "text" | "select"
    options_key: str | None = None  # key into lookup_options for select fields
    default_value: str = ""    # pre-selected value when no form data present


@dataclass(frozen=True)
class ReportDefinition:
    """Metadata describing one supported report."""
    name: str
    title: str
    description: str
    fields: list[ReportField]


REPORT_DEFINITIONS: list[ReportDefinition] = [
    ReportDefinition(
        name="trial-balance",
        title="Trial Balance",
        description="Control report showing net balances for all active accounts as of a specific date.",
        fields=[
            ReportField(
                name="as_of_date",
                label="As Of Date",
                placeholder="2026-01-31",
                required=True,
            ),
        ],
    ),
    ReportDefinition(
        name="general-ledger",
        title="General Ledger",
        description="Account-level journal detail with a running balance over a date range.",
        fields=[
            ReportField(
                name="account_id",
                label="Account",
                placeholder="",
                required=True,
                field_type="select",
                options_key="account_id",
            ),
            ReportField(
                name="from_date",
                label="From Date",
                placeholder="2026-01-01",
                required=True,
            ),
            ReportField(
                name="to_date",
                label="To Date",
                placeholder="2026-01-31",
                required=True,
            ),
        ],
    ),
    ReportDefinition(
        name="owner-ledger",
        title="Owner Ledger",
        description="Full-year owner receivable activity for a lot — dues, assessments, late fees, and payments — in date order.",
        fields=[
            ReportField(
                name="lot_id",
                label="Lot",
                placeholder="",
                required=True,
                field_type="select",
                options_key="lot_id",
            ),
            ReportField(
                name="year",
                label="Year",
                placeholder="2026",
                required=True,
            ),
        ],
    ),
    ReportDefinition(
        name="ar-aging",
        title="AR Aging",
        description="Open owner receivables bucketed by age as of a specific date.",
        fields=[
            ReportField(
                name="as_of_date",
                label="As Of Date",
                placeholder="2026-03-15",
                required=True,
            ),
            ReportField(
                name="receivable_account_id",
                label="Receivable Account",
                placeholder="",
                required=True,
                field_type="select",
                options_key="receivable_account_id",
            ),
        ],
    ),
    ReportDefinition(
        name="balance-sheet",
        title="Balance Sheet",
        description="Balance-sheet accounts and computed cumulative earnings as of a specific date.",
        fields=[
            ReportField(
                name="as_of_date",
                label="As Of Date",
                placeholder="2026-01-31",
                required=True,
            ),
        ],
    ),
    ReportDefinition(
        name="income-statement",
        title="Income Statement",
        description="Income and expense activity for a specific reporting period.",
        fields=[
            ReportField(
                name="from_date",
                label="From Date",
                placeholder="2026-01-01",
                required=True,
            ),
            ReportField(
                name="to_date",
                label="To Date",
                placeholder="2026-01-31",
                required=True,
            ),
        ],
    ),
    ReportDefinition(
        name="ytd-expense-summary",
        title="YTD Expense Summary",
        description=(
            "Expenses grouped by category and group, with YTD amount and "
            "transaction count per category. Zero-activity categories are "
            "included so the whole chart is visible at a glance."
        ),
        fields=[
            ReportField(
                name="from_date",
                label="From Date",
                placeholder="2026-01-01",
                required=True,
            ),
            ReportField(
                name="to_date",
                label="To Date",
                placeholder="2026-12-31",
                required=True,
            ),
        ],
    ),
    ReportDefinition(
        name="expenses-by-date",
        title="Expenses by Date",
        description="All expense journal entries in chronological order for a date range.",
        fields=[
            ReportField(
                name="from_date",
                label="From Date",
                placeholder="2026-01-01",
                required=True,
            ),
            ReportField(
                name="to_date",
                label="To Date",
                placeholder="2026-12-31",
                required=True,
            ),
        ],
    ),
    ReportDefinition(
        name="income-by-date",
        title="Income by Date",
        description="All income journal entries in chronological order for a date range.",
        fields=[
            ReportField(
                name="from_date",
                label="From Date",
                placeholder="2026-01-01",
                required=True,
            ),
            ReportField(
                name="to_date",
                label="To Date",
                placeholder="2026-12-31",
                required=True,
            ),
        ],
    ),
    ReportDefinition(
        name="vendor-expenses",
        title="Vendor Expenses",
        description="Expense entries grouped by vendor for a date range. Leave vendor blank to see all vendors.",
        fields=[
            ReportField(
                name="from_date",
                label="From Date",
                placeholder="2026-01-01",
                required=True,
            ),
            ReportField(
                name="to_date",
                label="To Date",
                placeholder="2026-12-31",
                required=True,
            ),
            ReportField(
                name="vendor_id",
                label="Vendor (optional — leave blank for all)",
                placeholder="",
                required=False,
                field_type="select",
                options_key="vendor_id",
            ),
        ],
    ),
    ReportDefinition(
        name="homeowner-contact-list",
        title="Homeowner Contact List",
        description="Directory of all active homeowners with lot assignment and contact information.",
        fields=[
            ReportField(
                name="sort_by",
                label="Sort Order",
                placeholder="",
                required=False,
                field_type="select",
                options_key="sort_by",
                default_value="name",
            ),
        ],
    ),
    ReportDefinition(
        name="expenses-vs-budget",
        title="Expenses vs Budget",
        description="Compare actual expenses against an approved budget for a fiscal year.",
        fields=[
            ReportField(
                name="fiscal_year",
                label="Fiscal Year",
                placeholder="2026",
                required=True,
            ),
            ReportField(
                name="fund_code",
                label="Fund",
                placeholder="",
                required=True,
                field_type="select",
                options_key="fund_code",
            ),
        ],
    ),
]


def get_report_definition(report_name: str) -> ReportDefinition:
    """Return the report definition for a report name."""
    normalized = report_name.strip().lower()
    for item in REPORT_DEFINITIONS:
        if item.name == normalized:
            return item
    return REPORT_DEFINITIONS[0]
