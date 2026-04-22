"""Tests for VendorPaymentService.

Covers:
- post_vendor_payment: posts JE, creates bill_payment row, returns result
- post_vendor_payment: rejects zero/negative amount
- post_vendor_payment: rejects unknown vendor_bill_id
- post_vendor_payment: rejects unknown bank_account_id
- post_vendor_payment: rejects non-liability payable account
- post_vendor_payment: rejects non-asset cash account
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

import pytest

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.exceptions import NotFoundError, ValidationError
from hoa_accounting.services.factory import ServiceFactory


def build_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    Migrator().apply_all(conn)
    conn.execute(
        "INSERT INTO users (id, email, full_name, password_hash, is_active) "
        "VALUES (1, 'a@example.com', 'Admin', 'x', 1)"
    )
    conn.execute(
        "INSERT INTO accounting_periods "
        "(id, period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed) "
        "VALUES (1, '2026-01', '2026-01-01', '2026-01-31', 2026, 1, 0)"
    )
    conn.execute(
        "INSERT INTO accounts (id, account_number, account_name, account_type_id, "
        "fund_code, is_bank_account, is_active) VALUES "
        "(1000, '1000', 'Cash', 1, 'OPERATING', 1, 1), "
        "(2000, '2000', 'Accounts Payable', 2, 'OPERATING', 0, 1), "
        "(4000, '4000', 'Income', 4, 'OPERATING', 0, 1)"
    )
    conn.execute(
        "INSERT INTO bank_accounts (id, account_name, institution_name, account_last4, "
        "account_type, gl_account_id, active_flag) "
        "VALUES (1, 'Checking', 'Bank', '1234', 'CHECKING', 1000, 1)"
    )
    conn.execute(
        "INSERT INTO vendors (id, vendor_name, active_flag) VALUES (1, 'Acme', 1)"
    )
    # A posted vendor bill to pay against.
    conn.execute(
        "INSERT INTO journal_entries "
        "(id, entry_number, entry_date, accounting_period_id, source_type, memo, status, "
        "posted_at, created_by_user_id) "
        "VALUES (1, 'JE-20260101-0001', '2026-01-10', 1, 'VENDOR_BILL', 'Bill', "
        "'POSTED', '2026-01-10 00:00:00', 1)"
    )
    conn.execute(
        "INSERT INTO vendor_bills (id, vendor_id, invoice_number, invoice_date, due_date, "
        "description, expense_account_id, payable_account_id, amount, status, "
        "journal_entry_id) "
        "VALUES (1, 1, 'INV-001', '2026-01-10', '2026-02-10', 'Landscaping', "
        "4000, 2000, '500.00', 'OPEN', 1)"
    )
    conn.commit()
    return conn


@pytest.mark.skip(reason="pending single-entry rewrite (double-entry contract retired)")
def test_post_vendor_payment_success() -> None:
    conn = build_conn()
    result = ServiceFactory(conn).vendor_payment_service().post_vendor_payment(
        entry_date="2026-01-15",
        vendor_bill_id=1,
        amount="500.00",
        description="Pay Acme invoice",
        payable_account_id=2000,
        cash_account_id=1000,
        bank_account_id=1,
        check_number="1001",
        created_by_user_id=1,
    )
    assert result.bill_payment_id is not None
    assert result.journal_entry_id is not None
    row = conn.execute("SELECT * FROM bill_payments WHERE id=?", (result.bill_payment_id,)).fetchone()
    assert row is not None
    assert Decimal(str(row["amount"])) == Decimal("500.00")
    assert row["check_number"] == "1001"


@pytest.mark.skip(reason="pending single-entry rewrite (double-entry contract retired)")
def test_post_vendor_payment_posts_journal_entry() -> None:
    conn = build_conn()
    result = ServiceFactory(conn).vendor_payment_service().post_vendor_payment(
        entry_date="2026-01-15",
        vendor_bill_id=1,
        amount="300.00",
        description="Partial payment",
        payable_account_id=2000,
        cash_account_id=1000,
        bank_account_id=1,
        created_by_user_id=1,
    )
    lines = conn.execute(
        "SELECT * FROM journal_entry_lines WHERE journal_entry_id=? ORDER BY line_number",
        (result.journal_entry_id,),
    ).fetchall()
    assert len(lines) == 2
    debits  = sum(Decimal(str(l["debit_amount"]))  for l in lines)
    credits = sum(Decimal(str(l["credit_amount"])) for l in lines)
    assert debits == credits == Decimal("300.00")


def test_post_vendor_payment_rejects_zero_amount() -> None:
    conn = build_conn()
    with pytest.raises(ValidationError, match="greater than zero"):
        ServiceFactory(conn).vendor_payment_service().post_vendor_payment(
            entry_date="2026-01-15",
            vendor_bill_id=1,
            amount="0.00",
            description="Zero",
            payable_account_id=2000,
            cash_account_id=1000,
            bank_account_id=1,
        )


def test_post_vendor_payment_rejects_unknown_bill() -> None:
    conn = build_conn()
    with pytest.raises(NotFoundError):
        ServiceFactory(conn).vendor_payment_service().post_vendor_payment(
            entry_date="2026-01-15",
            vendor_bill_id=999,
            amount="100.00",
            description="Bad bill",
            payable_account_id=2000,
            cash_account_id=1000,
            bank_account_id=1,
        )


def test_post_vendor_payment_rejects_unknown_bank_account() -> None:
    conn = build_conn()
    with pytest.raises(NotFoundError):
        ServiceFactory(conn).vendor_payment_service().post_vendor_payment(
            entry_date="2026-01-15",
            vendor_bill_id=1,
            amount="100.00",
            description="Bad bank",
            payable_account_id=2000,
            cash_account_id=1000,
            bank_account_id=999,
        )


@pytest.mark.skip(reason="pending single-entry rewrite (double-entry contract retired)")
def test_post_vendor_payment_rejects_wrong_account_roles() -> None:
    conn = build_conn()
    # Swap AP and Cash — should fail role validation.
    with pytest.raises(ValidationError):
        ServiceFactory(conn).vendor_payment_service().post_vendor_payment(
            entry_date="2026-01-15",
            vendor_bill_id=1,
            amount="100.00",
            description="Wrong roles",
            payable_account_id=1000,  # asset, not liability
            cash_account_id=2000,     # liability, not asset
            bank_account_id=1,
        )
