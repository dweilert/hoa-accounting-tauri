"""Tests for the report API layer."""

from __future__ import annotations

import sqlite3

from hoa_accounting.api.report_api import ReportAPIService
from hoa_accounting.application.report_runner import ReportRunner
from hoa_accounting.db.transaction import transaction
from hoa_accounting.services.factory import ServiceFactory

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, full_name TEXT NOT NULL, password_hash TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1, last_login_at TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE lots (id INTEGER PRIMARY KEY, lot_number TEXT NOT NULL UNIQUE);
CREATE TABLE owners (id INTEGER PRIMARY KEY, owner_type TEXT NOT NULL DEFAULT 'PERSON', display_name TEXT NOT NULL, active_flag INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE vendors (id INTEGER PRIMARY KEY, vendor_name TEXT NOT NULL, active_flag INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE account_types (id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL, normal_balance TEXT NOT NULL, financial_statement_group TEXT NOT NULL);
CREATE TABLE accounts (id INTEGER PRIMARY KEY, account_number TEXT NOT NULL UNIQUE, account_name TEXT NOT NULL, account_type_id INTEGER NOT NULL, fund_code TEXT NOT NULL DEFAULT 'OPERATING', is_bank_account INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1, description TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE accounting_periods (id INTEGER PRIMARY KEY, period_name TEXT NOT NULL UNIQUE, start_date TEXT NOT NULL, end_date TEXT NOT NULL, fiscal_year INTEGER NOT NULL, fiscal_period INTEGER NOT NULL, is_closed INTEGER NOT NULL DEFAULT 0, closed_at TEXT, closed_by_user_id INTEGER);
CREATE TABLE journal_entries (id INTEGER PRIMARY KEY, entry_number TEXT NOT NULL UNIQUE, entry_date TEXT NOT NULL, accounting_period_id INTEGER NOT NULL, source_type TEXT NOT NULL, source_id INTEGER, memo TEXT, status TEXT NOT NULL DEFAULT 'POSTED', reversal_entry_id INTEGER, created_by_user_id INTEGER, approved_by_user_id INTEGER, posted_at TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE journal_entry_lines (id INTEGER PRIMARY KEY, journal_entry_id INTEGER NOT NULL, line_number INTEGER NOT NULL, account_id INTEGER NOT NULL, lot_id INTEGER, owner_id INTEGER, vendor_id INTEGER, description TEXT, debit_amount NUMERIC NOT NULL DEFAULT 0, credit_amount NUMERIC NOT NULL DEFAULT 0);
CREATE TABLE assessments (id INTEGER PRIMARY KEY, lot_id INTEGER NOT NULL, owner_id INTEGER NOT NULL, assessment_rule_id INTEGER, assessment_date TEXT NOT NULL, due_date TEXT NOT NULL, amount NUMERIC NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', journal_entry_id INTEGER NOT NULL UNIQUE, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE payments (id INTEGER PRIMARY KEY, receipt_number TEXT NOT NULL UNIQUE, owner_id INTEGER NOT NULL, payment_date TEXT NOT NULL, amount NUMERIC NOT NULL, payment_method TEXT NOT NULL, reference_number TEXT, bank_account_id INTEGER NOT NULL, journal_entry_id INTEGER NOT NULL UNIQUE, notes TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE payment_applications (id INTEGER PRIMARY KEY, payment_id INTEGER NOT NULL, assessment_id INTEGER NOT NULL, applied_amount NUMERIC NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE bank_accounts (id INTEGER PRIMARY KEY, account_name TEXT NOT NULL, institution_name TEXT NOT NULL, account_last4 TEXT, account_type TEXT NOT NULL, gl_account_id INTEGER NOT NULL UNIQUE, active_flag INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE vendor_bills (id INTEGER PRIMARY KEY, vendor_id INTEGER NOT NULL, invoice_number TEXT NOT NULL, invoice_date TEXT NOT NULL, due_date TEXT, amount NUMERIC NOT NULL, expense_account_id INTEGER NOT NULL, payable_account_id INTEGER NOT NULL, fund_code TEXT NOT NULL DEFAULT 'OPERATING', status TEXT NOT NULL DEFAULT 'OPEN', journal_entry_id INTEGER NOT NULL UNIQUE, description TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE bill_payments (id INTEGER PRIMARY KEY, vendor_bill_id INTEGER NOT NULL, payment_date TEXT NOT NULL, amount NUMERIC NOT NULL, bank_account_id INTEGER NOT NULL, check_number TEXT, journal_entry_id INTEGER NOT NULL UNIQUE, notes TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE reserve_transfers (id INTEGER PRIMARY KEY, transfer_date TEXT NOT NULL, from_account_id INTEGER NOT NULL, to_account_id INTEGER NOT NULL, amount NUMERIC NOT NULL, journal_entry_id INTEGER NOT NULL UNIQUE, notes TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE owner_adjustments (id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, adjustment_date TEXT NOT NULL, amount NUMERIC NOT NULL, adjustment_type TEXT NOT NULL, reason TEXT, journal_entry_id INTEGER NOT NULL UNIQUE, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE audit_log (id INTEGER PRIMARY KEY, event_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, user_id INTEGER, entity_type TEXT NOT NULL, entity_id INTEGER NOT NULL, action TEXT NOT NULL, before_json TEXT, after_json TEXT, ip_address TEXT, user_agent TEXT);
"""


def build_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)

    conn.execute(
        """
        INSERT INTO accounting_periods
            (id, period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed)
        VALUES
            (1, '2026-01', '2026-01-01', '2026-01-31', 2026, 1, 0)
        """
    )
    conn.execute(
        """
        INSERT INTO users (id, email, full_name, password_hash, is_active)
        VALUES (1, 'a@example.com', 'Admin', 'x', 1)
        """
    )
    conn.execute("INSERT INTO lots (id, lot_number) VALUES (1, '1')")
    conn.execute(
        """
        INSERT INTO owners (id, display_name, owner_type, active_flag)
        VALUES (1, 'Owner 1', 'PERSON', 1)
        """
    )

    conn.execute(
        """
        INSERT INTO account_types (id, code, name, normal_balance, financial_statement_group)
        VALUES (1, 'ASSET', 'Asset', 'DEBIT', 'BALANCE_SHEET')
        """
    )
    conn.execute(
        """
        INSERT INTO account_types (id, code, name, normal_balance, financial_statement_group)
        VALUES (4, 'INCOME', 'Income', 'CREDIT', 'INCOME_STATEMENT')
        """
    )
    conn.execute(
        """
        INSERT INTO accounts
            (id, account_number, account_name, account_type_id, fund_code, is_bank_account, is_active)
        VALUES
            (1000, '1000', 'Cash', 1, 'OPERATING', 1, 1)
        """
    )
    conn.execute(
        """
        INSERT INTO accounts
            (id, account_number, account_name, account_type_id, fund_code, is_bank_account, is_active)
        VALUES
            (1100, '1100', 'AR', 1, 'OPERATING', 0, 1)
        """
    )
    conn.execute(
        """
        INSERT INTO accounts
            (id, account_number, account_name, account_type_id, fund_code, is_bank_account, is_active)
        VALUES
            (4000, '4000', 'Assessment Income', 4, 'OPERATING', 0, 1)
        """
    )
    conn.execute(
        """
        INSERT INTO bank_accounts
            (id, account_name, institution_name, account_last4, account_type, gl_account_id, active_flag)
        VALUES
            (1, 'Checking', 'Bank', '1234', 'CHECKING', 1000, 1)
        """
    )

    conn.commit()
    return conn


def seed_activity(conn: sqlite3.Connection) -> None:
    factory = ServiceFactory(conn)
    with transaction(conn):
        assessment = factory.assessment_service().post_assessment(
            entry_date="2026-01-10",
            lot_id=1,
            owner_id=1,
            amount="100.00",
            description="January assessment",
            receivable_account_id=1100,
            income_account_id=4000,
            created_by_user_id=1,
            due_date="2026-01-31",
        )
        factory.payment_service().post_payment(
            entry_date="2026-01-15",
            owner_id=1,
            amount="40.00",
            description="Partial payment",
            cash_account_id=1000,
            receivable_account_id=1100,
            bank_account_id=1,
            payment_method="ACH",
            receipt_number="API-1",
            created_by_user_id=1,
            apply_to_assessment_ids=[assessment.assessment_id],
        )


class _ConnectionProvider:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __call__(self) -> sqlite3.Connection:
        return self.conn


def test_report_api_health() -> None:
    conn = build_conn()
    runner = ReportRunner(connection_factory=_ConnectionProvider(conn))
    api = ReportAPIService(runner)

    response = api.get_health()

    assert response.status_code == 200
    assert response.body["ok"] is True
    assert response.body["status"] == "ready"


def test_report_api_returns_report_payload() -> None:
    conn = build_conn()
    seed_activity(conn)

    runner = ReportRunner(connection_factory=_ConnectionProvider(conn))
    api = ReportAPIService(runner)

    response = api.get_report(
        report_name="trial-balance",
        query_params={"as_of_date": "2026-01-31"},
    )

    assert response.status_code == 200
    assert response.body["ok"] is True
    assert response.body["report_name"] == "trial-balance"
    assert response.body["data"]["as_of_date"] == "2026-01-31"


def test_report_api_maps_validation_error_to_400() -> None:
    conn = build_conn()
    runner = ReportRunner(connection_factory=_ConnectionProvider(conn))
    api = ReportAPIService(runner)

    response = api.get_report(
        report_name="trial-balance",
        query_params={},
    )

    assert response.status_code == 400
    assert response.body["ok"] is False
    assert response.body["error"]["type"] == "validation_error"


def test_report_api_maps_not_found_to_404() -> None:
    conn = build_conn()
    seed_activity(conn)

    runner = ReportRunner(connection_factory=_ConnectionProvider(conn))
    api = ReportAPIService(runner)

    response = api.get_report(
        report_name="owner-ledger",
        query_params={
            "owner_id": "999",
            "receivable_account_id": "1100",
            "from_date": "2026-01-01",
            "to_date": "2026-01-31",
        },
    )

    assert response.status_code == 404
    assert response.body["ok"] is False
    assert response.body["error"]["type"] == "not_found"