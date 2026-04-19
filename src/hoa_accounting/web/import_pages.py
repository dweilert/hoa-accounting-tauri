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

TABLE_DEFS: dict[str, dict] = {
    "accounts": {
        "label": "Chart of Accounts",
        "order": 1,
        "requires": [],
        "fields": [
            {"name": "account_number",  "label": "Account Number",   "required": True,  "type": "text",    "key": True,  "note": "Must be unique, e.g. 4000"},
            {"name": "account_name",    "label": "Account Name",     "required": True,  "type": "text"},
            {"name": "account_type",    "label": "Account Type",     "required": True,  "type": "enum",    "values": ["Asset","Liability","Equity","Income","Expense"]},
            {"name": "fund_code",       "label": "Fund Code",        "required": True,  "type": "enum",    "values": ["OPERATING","RESERVE","SPECIAL"]},
            {"name": "is_bank_account", "label": "Is Bank Account",  "required": False, "type": "boolean", "note": "Yes or No, default No"},
            {"name": "active",          "label": "Active",           "required": False, "type": "boolean", "note": "Yes or No, default Yes"},
            {"name": "description",     "label": "Description",      "required": False, "type": "text"},
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
        "requires": ["Chart of Accounts"],
        "fields": [
            {"name": "account_name",     "label": "Account Name",      "required": True,  "type": "text", "key": True,  "note": "Must be unique"},
            {"name": "institution_name", "label": "Bank / Institution", "required": True,  "type": "text"},
            {"name": "account_last4",    "label": "Last 4 Digits",      "required": False, "type": "text"},
            {"name": "account_type",     "label": "Account Type",       "required": True,  "type": "enum",    "values": ["CHECKING","SAVINGS","MONEY_MARKET","OTHER"]},
            {"name": "gl_account_number","label": "GL Account #",       "required": True,  "type": "text",    "note": "Must match an existing account number"},
            {"name": "active",           "label": "Active",             "required": False, "type": "boolean", "note": "Yes or No, default Yes"},
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
    "renters": {
        "label": "Renters",
        "order": 8,
        "requires": ["Lots"],
        "fields": [
            {"name": "lot_number",      "label": "Lot Number",     "required": True,  "type": "text", "note": "Must match an existing lot"},
            {"name": "display_name",    "label": "Display Name",   "required": True,  "type": "text"},
            {"name": "first_name",      "label": "First Name",     "required": False, "type": "text"},
            {"name": "last_name",       "label": "Last Name",      "required": False, "type": "text"},
            {"name": "email",           "label": "Email",          "required": False, "type": "text"},
            {"name": "phone",           "label": "Phone",          "required": False, "type": "text"},
            {"name": "start_date",      "label": "Start Date",     "required": False, "type": "date", "note": "YYYY-MM-DD"},
            {"name": "end_date",        "label": "End Date",       "required": False, "type": "date", "note": "YYYY-MM-DD"},
            {"name": "notes",           "label": "Notes",          "required": False, "type": "text"},
        ],
    },
    "budget_lines": {
        "label": "Budget Lines",
        "order": 9,
        "requires": ["Budgets", "Chart of Accounts"],
        "fields": [
            {"name": "fiscal_year",    "label": "Fiscal Year",   "required": True, "type": "integer", "key": True,  "note": "Combined key"},
            {"name": "fund_code",      "label": "Fund Code",     "required": True, "type": "enum",    "key": True,  "values": ["OPERATING","RESERVE","SPECIAL"], "note": "Combined key"},
            {"name": "account_number", "label": "Account Number","required": True, "type": "text",    "key": True,  "note": "Combined key — must match an existing account"},
            {"name": "fiscal_period",  "label": "Fiscal Period", "required": True, "type": "integer", "key": True,  "note": "Combined key — 1–12"},
            {"name": "budget_amount",  "label": "Budget Amount", "required": True, "type": "decimal"},
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
        org: dict | None,
        theme: str,
        error_message: str = "",
    ) -> ImportPageResponse:
        ordered = sorted(TABLE_DEFS.items(), key=lambda kv: kv[1]["order"])
        ctx = {
            "heading":         "Import Data",
            "breadcrumb":      "System",
            "org":             org or {},
            "theme":           theme,
            "page_key":        "import",
            "table_defs_json": json.dumps(TABLE_DEFS),
            "import_order":    [(k, v) for k, v in ordered],
            "error_message":   error_message,
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
        org: dict | None,
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
        error_rows: list[dict] = []

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
    ) -> dict:
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
        error_rows: list[dict] = []

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

    def _check_row_db(self, data_type: str, row: dict) -> list[str]:
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
            return errs
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

    def _validate_row(self, table_def: dict, row: dict[str, str]) -> list[str]:
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
                    float(val)
                except ValueError:
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
            return errs
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

    def _v(self, row: dict, name: str, default: Any = None) -> Any:
        v = row.get(name, "").strip()
        return v if v else default

    def _bool(self, row: dict, name: str, default: int = 1) -> int:
        v = row.get(name, "").strip()
        return _parse_bool(v, default) if v else default

    # ── Per-type insert methods ──────────────────────────────────────────

    def _insert_accounts(self, row: dict) -> list[str]:
        at_name = self._v(row, "account_type", "")
        at_row  = self.conn.execute(
            "SELECT id FROM account_types WHERE LOWER(name)=LOWER(?)", (at_name,)
        ).fetchone()
        if not at_row:
            return [f"Account type \"{at_name}\" not found."]
        acct_num = self._v(row, "account_number")
        if self.conn.execute(
            "SELECT 1 FROM accounts WHERE account_number=?", (acct_num,)
        ).fetchone():
            return [f"Account number \"{acct_num}\" already exists."]
        self.conn.execute(
            """INSERT INTO accounts
               (account_number, account_name, account_type_id, fund_code,
                is_bank_account, is_active, description)
               VALUES (?,?,?,?,?,?,?)""",
            (
                acct_num,
                self._v(row, "account_name"),
                at_row[0],
                self._v(row, "fund_code", "").upper(),
                self._bool(row, "is_bank_account", 0),
                self._bool(row, "active",           1),
                self._v(row,  "description"),
            ),
        )
        return []

    def _insert_owners(self, row: dict) -> list[str]:
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

    def _insert_vendors(self, row: dict) -> list[str]:
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

    def _insert_budgets(self, row: dict) -> list[str]:
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

    def _insert_lots(self, row: dict) -> list[str]:
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

    def _insert_bank_accounts(self, row: dict) -> list[str]:
        gl_num = self._v(row, "gl_account_number")
        gl_row = self.conn.execute(
            "SELECT id FROM accounts WHERE account_number=?", (gl_num,)
        ).fetchone()
        if not gl_row:
            return [f"GL account \"{gl_num}\" not found in Chart of Accounts."]
        an = self._v(row, "account_name")
        if self.conn.execute(
            "SELECT 1 FROM bank_accounts WHERE account_name=?", (an,)
        ).fetchone():
            return [f"Bank account \"{an}\" already exists."]
        self.conn.execute(
            """INSERT INTO bank_accounts
               (account_name, institution_name, account_last4, account_type,
                gl_account_id, active_flag)
               VALUES (?,?,?,?,?,?)""",
            (
                an,
                self._v(row, "institution_name"),
                self._v(row, "account_last4"),
                self._v(row, "account_type", "").upper(),
                gl_row[0],
                self._bool(row, "active", 1),
            ),
        )
        return []

    def _insert_lot_ownership(self, row: dict) -> list[str]:
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

    def _insert_renters(self, row: dict) -> list[str]:
        lot_num = self._v(row, "lot_number")
        lot_row = self.conn.execute(
            "SELECT id FROM lots WHERE lot_number=?", (lot_num,)
        ).fetchone()
        if not lot_row:
            return [f"Lot \"{lot_num}\" not found. Import Lots first."]
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
                self._v(row, "end_date")   or None,
                self._v(row, "notes"),
            ),
        )
        return []

    def _insert_budget_lines(self, row: dict) -> list[str]:
        fy = int(self._v(row, "fiscal_year", 0))
        fc = self._v(row, "fund_code", "").upper()
        budget_row = self.conn.execute(
            "SELECT id FROM budgets WHERE fiscal_year=? AND fund_code=?", (fy, fc)
        ).fetchone()
        if not budget_row:
            return [f"Budget {fy} / {fc} not found. Import Budgets first."]

        acct_num = self._v(row, "account_number")
        acct_row = self.conn.execute(
            "SELECT id FROM accounts WHERE account_number=?", (acct_num,)
        ).fetchone()
        if not acct_row:
            return [f"Account \"{acct_num}\" not found. Import Chart of Accounts first."]

        period = int(self._v(row, "fiscal_period", 0))
        if not 1 <= period <= 12:
            return [f"Fiscal period must be 1–12 (got {period})."]

        if self.conn.execute(
            "SELECT 1 FROM budget_lines "
            "WHERE budget_id=? AND account_id=? AND fiscal_period=?",
            (budget_row[0], acct_row[0], period),
        ).fetchone():
            return ["This budget / account / period combination already exists."]

        self.conn.execute(
            """INSERT INTO budget_lines (budget_id, account_id, fiscal_period, budget_amount)
               VALUES (?,?,?,?)""",
            (
                budget_row[0],
                acct_row[0],
                period,
                float(self._v(row, "budget_amount", 0)),
            ),
        )
        return []
