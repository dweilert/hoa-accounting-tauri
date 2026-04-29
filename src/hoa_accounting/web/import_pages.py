"""
Data import page — System › Import Data.

Three-step flow (client-side state machine):
  1. Select target table  +  drag-and-drop CSV file
  2. Visual field mapper  —  draw connections between CSV columns and table fields
  3. Run import           —  server validates, inserts valid rows, returns result report

CSV format convention (mirrors export):
  • Commas inside cell values are encoded as &#x2C; on export.
  • Standard quoted CSV (from Excel, etc.) is also accepted on import.
  • &#x2C; is decoded back to a literal comma during parsing.

Import rules:
  • Insert-only — duplicate natural keys produce a row-level error, not a fatal stop.
  • Valid rows are committed; invalid rows are skipped and reported.
  • Each row is wrapped in a SAVEPOINT so a single failure never rolls back prior rows.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
from typing import Any

from hoa_accounting.web.template_engine import render_template


# ── Table definitions ────────────────────────────────────────────────────────
# Drives both the JS mapper UI (field list, labels, required flags) and the
# Python validation + insert logic (types, enum values, reference lookups).
#
# Import order is rigid for tables that have FK dependencies:
#   1-5 have no user-data FKs — import in any order among themselves.
#   6-9 depend on earlier tables — must come after their prerequisites.

TABLE_DEFS: dict[str, dict[str, Any]] = {
    "categories": {
        "label": "Categories",
        "order": 0,
        "requires": [],
        "fields": [
            {"name": "code",          "label": "Code",          "required": True,  "type": "text",    "key": True,  "note": "Must be unique, e.g. DUES, LANDSCAPING"},
            {"name": "name",          "label": "Name",          "required": True,  "type": "text"},
            {"name": "category_type", "label": "Category Type", "required": True,  "type": "enum",    "values": ["INCOME","EXPENSE","TRANSFER"]},
            {"name": "fund_code",     "label": "Fund Code",     "required": False, "type": "enum",    "values": ["OPERATING","RESERVE","SPECIAL"], "note": "Default OPERATING"},
            {"name": "group_name",    "label": "Group",         "required": False, "type": "text"},
            {"name": "sort_order",    "label": "Sort Order",    "required": False, "type": "integer", "note": "Lower numbers appear first; default 0"},
            {"name": "active",        "label": "Active",        "required": False, "type": "boolean", "note": "Yes or No, default Yes"},
            {"name": "description",   "label": "Description",   "required": False, "type": "text"},
        ],
    },
    "owners": {
        "label": "Owners",
        "order": 2,
        "requires": [],
        "fields": [
            {"name": "owner_type",        "label": "Owner Type",          "required": True,  "type": "enum",    "values": ["PERSON","ENTITY","TRUST"]},
            {"name": "display_name",      "label": "Display Name",        "required": True,  "type": "text",    "key": True,  "note": "Must be unique — used to link ownership records"},
            {"name": "first_name",        "label": "First Name",          "required": False, "type": "text"},
            {"name": "last_name",         "label": "Last Name",           "required": False, "type": "text"},
            {"name": "entity_name",       "label": "Entity / Trust Name", "required": False, "type": "text"},
            {"name": "mailing_address_1", "label": "Address Line 1",      "required": False, "type": "text"},
            {"name": "mailing_address_2", "label": "Address Line 2",      "required": False, "type": "text"},
            {"name": "city",              "label": "City",                "required": False, "type": "text"},
            {"name": "state",             "label": "State",               "required": False, "type": "text"},
            {"name": "postal_code",       "label": "Postal Code",         "required": False, "type": "text"},
            {"name": "phone",             "label": "Phone",               "required": False, "type": "text"},
            {"name": "email",             "label": "Email",               "required": False, "type": "text"},
            {"name": "active",            "label": "Active",              "required": False, "type": "boolean", "note": "Yes or No, default Yes"},
            {"name": "notes",             "label": "Notes",               "required": False, "type": "text"},
        ],
    },
    "vendors": {
        "label": "Vendors",
        "order": 3,
        "requires": [],
        "fields": [
            {"name": "vendor_name",  "label": "Vendor Name",    "required": True,  "type": "text", "key": True,  "note": "Must be unique"},
            {"name": "contact_name", "label": "Contact Name",   "required": False, "type": "text"},
            {"name": "email",        "label": "Email",          "required": False, "type": "text"},
            {"name": "phone",        "label": "Phone",          "required": False, "type": "text"},
            {"name": "address_1",    "label": "Address Line 1", "required": False, "type": "text"},
            {"name": "address_2",    "label": "Address Line 2", "required": False, "type": "text"},
            {"name": "city",         "label": "City",           "required": False, "type": "text"},
            {"name": "state",        "label": "State",          "required": False, "type": "text"},
            {"name": "postal_code",  "label": "Postal Code",    "required": False, "type": "text"},
            {"name": "active",       "label": "Active",         "required": False, "type": "boolean", "note": "Yes or No, default Yes"},
            {"name": "notes",        "label": "Notes",          "required": False, "type": "text"},
        ],
    },
    "budgets": {
        "label": "Budgets",
        "order": 4,
        "requires": [],
        "fields": [
            {"name": "fiscal_year", "label": "Fiscal Year", "required": True,  "type": "integer", "key": True,  "note": "Combined with Fund Code — must be unique together"},
            {"name": "fund_code",   "label": "Fund Code",   "required": True,  "type": "enum",    "key": True,  "values": ["OPERATING","RESERVE","SPECIAL"], "note": "Combined with Fiscal Year — must be unique together"},
            {"name": "status",      "label": "Status",      "required": True,  "type": "enum",    "values": ["DRAFT","APPROVED","ARCHIVED"]},
            {"name": "notes",       "label": "Notes",       "required": False, "type": "text"},
        ],
    },
    "lots": {
        "label": "Lots",
        "order": 5,
        "requires": [],
        "fields": [
            {"name": "lot_number",        "label": "Lot Number",     "required": True,  "type": "text", "key": True,  "note": "Must be unique"},
            {"name": "street_address_1",  "label": "Address Line 1", "required": False, "type": "text"},
            {"name": "street_address_2",  "label": "Address Line 2", "required": False, "type": "text"},
            {"name": "city",              "label": "City",           "required": False, "type": "text"},
            {"name": "state",             "label": "State",          "required": False, "type": "text"},
            {"name": "postal_code",       "label": "Postal Code",    "required": False, "type": "text"},
            {"name": "legal_description", "label": "Legal Desc.",    "required": False, "type": "text"},
            {"name": "active",            "label": "Active",         "required": False, "type": "boolean", "note": "Yes or No, default Yes"},
        ],
    },
    "bank_accounts": {
        "label": "Bank Accounts",
        "order": 6,
        "requires": [],
        "fields": [
            {"name": "account_name",     "label": "Account Name",      "required": True,  "type": "text", "key": True,  "note": "Must be unique"},
            {"name": "institution_name", "label": "Bank / Institution", "required": True,  "type": "text"},
            {"name": "account_last4",    "label": "Last 4 Digits",      "required": False, "type": "text"},
            {"name": "account_type",     "label": "Account Type",       "required": True,  "type": "enum",    "values": ["CHECKING","SAVINGS","MONEY_MARKET","OTHER"]},
            {"name": "fund_code",        "label": "Fund Code",          "required": False, "type": "enum",    "values": ["OPERATING","RESERVE","SPECIAL"], "note": "Default OPERATING"},
            {"name": "active",           "label": "Active",             "required": False, "type": "boolean", "note": "Yes or No, default Yes"},
        ],
    },
    "renters": {
        "label": "Renters",
        "order": 8,
        "requires": ["Lots"],
        "fields": [
            {"name": "lot_number",      "label": "Lot Number",     "required": True,  "type": "text",    "note": "Must match an existing lot"},
            {"name": "display_name",    "label": "Display Name",   "required": True,  "type": "text"},
            {"name": "first_name",      "label": "First Name",     "required": False, "type": "text"},
            {"name": "last_name",       "label": "Last Name",      "required": False, "type": "text"},
            {"name": "email",           "label": "Email",          "required": False, "type": "text"},
            {"name": "phone",           "label": "Phone",          "required": False, "type": "text"},
            {"name": "start_date",      "label": "Start Date",     "required": False, "type": "date",    "note": "YYYY-MM-DD"},
            {"name": "end_date",        "label": "End Date",       "required": False, "type": "date",    "note": "YYYY-MM-DD"},
            {"name": "notes",           "label": "Notes",          "required": False, "type": "text"},
        ],
    },
    "lot_ownership": {
        "label": "Lot Ownership History",
        "order": 7,
        "requires": ["Lots", "Owners"],
        "fields": [
            {"name": "lot_number",        "label": "Lot Number",      "required": True,  "type": "text",    "key": True,  "note": "Combined key — must match an existing lot"},
            {"name": "owner_name",        "label": "Owner Name",      "required": True,  "type": "text",    "key": True,  "note": "Combined key — must match owner's display name"},
            {"name": "start_date",        "label": "Start Date",      "required": True,  "type": "date",    "key": True,  "note": "Combined key — YYYY-MM-DD"},
            {"name": "end_date",          "label": "End Date",        "required": False, "type": "date",    "note": "YYYY-MM-DD, blank = current owner"},
        ],
    },
    "board_members": {
        "label": "Board Members",
        "order": 8,
        "requires": [],
        "fields": [
            {"name": "full_name",  "label": "Full Name",  "required": True,  "type": "text"},
            {"name": "title",      "label": "Title",      "required": True,  "type": "text", "note": "e.g. President, Treasurer"},
            {"name": "email",      "label": "Email",      "required": False, "type": "text"},
            {"name": "phone",      "label": "Phone",      "required": False, "type": "text"},
            {"name": "start_date", "label": "Start Date", "required": False, "type": "date"},
            {"name": "end_date",   "label": "End Date",   "required": False, "type": "date"},
            {"name": "active",     "label": "Active",     "required": False, "type": "boolean", "note": "Yes or No, default Yes"},
            {"name": "notes",      "label": "Notes",      "required": False, "type": "text"},
        ],
    },
    "assessment_rules": {
        "label": "Assessment Rules",
        "order": 10,
        "requires": ["Categories"],
        "fields": [
            {"name": "rule_name",            "label": "Rule Name",         "required": True,  "type": "text", "key": True, "note": "Must be unique"},
            {"name": "frequency",            "label": "Frequency",         "required": True,  "type": "enum",    "values": ["ANNUAL","SEMIANNUAL","QUARTERLY","MONTHLY","CUSTOM"]},
            {"name": "default_amount",       "label": "Default Amount",    "required": True,  "type": "decimal"},
            {"name": "category_code",        "label": "Category Code",     "required": False, "type": "text", "note": "Must match an existing category code (e.g. DUES). Defaults to DUES."},
            {"name": "fund_code",            "label": "Fund Code",         "required": False, "type": "enum", "values": ["OPERATING","RESERVE","SPECIAL"], "note": "Default OPERATING"},
            {"name": "effective_start_date", "label": "Effective Start",   "required": True,  "type": "date"},
            {"name": "effective_end_date",   "label": "Effective End",     "required": False, "type": "date"},
            {"name": "active",               "label": "Active",            "required": False, "type": "boolean", "note": "Yes or No, default Yes"},
            {"name": "notes",                "label": "Notes",             "required": False, "type": "text"},
        ],
    },
    "bank_transaction_rules": {
        "label": "Bank Transaction Rules",
        "order": 11,
        "requires": ["Categories", "Bank Accounts", "Vendors", "Lots"],
        "fields": [
            {"name": "rule_name",            "label": "Rule Name",             "required": True,  "type": "text", "key": True, "note": "Must be unique"},
            {"name": "action_type",          "label": "Action Type",           "required": True,  "type": "enum", "values": ["recurring_bill","dues_payment","fee_income","bank_charge","direct_expense","direct_income","homeowner_batch","vendor_bill_match"]},
            {"name": "description_contains", "label": "Description Contains",   "required": False, "type": "text", "note": "Substring to match in bank description"},
            {"name": "match_type",           "label": "Match Type",             "required": False, "type": "text"},
            {"name": "match_memo",           "label": "Match Memo",             "required": False, "type": "text"},
            {"name": "match_amount",         "label": "Match Amount",           "required": False, "type": "text"},
            {"name": "category_code",        "label": "Category Code",          "required": False, "type": "text", "note": "Must match an existing category code"},
            {"name": "vendor_name",          "label": "Vendor Name",            "required": False, "type": "text", "note": "Must match an existing vendor name"},
            {"name": "lot_number",           "label": "Lot Number",             "required": False, "type": "text", "note": "Must match an existing lot"},
            {"name": "bank_account_name",    "label": "Bank Account Name",      "required": False, "type": "text", "note": "Must match an existing bank account name"},
            {"name": "default_memo",         "label": "Default Memo",           "required": False, "type": "text"},
            {"name": "confidence_mode",      "label": "Confidence Mode",        "required": False, "type": "text", "note": "review_first or auto_post; default review_first"},
            {"name": "auto_post_after_n",    "label": "Auto-Post After N",      "required": False, "type": "integer", "note": "Default 3"},
            {"name": "active",               "label": "Active",                 "required": False, "type": "boolean", "note": "Yes or No, default Yes"},
        ],
    },
    "opening_balances": {
        "label": "Opening Balances",
        "order": 12,
        "requires": ["Bank Accounts", "Lots"],
        "fields": [
            {"name": "as_of_date",     "label": "As Of Date",     "required": True,  "type": "date", "key": True, "note": "YYYY-MM-DD"},
            {"name": "entity_type",    "label": "Entity Type",    "required": True,  "type": "enum", "key": True,
             "values": ["BANK_ACCOUNT", "LOT_DUES", "LOT_ASSESSMENT"],
             "note": "BANK_ACCOUNT = cash on hand; LOT_DUES / LOT_ASSESSMENT = owner balance on a lot"},
            {"name": "entity_key",     "label": "Entity Key",     "required": True,  "type": "text", "key": True,
             "note": "Bank Account name for BANK_ACCOUNT; Lot # for LOT_DUES / LOT_ASSESSMENT"},
            {"name": "amount",         "label": "Amount",         "required": True,  "type": "decimal"},
        ],
    },
    "budget_lines": {
        "label": "Budget Lines",
        "order": 9,
        "requires": ["Budgets", "Categories"],
        "fields": [
            {"name": "fiscal_year",    "label": "Fiscal Year",   "required": True, "type": "integer", "key": True,  "note": "Combined key"},
            {"name": "fund_code",      "label": "Fund Code",     "required": True, "type": "enum",    "key": True,  "values": ["OPERATING","RESERVE","SPECIAL"], "note": "Combined key"},
            {"name": "category_code",  "label": "Category Code", "required": True, "type": "text",    "key": True,  "note": "Combined key — must match an existing category code"},
            {"name": "fiscal_period",  "label": "Fiscal Period", "required": True, "type": "integer", "key": True,  "note": "Combined key — 1–12"},
            {"name": "budget_amount",  "label": "Budget Amount", "required": True, "type": "decimal"},
        ],
    },
    "deposit_batches": {
        "label": "Deposit Batches",
        "order": 14,
        "requires": ["Bank Accounts"],
        "fields": [
            {"name": "deposit_date",       "label": "Deposit Date",     "required": True,  "type": "date",    "key": True, "note": "YYYY-MM-DD"},
            {"name": "bank_account_name",  "label": "Bank Account",     "required": True,  "type": "text",    "key": True, "note": "Must match an existing bank account name"},
            {"name": "total_amount",       "label": "Total Amount",     "required": True,  "type": "decimal", "key": True},
            {"name": "category_code",      "label": "Category Code",    "required": False, "type": "text",    "note": "Optional — must match an existing category code"},
            {"name": "notes",              "label": "Notes",            "required": False, "type": "text"},
        ],
    },
    "assessments": {
        "label": "Assessments / Charges",
        "order": 15,
        "requires": ["Lots", "Owners", "Categories"],
        "fields": [
            {"name": "lot_number",         "label": "Lot Number",       "required": True,  "type": "text",    "key": True, "note": "Must match an existing lot"},
            {"name": "owner_name",         "label": "Owner Name",       "required": True,  "type": "text",    "key": True, "note": "Must match an existing owner display name"},
            {"name": "charge_type",        "label": "Charge Type",      "required": True,  "type": "enum",    "values": ["DUES","LATE_FEE","RESALE_FEE","SPECIAL","OTHER"]},
            {"name": "assessment_date",    "label": "Assessment Date",  "required": True,  "type": "date",    "key": True, "note": "YYYY-MM-DD"},
            {"name": "due_date",           "label": "Due Date",         "required": True,  "type": "date"},
            {"name": "amount",             "label": "Amount",           "required": True,  "type": "decimal"},
            {"name": "category_code",      "label": "Category Code",    "required": False, "type": "text"},
            {"name": "status",             "label": "Status",           "required": False, "type": "enum",    "values": ["OPEN","PAID","PARTIAL","VOID","WRITTEN_OFF"], "note": "Default OPEN"},
            {"name": "description",        "label": "Description",      "required": False, "type": "text"},
        ],
    },
    "payments": {
        "label": "Payments Received",
        "order": 16,
        "requires": ["Owners", "Bank Accounts"],
        "fields": [
            {"name": "receipt_number",     "label": "Receipt Number",   "required": True,  "type": "text",    "key": True, "note": "Must be unique"},
            {"name": "owner_name",         "label": "Owner Name",       "required": True,  "type": "text",    "note": "Must match an existing owner display name"},
            {"name": "payment_date",       "label": "Payment Date",     "required": True,  "type": "date"},
            {"name": "amount",             "label": "Amount",           "required": True,  "type": "decimal"},
            {"name": "payment_method",     "label": "Payment Method",   "required": True,  "type": "enum",    "values": ["CHECK","CASH","ACH","CREDIT_CARD","OTHER"]},
            {"name": "reference_number",   "label": "Reference Number", "required": False, "type": "text"},
            {"name": "bank_account_name",  "label": "Bank Account",     "required": True,  "type": "text",    "note": "Must match an existing bank account name"},
            {"name": "category_code",      "label": "Category Code",    "required": False, "type": "text"},
            {"name": "notes",              "label": "Notes",            "required": False, "type": "text"},
        ],
    },
    "vendor_bills": {
        "label": "Vendor Bills",
        "order": 17,
        "requires": ["Vendors", "Categories"],
        "fields": [
            {"name": "vendor_name",        "label": "Vendor Name",      "required": True,  "type": "text",    "key": True, "note": "Must match an existing vendor"},
            {"name": "invoice_number",     "label": "Invoice Number",   "required": True,  "type": "text",    "key": True, "note": "Unique per vendor"},
            {"name": "invoice_date",       "label": "Invoice Date",     "required": True,  "type": "date"},
            {"name": "due_date",           "label": "Due Date",         "required": False, "type": "date"},
            {"name": "amount",             "label": "Amount",           "required": True,  "type": "decimal"},
            {"name": "fund_code",          "label": "Fund Code",        "required": False, "type": "enum",    "values": ["OPERATING","RESERVE","SPECIAL"], "note": "Default OPERATING"},
            {"name": "category_code",      "label": "Category Code",    "required": True,  "type": "text",    "note": "Must match an existing category code"},
            {"name": "status",             "label": "Status",           "required": False, "type": "enum",    "values": ["OPEN","PAID","VOID"], "note": "Default OPEN"},
            {"name": "description",        "label": "Description",      "required": False, "type": "text"},
        ],
    },
    "bill_payments": {
        "label": "Bill Payments",
        "order": 18,
        "requires": ["Vendor Bills", "Bank Accounts"],
        "fields": [
            {"name": "vendor_name",        "label": "Vendor Name",      "required": True,  "type": "text",    "key": True, "note": "Combined key with invoice number"},
            {"name": "invoice_number",     "label": "Invoice Number",   "required": True,  "type": "text",    "key": True, "note": "Bill must already exist"},
            {"name": "payment_date",       "label": "Payment Date",     "required": True,  "type": "date"},
            {"name": "amount",             "label": "Amount",           "required": True,  "type": "decimal"},
            {"name": "bank_account_name",  "label": "Bank Account",     "required": True,  "type": "text",    "note": "Must match an existing bank account name"},
            {"name": "check_number",       "label": "Check Number",     "required": False, "type": "text"},
            {"name": "notes",              "label": "Notes",            "required": False, "type": "text"},
        ],
    },
    "non_dues_income": {
        "label": "Non-Dues Income",
        "order": 19,
        "requires": ["Bank Accounts", "Categories"],
        "fields": [
            {"name": "posting_date",       "label": "Posting Date",     "required": True,  "type": "date",    "key": True},
            {"name": "bank_account_name",  "label": "Bank Account",     "required": True,  "type": "text",    "key": True, "note": "Must match an existing bank account name"},
            {"name": "category_code",      "label": "Category Code",    "required": False, "type": "text",    "note": "Optional"},
            {"name": "income_description", "label": "Description",      "required": True,  "type": "text",    "key": True},
            {"name": "total_amount",       "label": "Total Amount",     "required": True,  "type": "decimal"},
            {"name": "notes",              "label": "Notes",            "required": False, "type": "text"},
        ],
    },
    "reserve_transfers": {
        "label": "Reserve Transfers",
        "order": 20,
        "requires": ["Bank Accounts"],
        "fields": [
            {"name": "transfer_date",        "label": "Transfer Date",      "required": True,  "type": "date",    "key": True},
            {"name": "from_bank_account",    "label": "From Bank Account",  "required": True,  "type": "text",    "key": True, "note": "Must match an existing bank account name"},
            {"name": "to_bank_account",      "label": "To Bank Account",    "required": True,  "type": "text",    "key": True, "note": "Must match an existing bank account name"},
            {"name": "amount",               "label": "Amount",             "required": True,  "type": "decimal"},
            {"name": "transfer_type",        "label": "Transfer Type",      "required": False, "type": "text",    "note": "e.g. CONTRIBUTION, FUNDING, OTHER"},
            {"name": "purpose",              "label": "Purpose",            "required": False, "type": "text"},
            {"name": "notes",                "label": "Notes",              "required": False, "type": "text"},
        ],
    },
}


# ── CSV parsing ───────────────────────────────────────────────────────────────

def _parse_csv(content: str) -> tuple[list[str], list[list[str]]]:
    """
    Parse CSV content, accepting both:
      • Standard quoted CSV (Excel, Google Sheets, etc.)
      • Our &#x2C;-encoded format (exported by this app)
    Returns (headers, data_rows).
    """
    reader = csv.reader(io.StringIO(content.strip()))
    all_rows = list(reader)
    if not all_rows:
        return [], []
    headers = [h.strip().replace("&#x2C;", ",") for h in all_rows[0]]
    data_rows = [
        [cell.replace("&#x2C;", ",") for cell in row]
        for row in all_rows[1:]
        if any(cell.strip() for cell in row)   # skip blank lines
    ]
    return headers, data_rows


# ── Value coercion helpers ────────────────────────────────────────────────────

def _parse_bool(v: str, default: int = 1) -> int:
    s = v.strip().lower()
    if s in {"yes", "y", "true", "1"}:
        return 1
    if s in {"no", "n", "false", "0"}:
        return 0
    return default


# ── Response types ────────────────────────────────────────────────────────────

@dataclass
class ImportPageResponse:
    status_code: int
    body_html: str


# ── Page service ──────────────────────────────────────────────────────────────

class ImportPages:
    TEMPLATE        = "import.html"
    RESULT_TEMPLATE = "import_result.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ── GET ──────────────────────────────────────────────────────────────

    def render_page(
        self,
        *,
        org: dict[str, Any] | None,
        theme: str,
        error_message: str = "",
        prefill_type: str = "",
        stash_token: str = "",
        bank_account_id: int | None = None,
        note: str = "",
    ) -> ImportPageResponse:
        # Expose a virtual ``bank_statement_csv`` target so the existing
        # wizard can be reused for mapping bank CSVs onto canonical ingest
        # fields. The entry is built lazily here (instead of living in
        # TABLE_DEFS permanently) because its submit path doesn't insert
        # rows — it saves a column map and re-runs ingest.
        from hoa_accounting.web.bank_ingest import (
            CANONICAL_CSV_FIELDS, peek_stash,
        )
        defs = dict(TABLE_DEFS)
        defs["bank_statement_csv"] = {
            "label":    "Bank Statement (CSV)",
            "order":    99,
            "requires": [],
            "fields":   CANONICAL_CSV_FIELDS,
            "save_only": True,
            "submit_url": "/bank-import/save-mapping",
        }

        # If the caller handed us a stash token, pre-load its CSV so the
        # wizard opens on step 2 with the headers already visible.
        prefill_csv = ""
        prefill_filename = ""
        if stash_token:
            row = peek_stash(self.conn, stash_token)
            if row is not None:
                _, prefill_filename, content = row
                prefill_csv = content.decode("utf-8-sig", errors="replace")

        ordered = sorted(defs.items(), key=lambda kv: kv[1]["order"])
        ctx = {
            "heading":         "Import Data",
            "breadcrumb":      "System",
            "org":             org or {},
            "theme":           theme,
            "page_key":        "import",
            "table_defs_json": json.dumps(defs),
            "import_order":    [(k, v) for k, v in ordered],
            "error_message":   error_message,
            "prefill_type":    prefill_type,
            "stash_token":     stash_token,
            "bank_account_id": bank_account_id or "",
            "prefill_csv":     prefill_csv,
            "prefill_filename": prefill_filename,
            "note":            note,
        }
        return ImportPageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.TEMPLATE, ctx),
        )

    # ── POST: run import ─────────────────────────────────────────────────

    def handle_run(
        self,
        *,
        data_type: str,
        mapping_json: str,
        csv_content: str,
        file_name: str,
        org: dict[str, Any] | None,
        theme: str,
    ) -> ImportPageResponse:
        if data_type not in TABLE_DEFS:
            return self.render_page(org=org, theme=theme,
                                    error_message=f"Unknown data type '{data_type}'.")

        try:
            mapping: dict[str, str] = json.loads(mapping_json)
        except Exception:
            return self.render_page(org=org, theme=theme,
                                    error_message="Could not read field mapping.")

        csv_headers, csv_rows = _parse_csv(csv_content)
        if not csv_rows:
            return self.render_page(org=org, theme=theme,
                                    error_message="The file contains no data rows.")

        table_def = TABLE_DEFS[data_type]
        imported  = 0
        error_rows: list[dict[str, Any]] = []

        for row_num, csv_row in enumerate(csv_rows, start=2):
            # Build {csvColumn: value} from the raw row
            raw: dict[str, str] = {
                csv_headers[j]: (csv_row[j] if j < len(csv_row) else "")
                for j in range(len(csv_headers))
            }
            # Translate via mapping to {tableField: value}
            table_row: dict[str, str] = {
                tf: raw.get(csv_col, "")
                for tf, csv_col in mapping.items()
            }

            # Validate (no DB)
            errs = self._validate_row(table_def, table_row)

            # Insert (with savepoint so prior rows stay committed)
            if not errs:
                errs = self._insert_row(data_type, table_row)

            if errs:
                error_rows.append({"row": row_num, "errors": errs})
            else:
                imported += 1

        # Commit all successfully inserted rows to the database.
        if imported:
            self.conn.commit()

        ctx = {
            "heading":         "Import Results",
            "breadcrumb":      "System",
            "org":             org or {},
            "theme":           theme,
            "page_key":        "import",
            "data_type_label": table_def["label"],
            "file_name":       file_name,
            "checked_at":      datetime.now().strftime("%-I:%M:%S %p on %b %-d, %Y"),
            "imported":        imported,
            "failed":          len(error_rows),
            "total":           imported + len(error_rows),
            "error_rows":      error_rows,
        }
        return ImportPageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.RESULT_TEMPLATE, ctx),
        )

    # ── Validate-only (dry run) ──────────────────────────────────────

    def handle_validate(
        self,
        *,
        data_type: str,
        mapping_json: str,
        csv_content: str,
        filter_field: str = "",   # empty = all fields; non-empty = only check this column
    ) -> dict[str, Any]:
        """
        Validate without inserting.  Returns a dict for JSON serialization.

        filter_field — when set to a table field name, only rows where that
        mapped column has an issue are returned.  Use "" for a full-file check.

        Note: each row is checked independently against the current DB state.
        Duplicates *within* the file (row A and row B share the same key) will
        not be flagged here — they are caught at import time when the second
        row fails to insert.
        """
        if data_type not in TABLE_DEFS:
            return {"error": f"Unknown data type '{data_type}'."}
        try:
            mapping: dict[str, str] = json.loads(mapping_json)
        except Exception:
            return {"error": "Could not read field mapping."}

        csv_headers, csv_rows = _parse_csv(csv_content)
        if not csv_rows:
            return {"total": 0, "ok_count": 0, "error_count": 0, "errors": []}

        table_def = TABLE_DEFS[data_type]
        ok_count  = 0
        error_rows: list[dict[str, Any]] = []

        for row_num, csv_row in enumerate(csv_rows, start=2):
            raw: dict[str, str] = {
                csv_headers[j]: (csv_row[j] if j < len(csv_row) else "")
                for j in range(len(csv_headers))
            }
            table_row: dict[str, str] = {
                tf: raw.get(csv_col, "")
                for tf, csv_col in mapping.items()
            }

            # Format validation (no DB)
            errs = self._validate_row(table_def, table_row)

            # DB validation — always rolled back
            if not errs:
                errs = self._check_row_db(data_type, table_row)

            # If filtering to a specific mapped column, keep only errors that
            # involve that field (heuristic: error text contains the field label)
            if filter_field and errs:
                field_label = next(
                    (f["label"] for f in table_def["fields"] if f["name"] == filter_field),
                    filter_field,
                )
                errs = [e for e in errs if filter_field in e or field_label in e]

            if errs:
                error_rows.append({
                    "row": row_num,
                    "errors": errs,
                    "value": table_row.get(filter_field, "") if filter_field else "",
                })
            else:
                ok_count += 1

        return {
            "total":       len(csv_rows),
            "ok_count":    ok_count,
            "error_count": len(error_rows),
            "errors":      error_rows,
        }

    def _check_row_db(self, data_type: str, row: dict[str, Any]) -> list[str]:
        """
        Run the insert logic inside a savepoint that is always rolled back.
        Returns the same errors _insert_X would produce, without persisting anything.
        """
        method = getattr(self, f"_insert_{data_type}", None)
        if method is None:
            return []
        try:
            self.conn.execute("SAVEPOINT chk_row")
            errs = method(row)
            self.conn.execute("ROLLBACK TO SAVEPOINT chk_row")
            return errs  # type: ignore[no-any-return]
        except sqlite3.IntegrityError as e:
            try:
                self.conn.execute("ROLLBACK TO SAVEPOINT chk_row")
            except Exception:
                pass
            msg = str(e)
            if "UNIQUE constraint" in msg:
                return ["A record with this key already exists (duplicate)."]
            if "FOREIGN KEY constraint" in msg:
                return ["A referenced record does not exist (foreign key error)."]
            return [f"Data integrity error: {msg}"]
        except Exception as e:
            try:
                self.conn.execute("ROLLBACK TO SAVEPOINT chk_row")
            except Exception:
                pass
            return [f"Unexpected error: {e}"]

    # ── Validation ───────────────────────────────────────────────────────

    def _validate_row(self, table_def: dict[str, Any], row: dict[str, str]) -> list[str]:
        errs: list[str] = []
        for field in table_def["fields"]:
            name = field["name"]
            val  = row.get(name, "").strip()
            if not val:
                if field["required"]:
                    errs.append(f"'{field['label']}' is required but empty.")
                continue
            ftype = field.get("type", "text")
            if ftype == "enum":
                valid_upper = [v.upper() for v in field.get("values", [])]
                if val.upper() not in valid_upper:
                    errs.append(
                        f"'{field['label']}': \"{val}\" is not valid. "
                        f"Allowed: {', '.join(field['values'])}"
                    )
            elif ftype == "integer":
                try:
                    int(val)
                except ValueError:
                    errs.append(f"'{field['label']}': \"{val}\" must be a whole number.")
            elif ftype == "decimal":
                try:
                    Decimal(val)
                except (InvalidOperation, ValueError):
                    errs.append(f"'{field['label']}': \"{val}\" must be a number.")
            elif ftype == "date":
                try:
                    datetime.strptime(val, "%Y-%m-%d")
                except ValueError:
                    errs.append(
                        f"'{field['label']}': \"{val}\" must be in YYYY-MM-DD format."
                    )
        return errs

    # ── Insert dispatcher ────────────────────────────────────────────────

    def _insert_row(self, data_type: str, row: dict[str, str]) -> list[str]:
        method = getattr(self, f"_insert_{data_type}", None)
        if method is None:
            return [f"No insert handler for '{data_type}'."]
        try:
            self.conn.execute("SAVEPOINT import_row")
            errs = method(row)
            if errs:
                self.conn.execute("ROLLBACK TO SAVEPOINT import_row")
            else:
                self.conn.execute("RELEASE SAVEPOINT import_row")
            return errs  # type: ignore[no-any-return]
        except sqlite3.IntegrityError as e:
            self.conn.execute("ROLLBACK TO SAVEPOINT import_row")
            msg = str(e)
            if "UNIQUE constraint" in msg:
                return ["A record with this key already exists (duplicate)."]
            if "FOREIGN KEY constraint" in msg:
                return ["A referenced record does not exist (foreign key error)."]
            return [f"Data integrity error: {msg}"]
        except Exception as e:
            self.conn.execute("ROLLBACK TO SAVEPOINT import_row")
            return [f"Unexpected error: {e}"]

    # ── Convenience helpers ──────────────────────────────────────────────

    def _v(self, row: dict[str, Any], name: str, default: Any = None) -> Any:
        v = row.get(name, "").strip()
        return v if v else default

    def _bool(self, row: dict[str, Any], name: str, default: int = 1) -> int:
        v = row.get(name, "").strip()
        return _parse_bool(v, default) if v else default

    # ── Per-type insert methods ──────────────────────────────────────────

    def _insert_categories(self, row: dict[str, Any]) -> list[str]:
        code = self._v(row, "code", "").upper()
        if not code:
            return ["Code is required."]
        if self.conn.execute(
            "SELECT 1 FROM categories WHERE code=?", (code,)
        ).fetchone():
            return [f"Category code \"{code}\" already exists."]
        ct = self._v(row, "category_type", "").upper()
        fund = self._v(row, "fund_code", "OPERATING").upper() or "OPERATING"
        try:
            sort_order = int(self._v(row, "sort_order", "0") or "0")
        except ValueError:
            sort_order = 0
        self.conn.execute(
            """INSERT INTO categories
               (code, name, category_type, fund_code, group_name,
                sort_order, active_flag, description)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                code,
                self._v(row, "name"),
                ct,
                fund,
                self._v(row, "group_name"),
                sort_order,
                self._bool(row, "active", 1),
                self._v(row, "description"),
            ),
        )
        return []

    def _insert_owners(self, row: dict[str, Any]) -> list[str]:
        dn = self._v(row, "display_name")
        if self.conn.execute(
            "SELECT 1 FROM owners WHERE display_name=?", (dn,)
        ).fetchone():
            return [f"Owner \"{dn}\" already exists."]
        self.conn.execute(
            """INSERT INTO owners
               (owner_type, display_name, first_name, last_name, entity_name,
                mailing_address_1, mailing_address_2, city, state, postal_code,
                phone, email, active_flag, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                self._v(row, "owner_type", "").upper(),
                dn,
                self._v(row, "first_name"),
                self._v(row, "last_name"),
                self._v(row, "entity_name"),
                self._v(row, "mailing_address_1"),
                self._v(row, "mailing_address_2"),
                self._v(row, "city"),
                self._v(row, "state"),
                self._v(row, "postal_code"),
                self._v(row, "phone"),
                self._v(row, "email"),
                self._bool(row, "active", 1),
                self._v(row, "notes"),
            ),
        )
        return []

    def _insert_vendors(self, row: dict[str, Any]) -> list[str]:
        vn = self._v(row, "vendor_name")
        if self.conn.execute(
            "SELECT 1 FROM vendors WHERE vendor_name=?", (vn,)
        ).fetchone():
            return [f"Vendor \"{vn}\" already exists."]
        self.conn.execute(
            """INSERT INTO vendors
               (vendor_name, contact_name, email, phone,
                address_1, address_2, city, state, postal_code,
                active_flag, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                vn,
                self._v(row, "contact_name"),
                self._v(row, "email"),
                self._v(row, "phone"),
                self._v(row, "address_1"),
                self._v(row, "address_2"),
                self._v(row, "city"),
                self._v(row, "state"),
                self._v(row, "postal_code"),
                self._bool(row, "active", 1),
                self._v(row, "notes"),
            ),
        )
        return []

    def _insert_budgets(self, row: dict[str, Any]) -> list[str]:
        fy = int(self._v(row, "fiscal_year", 0))
        fc = self._v(row, "fund_code", "").upper()
        if self.conn.execute(
            "SELECT 1 FROM budgets WHERE fiscal_year=? AND fund_code=?", (fy, fc)
        ).fetchone():
            return [f"Budget {fy} / {fc} already exists."]
        self.conn.execute(
            "INSERT INTO budgets (fiscal_year, fund_code, status, notes) VALUES (?,?,?,?)",
            (fy, fc, self._v(row, "status", "DRAFT").upper(), self._v(row, "notes")),
        )
        return []

    def _insert_lots(self, row: dict[str, Any]) -> list[str]:
        ln = self._v(row, "lot_number")
        if self.conn.execute(
            "SELECT 1 FROM lots WHERE lot_number=?", (ln,)
        ).fetchone():
            return [f"Lot \"{ln}\" already exists."]
        self.conn.execute(
            """INSERT INTO lots
               (lot_number, street_address_1, street_address_2,
                city, state, postal_code, legal_description, active_flag)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                ln,
                self._v(row, "street_address_1"),
                self._v(row, "street_address_2"),
                self._v(row, "city"),
                self._v(row, "state"),
                self._v(row, "postal_code"),
                self._v(row, "legal_description"),
                self._bool(row, "active", 1),
            ),
        )
        return []

    def _insert_bank_accounts(self, row: dict[str, Any]) -> list[str]:
        an = self._v(row, "account_name")
        if self.conn.execute(
            "SELECT 1 FROM bank_accounts WHERE account_name=?", (an,)
        ).fetchone():
            return [f'Bank account "{an}" already exists.']
        fund = (self._v(row, "fund_code", "OPERATING") or "OPERATING").upper()
        if fund not in ("OPERATING", "RESERVE", "SPECIAL"):
            fund = "OPERATING"
        self.conn.execute(
            """INSERT INTO bank_accounts
               (account_name, institution_name, account_last4, account_type,
                fund_code, active_flag)
               VALUES (?,?,?,?,?,?)""",
            (
                an,
                self._v(row, "institution_name"),
                self._v(row, "account_last4"),
                self._v(row, "account_type", "").upper(),
                fund,
                self._bool(row, "active", 1),
            ),
        )
        return []

    def _insert_lot_ownership(self, row: dict[str, Any]) -> list[str]:
        lot_num = self._v(row, "lot_number")
        lot_row = self.conn.execute(
            "SELECT id FROM lots WHERE lot_number=?", (lot_num,)
        ).fetchone()
        if not lot_row:
            return [f"Lot \"{lot_num}\" not found. Import Lots first."]

        owner_name = self._v(row, "owner_name")
        owner_row  = self.conn.execute(
            "SELECT id FROM owners WHERE display_name=?", (owner_name,)
        ).fetchone()
        if not owner_row:
            return [f"Owner \"{owner_name}\" not found. Import Owners first."]

        sd = self._v(row, "start_date")
        if self.conn.execute(
            "SELECT 1 FROM lot_ownership WHERE lot_id=? AND owner_id=? AND start_date=?",
            (lot_row[0], owner_row[0], sd),
        ).fetchone():
            return ["This lot / owner / start-date combination already exists."]

        self.conn.execute(
            """INSERT INTO lot_ownership
               (lot_id, owner_id, start_date, end_date)
               VALUES (?,?,?,?)""",
            (
                lot_row[0],
                owner_row[0],
                sd,
                self._v(row, "end_date") or None,
            ),
        )
        return []

    def _insert_renters(self, row: dict[str, Any]) -> list[str]:
        lot_num = self._v(row, "lot_number")
        lot_row = self.conn.execute(
            "SELECT id FROM lots WHERE lot_number=?", (lot_num,)
        ).fetchone()
        if not lot_row:
            return [f'Lot "{lot_num}" not found. Import Lots first.']
        self.conn.execute(
            """INSERT INTO lot_renters
               (lot_id, display_name, first_name, last_name,
                email, phone, start_date, end_date, notes)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                lot_row[0],
                self._v(row, "display_name"),
                self._v(row, "first_name"),
                self._v(row, "last_name"),
                self._v(row, "email"),
                self._v(row, "phone"),
                self._v(row, "start_date") or None,
                self._v(row, "end_date") or None,
                self._v(row, "notes"),
            ),
        )
        return []

    def _insert_budget_lines(self, row: dict[str, Any]) -> list[str]:
        fy = int(self._v(row, "fiscal_year", 0))
        fc = self._v(row, "fund_code", "").upper()
        budget_row = self.conn.execute(
            "SELECT id FROM budgets WHERE fiscal_year=? AND fund_code=?", (fy, fc)
        ).fetchone()
        if not budget_row:
            return [f"Budget {fy} / {fc} not found. Import Budgets first."]

        cat_code = self._v(row, "category_code", "").upper()
        cat_row = self.conn.execute(
            "SELECT id FROM categories WHERE UPPER(code)=?", (cat_code,)
        ).fetchone()
        if not cat_row:
            return [f'Category "{cat_code}" not found. Import Categories first.']

        period = int(self._v(row, "fiscal_period", 0))
        if not 1 <= period <= 12:
            return [f"Fiscal period must be 1–12 (got {period})."]

        if self.conn.execute(
            "SELECT 1 FROM budget_lines "
            "WHERE budget_id=? AND category_id=? AND fiscal_period=?",
            (budget_row[0], cat_row[0], period),
        ).fetchone():
            return ["This budget / category / period combination already exists."]

        self.conn.execute(
            """INSERT INTO budget_lines (budget_id, category_id, fiscal_period, budget_amount)
               VALUES (?,?,?,?)""",
            (
                budget_row[0],
                cat_row[0],
                period,
                Decimal(str(self._v(row, "budget_amount", "0"))),
            ),
        )
        return []


    # ── Transactional imports (mid-year migration) ─────────────────────

    def _lookup(self, table: str, key_col: str, value: str, label: str | None = None) -> Any:
        if not value:
            return None, [f'{label or key_col} is required.']
        row = self.conn.execute(
            f"SELECT id FROM {table} WHERE {key_col}=?", (value,)
        ).fetchone()
        if not row:
            return None, [f'{label or key_col} "{value}" not found.']
        return int(row[0]), []

    def _insert_deposit_batches(self, row: dict[str, Any]) -> list[str]:
        bank_id, errs = self._lookup("bank_accounts", "account_name",
                                     self._v(row, "bank_account_name"), "Bank account")
        if errs:
            return errs  # type: ignore[no-any-return]
        cat_code = (self._v(row, "category_code", "") or "").upper()
        cat_id = None
        if cat_code:
            cid, e = self._lookup("categories", "UPPER(code)", cat_code, "Category")
            if e:
                return e  # type: ignore[no-any-return]
            cat_id = cid
        try:
            total = Decimal(self._v(row, "total_amount", "0"))
        except (InvalidOperation, ValueError):
            return ["Total amount must be a number."]
        deposit_date = self._v(row, "deposit_date")
        if self.conn.execute(
            """SELECT 1 FROM deposit_batches
                WHERE deposit_date=? AND bank_account_id=? AND total_amount=?""",
            (deposit_date, bank_id, str(total)),
        ).fetchone():
            return ["A deposit with this date / bank / amount already exists."]
        self.conn.execute(
            """INSERT INTO deposit_batches
               (deposit_date, bank_account_id, total_amount, category_id, notes)
               VALUES (?,?,?,?,?)""",
            (deposit_date, bank_id, str(total), cat_id, self._v(row, "notes")),
        )
        return []

    def _insert_assessments(self, row: dict[str, Any]) -> list[str]:
        lot_id, errs = self._lookup("lots", "lot_number",
                                    self._v(row, "lot_number"), "Lot")
        if errs:
            return errs  # type: ignore[no-any-return]
        owner_id, errs = self._lookup("owners", "display_name",
                                      self._v(row, "owner_name"), "Owner")
        if errs:
            return errs  # type: ignore[no-any-return]
        cat_id = None
        cat_code = (self._v(row, "category_code", "") or "").upper()
        if cat_code:
            cid, e = self._lookup("categories", "UPPER(code)", cat_code, "Category")
            if e:
                return e  # type: ignore[no-any-return]
            cat_id = cid
        try:
            amt = Decimal(self._v(row, "amount", "0"))
        except (InvalidOperation, ValueError):
            return ["Amount must be a number."]
        charge_type = (self._v(row, "charge_type", "") or "").upper()
        assessment_date = self._v(row, "assessment_date")
        due_date = self._v(row, "due_date")
        status = (self._v(row, "status", "OPEN") or "OPEN").upper()
        if self.conn.execute(
            """SELECT 1 FROM assessments
                WHERE lot_id=? AND owner_id=? AND charge_type=?
                  AND assessment_date=? AND amount=?""",
            (lot_id, owner_id, charge_type, assessment_date, str(amt)),
        ).fetchone():
            return ["This lot / owner / charge_type / date / amount already exists."]
        self.conn.execute(
            """INSERT INTO assessments
               (lot_id, owner_id, charge_type, assessment_date, due_date,
                amount, status, category_id, description)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (lot_id, owner_id, charge_type, assessment_date, due_date,
             str(amt), status, cat_id, self._v(row, "description")),
        )
        return []

    def _insert_payments(self, row: dict[str, Any]) -> list[str]:
        receipt = self._v(row, "receipt_number")
        if not receipt:
            return ["Receipt Number is required."]
        if self.conn.execute(
            "SELECT 1 FROM payments WHERE receipt_number=?", (receipt,)
        ).fetchone():
            return [f'Receipt "{receipt}" already exists.']
        owner_id, errs = self._lookup("owners", "display_name",
                                      self._v(row, "owner_name"), "Owner")
        if errs:
            return errs  # type: ignore[no-any-return]
        bank_id, errs = self._lookup("bank_accounts", "account_name",
                                     self._v(row, "bank_account_name"), "Bank account")
        if errs:
            return errs  # type: ignore[no-any-return]
        cat_id = None
        cat_code = (self._v(row, "category_code", "") or "").upper()
        if cat_code:
            cid, e = self._lookup("categories", "UPPER(code)", cat_code, "Category")
            if e:
                return e  # type: ignore[no-any-return]
            cat_id = cid
        try:
            amt = Decimal(self._v(row, "amount", "0"))
        except (InvalidOperation, ValueError):
            return ["Amount must be a number."]
        method = (self._v(row, "payment_method", "") or "").upper()
        self.conn.execute(
            """INSERT INTO payments
               (receipt_number, owner_id, payment_date, amount, payment_method,
                reference_number, bank_account_id, category_id, notes)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (receipt, owner_id, self._v(row, "payment_date"), str(amt), method,
             self._v(row, "reference_number"), bank_id, cat_id,
             self._v(row, "notes")),
        )
        return []

    def _insert_vendor_bills(self, row: dict[str, Any]) -> list[str]:
        vendor_id, errs = self._lookup("vendors", "vendor_name",
                                       self._v(row, "vendor_name"), "Vendor")
        if errs:
            return errs  # type: ignore[no-any-return]
        cat_id, errs = self._lookup("categories", "UPPER(code)",
                                    (self._v(row, "category_code", "") or "").upper(),
                                    "Category")
        if errs:
            return errs  # type: ignore[no-any-return]
        invoice = self._v(row, "invoice_number")
        if self.conn.execute(
            "SELECT 1 FROM vendor_bills WHERE vendor_id=? AND invoice_number=?",
            (vendor_id, invoice),
        ).fetchone():
            return [f'Invoice "{invoice}" already exists for this vendor.']
        try:
            amt = Decimal(self._v(row, "amount", "0"))
        except (InvalidOperation, ValueError):
            return ["Amount must be a number."]
        fund = (self._v(row, "fund_code", "OPERATING") or "OPERATING").upper()
        if fund not in ("OPERATING", "RESERVE", "SPECIAL"):
            fund = "OPERATING"
        status = (self._v(row, "status", "OPEN") or "OPEN").upper()
        self.conn.execute(
            """INSERT INTO vendor_bills
               (vendor_id, invoice_number, invoice_date, due_date, amount,
                fund_code, status, description, category_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (vendor_id, invoice, self._v(row, "invoice_date"),
             self._v(row, "due_date") or None, str(amt), fund, status,
             self._v(row, "description"), cat_id),
        )
        return []

    def _insert_bill_payments(self, row: dict[str, Any]) -> list[str]:
        vn = self._v(row, "vendor_name")
        inv = self._v(row, "invoice_number")
        bill = self.conn.execute(
            """SELECT vb.id FROM vendor_bills vb
                JOIN vendors v ON v.id = vb.vendor_id
                WHERE v.vendor_name=? AND vb.invoice_number=?""",
            (vn, inv),
        ).fetchone()
        if not bill:
            return [f'Bill "{inv}" for vendor "{vn}" not found.']
        bank_id, errs = self._lookup("bank_accounts", "account_name",
                                     self._v(row, "bank_account_name"), "Bank account")
        if errs:
            return errs  # type: ignore[no-any-return]
        try:
            amt = Decimal(self._v(row, "amount", "0"))
        except (InvalidOperation, ValueError):
            return ["Amount must be a number."]
        if self.conn.execute(
            """SELECT 1 FROM bill_payments
                WHERE vendor_bill_id=? AND payment_date=? AND amount=?""",
            (int(bill[0]), self._v(row, "payment_date"), str(amt)),
        ).fetchone():
            return ["A payment for this bill / date / amount already exists."]
        self.conn.execute(
            """INSERT INTO bill_payments
               (vendor_bill_id, payment_date, amount, bank_account_id,
                check_number, notes)
               VALUES (?,?,?,?,?,?)""",
            (int(bill[0]), self._v(row, "payment_date"), str(amt), bank_id,
             self._v(row, "check_number"), self._v(row, "notes")),
        )
        return []

    def _insert_non_dues_income(self, row: dict[str, Any]) -> list[str]:
        bank_id, errs = self._lookup("bank_accounts", "account_name",
                                     self._v(row, "bank_account_name"), "Bank account")
        if errs:
            return errs  # type: ignore[no-any-return]
        cat_id = None
        cat_code = (self._v(row, "category_code", "") or "").upper()
        if cat_code:
            cid, e = self._lookup("categories", "UPPER(code)", cat_code, "Category")
            if e:
                return e  # type: ignore[no-any-return]
            cat_id = cid
        try:
            total = Decimal(self._v(row, "total_amount", "0"))
        except (InvalidOperation, ValueError):
            return ["Total amount must be a number."]
        posting_date = self._v(row, "posting_date")
        desc = self._v(row, "income_description")
        if self.conn.execute(
            """SELECT 1 FROM income_batches
                WHERE posting_date=? AND bank_account_id=?
                  AND income_description=? AND total_amount=?""",
            (posting_date, bank_id, desc, str(total)),
        ).fetchone():
            return ["A batch with this date / bank / description / amount already exists."]
        self.conn.execute(
            """INSERT INTO income_batches
               (posting_date, bank_account_id, income_description,
                total_amount, notes, category_id)
               VALUES (?,?,?,?,?,?)""",
            (posting_date, bank_id, desc, str(total),
             self._v(row, "notes"), cat_id),
        )
        return []

    def _insert_reserve_transfers(self, row: dict[str, Any]) -> list[str]:
        from_id, errs = self._lookup("bank_accounts", "account_name",
                                     self._v(row, "from_bank_account"), "From bank account")
        if errs:
            return errs  # type: ignore[no-any-return]
        to_id, errs = self._lookup("bank_accounts", "account_name",
                                   self._v(row, "to_bank_account"), "To bank account")
        if errs:
            return errs  # type: ignore[no-any-return]
        if from_id == to_id:
            return ["From and To bank accounts must be different."]
        try:
            amt = Decimal(self._v(row, "amount", "0"))
        except (InvalidOperation, ValueError):
            return ["Amount must be a number."]
        transfer_date = self._v(row, "transfer_date")
        if self.conn.execute(
            """SELECT 1 FROM reserve_transfers
                WHERE transfer_date=? AND from_bank_account_id=?
                  AND to_bank_account_id=? AND amount=?""",
            (transfer_date, from_id, to_id, str(amt)),
        ).fetchone():
            return ["A transfer with this date / accounts / amount already exists."]
        self.conn.execute(
            """INSERT INTO reserve_transfers
               (transfer_date, from_bank_account_id, to_bank_account_id,
                amount, transfer_type, purpose, notes)
               VALUES (?,?,?,?,?,?,?)""",
            (transfer_date, from_id, to_id, str(amt),
             (self._v(row, "transfer_type", "") or "").upper() or None,
             self._v(row, "purpose"), self._v(row, "notes")),
        )
        return []

    def _insert_board_members(self, row: dict[str, Any]) -> list[str]:
        self.conn.execute(
            """INSERT INTO board_members
               (full_name, title, email, phone, start_date, end_date, is_active, notes)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                self._v(row, "full_name"),
                self._v(row, "title"),
                self._v(row, "email"),
                self._v(row, "phone"),
                self._v(row, "start_date") or None,
                self._v(row, "end_date") or None,
                self._bool(row, "active", 1),
                self._v(row, "notes"),
            ),
        )
        return []

    def _insert_assessment_rules(self, row: dict[str, Any]) -> list[str]:
        rn = self._v(row, "rule_name")
        if not rn:
            return ["Rule Name is required."]
        if self.conn.execute("SELECT 1 FROM assessment_rules WHERE rule_name=?", (rn,)).fetchone():
            return [f'Rule "{rn}" already exists.']
        cat_code = (self._v(row, "category_code", "DUES") or "DUES").upper()
        cat_row = self.conn.execute(
            "SELECT id FROM categories WHERE UPPER(code)=?", (cat_code,)
        ).fetchone()
        if not cat_row:
            return [f'Category "{cat_code}" not found.']
        try:
            amt = Decimal(self._v(row, "default_amount", "0"))
        except ValueError:
            return ["Default Amount must be a number."]
        self.conn.execute(
            """INSERT INTO assessment_rules
               (rule_name, frequency, default_amount, category_id,
                fund_code, effective_start_date, effective_end_date,
                active_flag, notes)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                rn,
                self._v(row, "frequency", "").upper(),
                amt,
                cat_row[0],
                (self._v(row, "fund_code", "OPERATING") or "OPERATING").upper(),
                self._v(row, "effective_start_date"),
                self._v(row, "effective_end_date") or None,
                self._bool(row, "active", 1),
                self._v(row, "notes"),
            ),
        )
        return []

    def _insert_bank_transaction_rules(self, row: dict[str, Any]) -> list[str]:
        rn = self._v(row, "rule_name")
        if not rn:
            return ["Rule Name is required."]
        if self.conn.execute("SELECT 1 FROM bank_transaction_rules WHERE rule_name=?", (rn,)).fetchone():
            return [f"Rule \"{rn}\" already exists."]

        def _lookup(table: str, col: str, val: Any) -> int | None:
            if not val:
                return None
            r = self.conn.execute(f"SELECT id FROM {table} WHERE {col}=?", (val,)).fetchone()
            return r[0] if r else None

        cat_code = self._v(row, "category_code", "")
        cat_id = None
        if cat_code:
            r = self.conn.execute("SELECT id FROM categories WHERE UPPER(code)=UPPER(?)", (cat_code,)).fetchone()
            if not r:
                return [f"Category code \"{cat_code}\" not found."]
            cat_id = r[0]
        vname = self._v(row, "vendor_name", "")
        vendor_id = _lookup("vendors", "vendor_name", vname)
        if vname and vendor_id is None:
            return [f"Vendor \"{vname}\" not found."]
        lnum = self._v(row, "lot_number", "")
        lot_id = _lookup("lots", "lot_number", lnum)
        if lnum and lot_id is None:
            return [f"Lot \"{lnum}\" not found."]
        baname = self._v(row, "bank_account_name", "")
        ba_id = _lookup("bank_accounts", "account_name", baname)
        if baname and ba_id is None:
            return [f"Bank account \"{baname}\" not found."]
        try:
            apan = int(self._v(row, "auto_post_after_n", "3") or "3")
        except ValueError:
            apan = 3
        self.conn.execute(
            """INSERT INTO bank_transaction_rules
               (rule_name, action_type, description_contains, match_type,
                match_memo, match_amount, category_id, vendor_id, lot_id,
                bank_account_id, default_memo,
                confidence_mode, auto_post_after_n, active_flag)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rn,
                self._v(row, "action_type", "").lower(),
                self._v(row, "description_contains", ""),
                self._v(row, "match_type", ""),
                self._v(row, "match_memo", ""),
                self._v(row, "match_amount", ""),
                cat_id,
                vendor_id,
                lot_id,
                ba_id,
                self._v(row, "default_memo", ""),
                self._v(row, "confidence_mode", "review_first") or "review_first",
                apan,
                self._bool(row, "active", 1),
            ),
        )
        return []

    def _insert_opening_balances(self, row: dict[str, Any]) -> list[str]:
        et = self._v(row, "entity_type", "").upper()
        if et not in ("BANK_ACCOUNT", "LOT_DUES", "LOT_ASSESSMENT"):
            return ['Entity Type must be "BANK_ACCOUNT", "LOT_DUES", or "LOT_ASSESSMENT".']
        key = self._v(row, "entity_key", "")
        if et == "BANK_ACCOUNT":
            r = self.conn.execute(
                "SELECT id FROM bank_accounts WHERE account_name=?", (key,)
            ).fetchone()
            if not r:
                return [f'Bank account "{key}" not found.']
            entity_id = r[0]
        else:
            r = self.conn.execute(
                "SELECT id FROM lots WHERE lot_number=?", (key,)
            ).fetchone()
            if not r:
                return [f'Lot "{key}" not found.']
            entity_id = r[0]
        as_of = self._v(row, "as_of_date")
        if self.conn.execute(
            "SELECT 1 FROM opening_balances WHERE entity_type=? AND entity_id=?",
            (et, entity_id),
        ).fetchone():
            return ["This entity already has an opening balance — delete it first to re-import."]
        try:
            amt = Decimal(self._v(row, "amount", "0"))
        except (InvalidOperation, ValueError):
            return ["Amount must be a number."]
        self.conn.execute(
            """INSERT INTO opening_balances (as_of_date, entity_type, entity_id, amount)
               VALUES (?,?,?,?)""",
            (as_of, et, entity_id, amt),
        )
        return []
