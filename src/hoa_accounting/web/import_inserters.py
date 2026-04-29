"""Per-data-type SQL inserters for the CSV import pipeline.

Pure functions over a sqlite3.Connection — no Flask, no Pages object.
Each ``insert_<data_type>(conn, row)`` validates the row and writes
exactly one row, returning a list of human-readable error strings (empty
on success). The ``INSERTERS`` dispatch table is consumed by
``ImportPages._insert_row`` to route a parsed CSV row to the right
handler.

These were originally methods on ``ImportPages`` — extracted to keep
``import_pages.py`` focused on render/POST orchestration.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any

from hoa_accounting.web.import_parsing import parse_bool

# ── Cell helpers ───────────────────────────────────────────────────────


def _v(row: dict[str, Any], name: str, default: Any = None) -> Any:
    v = row.get(name, "").strip()
    return v if v else default


def _bool(row: dict[str, Any], name: str, default: int = 1) -> int:
    v = row.get(name, "").strip()
    return parse_bool(v, default) if v else default


def _lookup(
    conn: sqlite3.Connection,
    table: str,
    key_col: str,
    value: str,
    label: str | None = None,
) -> tuple[int | None, list[str]]:
    """Return (id, []) on hit, (None, [error]) on miss / blank input."""
    if not value:
        return None, [f"{label or key_col} is required."]
    row = conn.execute(
        f"SELECT id FROM {table} WHERE {key_col}=?", (value,)  # noqa: S608
    ).fetchone()
    if not row:
        return None, [f'{label or key_col} "{value}" not found.']
    return int(row[0]), []


# ── Static data inserters ──────────────────────────────────────────────


def insert_categories(conn: sqlite3.Connection, row: dict[str, Any]) -> list[str]:
    code = _v(row, "code", "").upper()
    if not code:
        return ["Code is required."]
    if conn.execute("SELECT 1 FROM categories WHERE code=?", (code,)).fetchone():
        return [f'Category code "{code}" already exists.']
    ct = _v(row, "category_type", "").upper()
    fund = _v(row, "fund_code", "OPERATING").upper() or "OPERATING"
    try:
        sort_order = int(_v(row, "sort_order", "0") or "0")
    except ValueError:
        sort_order = 0
    conn.execute(
        """INSERT INTO categories
           (code, name, category_type, fund_code, group_name,
            sort_order, active_flag, description)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            code,
            _v(row, "name"),
            ct,
            fund,
            _v(row, "group_name"),
            sort_order,
            _bool(row, "active", 1),
            _v(row, "description"),
        ),
    )
    return []


def insert_owners(conn: sqlite3.Connection, row: dict[str, Any]) -> list[str]:
    dn = _v(row, "display_name")
    if conn.execute("SELECT 1 FROM owners WHERE display_name=?", (dn,)).fetchone():
        return [f'Owner "{dn}" already exists.']
    conn.execute(
        """INSERT INTO owners
           (owner_type, display_name, first_name, last_name, entity_name,
            mailing_address_1, mailing_address_2, city, state, postal_code,
            phone, email, active_flag, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            _v(row, "owner_type", "").upper(),
            dn,
            _v(row, "first_name"),
            _v(row, "last_name"),
            _v(row, "entity_name"),
            _v(row, "mailing_address_1"),
            _v(row, "mailing_address_2"),
            _v(row, "city"),
            _v(row, "state"),
            _v(row, "postal_code"),
            _v(row, "phone"),
            _v(row, "email"),
            _bool(row, "active", 1),
            _v(row, "notes"),
        ),
    )
    return []


def insert_vendors(conn: sqlite3.Connection, row: dict[str, Any]) -> list[str]:
    vn = _v(row, "vendor_name")
    if conn.execute("SELECT 1 FROM vendors WHERE vendor_name=?", (vn,)).fetchone():
        return [f'Vendor "{vn}" already exists.']
    conn.execute(
        """INSERT INTO vendors
           (vendor_name, contact_name, email, phone,
            address_1, address_2, city, state, postal_code,
            active_flag, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            vn,
            _v(row, "contact_name"),
            _v(row, "email"),
            _v(row, "phone"),
            _v(row, "address_1"),
            _v(row, "address_2"),
            _v(row, "city"),
            _v(row, "state"),
            _v(row, "postal_code"),
            _bool(row, "active", 1),
            _v(row, "notes"),
        ),
    )
    return []


