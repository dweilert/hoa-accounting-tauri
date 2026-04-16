"""Reporting tests."""

from __future__ import annotations

import sqlite3

from hoa_accounting.db.transaction import transaction
from hoa_accounting.reporting.ar_aging import ARAgingReportService
from hoa_accounting.reporting.balance_sheet import BalanceSheetReportService
from hoa_accounting.reporting.general_ledger import GeneralLedgerReportService
from hoa_accounting.reporting.income_statement import IncomeStatementReportService
from hoa_accounting.reporting.owner_ledger import OwnerLedgerReportService
from hoa_accounting.reporting.trial_balance import TrialBalanceReportService
from hoa_accounting.services.factory import ServiceFactory

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
        INSERT INTO accounting_periods
            (id, period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed)
        VALUES
            (3, '2026-03', '2026-03-01', '2026-03-31', 2026, 3, 0)
        """
    )

    conn.execute(
        """
        INSERT INTO users (id, email, full_name, password_hash, is_active)
        VALUES (1, 'a@example.com', 'Admin', 'x', 1)
        """
    )
    conn.execute("INSERT INTO lots (id, lot_number) VALUES (1, '1')")
    conn.execute("INSERT INTO lots (id, lot_number) VALUES (2, '2')")
    conn.execute(
        """
        INSERT INTO owners (id, display_name, owner_type, active_flag)
        VALUES (1, 'Owner 1', 'PERSON', 1)
        """
    )
    conn.execute(
        """
        INSERT INTO owners (id, display_name, owner_type, active_flag)
        VALUES (2, 'Owner 2', 'PERSON', 1)
        """
    )
    conn.execute(
        """
        INSERT INTO vendors (id, vendor_name, active_flag)
        VALUES (1, 'Vendor 1', 1)
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
            (1010, '1010', 'Reserve Cash', 1, 'RESERVE', 1, 1)
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
            (2000, '2000', 'AP', 2, 'OPERATING', 0, 1)
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


def test_trial_balance_balances_after_assessment_and_payment() -> None:
    conn = build_conn()
    factory = ServiceFactory(conn)

    with transaction(conn):
        assessment = factory.assessment_service().post_assessment(
            entry_date="2026-01-10",
            lot_id=1,
            owner_id=1,
            amount="100.00",
            description="Assessment",
            receivable_account_id=1100,
            income_account_id=4000,
            created_by_user_id=1,
        )
        factory.payment_service().post_payment(
            entry_date="2026-01-11",
            owner_id=1,
            amount="100.00",
            description="Payment",
            cash_account_id=1000,
            receivable_account_id=1100,
            bank_account_id=1,
            payment_method="CHECK",
            receipt_number="R1",
            created_by_user_id=1,
            apply_to_assessment_ids=[assessment.assessment_id],
        )

    report = TrialBalanceReportService(conn).generate(as_of_date="2026-01-31")
    assert report.total_debits == report.total_credits
    assert len(report.rows) >= 2


def test_general_ledger_running_balance_for_cash_account() -> None:
    conn = build_conn()
    factory = ServiceFactory(conn)

    with transaction(conn):
        assessment = factory.assessment_service().post_assessment(
            entry_date="2026-01-10",
            lot_id=1,
            owner_id=1,
            amount="100.00",
            description="Assessment",
            receivable_account_id=1100,
            income_account_id=4000,
            created_by_user_id=1,
        )
        factory.payment_service().post_payment(
            entry_date="2026-01-11",
            owner_id=1,
            amount="100.00",
            description="Payment",
            cash_account_id=1000,
            receivable_account_id=1100,
            bank_account_id=1,
            payment_method="CHECK",
            receipt_number="R1",
            created_by_user_id=1,
            apply_to_assessment_ids=[assessment.assessment_id],
        )

    ledger = GeneralLedgerReportService(conn).generate(
        account_id=1000,
        from_date="2026-01-01",
        to_date="2026-01-31",
    )
    assert len(ledger.rows) == 1
    assert ledger.rows[0].debit_amount == 100
    assert ledger.rows[0].running_balance == 100


