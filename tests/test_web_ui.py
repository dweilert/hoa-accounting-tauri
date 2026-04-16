"""Tests for the minimal report UI layer."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from hoa_accounting.api.report_api import ReportAPIService
from hoa_accounting.application.report_runner import ReportRunner
from hoa_accounting.db.transaction import transaction
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.web.ui_server import HomePageService, ReportConsolePageService

from hoa_accounting.web.view_models import (
    build_home_page_context,
    build_report_console_context,
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
        INSERT INTO accounting_periods
            (id, period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed)
        VALUES
            (2, '2026-02', '2026-02-01', '2026-02-28', 2026, 2, 0)
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
        VALUES (2, 'LIABILITY', 'Liability', 'CREDIT', 'BALANCE_SHEET')
        """
    )
    conn.execute(
        """
        INSERT INTO account_types (id, code, name, normal_balance, financial_statement_group)
        VALUES (3, 'EQUITY', 'Equity', 'CREDIT', 'BALANCE_SHEET')
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
        INSERT INTO account_types (id, code, name, normal_balance, financial_statement_group)
        VALUES (5, 'EXPENSE', 'Expense', 'DEBIT', 'INCOME_STATEMENT')
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
            (3000, '3000', 'Retained Earnings', 3, 'OPERATING', 0, 1)
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
        INSERT INTO accounts
            (id, account_number, account_name, account_type_id, fund_code, is_bank_account, is_active)
        VALUES
            (6000, '6000', 'Expense', 5, 'OPERATING', 0, 1)
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
        january = factory.assessment_service().post_assessment(
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
            receipt_number="UI-1",
            created_by_user_id=1,
            apply_to_assessment_ids=[january.assessment_id],
        )
        factory.assessment_service().post_assessment(
            entry_date="2026-02-10",
            lot_id=1,
            owner_id=1,
            amount="120.00",
            description="February assessment",
            receivable_account_id=1100,
            income_account_id=4000,
            created_by_user_id=1,
            due_date="2026-02-28",
        )


class _ConnectionProvider:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __call__(self) -> sqlite3.Connection:
        return self.conn


def build_services() -> tuple[HomePageService, ReportConsolePageService]:
    conn = build_conn()
    seed_activity(conn)
    runner = ReportRunner(connection_factory=_ConnectionProvider(conn))
    api_service = ReportAPIService(runner)
    base_path = Path(__file__).resolve().parents[1] / "src" / "hoa_accounting" / "web" / "templates"
    home_service = HomePageService(api_service, base_path / "home.html")
    report_service = ReportConsolePageService(api_service, base_path / "report_console.html")
    return home_service, report_service


def test_home_page_renders_dashboard() -> None:
    home_service, _ = build_services()

    response = home_service.render_page()

    assert response.status_code == 200
    # New shell: sidebar, topbar heading, status pill, quick reports panel.
    assert "Dashboard" in response.body_html
    assert "Quick Reports" in response.body_html
    assert "READY" in response.body_html
    assert 'class="sidebar' in response.body_html
    assert 'class="pill' in response.body_html


def test_render_trial_balance_summary_table() -> None:
    _, page_service = build_services()

    response = page_service.render_report(
        report_name="trial-balance",
        query_params={"as_of_date": "2026-01-31"},
    )

    assert response.status_code == 200
    assert "Total Debits" in response.body_html
    assert "Total Credits" in response.body_html
    assert "Assessment Income" in response.body_html


def test_render_balance_sheet_summary_table() -> None:
    _, page_service = build_services()

    response = page_service.render_report(
        report_name="balance-sheet",
        query_params={"as_of_date": "2026-01-31"},
    )

    assert response.status_code == 200
    # Section headings from the redesign; totals-block labels; cumulative line.
    assert "Assets" in response.body_html
    assert "Liabilities" in response.body_html
    assert "Equity" in response.body_html
    assert "Cumulative Earnings" in response.body_html


def test_render_income_statement_summary_table() -> None:
    _, page_service = build_services()

    response = page_service.render_report(
        report_name="income-statement",
        query_params={
            "from_date": "2026-01-01",
            "to_date": "2026-01-31",
        },
    )

    assert response.status_code == 200
    assert "Income" in response.body_html
    assert "Expenses" in response.body_html
    assert "Net Income" in response.body_html
    assert "Assessment Income" in response.body_html


def test_render_owner_ledger_summary_table() -> None:
    _, page_service = build_services()

    response = page_service.render_report(
        report_name="owner-ledger",
        query_params={
            "owner_id": "1",
            "receivable_account_id": "1100",
            "from_date": "2026-01-01",
            "to_date": "2026-01-31",
        },
    )

    assert response.status_code == 200
    assert "Opening Balance" in response.body_html
    assert "Closing Balance" in response.body_html
    assert "Owner 1" in response.body_html
    assert "UI-1" in response.body_html
    assert "Running" in response.body_html


def test_render_ar_aging_summary_table() -> None:
    _, page_service = build_services()

    response = page_service.render_report(
        report_name="ar-aging",
        query_params={
            "as_of_date": "2026-02-28",
            "receivable_account_id": "1100",
        },
    )

    assert response.status_code == 200
    assert "Owner Summaries" in response.body_html
    assert "Open Items" in response.body_html
    assert "Total Open" in response.body_html
    assert "Owner 1" in response.body_html
    # AR aging uses an en-dash in the redesign ("1–30"); accept either form.
    assert "1-30" in response.body_html or "1&#8211;30" in response.body_html or "CURRENT" in response.body_html

def test_build_home_page_context_contains_report_cards() -> None:
    context = build_home_page_context(api_status="READY")

    assert context.api_status == "READY"
    assert len(context.report_cards) >= 1
    assert any(card.name == "trial-balance" for card in context.report_cards)
    assert any(card.title == "Trial Balance" for card in context.report_cards)


def test_build_report_console_context_contains_selected_report_state() -> None:
    context = build_report_console_context(
        selected_report="income-statement",
        form_values={
            "from_date": "2026-01-01",
            "to_date": "2026-01-31",
        },
        summary_template="partials/summary_not_available.html",
        summary={"message": "No formatted summary available."},
        error_message="",
        api_payload=None,
    )

    assert context.report_title == "Income Statement"
    assert context.report_description
    assert any(
        option.name == "income-statement" and option.selected
        for option in context.report_options
    )
    assert any(field.name == "from_date" for field in context.parameter_fields)
    assert any(field.name == "to_date" for field in context.parameter_fields)
    assert context.raw_json == ""


def test_build_report_console_context_formats_raw_json() -> None:
    context = build_report_console_context(
        selected_report="trial-balance",
        form_values={"as_of_date": "2026-01-31"},
        summary_template="partials/summary_not_available.html",
        summary={"message": "No formatted summary available."},
        error_message="problem",
        api_payload={"ok": False, "error": {"message": "bad input"}},
    )

    assert context.error_message == "problem"
    assert '"ok": false' in context.raw_json
    assert '"message": "bad input"' in context.raw_json