def insert_budgets(conn: sqlite3.Connection, row: dict[str, Any]) -> list[str]:
    fy = int(_v(row, "fiscal_year", 0))
    fc = _v(row, "fund_code", "").upper()
    if conn.execute(
        "SELECT 1 FROM budgets WHERE fiscal_year=? AND fund_code=?", (fy, fc)
    ).fetchone():
        return [f"Budget {fy} / {fc} already exists."]
    conn.execute(
        "INSERT INTO budgets (fiscal_year, fund_code, status, notes) VALUES (?,?,?,?)",
        (fy, fc, _v(row, "status", "DRAFT").upper(), _v(row, "notes")),
    )
    return []


def insert_lots(conn: sqlite3.Connection, row: dict[str, Any]) -> list[str]:
    ln = _v(row, "lot_number")
    if conn.execute("SELECT 1 FROM lots WHERE lot_number=?", (ln,)).fetchone():
        return [f'Lot "{ln}" already exists.']
    conn.execute(
        """INSERT INTO lots
           (lot_number, street_address_1, street_address_2,
            city, state, postal_code, legal_description, active_flag)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            ln,
            _v(row, "street_address_1"),
            _v(row, "street_address_2"),
            _v(row, "city"),
            _v(row, "state"),
            _v(row, "postal_code"),
            _v(row, "legal_description"),
            _bool(row, "active", 1),
        ),
    )
    return []


def insert_bank_accounts(conn: sqlite3.Connection, row: dict[str, Any]) -> list[str]:
    an = _v(row, "account_name")
    if conn.execute(
        "SELECT 1 FROM bank_accounts WHERE account_name=?", (an,)
    ).fetchone():
        return [f'Bank account "{an}" already exists.']
    fund = (_v(row, "fund_code", "OPERATING") or "OPERATING").upper()
    if fund not in ("OPERATING", "RESERVE", "SPECIAL"):
        fund = "OPERATING"
    conn.execute(
        """INSERT INTO bank_accounts
           (account_name, institution_name, account_last4, account_type,
            fund_code, active_flag)
           VALUES (?,?,?,?,?,?)""",
        (
            an,
            _v(row, "institution_name"),
            _v(row, "account_last4"),
            _v(row, "account_type", "").upper(),
            fund,
            _bool(row, "active", 1),
        ),
    )
    return []


def insert_lot_ownership(conn: sqlite3.Connection, row: dict[str, Any]) -> list[str]:
    lot_num = _v(row, "lot_number")
    lot_row = conn.execute(
        "SELECT id FROM lots WHERE lot_number=?", (lot_num,)
    ).fetchone()
    if not lot_row:
        return [f'Lot "{lot_num}" not found. Import Lots first.']

    owner_name = _v(row, "owner_name")
    owner_row = conn.execute(
        "SELECT id FROM owners WHERE display_name=?", (owner_name,)
    ).fetchone()
    if not owner_row:
        return [f'Owner "{owner_name}" not found. Import Owners first.']

    sd = _v(row, "start_date")
    if conn.execute(
        "SELECT 1 FROM lot_ownership WHERE lot_id=? AND owner_id=? AND start_date=?",
        (lot_row[0], owner_row[0], sd),
    ).fetchone():
        return ["This lot / owner / start-date combination already exists."]

    conn.execute(
        """INSERT INTO lot_ownership
           (lot_id, owner_id, start_date, end_date)
           VALUES (?,?,?,?)""",
        (lot_row[0], owner_row[0], sd, _v(row, "end_date") or None),
    )
    return []


def insert_renters(conn: sqlite3.Connection, row: dict[str, Any]) -> list[str]:
    lot_num = _v(row, "lot_number")
    lot_row = conn.execute(
        "SELECT id FROM lots WHERE lot_number=?", (lot_num,)
    ).fetchone()
    if not lot_row:
        return [f'Lot "{lot_num}" not found. Import Lots first.']
    conn.execute(
        """INSERT INTO lot_renters
           (lot_id, display_name, first_name, last_name,
            email, phone, start_date, end_date, notes)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            lot_row[0],
            _v(row, "display_name"),
            _v(row, "first_name"),
            _v(row, "last_name"),
            _v(row, "email"),
            _v(row, "phone"),
            _v(row, "start_date") or None,
            _v(row, "end_date") or None,
            _v(row, "notes"),
        ),
    )
    return []


