"""Service-level validation tests."""

from __future__ import annotations

import sqlite3

from hoa_accounting.bootstrap.migrator import Migrator

import pytest

from hoa_accounting.db.transaction import transaction
from hoa_accounting.exceptions import ValidationError
from hoa_accounting.services.factory import ServiceFactory

import pytest
pytestmark = pytest.mark.skip(
    reason="Pending rewrite after Chart of Accounts removal (migration 0061)"
)
SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, full_name TEXT NOT NULL, password_hash TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1, last_login_at TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE lots (id INTEGER PRIMARY KEY, lot_number TEXT NOT NULL UNIQUE);
CREATE TABLE owners (id INTEGER PRIMARY KEY, owner_type TEXT NOT NULL DEFAULT 'PERSON', display_name TEXT NOT NULL, active_flag INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE vendors (id INTEGER PRIMARY KEY, vendor_name TEXT NOT NULL, active_flag INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE account_types (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, normal_balance TEXT NOT NULL, financial_statement_group TEXT NOT NULL);
CREATE TABLE accounts (id INTEGER PRIMARY KEY, account_number TEXT NOT NULL UNIQUE, account_name TEXT NOT NULL, account_type_id INTEGER NOT NULL, fund_code TEXT NOT NULL DEFAULT 'OPERATING', is_bank_account INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1, description TEXT, group_code TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE accounting_periods (id INTEGER PRIMARY KEY, period_name TEXT NOT NULL UNIQUE, start_date TEXT NOT NULL, end_date TEXT NOT NULL, fiscal_year INTEGER NOT NULL, fiscal_period INTEGER NOT NULL, is_closed INTEGER NOT NULL DEFAULT 0, closed_at TEXT, closed_by_user_id INTEGER);
CREATE TABLE journal_entries (id INTEGER PRIMARY KEY, entry_number TEXT NOT NULL UNIQUE, entry_date TEXT NOT NULL, accounting_period_id INTEGER NOT NULL, source_type TEXT NOT NULL, source_id INTEGER, memo TEXT, status TEXT NOT NULL DEFAULT 'POSTED', reversal_entry_id INTEGER, created_by_user_id INTEGER, approved_by_user_id INTEGER, posted_at TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE journal_entry_lines (id INTEGER PRIMARY KEY, journal_entry_id INTEGER NOT NULL, line_number INTEGER NOT NULL, account_id INTEGER NOT NULL, lot_id INTEGER, owner_id INTEGER, vendor_id INTEGER, description TEXT, debit_amount NUMERIC NOT NULL DEFAULT 0, credit_amount NUMERIC NOT NULL DEFAULT 0, expense_classification TEXT);
CREATE TABLE assessments (id INTEGER PRIMARY KEY, lot_id INTEGER NOT NULL, owner_id INTEGER NOT NULL, assessment_rule_id INTEGER, assessment_date TEXT NOT NULL, due_date TEXT NOT NULL, amount NUMERIC NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', journal_entry_id INTEGER NOT NULL UNIQUE, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE payments (id INTEGER PRIMARY KEY, receipt_number TEXT NOT NULL UNIQUE, owner_id INTEGER NOT NULL, payment_date TEXT NOT NULL, amount NUMERIC NOT NULL, payment_method TEXT NOT NULL, reference_number TEXT, bank_account_id INTEGER NOT NULL, journal_entry_id INTEGER NOT NULL, notes TEXT, deposit_batch_id INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE payment_applications (id INTEGER PRIMARY KEY, payment_id INTEGER NOT NULL, assessment_id INTEGER NOT NULL, applied_amount NUMERIC NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE bank_accounts (id INTEGER PRIMARY KEY, account_name TEXT NOT NULL, institution_name TEXT NOT NULL, account_last4 TEXT, account_type TEXT NOT NULL, gl_account_id INTEGER NOT NULL UNIQUE, active_flag INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE vendor_bills (id INTEGER PRIMARY KEY, vendor_id INTEGER NOT NULL, invoice_number TEXT NOT NULL, invoice_date TEXT NOT NULL, due_date TEXT, amount NUMERIC NOT NULL, expense_account_id INTEGER NOT NULL, payable_account_id INTEGER NOT NULL, fund_code TEXT NOT NULL DEFAULT 'OPERATING', status TEXT NOT NULL DEFAULT 'OPEN', journal_entry_id INTEGER NOT NULL UNIQUE, description TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE bill_payments (id INTEGER PRIMARY KEY, vendor_bill_id INTEGER NOT NULL, payment_date TEXT NOT NULL, amount NUMERIC NOT NULL, bank_account_id INTEGER NOT NULL, check_number TEXT, journal_entry_id INTEGER NOT NULL UNIQUE, notes TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE reserve_transfers (id INTEGER PRIMARY KEY, transfer_date TEXT NOT NULL, from_account_id INTEGER NOT NULL, to_account_id INTEGER NOT NULL, amount NUMERIC NOT NULL, journal_entry_id INTEGER NOT NULL UNIQUE, notes TEXT, transfer_type TEXT CHECK (transfer_type IN ('FUND', 'WITHDRAW')), purpose TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE opening_balances (id INTEGER PRIMARY KEY, entity_type TEXT NOT NULL CHECK (entity_type IN ('BANK_ACCOUNT', 'LOT')), entity_id INTEGER NOT NULL, as_of_date TEXT NOT NULL, amount NUMERIC NOT NULL DEFAULT 0, journal_entry_id INTEGER REFERENCES journal_entries(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE (entity_type, entity_id));
CREATE TABLE audit_log (id INTEGER PRIMARY KEY, event_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, user_id INTEGER, entity_type TEXT NOT NULL, entity_id INTEGER NOT NULL, action TEXT NOT NULL, before_json TEXT, after_json TEXT, ip_address TEXT, user_agent TEXT);
"""

def build_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    Migrator().apply_all(conn)
    conn.execute("INSERT INTO accounting_periods (id, period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed) VALUES (1, '2026-01', '2026-01-01', '2026-01-31', 2026, 1, 0)")
    conn.execute("INSERT INTO users (id, email, full_name, password_hash, is_active) VALUES (1, 'a@example.com', 'Admin', 'x', 1)")
    conn.execute("INSERT INTO lots (id, lot_number) VALUES (1, '1')")
    conn.execute("INSERT INTO owners (id, display_name, owner_type, active_flag) VALUES (1, 'Owner 1', 'PERSON', 1)")
    conn.execute("INSERT INTO vendors (id, vendor_name, active_flag) VALUES (1, 'Vendor 1', 1)")
    conn.execute("INSERT INTO accounts (id, account_number, account_name, account_type_id, fund_code, is_bank_account, is_active) VALUES (1000, '1000', 'Cash', 1, 'OPERATING', 1, 1)")
    conn.execute("INSERT INTO accounts (id, account_number, account_name, account_type_id, fund_code, is_bank_account, is_active) VALUES (1010, '1010', 'Reserve Cash', 1, 'RESERVE', 1, 1)")
    conn.execute("INSERT INTO accounts (id, account_number, account_name, account_type_id, fund_code, is_bank_account, is_active) VALUES (1100, '1100', 'AR', 1, 'OPERATING', 0, 1)")
    conn.execute("INSERT INTO accounts (id, account_number, account_name, account_type_id, fund_code, is_bank_account, is_active) VALUES (2000, '2000', 'AP', 2, 'OPERATING', 0, 1)")
    conn.execute("INSERT INTO accounts (id, account_number, account_name, account_type_id, fund_code, is_bank_account, is_active) VALUES (4000, '4000', 'Assessment Income', 4, 'OPERATING', 0, 1)")
    conn.execute("INSERT INTO accounts (id, account_number, account_name, account_type_id, fund_code, is_bank_account, is_active) VALUES (6000, '6000', 'Expense', 5, 'OPERATING', 0, 1)")
    conn.execute("INSERT INTO bank_accounts (id, account_name, institution_name, account_last4, account_type, gl_account_id, active_flag) VALUES (1, 'Checking', 'Bank', '1234', 'CHECKING', 1000, 1)")
    conn.commit()
    return conn

@pytest.mark.skip(reason="pending single-entry rewrite (double-entry contract retired)")
def test_assessment_rejects_liability_as_income_account() -> None:
    conn = build_conn()
    factory = ServiceFactory(conn)
    with transaction(conn), pytest.raises(ValidationError):
        factory.assessment_service().post_assessment(
            entry_date="2026-01-10",
            lot_id=1,
            owner_id=1,
            amount="100.00",
            description="Bad assessment",
            receivable_account_id=1100,
            income_account_id=2000,
            created_by_user_id=1,
        )

@pytest.mark.skip(reason="pending single-entry rewrite (double-entry contract retired)")
def test_vendor_bill_rejects_asset_as_expense_account() -> None:
    conn = build_conn()
    factory = ServiceFactory(conn)
    with transaction(conn), pytest.raises(ValidationError):
        factory.vendor_bill_service().post_vendor_bill(
            entry_date="2026-01-12",
            vendor_id=1,
            amount="55.00",
            description="Bad vendor bill",
            expense_account_id=1000,
            payable_account_id=2000,
            invoice_number="INV-1",
            invoice_date="2026-01-12",
            created_by_user_id=1,
        )

def test_reserve_transfer_posts_record() -> None:
    conn = build_conn()
    factory = ServiceFactory(conn)
    with transaction(conn):
        result = factory.reserve_transfer_service().post_reserve_transfer(
            entry_date="2026-01-31",
            amount="25.00",
            description="Monthly reserve transfer",
            from_account_id=1000,
            to_account_id=1010,
            created_by_user_id=1,
        )
    row = conn.execute("SELECT amount FROM reserve_transfers WHERE id = ?", (result.reserve_transfer_id,)).fetchone()
    assert row is not None
    from decimal import Decimal
    assert Decimal(str(row["amount"])) == Decimal("25.00")
