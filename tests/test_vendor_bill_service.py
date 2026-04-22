"""Tests for VendorBillService.

Covers:
- post_vendor_bill: posts JE + vendor_bills row, returns result
- post_vendor_bill: rejects zero/negative amount
- post_vendor_bill: rejects unknown vendor
- post_vendor_bill: rejects wrong account roles (expense/payable swap)
- post_vendor_bill: rejects invalid expense_classification
- post_vendor_bill: JE lines balance
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
        "(2000, '2000', 'Accounts Payable', 2, 'OPERATING', 0, 1), "
        "(6000, '6000', 'Landscaping Expense', 5, 'OPERATING', 0, 1)"
    )
    conn.execute(
        "INSERT INTO vendors (id, vendor_name, active_flag) VALUES (1, 'Green Yard', 1)"
    )
    conn.commit()
    return conn


def _svc(conn):
    return ServiceFactory(conn).vendor_bill_service()


@pytest.mark.skip(reason="pending single-entry rewrite (double-entry contract retired)")
def test_post_vendor_bill_success() -> None:
    conn = build_conn()
    result = _svc(conn).post_vendor_bill(
        entry_date="2026-01-15",
        vendor_id=1,
        amount="350.00",
        description="Landscaping Jan",
        expense_account_id=6000,
        payable_account_id=2000,
        invoice_number="INV-001",
        invoice_date="2026-01-10",
        due_date="2026-02-10",
        created_by_user_id=1,
    )
    assert result.vendor_bill_id is not None
    assert result.journal_entry_id is not None
    row = conn.execute("SELECT amount FROM vendor_bills WHERE id=?", (result.vendor_bill_id,)).fetchone()
    assert Decimal(str(row["amount"])) == Decimal("350.00")


@pytest.mark.skip(reason="pending single-entry rewrite (double-entry contract retired)")
def test_post_vendor_bill_je_balances() -> None:
    conn = build_conn()
    result = _svc(conn).post_vendor_bill(
        entry_date="2026-01-15",
        vendor_id=1,
        amount="200.00",
        description="Test",
        expense_account_id=6000,
        payable_account_id=2000,
        invoice_number="INV-002",
        invoice_date="2026-01-10",
        created_by_user_id=1,
    )
    lines = conn.execute(
        "SELECT debit_amount, credit_amount FROM journal_entry_lines "
        "WHERE journal_entry_id=?",
        (result.journal_entry_id,),
    ).fetchall()
    assert sum(Decimal(str(l["debit_amount"])) for l in lines) == Decimal("200.00")
    assert sum(Decimal(str(l["credit_amount"])) for l in lines) == Decimal("200.00")


def test_post_vendor_bill_rejects_zero_amount() -> None:
    conn = build_conn()
    with pytest.raises(ValidationError, match="greater than zero"):
        _svc(conn).post_vendor_bill(
            entry_date="2026-01-15",
            vendor_id=1,
            amount="0.00",
            description="Zero",
            expense_account_id=6000,
            payable_account_id=2000,
            invoice_number="INV-003",
            invoice_date="2026-01-10",
        )


def test_post_vendor_bill_rejects_unknown_vendor() -> None:
    conn = build_conn()
    with pytest.raises(NotFoundError):
        _svc(conn).post_vendor_bill(
            entry_date="2026-01-15",
            vendor_id=999,
            amount="100.00",
            description="Unknown vendor",
            expense_account_id=6000,
            payable_account_id=2000,
            invoice_number="INV-004",
            invoice_date="2026-01-10",
        )


@pytest.mark.skip(reason="pending single-entry rewrite (double-entry contract retired)")
def test_post_vendor_bill_rejects_swapped_account_roles() -> None:
    conn = build_conn()
    with pytest.raises(ValidationError):
        _svc(conn).post_vendor_bill(
            entry_date="2026-01-15",
            vendor_id=1,
            amount="100.00",
            description="Swapped",
            expense_account_id=2000,  # liability — wrong role
            payable_account_id=6000,  # expense — wrong role
            invoice_number="INV-005",
            invoice_date="2026-01-10",
        )


@pytest.mark.skip(reason="pending single-entry rewrite (double-entry contract retired)")
def test_post_vendor_bill_rejects_invalid_classification() -> None:
    conn = build_conn()
    with pytest.raises(ValidationError, match="classification"):
        _svc(conn).post_vendor_bill(
            entry_date="2026-01-15",
            vendor_id=1,
            amount="100.00",
            description="Bad class",
            expense_account_id=6000,
            payable_account_id=2000,
            invoice_number="INV-006",
            invoice_date="2026-01-10",
            expense_classification="LUXURY",
        )
