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
    options_key: str | None = None
    default_value: str = ""


@dataclass(frozen=True)
class ReportDefinition:
    """Metadata describing one supported report."""
    name: str
    title: str
    description: str
    fields: list[ReportField]


REPORT_DEFINITIONS: list[ReportDefinition] = [
    ReportDefinition(
        name="ytd-expense-summary",
        title="Expense Summary",
        description=(
            "Expenses grouped by category and group, with total amount and "
            "bill count per category. Zero-activity categories are included "
            "so the full picture is always visible."
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
        name="income-by-date",
        title="Income Summary",
        description="All income (dues, assessments, non-dues) in chronological order for a date range.",
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
        title="Expense Detail",
        description="All vendor bills in chronological order for a date range.",
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
        description="Bills grouped by vendor for a date range. Leave vendor blank to see all vendors.",
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
                required=False,
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
        name="budget-summary",
        title="Budget Summary",
        description="Annual budget amounts by category and group across one, two, or three fiscal years with year-over-year percent change.",
        fields=[
            ReportField(
                name="fiscal_year",
                label="Current Year",
                placeholder="2026",
                required=False,
            ),
            ReportField(
                name="years_mode",
                label="Years to Show",
                placeholder="",
                required=False,
                field_type="select",
                options_key="years_mode",
                default_value="prev_current",
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
                required=False,
            ),
            ReportField(
                name="fund_code",
                label="Fund",
                placeholder="",
                required=False,
                field_type="select",
                options_key="fund_code",
                default_value="OPERATING",
            ),
        ],
    ),
]


def get_report_definition(report_name: str) -> ReportDefinition:
    """Return the report definition for a report name, defaulting to the first report."""
    normalized = report_name.strip().lower()
    for item in REPORT_DEFINITIONS:
        if item.name == normalized:
            return item
    return REPORT_DEFINITIONS[0]
