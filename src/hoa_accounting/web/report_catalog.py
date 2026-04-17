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
                label="Account ID",
                placeholder="1000",
                required=True,
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
        description="Owner receivable subledger activity and running balance over a date range.",
        fields=[
            ReportField(
                name="owner_id",
                label="Owner ID",
                placeholder="1",
                required=True,
            ),
            ReportField(
                name="receivable_account_id",
                label="Receivable Account ID",
                placeholder="1100",
                required=True,
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
                label="Receivable Account ID",
                placeholder="1100",
                required=True,
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
]


def get_report_definition(report_name: str) -> ReportDefinition:
    """Return the report definition for a report name."""
    normalized = report_name.strip().lower()
    for item in REPORT_DEFINITIONS:
        if item.name == normalized:
            return item
    return REPORT_DEFINITIONS[0]