def insert_budget_lines(conn: sqlite3.Connection, row: dict[str, Any]) -> list[str]:
    fy = int(_v(row, "fiscal_year", 0))
    fc = _v(row, "fund_code", "").upper()
    budget_row = conn.execute(
        "SELECT id FROM budgets WHERE fiscal_year=? AND fund_code=?", (fy, fc)
    ).fetchone()
    if not budget_row:
        return [f"Budget {fy} / {fc} not found. Import Budgets first."]

    cat_code = _v(row, "category_code", "").upper()
    cat_row = conn.execute(
        "SELECT id FROM categories WHERE UPPER(code)=?", (cat_code,)
    ).fetchone()
    if not cat_row:
        return [f'Category "{cat_code}" not found. Import Categories first.']

    period = int(_v(row, "fiscal_period", 0))
    if not 1 <= period <= 12:
        return [f"Fiscal period must be 1–12 (got {period})."]

    if conn.execute(
        "SELECT 1 FROM budget_lines "
        "WHERE budget_id=? AND category_id=? AND fiscal_period=?",
        (budget_row[0], cat_row[0], period),
    ).fetchone():
        return ["This budget / category / period combination already exists."]

    conn.execute(
        """INSERT INTO budget_lines (budget_id, category_id, fiscal_period, budget_amount)
           VALUES (?,?,?,?)""",
        (
            budget_row[0],
            cat_row[0],
            period,
            Decimal(str(_v(row, "budget_amount", "0"))),
        ),
    )
    return []


# ── Transactional imports (mid-year migration) ─────────────────────────


def insert_deposit_batches(conn: sqlite3.Connection, row: dict[str, Any]) -> list[str]:
    bank_id, errs = _lookup(
        conn,
        "bank_accounts",
        "account_name",
        _v(row, "bank_account_name"),
        "Bank account",
    )
    if errs:
        return errs
    cat_code = (_v(row, "category_code", "") or "").upper()
    cat_id = None
    if cat_code:
        cid, e = _lookup(conn, "categories", "UPPER(code)", cat_code, "Category")
        if e:
            return e
        cat_id = cid
    try:
        total = Decimal(_v(row, "total_amount", "0"))
    except (InvalidOperation, ValueError):
        return ["Total amount must be a number."]
    deposit_date = _v(row, "deposit_date")
    if conn.execute(
        """SELECT 1 FROM deposit_batches
            WHERE deposit_date=? AND bank_account_id=? AND total_amount=?""",
        (deposit_date, bank_id, str(total)),
    ).fetchone():
        return ["A deposit with this date / bank / amount already exists."]
    conn.execute(
        """INSERT INTO deposit_batches
           (deposit_date, bank_account_id, total_amount, category_id, notes)
           VALUES (?,?,?,?,?)""",
        (deposit_date, bank_id, str(total), cat_id, _v(row, "notes")),
    )
    return []