def test_owner_ledger_report_shows_running_balance_and_opening_balance() -> None:
    conn = build_conn()
    factory = ServiceFactory(conn)

    with transaction(conn):
        factory.assessment_service().post_assessment(
            entry_date="2026-01-05",
            lot_id=1,
            owner_id=1,
            amount="120.00",
            description="January assessment",
            receivable_account_id=1100,
            income_account_id=4000,
            created_by_user_id=1,
            due_date="2026-01-31",
        )
        factory.payment_service().post_payment(
            entry_date="2026-01-20",
            owner_id=1,
            amount="70.00",
            description="Partial payment",
            cash_account_id=1000,
            receivable_account_id=1100,
            bank_account_id=1,
            payment_method="CHECK",
            receipt_number="R-100",
            created_by_user_id=1,
        )
        factory.assessment_service().post_assessment(
            entry_date="2026-02-05",
            lot_id=1,
            owner_id=1,
            amount="120.00",
            description="February assessment",
            receivable_account_id=1100,
            income_account_id=4000,
            created_by_user_id=1,
            due_date="2026-02-28",
        )

    january_report = OwnerLedgerReportService(conn).generate(
        owner_id=1,
        receivable_account_id=1100,
        from_date="2026-01-01",
        to_date="2026-01-31",
    )
    assert january_report.opening_balance == 0
    assert january_report.closing_balance == 50
    assert len(january_report.rows) == 2
    assert january_report.rows[0].source_type == "ASSESSMENT"
    assert january_report.rows[0].debit_amount == 120
    assert january_report.rows[0].running_balance == 120
    assert january_report.rows[0].due_date == "2026-01-31"
    assert january_report.rows[0].lot_number == "1"
    assert january_report.rows[1].source_type == "PAYMENT"
    assert january_report.rows[1].credit_amount == 70
    assert january_report.rows[1].running_balance == 50
    assert january_report.rows[1].receipt_number == "R-100"
    assert january_report.rows[1].payment_method == "CHECK"

    february_report = OwnerLedgerReportService(conn).generate(
        owner_id=1,
        receivable_account_id=1100,
        from_date="2026-02-01",
        to_date="2026-02-28",
    )
    assert february_report.opening_balance == 50
    assert february_report.closing_balance == 170
    assert len(february_report.rows) == 1
    assert february_report.rows[0].running_balance == 170


def test_owner_ledger_report_supports_owner_credit_balance() -> None:
    conn = build_conn()
    factory = ServiceFactory(conn)

    with transaction(conn):
        factory.payment_service().post_payment(
            entry_date="2026-01-10",
            owner_id=1,
            amount="25.00",
            description="Advance payment",
            cash_account_id=1000,
            receivable_account_id=1100,
            bank_account_id=1,
            payment_method="ACH",
            receipt_number="R-200",
            created_by_user_id=1,
        )

    report = OwnerLedgerReportService(conn).generate(
        owner_id=1,
        receivable_account_id=1100,
        from_date="2026-01-01",
        to_date="2026-01-31",
    )

    assert report.opening_balance == 0
    assert report.closing_balance == -25
    assert len(report.rows) == 1
    assert report.rows[0].credit_amount == 25
    assert report.rows[0].running_balance == -25


def test_ar_aging_report_buckets_open_assessments_by_owner() -> None:
    conn = build_conn()
    factory = ServiceFactory(conn)

    with transaction(conn):
        january = factory.assessment_service().post_assessment(
            entry_date="2026-01-05",
            lot_id=1,
            owner_id=1,
            amount="100.00",
            description="January assessment",
            receivable_account_id=1100,
            income_account_id=4000,
            created_by_user_id=1,
            due_date="2026-01-31",
        )
        factory.assessment_service().post_assessment(
            entry_date="2026-02-05",
            lot_id=1,
            owner_id=1,
            amount="200.00",
            description="February assessment",
            receivable_account_id=1100,
            income_account_id=4000,
            created_by_user_id=1,
            due_date="2026-02-28",
        )
        factory.payment_service().post_payment(
            entry_date="2026-02-15",
            owner_id=1,
            amount="60.00",
            description="Partial payment",
            cash_account_id=1000,
            receivable_account_id=1100,
            bank_account_id=1,
            payment_method="CHECK",
            receipt_number="R-300",
            created_by_user_id=1,
            apply_to_assessment_ids=[january.assessment_id],
        )

    report = ARAgingReportService(conn).generate(
        as_of_date="2026-03-15",
        receivable_account_id=1100,
    )

    assert len(report.detail_rows) == 2
    assert report.detail_rows[0].assessment_id == 1
    assert report.detail_rows[0].remaining_amount == 40
    assert report.detail_rows[0].aging_bucket == "31-60"
    assert report.detail_rows[1].remaining_amount == 200
    assert report.detail_rows[1].aging_bucket == "1-30"

    assert len(report.owner_summaries) == 1
    summary = report.owner_summaries[0]
    assert summary.owner_id == 1
    assert summary.current_amount == 0
    assert summary.amount_1_30 == 200
    assert summary.amount_31_60 == 40
    assert summary.amount_61_90 == 0
    assert summary.amount_90_plus == 0
    assert summary.total_open_amount == 240
    assert summary.credit_balance == 0
    assert summary.ledger_balance == 240

    assert report.total_current_amount == 0
    assert report.total_amount_1_30 == 200
    assert report.total_amount_31_60 == 40
    assert report.total_amount_61_90 == 0
    assert report.total_amount_90_plus == 0
    assert report.total_open_amount == 240
    assert report.total_credit_balance == 0
    assert report.total_ledger_balance == 240


