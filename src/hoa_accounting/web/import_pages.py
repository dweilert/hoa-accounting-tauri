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
            {
                "name": "code",
                "label": "Code",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Must be unique, e.g. DUES, LANDSCAPING",
            },
            {"name": "name", "label": "Name", "required": True, "type": "text"},
            {
                "name": "category_type",
                "label": "Category Type",
                "required": True,
                "type": "enum",
                "values": ["INCOME", "EXPENSE", "TRANSFER"],
            },
            {
                "name": "fund_code",
                "label": "Fund Code",
                "required": False,
                "type": "enum",
                "values": ["OPERATING", "RESERVE", "SPECIAL"],
                "note": "Default OPERATING",
            },
            {"name": "group_name", "label": "Group", "required": False, "type": "text"},
            {
                "name": "sort_order",
                "label": "Sort Order",
                "required": False,
                "type": "integer",
                "note": "Lower numbers appear first; default 0",
            },
            {
                "name": "active",
                "label": "Active",
                "required": False,
                "type": "boolean",
                "note": "Yes or No, default Yes",
            },
            {
                "name": "description",
                "label": "Description",
                "required": False,
                "type": "text",
            },
        ],
    },
    "owners": {
        "label": "Owners",
        "order": 2,
        "requires": [],
        "fields": [
            {
                "name": "owner_type",
                "label": "Owner Type",
                "required": True,
                "type": "enum",
                "values": ["PERSON", "ENTITY", "TRUST"],
            },
            {
                "name": "display_name",
                "label": "Display Name",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Must be unique — used to link ownership records",
            },
            {
                "name": "first_name",
                "label": "First Name",
                "required": False,
                "type": "text",
            },
            {
                "name": "last_name",
                "label": "Last Name",
                "required": False,
                "type": "text",
            },
            {
                "name": "entity_name",
                "label": "Entity / Trust Name",
                "required": False,
                "type": "text",
            },
            {
                "name": "mailing_address_1",
                "label": "Address Line 1",
                "required": False,
                "type": "text",
            },
            {
                "name": "mailing_address_2",
                "label": "Address Line 2",
                "required": False,
                "type": "text",
            },
            {"name": "city", "label": "City", "required": False, "type": "text"},
            {"name": "state", "label": "State", "required": False, "type": "text"},
            {
                "name": "postal_code",
                "label": "Postal Code",
                "required": False,
                "type": "text",
            },
            {"name": "phone", "label": "Phone", "required": False, "type": "text"},
            {"name": "email", "label": "Email", "required": False, "type": "text"},
            {
                "name": "active",
                "label": "Active",
                "required": False,
                "type": "boolean",
                "note": "Yes or No, default Yes",
            },
            {"name": "notes", "label": "Notes", "required": False, "type": "text"},
        ],
    },
    "vendors": {
        "label": "Vendors",
        "order": 3,
        "requires": [],
        "fields": [
            {
                "name": "vendor_name",
                "label": "Vendor Name",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Must be unique",
            },
            {
                "name": "contact_name",
                "label": "Contact Name",
                "required": False,
                "type": "text",
            },
            {"name": "email", "label": "Email", "required": False, "type": "text"},
            {"name": "phone", "label": "Phone", "required": False, "type": "text"},
            {
                "name": "address_1",
                "label": "Address Line 1",
                "required": False,
                "type": "text",
            },
            {
                "name": "address_2",
                "label": "Address Line 2",
                "required": False,
                "type": "text",
            },
            {"name": "city", "label": "City", "required": False, "type": "text"},
            {"name": "state", "label": "State", "required": False, "type": "text"},
            {
                "name": "postal_code",
                "label": "Postal Code",
                "required": False,
                "type": "text",
            },
            {
                "name": "active",
                "label": "Active",
                "required": False,
                "type": "boolean",
                "note": "Yes or No, default Yes",
            },
            {"name": "notes", "label": "Notes", "required": False, "type": "text"},
        ],
    },
    "budgets": {
        "label": "Budgets",
        "order": 4,
        "requires": [],
        "fields": [
            {
                "name": "fiscal_year",
                "label": "Fiscal Year",
                "required": True,
                "type": "integer",
                "key": True,
                "note": "Combined with Fund Code — must be unique together",
            },
            {
                "name": "fund_code",
                "label": "Fund Code",
                "required": True,
                "type": "enum",
                "key": True,
                "values": ["OPERATING", "RESERVE", "SPECIAL"],
                "note": "Combined with Fiscal Year — must be unique together",
            },
            {
                "name": "status",
                "label": "Status",
                "required": True,
                "type": "enum",
                "values": ["DRAFT", "APPROVED", "ARCHIVED"],
            },
            {"name": "notes", "label": "Notes", "required": False, "type": "text"},
        ],
    },
    "lots": {
        "label": "Lots",
        "order": 5,
        "requires": [],
        "fields": [
            {
                "name": "lot_number",
                "label": "Lot Number",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Must be unique",
            },
            {
                "name": "street_address_1",
                "label": "Address Line 1",
                "required": False,
                "type": "text",
            },
            {
                "name": "street_address_2",
                "label": "Address Line 2",
                "required": False,
                "type": "text",
            },
            {"name": "city", "label": "City", "required": False, "type": "text"},
            {"name": "state", "label": "State", "required": False, "type": "text"},
            {
                "name": "postal_code",
                "label": "Postal Code",
                "required": False,
                "type": "text",
            },
            {
                "name": "legal_description",
                "label": "Legal Desc.",
                "required": False,
                "type": "text",
            },
            {
                "name": "active",
                "label": "Active",
                "required": False,
                "type": "boolean",
                "note": "Yes or No, default Yes",
            },
        ],
    },
    "bank_accounts": {
        "label": "Bank Accounts",
        "order": 6,
        "requires": [],
        "fields": [
            {
                "name": "account_name",
                "label": "Account Name",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Must be unique",
            },
            {
                "name": "institution_name",
                "label": "Bank / Institution",
                "required": True,
                "type": "text",
            },
            {
                "name": "account_last4",
                "label": "Last 4 Digits",
                "required": False,
                "type": "text",
            },
            {
                "name": "account_type",
                "label": "Account Type",
                "required": True,
                "type": "enum",
                "values": ["CHECKING", "SAVINGS", "MONEY_MARKET", "OTHER"],
            },
            {
                "name": "fund_code",
                "label": "Fund Code",
                "required": False,
                "type": "enum",
                "values": ["OPERATING", "RESERVE", "SPECIAL"],
                "note": "Default OPERATING",
            },
            {
                "name": "active",
                "label": "Active",
                "required": False,
                "type": "boolean",
                "note": "Yes or No, default Yes",
            },
        ],
    },
    "renters": {
        "label": "Renters",
        "order": 8,
        "requires": ["Lots"],
        "fields": [
            {
                "name": "lot_number",
                "label": "Lot Number",
                "required": True,
                "type": "text",
                "note": "Must match an existing lot",
            },
            {
                "name": "display_name",
                "label": "Display Name",
                "required": True,
                "type": "text",
            },
            {
                "name": "first_name",
                "label": "First Name",
                "required": False,
                "type": "text",
            },
            {
                "name": "last_name",
                "label": "Last Name",
                "required": False,
                "type": "text",
            },
            {"name": "email", "label": "Email", "required": False, "type": "text"},
            {"name": "phone", "label": "Phone", "required": False, "type": "text"},
            {
                "name": "start_date",
                "label": "Start Date",
                "required": False,
                "type": "date",
                "note": "YYYY-MM-DD",
            },
            {
                "name": "end_date",
                "label": "End Date",
                "required": False,
                "type": "date",
                "note": "YYYY-MM-DD",
            },
            {"name": "notes", "label": "Notes", "required": False, "type": "text"},
        ],
    },
    "lot_ownership": {
        "label": "Lot Ownership History",
        "order": 7,
        "requires": ["Lots", "Owners"],
        "fields": [
            {
                "name": "lot_number",
                "label": "Lot Number",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Combined key — must match an existing lot",
            },
            {
                "name": "owner_name",
                "label": "Owner Name",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Combined key — must match owner's display name",
            },
            {
                "name": "start_date",
                "label": "Start Date",
                "required": True,
                "type": "date",
                "key": True,
                "note": "Combined key — YYYY-MM-DD",
            },
            {
                "name": "end_date",
                "label": "End Date",
                "required": False,
                "type": "date",
                "note": "YYYY-MM-DD, blank = current owner",
            },
        ],
    },
    "board_members": {
        "label": "Board Members",
        "order": 8,
        "requires": [],
        "fields": [
            {
                "name": "full_name",
                "label": "Full Name",
                "required": True,
                "type": "text",
            },
            {
                "name": "title",
                "label": "Title",
                "required": True,
                "type": "text",
                "note": "e.g. President, Treasurer",
            },
            {"name": "email", "label": "Email", "required": False, "type": "text"},
            {"name": "phone", "label": "Phone", "required": False, "type": "text"},
            {
                "name": "start_date",
                "label": "Start Date",
                "required": False,
                "type": "date",
            },
            {
                "name": "end_date",
                "label": "End Date",
                "required": False,
                "type": "date",
            },
            {
                "name": "active",
                "label": "Active",
                "required": False,
                "type": "boolean",
                "note": "Yes or No, default Yes",
            },
            {"name": "notes", "label": "Notes", "required": False, "type": "text"},
        ],
    },
    "assessment_rules": {
        "label": "Assessment Rules",
        "order": 10,
        "requires": ["Categories"],
        "fields": [
            {
                "name": "rule_name",
                "label": "Rule Name",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Must be unique",
            },
            {
                "name": "frequency",
                "label": "Frequency",
                "required": True,
                "type": "enum",
                "values": ["ANNUAL", "SEMIANNUAL", "QUARTERLY", "MONTHLY", "CUSTOM"],
            },
            {
                "name": "default_amount",
                "label": "Default Amount",
                "required": True,
                "type": "decimal",
            },
            {
                "name": "category_code",
                "label": "Category Code",
                "required": False,
                "type": "text",
                "note": "Must match an existing category code (e.g. DUES). Defaults to DUES.",
            },
            {
                "name": "fund_code",
                "label": "Fund Code",
                "required": False,
                "type": "enum",
                "values": ["OPERATING", "RESERVE", "SPECIAL"],
                "note": "Default OPERATING",
            },
            {
                "name": "effective_start_date",
                "label": "Effective Start",
                "required": True,
                "type": "date",
            },
            {
                "name": "effective_end_date",
                "label": "Effective End",
                "required": False,
                "type": "date",
            },
            {
                "name": "active",
                "label": "Active",
                "required": False,
                "type": "boolean",
                "note": "Yes or No, default Yes",
            },
            {"name": "notes", "label": "Notes", "required": False, "type": "text"},
        ],
    },
    "bank_transaction_rules": {
        "label": "Bank Transaction Rules",
        "order": 11,
        "requires": ["Categories", "Bank Accounts", "Vendors", "Lots"],
        "fields": [
            {
                "name": "rule_name",
                "label": "Rule Name",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Must be unique",
            },
            {
                "name": "action_type",
                "label": "Action Type",
                "required": True,
                "type": "enum",
                "values": [
                    "recurring_bill",
                    "dues_payment",
                    "fee_income",
                    "bank_charge",
                    "direct_expense",
                    "direct_income",
                    "homeowner_batch",
                    "vendor_bill_match",
                ],
            },
            {
                "name": "description_contains",
                "label": "Description Contains",
                "required": False,
                "type": "text",
                "note": "Substring to match in bank description",
            },
            {
                "name": "match_type",
                "label": "Match Type",
                "required": False,
                "type": "text",
            },
            {
                "name": "match_memo",
                "label": "Match Memo",
                "required": False,
                "type": "text",
            },
            {
                "name": "match_amount",
                "label": "Match Amount",
                "required": False,
                "type": "text",
            },
            {
                "name": "category_code",
                "label": "Category Code",
                "required": False,
                "type": "text",
                "note": "Must match an existing category code",
            },
            {
                "name": "vendor_name",
                "label": "Vendor Name",
                "required": False,
                "type": "text",
                "note": "Must match an existing vendor name",
            },
            {
                "name": "lot_number",
                "label": "Lot Number",
                "required": False,
                "type": "text",
                "note": "Must match an existing lot",
            },
            {
                "name": "bank_account_name",
                "label": "Bank Account Name",
                "required": False,
                "type": "text",
                "note": "Must match an existing bank account name",
            },
            {
                "name": "default_memo",
                "label": "Default Memo",
                "required": False,
                "type": "text",
            },
            {
                "name": "confidence_mode",
                "label": "Confidence Mode",
                "required": False,
                "type": "text",
                "note": "review_first or auto_post; default review_first",
            },
            {
                "name": "auto_post_after_n",
                "label": "Auto-Post After N",
                "required": False,
                "type": "integer",
                "note": "Default 3",
            },
            {
                "name": "active",
                "label": "Active",
                "required": False,
                "type": "boolean",
                "note": "Yes or No, default Yes",
            },
        ],
    },
    "opening_balances": {
        "label": "Opening Balances",
        "order": 12,
        "requires": ["Bank Accounts", "Lots"],
        "fields": [
            {
                "name": "as_of_date",
                "label": "As Of Date",
                "required": True,
                "type": "date",
                "key": True,
                "note": "YYYY-MM-DD",
            },
            {
                "name": "entity_type",
                "label": "Entity Type",
                "required": True,
                "type": "enum",
                "key": True,
                "values": ["BANK_ACCOUNT", "LOT_DUES", "LOT_ASSESSMENT"],
                "note": "BANK_ACCOUNT = cash on hand; LOT_DUES / LOT_ASSESSMENT = owner balance on a lot",
            },
            {
                "name": "entity_key",
                "label": "Entity Key",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Bank Account name for BANK_ACCOUNT; Lot # for LOT_DUES / LOT_ASSESSMENT",
            },
            {"name": "amount", "label": "Amount", "required": True, "type": "decimal"},
        ],
    },
    "budget_lines": {
        "label": "Budget Lines",
        "order": 9,
        "requires": ["Budgets", "Categories"],
        "fields": [
            {
                "name": "fiscal_year",
                "label": "Fiscal Year",
                "required": True,
                "type": "integer",
                "key": True,
                "note": "Combined key",
            },
            {
                "name": "fund_code",
                "label": "Fund Code",
                "required": True,
                "type": "enum",
                "key": True,
                "values": ["OPERATING", "RESERVE", "SPECIAL"],
                "note": "Combined key",
            },
            {
                "name": "category_code",
                "label": "Category Code",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Combined key — must match an existing category code",
            },
            {
                "name": "fiscal_period",
                "label": "Fiscal Period",
                "required": True,
                "type": "integer",
                "key": True,
                "note": "Combined key — 1–12",
            },
            {
                "name": "budget_amount",
                "label": "Budget Amount",
                "required": True,
                "type": "decimal",
            },
        ],
    },
    "deposit_batches": {
        "label": "Deposit Batches",
        "order": 14,
        "requires": ["Bank Accounts"],
        "fields": [
            {
                "name": "deposit_date",
                "label": "Deposit Date",
                "required": True,
                "type": "date",
                "key": True,
                "note": "YYYY-MM-DD",
            },
            {
                "name": "bank_account_name",
                "label": "Bank Account",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Must match an existing bank account name",
            },
            {
                "name": "total_amount",
                "label": "Total Amount",
                "required": True,
                "type": "decimal",
                "key": True,
            },
            {
                "name": "category_code",
                "label": "Category Code",
                "required": False,
                "type": "text",
                "note": "Optional — must match an existing category code",
            },
            {"name": "notes", "label": "Notes", "required": False, "type": "text"},
        ],
    },
    "assessments": {
        "label": "Assessments / Charges",
        "order": 15,
        "requires": ["Lots", "Owners", "Categories"],
        "fields": [
            {
                "name": "lot_number",
                "label": "Lot Number",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Must match an existing lot",
            },
            {
                "name": "owner_name",
                "label": "Owner Name",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Must match an existing owner display name",
            },
            {
                "name": "charge_type",
                "label": "Charge Type",
                "required": True,
                "type": "enum",
                "values": ["DUES", "LATE_FEE", "RESALE_FEE", "SPECIAL", "OTHER"],
            },
            {
                "name": "assessment_date",
                "label": "Assessment Date",
                "required": True,
                "type": "date",
                "key": True,
                "note": "YYYY-MM-DD",
            },
            {"name": "due_date", "label": "Due Date", "required": True, "type": "date"},
            {"name": "amount", "label": "Amount", "required": True, "type": "decimal"},
            {
                "name": "category_code",
                "label": "Category Code",
                "required": False,
                "type": "text",
            },
            {
                "name": "status",
                "label": "Status",
                "required": False,
                "type": "enum",
                "values": ["OPEN", "PAID", "PARTIAL", "VOID", "WRITTEN_OFF"],
                "note": "Default OPEN",
            },
            {
                "name": "description",
                "label": "Description",
                "required": False,
                "type": "text",
            },
        ],
    },
    "payments": {
        "label": "Payments Received",
        "order": 16,
        "requires": ["Owners", "Bank Accounts"],
        "fields": [
            {
                "name": "receipt_number",
                "label": "Receipt Number",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Must be unique",
            },
            {
                "name": "owner_name",
                "label": "Owner Name",
                "required": True,
                "type": "text",
                "note": "Must match an existing owner display name",
            },
            {
                "name": "payment_date",
                "label": "Payment Date",
                "required": True,
                "type": "date",
            },
            {"name": "amount", "label": "Amount", "required": True, "type": "decimal"},
            {
                "name": "payment_method",
                "label": "Payment Method",
                "required": True,
                "type": "enum",
                "values": ["CHECK", "CASH", "ACH", "CREDIT_CARD", "OTHER"],
            },
            {
                "name": "reference_number",
                "label": "Reference Number",
                "required": False,
                "type": "text",
            },
            {
                "name": "bank_account_name",
                "label": "Bank Account",
                "required": True,
                "type": "text",
                "note": "Must match an existing bank account name",
            },
            {
                "name": "category_code",
                "label": "Category Code",
                "required": False,
                "type": "text",
            },
            {"name": "notes", "label": "Notes", "required": False, "type": "text"},
        ],
    },
    "vendor_bills": {
        "label": "Vendor Bills",
        "order": 17,
        "requires": ["Vendors", "Categories"],
        "fields": [
            {
                "name": "vendor_name",
                "label": "Vendor Name",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Must match an existing vendor",
            },
            {
                "name": "invoice_number",
                "label": "Invoice Number",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Unique per vendor",
            },
            {
                "name": "invoice_date",
                "label": "Invoice Date",
                "required": True,
                "type": "date",
            },
            {
                "name": "due_date",
                "label": "Due Date",
                "required": False,
                "type": "date",
            },
            {"name": "amount", "label": "Amount", "required": True, "type": "decimal"},
            {
                "name": "fund_code",
                "label": "Fund Code",
                "required": False,
                "type": "enum",
                "values": ["OPERATING", "RESERVE", "SPECIAL"],
                "note": "Default OPERATING",
            },
            {
                "name": "category_code",
                "label": "Category Code",
                "required": True,
                "type": "text",
                "note": "Must match an existing category code",
            },
            {
                "name": "status",
                "label": "Status",
                "required": False,
                "type": "enum",
                "values": ["OPEN", "PAID", "VOID"],
                "note": "Default OPEN",
            },
            {
                "name": "description",
                "label": "Description",
                "required": False,
                "type": "text",
            },
        ],
    },
    "bill_payments": {
        "label": "Bill Payments",
        "order": 18,
        "requires": ["Vendor Bills", "Bank Accounts"],
        "fields": [
            {
                "name": "vendor_name",
                "label": "Vendor Name",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Combined key with invoice number",
            },
            {
                "name": "invoice_number",
                "label": "Invoice Number",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Bill must already exist",
            },
            {
                "name": "payment_date",
                "label": "Payment Date",
                "required": True,
                "type": "date",
            },
            {"name": "amount", "label": "Amount", "required": True, "type": "decimal"},
            {
                "name": "bank_account_name",
                "label": "Bank Account",
                "required": True,
                "type": "text",
                "note": "Must match an existing bank account name",
            },
            {
                "name": "check_number",
                "label": "Check Number",
                "required": False,
                "type": "text",
            },
            {"name": "notes", "label": "Notes", "required": False, "type": "text"},
        ],
    },
    "non_dues_income": {
        "label": "Non-Dues Income",
        "order": 19,
        "requires": ["Bank Accounts", "Categories"],
        "fields": [
            {
                "name": "posting_date",
                "label": "Posting Date",
                "required": True,
                "type": "date",
                "key": True,
            },
            {
                "name": "bank_account_name",
                "label": "Bank Account",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Must match an existing bank account name",
            },
            {
                "name": "category_code",
                "label": "Category Code",
                "required": False,
                "type": "text",
                "note": "Optional",
            },
            {
                "name": "income_description",
                "label": "Description",
                "required": True,
                "type": "text",
                "key": True,
            },
            {
                "name": "total_amount",
                "label": "Total Amount",
                "required": True,
                "type": "decimal",
            },
            {"name": "notes", "label": "Notes", "required": False, "type": "text"},
        ],
    },
    "reserve_transfers": {
        "label": "Reserve Transfers",
        "order": 20,
        "requires": ["Bank Accounts"],
        "fields": [
            {
                "name": "transfer_date",
                "label": "Transfer Date",
                "required": True,
                "type": "date",
                "key": True,
            },
            {
                "name": "from_bank_account",
                "label": "From Bank Account",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Must match an existing bank account name",
            },
            {
                "name": "to_bank_account",
                "label": "To Bank Account",
                "required": True,
                "type": "text",
                "key": True,
                "note": "Must match an existing bank account name",
            },
            {"name": "amount", "label": "Amount", "required": True, "type": "decimal"},
            {
                "name": "transfer_type",
                "label": "Transfer Type",
                "required": False,
                "type": "text",
                "note": "e.g. CONTRIBUTION, FUNDING, OTHER",
            },
            {"name": "purpose", "label": "Purpose", "required": False, "type": "text"},
            {"name": "notes", "label": "Notes", "required": False, "type": "text"},
        ],
    },
}