def insert_assessments(conn: sqlite3.Connection, row: dict[str, Any]) -> list[str]:
    lot_id, errs = _lookup(conn, "lots", "lot_number", _v(row, "lot_number"), "Lot")
    if errs:
        return errs
    owner_id, errs = _lookup(
        conn, "owners", "display_name", _v(row, "owner_name"), "Owner"
    )
    if errs:
        return errs
    cat_id = None
    cat_code = (_v(row, "category_code", "") or "").upper()
    if cat_code:
        cid, e = _lookup(conn, "categories", "UPPER(code)", cat_code, "Category")
        if e:
            return e
        cat_id = cid
    try:
        amt = Decimal(_v(row, "amount", "0"))
    except (InvalidOperation, ValueError):
        return ["Amount must be a number."]
    charge_type = (_v(row, "charge_type", "") or "").upper()
    assessment_date = _v(row, "assessment_date")
    due_date = _v(row, "due_date")
    status = (_v(row, "status", "OPEN") or "OPEN").upper()
    if conn.execute(
        """SELECT 1 FROM assessments
            WHERE lot_id=? AND owner_id=? AND charge_type=?
              AND assessment_date=? AND amount=?""",
        (lot_id, owner_id, charge_type, assessment_date, str(amt)),
    ).fetchone():
        return ["This lot / owner / charge_type / date / amount already exists."]
    conn.execute(
        """INSERT INTO assessments
           (lot_id, owner_id, charge_type, assessment_date, due_date,
            amount, status, category_id, description)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            lot_id,
            owner_id,
            charge_type,
            assessment_date,
            due_date,
            str(amt),
            status,
            cat_id,
            _v(row, "description"),
        ),
    )
    return []


def insert_payments(conn: sqlite3.Connection, row: dict[str, Any]) -> list[str]:
    receipt = _v(row, "receipt_number")
    if not receipt:
        return ["Receipt Number is required."]
    if conn.execute(
        "SELECT 1 FROM payments WHERE receipt_number=?", (receipt,)
    ).fetchone():
        return [f'Receipt "{receipt}" already exists.']
    owner_id, errs = _lookup(
        conn, "owners", "display_name", _v(row, "owner_name"), "Owner"
    )
    if errs:
        return errs
    bank_id, errs = _lookup(
        conn,
        "bank_accounts",
        "account_name",
        _v(row, "bank_account_name"),
        "Bank account",
    )
    if errs:
        return errs
    cat_id = None
    cat_code = (_v(row, "category_code", "") or "").upper()
    if cat_code:
        cid, e = _lookup(conn, "categories", "UPPER(code)", cat_code, "Category")
        if e:
            return e
        cat_id = cid
    try:
        amt = Decimal(_v(row, "amount", "0"))
    except (InvalidOperation, ValueError):
        return ["Amount must be a number."]
    method = (_v(row, "payment_method", "") or "").upper()
    conn.execute(
        """INSERT INTO payments
           (receipt_number, owner_id, payment_date, amount, payment_method,
            reference_number, bank_account_id, category_id, notes)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            receipt,
            owner_id,
            _v(row, "payment_date"),
            str(amt),
            method,
            _v(row, "reference_number"),
            bank_id,
            cat_id,
            _v(row, "notes"),
        ),
    )
    return []