def test_ar_aging_report_respects_as_of_date_for_payment_applications() -> None:
    conn = build_conn()
    factory = ServiceFactory(conn)

    with transaction(conn):
        assessment = factory.assessment_service().post_assessment(
            entry_date="2026-01-05",
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
            entry_date="2026-02-10",
            owner_id=1,
            amount="100.00",
            description="Late payment",
            cash_account_id=1000,
            receivable_account_id=1100,
            bank_account_id=1,
            payment_method="ACH",
            receipt_number="R-400",
            created_by_user_id=1,
            apply_to_assessment_ids=[assessment.assessment_id],
        )

    january_report = ARAgingReportService(conn).generate(
        as_of_date="2026-01-31",
        receivable_account_id=1100,
    )
    assert len(january_report.detail_rows) == 1
    assert january_report.detail_rows[0].remaining_amount == 100
    assert january_report.owner_summaries[0].ledger_balance == 100

    february_report = ARAgingReportService(conn).generate(
        as_of_date="2026-02-28",
        receivable_account_id=1100,
    )
    assert len(february_report.detail_rows) == 0
    assert february_report.owner_summaries[0].ledger_balance == 0
    assert february_report.total_open_amount == 0
    assert february_report.total_ledger_balance == 0


def test_ar_aging_report_shows_owner_credit_balance_without_open_items() -> None:
    conn = build_conn()
    factory = ServiceFactory(conn)

    with transaction(conn):
        factory.payment_service().post_payment(
            entry_date="2026-01-10",
            owner_id=1,
            amount="25.00",
            description="Advance payment",
            cash_account_id=1000,
            receivable_account_id=1100,
            bank_account_id=1,
            payment_method="ACH",
            receipt_number="R-500",
            created_by_user_id=1,
        )

    report = ARAgingReportService(conn).generate(
        as_of_date="2026-01-31",
        receivable_account_id=1100,
    )

    assert len(report.detail_rows) == 0
    assert len(report.owner_summaries) == 1

    summary = report.owner_summaries[0]
    assert summary.total_open_amount == 0
    assert summary.credit_balance == 25
    assert summary.ledger_balance == -25

    assert report.total_open_amount == 0
    assert report.total_credit_balance == 25
    assert report.total_ledger_balance == -25


def test_balance_sheet_balances_with_cumulative_earnings() -> None:
    conn = build_conn()
    factory = ServiceFactory(conn)

    with transaction(conn):
        assessment = factory.assessment_service().post_assessment(
            entry_date="2026-01-10",
            lot_id=1,
            owner_id=1,
            amount="100.00",
            description="Assessment",
            receivable_account_id=1100,
            income_account_id=4000,
            created_by_user_id=1,
            due_date="2026-01-31",
        )
        factory.payment_service().post_payment(
            entry_date="2026-01-11",
            owner_id=1,
            amount="100.00",
            description="Payment",
            cash_account_id=1000,
            receivable_account_id=1100,
            bank_account_id=1,
            payment_method="CHECK",
            receipt_number="R-BS-1",
            created_by_user_id=1,
            apply_to_assessment_ids=[assessment.assessment_id],
        )

    report = BalanceSheetReportService(conn).generate(as_of_date="2026-01-31")

    assert report.total_assets == 100
    assert report.total_liabilities == 0
    assert report.total_equity == 100
    assert report.total_liabilities_and_equity == 100
    assert report.balancing_difference == 0

    assert len(report.assets.rows) == 1
    assert report.assets.rows[0].account_number == "1000"
    assert report.assets.rows[0].account_name == "Cash"
    assert report.assets.rows[0].amount == 100

    assert len(report.equity.rows) == 1
    assert report.equity.rows[0].account_name == "Cumulative Earnings"
    assert report.equity.rows[0].amount == 100
    assert report.equity.rows[0].is_system is True