# ── CSV parsing ───────────────────────────────────────────────────────────────


from hoa_accounting.web.import_parsing import (
    parse_csv as _parse_csv,
)

# ── Response types ────────────────────────────────────────────────────────────


@dataclass
class ImportPageResponse:
    status_code: int
    body_html: str


# ── Page service ──────────────────────────────────────────────────────────────


class ImportPages:
    TEMPLATE = "import.html"
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
            CANONICAL_CSV_FIELDS,
            peek_stash,
        )

        defs = dict(TABLE_DEFS)
        defs["bank_statement_csv"] = {
            "label": "Bank Statement (CSV)",
            "order": 99,
            "requires": [],
            "fields": CANONICAL_CSV_FIELDS,
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
            "heading": "Import Data",
            "breadcrumb": "System",
            "org": org or {},
            "theme": theme,
            "page_key": "import",
            "table_defs_json": json.dumps(defs),
            "import_order": [(k, v) for k, v in ordered],
            "error_message": error_message,
            "prefill_type": prefill_type,
            "stash_token": stash_token,
            "bank_account_id": bank_account_id or "",
            "prefill_csv": prefill_csv,
            "prefill_filename": prefill_filename,
            "note": note,
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
            return self.render_page(
                org=org, theme=theme, error_message=f"Unknown data type '{data_type}'."
            )

        try:
            mapping: dict[str, str] = json.loads(mapping_json)
        except Exception:
            return self.render_page(
                org=org, theme=theme, error_message="Could not read field mapping."
            )

        csv_headers, csv_rows = _parse_csv(csv_content)
        if not csv_rows:
            return self.render_page(
                org=org, theme=theme, error_message="The file contains no data rows."
            )

        table_def = TABLE_DEFS[data_type]
        imported = 0
        error_rows: list[dict[str, Any]] = []

        for row_num, csv_row in enumerate(csv_rows, start=2):
            # Build {csvColumn: value} from the raw row
            raw: dict[str, str] = {
                csv_headers[j]: (csv_row[j] if j < len(csv_row) else "")
                for j in range(len(csv_headers))
            }
            # Translate via mapping to {tableField: value}
            table_row: dict[str, str] = {
                tf: raw.get(csv_col, "") for tf, csv_col in mapping.items()
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
            "heading": "Import Results",
            "breadcrumb": "System",
            "org": org or {},
            "theme": theme,
            "page_key": "import",
            "data_type_label": table_def["label"],
            "file_name": file_name,
            "checked_at": datetime.now().strftime("%-I:%M:%S %p on %b %-d, %Y"),
            "imported": imported,
            "failed": len(error_rows),
            "total": imported + len(error_rows),
            "error_rows": error_rows,
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
        filter_field: str = "",  # empty = all fields; non-empty = only check this column
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
        ok_count = 0
        error_rows: list[dict[str, Any]] = []

        for row_num, csv_row in enumerate(csv_rows, start=2):
            raw: dict[str, str] = {
                csv_headers[j]: (csv_row[j] if j < len(csv_row) else "")
                for j in range(len(csv_headers))
            }
            table_row: dict[str, str] = {
                tf: raw.get(csv_col, "") for tf, csv_col in mapping.items()
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
                    (
                        f["label"]
                        for f in table_def["fields"]
                        if f["name"] == filter_field
                    ),
                    filter_field,
                )
                errs = [e for e in errs if filter_field in e or field_label in e]

            if errs:
                error_rows.append(
                    {
                        "row": row_num,
                        "errors": errs,
                        "value": (
                            table_row.get(filter_field, "") if filter_field else ""
                        ),
                    }
                )
            else:
                ok_count += 1

        return {
            "total": len(csv_rows),
            "ok_count": ok_count,
            "error_count": len(error_rows),
            "errors": error_rows,
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

    def _validate_row(
        self, table_def: dict[str, Any], row: dict[str, str]
    ) -> list[str]:
        errs: list[str] = []
        for field in table_def["fields"]:
            name = field["name"]
            val = row.get(name, "").strip()
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
                    errs.append(
                        f"'{field['label']}': \"{val}\" must be a whole number."
                    )
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
        """Route a parsed CSV row to its data-type-specific inserter.

        Wraps the call in a SAVEPOINT so a failure on one row leaves
        earlier successful rows intact and the broader import
        transaction recoverable.
        """
        from hoa_accounting.web.import_inserters import INSERTERS

        handler = INSERTERS.get(data_type)
        if handler is None:
            return [f"No insert handler for '{data_type}'."]
        try:
            self.conn.execute("SAVEPOINT import_row")
            errs = handler(self.conn, row)
            if errs:
                self.conn.execute("ROLLBACK TO SAVEPOINT import_row")
            else:
                self.conn.execute("RELEASE SAVEPOINT import_row")
            return errs
        except sqlite3.IntegrityError as e:
            self.conn.execute("ROLLBACK TO SAVEPOINT import_row")
            msg = str(e)
            if "UNIQUE constraint" in msg:
                return ["A record with this key already exists (duplicate)."]
            if "FOREIGN KEY constraint" in msg:
                return ["A referenced record does not exist (foreign key error)."]
            return [f"Data integrity error: {msg}"]
        except Exception as e:  # noqa: BLE001
            self.conn.execute("ROLLBACK TO SAVEPOINT import_row")
            return [f"Unexpected error: {e}"]