def insert_vendor_bills(conn: sqlite3.Connection, row: dict[str, Any]) -> list[str]:
    vendor_id, errs = _lookup(
        conn, "vendors", "vendor_name", _v(row, "vendor_name"), "Vendor"
    )
    if errs:
        return errs
    cat_id, errs = _lookup(
        conn,
        "categories",
        "UPPER(code)",
        (_v(row, "category_code", "") or "").upper(),
        "Category",
    )
    if errs:
        return errs
    invoice = _v(row, "invoice_number")
    if conn.execute(
        "SELECT 1 FROM vendor_bills WHERE vendor_id=? AND invoice_number=?",
        (vendor_id, invoice),
    ).fetchone():
        return [f'Invoice "{invoice}" already exists for this vendor.']
    try:
        amt = Decimal(_v(row, "amount", "0"))
    except (InvalidOperation, ValueError):
        return ["Amount must be a number."]
    fund = (_v(row, "fund_code", "OPERATING") or "OPERATING").upper()
    if fund not in ("OPERATING", "RESERVE", "SPECIAL"):
        fund = "OPERATING"
    status = (_v(row, "status", "OPEN") or "OPEN").upper()
    conn.execute(
        """INSERT INTO vendor_bills
           (vendor_id, invoice_number, invoice_date, due_date, amount,
            fund_code, status, description, category_id)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            vendor_id,
            invoice,
            _v(row, "invoice_date"),
            _v(row, "due_date") or None,
            str(amt),
            fund,
            status,
            _v(row, "description"),
            cat_id,
        ),
    )
    return []


def insert_bill_payments(conn: sqlite3.Connection, row: dict[str, Any]) -> list[str]:
    vn = _v(row, "vendor_name")
    inv = _v(row, "invoice_number")
    bill = conn.execute(
        """SELECT vb.id FROM vendor_bills vb
            JOIN vendors v ON v.id = vb.vendor_id
            WHERE v.vendor_name=? AND vb.invoice_number=?""",
        (vn, inv),
    ).fetchone()
    if not bill:
        return [f'Bill "{inv}" for vendor "{vn}" not found.']
    bank_id, errs = _lookup(
        conn,
        "bank_accounts",
        "account_name",
        _v(row, "bank_account_name"),
        "Bank account",
    )
    if errs:
        return errs
    try:
        amt = Decimal(_v(row, "amount", "0"))
    except (InvalidOperation, ValueError):
        return ["Amount must be a number."]
    if conn.execute(
        """SELECT 1 FROM bill_payments
            WHERE vendor_bill_id=? AND payment_date=? AND amount=?""",
        (int(bill[0]), _v(row, "payment_date"), str(amt)),
    ).fetchone():
        return ["A payment for this bill / date / amount already exists."]
    conn.execute(
        """INSERT INTO bill_payments
           (vendor_bill_id, payment_date, amount, bank_account_id,
            check_number, notes)
           VALUES (?,?,?,?,?,?)""",
        (
            int(bill[0]),
            _v(row, "payment_date"),
            str(amt),
            bank_id,
            _v(row, "check_number"),
            _v(row, "notes"),
        ),
    )
    return []


def insert_non_dues_income(conn: sqlite3.Connection, row: dict[str, Any]) -> list[str]:
    bank_id, errs = _lookup(
        conn,
        "bank_accounts",
        "account_name",
        _v(row, "bank_account_name"),
        "Bank account",
    )
    if errs:
        return errs
    cat_id = None
    cat_code = (_v(row, "category_code", "") or "").upper()
    if cat_code:
        cid, e = _lookup(conn, "categories", "UPPER(code)", cat_code, "Category")
        if e:
            return e
        cat_id = cid
    try:
        total = Decimal(_v(row, "total_amount", "0"))
    except (InvalidOperation, ValueError):
        return ["Total amount must be a number."]
    posting_date = _v(row, "posting_date")
    desc = _v(row, "income_description")
    if conn.execute(
        """SELECT 1 FROM income_batches
            WHERE posting_date=? AND bank_account_id=?
              AND income_description=? AND total_amount=?""",
        (posting_date, bank_id, desc, str(total)),
    ).fetchone():
        return ["A batch with this date / bank / description / amount already exists."]
    conn.execute(
        """INSERT INTO income_batches
           (posting_date, bank_account_id, income_description,
            total_amount, notes, category_id)
           VALUES (?,?,?,?,?,?)""",
        (posting_date, bank_id, desc, str(total), _v(row, "notes"), cat_id),
    )
    return []


def insert_reserve_transfers(
    conn: sqlite3.Connection, row: dict[str, Any]
) -> list[str]:
    from_id, errs = _lookup(
        conn,
        "bank_accounts",
        "account_name",
        _v(row, "from_bank_account"),
        "From bank account",
    )
    if errs:
        return errs
    to_id, errs = _lookup(
        conn,
        "bank_accounts",
        "account_name",
        _v(row, "to_bank_account"),
        "To bank account",
    )
    if errs:
        return errs
    if from_id == to_id:
        return ["From and To bank accounts must be different."]
    try:
        amt = Decimal(_v(row, "amount", "0"))
    except (InvalidOperation, ValueError):
        return ["Amount must be a number."]
    transfer_date = _v(row, "transfer_date")
    if conn.execute(
        """SELECT 1 FROM reserve_transfers
            WHERE transfer_date=? AND from_bank_account_id=?
              AND to_bank_account_id=? AND amount=?""",
        (transfer_date, from_id, to_id, str(amt)),
    ).fetchone():
        return ["A transfer with this date / accounts / amount already exists."]
    conn.execute(
        """INSERT INTO reserve_transfers
           (transfer_date, from_bank_account_id, to_bank_account_id,
            amount, transfer_type, purpose, notes)
           VALUES (?,?,?,?,?,?,?)""",
        (
            transfer_date,
            from_id,
            to_id,
            str(amt),
            (_v(row, "transfer_type", "") or "").upper() or None,
            _v(row, "purpose"),
            _v(row, "notes"),
        ),
    )
    return []


def insert_board_members(conn: sqlite3.Connection, row: dict[str, Any]) -> list[str]:
    conn.execute(
        """INSERT INTO board_members
           (full_name, title, email, phone, start_date, end_date, is_active, notes)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            _v(row, "full_name"),
            _v(row, "title"),
            _v(row, "email"),
            _v(row, "phone"),
            _v(row, "start_date") or None,
            _v(row, "end_date") or None,
            _bool(row, "active", 1),
            _v(row, "notes"),
        ),
    )
    return []