def test_balance_sheet_respects_as_of_date() -> None:
    conn = build_conn()
    factory = ServiceFactory(conn)

    with transaction(conn):
        january = factory.assessment_service().post_assessment(
            entry_date="2026-01-05",
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
            description="Partial January payment",
            cash_account_id=1000,
            receivable_account_id=1100,
            bank_account_id=1,
            payment_method="ACH",
            receipt_number="R-BS-2",
            created_by_user_id=1,
            apply_to_assessment_ids=[january.assessment_id],
        )
        factory.assessment_service().post_assessment(
            entry_date="2026-02-05",
            lot_id=1,
            owner_id=1,
            amount="120.00",
            description="February assessment",
            receivable_account_id=1100,
            income_account_id=4000,
            created_by_user_id=1,
            due_date="2026-02-28",
        )

    january_report = BalanceSheetReportService(conn).generate(as_of_date="2026-01-31")
    assert january_report.total_assets == 100
    assert january_report.total_equity == 100
    assert january_report.balancing_difference == 0

    january_asset_accounts = {
        row.account_number: row.amount
        for row in january_report.assets.rows
    }
    assert january_asset_accounts["1000"] == 40
    assert january_asset_accounts["1100"] == 60

    february_report = BalanceSheetReportService(conn).generate(as_of_date="2026-02-28")
    assert february_report.total_assets == 220
    assert february_report.total_equity == 220
    assert february_report.balancing_difference == 0

    february_asset_accounts = {
        row.account_number: row.amount
        for row in february_report.assets.rows
    }
    assert february_asset_accounts["1000"] == 40
    assert february_asset_accounts["1100"] == 180


def test_income_statement_reports_income_for_period() -> None:
    conn = build_conn()
    factory = ServiceFactory(conn)

    with transaction(conn):
        factory.assessment_service().post_assessment(
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

    january_report = IncomeStatementReportService(conn).generate(
        from_date="2026-01-01",
        to_date="2026-01-31",
    )
    assert january_report.total_income == 100
    assert january_report.total_expenses == 0
    assert january_report.net_income == 100
    assert len(january_report.income.rows) == 1
    assert january_report.income.rows[0].account_number == "4000"
    assert january_report.income.rows[0].amount == 100

    february_report = IncomeStatementReportService(conn).generate(
        from_date="2026-02-01",
        to_date="2026-02-28",
    )
    assert february_report.total_income == 120
    assert february_report.total_expenses == 0
    assert february_report.net_income == 120


def test_income_statement_respects_date_range_boundaries() -> None:
    conn = build_conn()
    factory = ServiceFactory(conn)

    with transaction(conn):
        factory.assessment_service().post_assessment(
            entry_date="2026-01-31",
            lot_id=1,
            owner_id=1,
            amount="75.00",
            description="January month-end assessment",
            receivable_account_id=1100,
            income_account_id=4000,
            created_by_user_id=1,
            due_date="2026-01-31",
        )
        factory.assessment_service().post_assessment(
            entry_date="2026-02-01",
            lot_id=1,
            owner_id=1,
            amount="125.00",
            description="February start assessment",
            receivable_account_id=1100,
            income_account_id=4000,
            created_by_user_id=1,
            due_date="2026-02-28",
        )

    january_report = IncomeStatementReportService(conn).generate(
        from_date="2026-01-01",
        to_date="2026-01-31",
    )
    assert january_report.total_income == 75
    assert january_report.net_income == 75

    february_report = IncomeStatementReportService(conn).generate(
        from_date="2026-02-01",
        to_date="2026-02-28",
    )
    assert february_report.total_income == 125
    assert february_report.net_income == 125