def insert_assessment_rules(conn: sqlite3.Connection, row: dict[str, Any]) -> list[str]:
    rn = _v(row, "rule_name")
    if not rn:
        return ["Rule Name is required."]
    if conn.execute(
        "SELECT 1 FROM assessment_rules WHERE rule_name=?", (rn,)
    ).fetchone():
        return [f'Rule "{rn}" already exists.']
    cat_code = (_v(row, "category_code", "DUES") or "DUES").upper()
    cat_row = conn.execute(
        "SELECT id FROM categories WHERE UPPER(code)=?", (cat_code,)
    ).fetchone()
    if not cat_row:
        return [f'Category "{cat_code}" not found.']
    try:
        amt = Decimal(_v(row, "default_amount", "0"))
    except ValueError:
        return ["Default Amount must be a number."]
    conn.execute(
        """INSERT INTO assessment_rules
           (rule_name, frequency, default_amount, category_id,
            fund_code, effective_start_date, effective_end_date,
            active_flag, notes)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            rn,
            _v(row, "frequency", "").upper(),
            amt,
            cat_row[0],
            (_v(row, "fund_code", "OPERATING") or "OPERATING").upper(),
            _v(row, "effective_start_date"),
            _v(row, "effective_end_date") or None,
            _bool(row, "active", 1),
            _v(row, "notes"),
        ),
    )
    return []


def insert_bank_transaction_rules(
    conn: sqlite3.Connection, row: dict[str, Any]
) -> list[str]:
    rn = _v(row, "rule_name")
    if not rn:
        return ["Rule Name is required."]
    if conn.execute(
        "SELECT 1 FROM bank_transaction_rules WHERE rule_name=?", (rn,)
    ).fetchone():
        return [f'Rule "{rn}" already exists.']

    def _opt_lookup(table: str, col: str, val: Any) -> int | None:
        if not val:
            return None
        r = conn.execute(
            f"SELECT id FROM {table} WHERE {col}=?", (val,)  # noqa: S608
        ).fetchone()
        return r[0] if r else None

    cat_code = _v(row, "category_code", "")
    cat_id = None
    if cat_code:
        r = conn.execute(
            "SELECT id FROM categories WHERE UPPER(code)=UPPER(?)", (cat_code,)
        ).fetchone()
        if not r:
            return [f'Category code "{cat_code}" not found.']
        cat_id = r[0]
    vname = _v(row, "vendor_name", "")
    vendor_id = _opt_lookup("vendors", "vendor_name", vname)
    if vname and vendor_id is None:
        return [f'Vendor "{vname}" not found.']
    lnum = _v(row, "lot_number", "")
    lot_id = _opt_lookup("lots", "lot_number", lnum)
    if lnum and lot_id is None:
        return [f'Lot "{lnum}" not found.']
    baname = _v(row, "bank_account_name", "")
    ba_id = _opt_lookup("bank_accounts", "account_name", baname)
    if baname and ba_id is None:
        return [f'Bank account "{baname}" not found.']
    try:
        apan = int(_v(row, "auto_post_after_n", "3") or "3")
    except ValueError:
        apan = 3
    conn.execute(
        """INSERT INTO bank_transaction_rules
           (rule_name, action_type, description_contains, match_type,
            match_memo, match_amount, category_id, vendor_id, lot_id,
            bank_account_id, default_memo,
            confidence_mode, auto_post_after_n, active_flag)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            rn,
            _v(row, "action_type", "").lower(),
            _v(row, "description_contains", ""),
            _v(row, "match_type", ""),
            _v(row, "match_memo", ""),
            _v(row, "match_amount", ""),
            cat_id,
            vendor_id,
            lot_id,
            ba_id,
            _v(row, "default_memo", ""),
            _v(row, "confidence_mode", "review_first") or "review_first",
            apan,
            _bool(row, "active", 1),
        ),
    )
    return []


def insert_opening_balances(conn: sqlite3.Connection, row: dict[str, Any]) -> list[str]:
    et = _v(row, "entity_type", "").upper()
    if et not in ("BANK_ACCOUNT", "LOT_DUES", "LOT_ASSESSMENT"):
        return ['Entity Type must be "BANK_ACCOUNT", "LOT_DUES", or "LOT_ASSESSMENT".']
    key = _v(row, "entity_key", "")
    if et == "BANK_ACCOUNT":
        r = conn.execute(
            "SELECT id FROM bank_accounts WHERE account_name=?", (key,)
        ).fetchone()
        if not r:
            return [f'Bank account "{key}" not found.']
        entity_id = r[0]
    else:
        r = conn.execute("SELECT id FROM lots WHERE lot_number=?", (key,)).fetchone()
        if not r:
            return [f'Lot "{key}" not found.']
        entity_id = r[0]
    as_of = _v(row, "as_of_date")
    if conn.execute(
        "SELECT 1 FROM opening_balances WHERE entity_type=? AND entity_id=?",
        (et, entity_id),
    ).fetchone():
        return [
            "This entity already has an opening balance — delete it first to re-import."
        ]
    try:
        amt = Decimal(_v(row, "amount", "0"))
    except (InvalidOperation, ValueError):
        return ["Amount must be a number."]
    conn.execute(
        """INSERT INTO opening_balances (as_of_date, entity_type, entity_id, amount)
           VALUES (?,?,?,?)""",
        (as_of, et, entity_id, amt),
    )
    return []


# ── Dispatch table ─────────────────────────────────────────────────────


# Maps the import data_type string → its inserter. ImportPages._insert_row
# looks up here instead of using getattr(self, f"_insert_{data_type}").
INSERTERS: dict[str, Callable[[sqlite3.Connection, dict[str, Any]], list[str]]] = {
    "categories": insert_categories,
    "owners": insert_owners,
    "vendors": insert_vendors,
    "budgets": insert_budgets,
    "lots": insert_lots,
    "bank_accounts": insert_bank_accounts,
    "lot_ownership": insert_lot_ownership,
    "renters": insert_renters,
    "budget_lines": insert_budget_lines,
    "deposit_batches": insert_deposit_batches,
    "assessments": insert_assessments,
    "payments": insert_payments,
    "vendor_bills": insert_vendor_bills,
    "bill_payments": insert_bill_payments,
    "non_dues_income": insert_non_dues_income,
    "reserve_transfers": insert_reserve_transfers,
    "board_members": insert_board_members,
    "assessment_rules": insert_assessment_rules,
    "bank_transaction_rules": insert_bank_transaction_rules,
    "opening_balances": insert_opening_balances,
}
