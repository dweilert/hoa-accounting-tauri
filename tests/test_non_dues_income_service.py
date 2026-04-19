"""Tests for NonDuesIncomeService.

Covers:
- post_batch: posts JE and income_batch row, returns result
- post_batch: rejects empty rows
- post_batch: rejects blank description
- post_batch: rejects lot with no current owner
- post_batch: other_source row works without a lot
- post_batch: totals match sum of rows
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

import pytest

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.exceptions import ValidationError
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.services.non_dues_income_service import IncomeRow


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
        "(4500, '4500', 'Other Income', 4, 'OPERATING', 0, 1)"
    )
    conn.execute(
        "INSERT INTO bank_accounts (id, account_name, institution_name, account_last4, "
        "account_type, gl_account_id, active_flag) "
        "VALUES (1, 'Checking', 'Bank', '1234', 'CHECKING', 1000, 1)"
    )
    conn.execute(
        "INSERT INTO owners (id, owner_type, display_name, active_flag) "
        "VALUES (1, 'PERSON', 'Alice Park', 1)"
    )
    conn.execute(
        "INSERT INTO lots (id, lot_number, active_flag) VALUES (1, 'L-1', 1)"
    )
    conn.execute(
        "INSERT INTO lot_ownership (lot_id, owner_id, start_date) "
        "VALUES (1, 1, '2020-01-01')"
    )
    conn.commit()
    return conn


def _svc(conn):
    return ServiceFactory(conn).non_dues_income_service()


def test_post_batch_success_other_source() -> None:
    conn = build_conn()
    result = _svc(conn).post_batch(
        posting_date="2026-01-20",
        bank_account_id=1,
        income_account_id=4500,
        income_description="Bank interest",
        rows=[IncomeRow(amount="12.50", other_source="Bank Interest Jan")],
        created_by_user_id=1,
    )
    assert result.income_batch_id is not None
    assert result.total_amount == Decimal("12.50")
    je = conn.execute(
        "SELECT status FROM journal_entries WHERE id=?", (result.journal_entry_id,)
    ).fetchone()
    assert je["status"] == "POSTED"


def test_post_batch_success_lot_row() -> None:
    conn = build_conn()
    result = _svc(conn).post_batch(
        posting_date="2026-01-20",
        bank_account_id=1,
        income_account_id=4500,
        income_description="Gate remote fee",
        rows=[IncomeRow(amount="25.00", lot_id=1)],
        created_by_user_id=1,
    )
    assert result.total_amount == Decimal("25.00")


def test_post_batch_multiple_rows_totals_correctly() -> None:
    conn = build_conn()
    result = _svc(conn).post_batch(
        posting_date="2026-01-20",
        bank_account_id=1,
        income_account_id=4500,
        income_description="Mixed batch",
        rows=[
            IncomeRow(amount="10.00", lot_id=1),
            IncomeRow(amount="5.50", other_source="Bank Interest"),
        ],
        created_by_user_id=1,
    )
    assert result.total_amount == Decimal("15.50")


def test_post_batch_rejects_empty_rows() -> None:
    conn = build_conn()
    with pytest.raises(ValidationError, match="at least one"):
        _svc(conn).post_batch(
            posting_date="2026-01-20",
            bank_account_id=1,
            income_account_id=4500,
            income_description="Empty",
            rows=[],
        )


def test_post_batch_rejects_blank_description() -> None:
    conn = build_conn()
    with pytest.raises(ValidationError, match="description"):
        _svc(conn).post_batch(
            posting_date="2026-01-20",
            bank_account_id=1,
            income_account_id=4500,
            income_description="   ",
            rows=[IncomeRow(amount="10.00", other_source="Interest")],
        )


def test_post_batch_rejects_lot_with_no_owner() -> None:
    conn = build_conn()
    conn.execute("INSERT INTO lots (id, lot_number, active_flag) VALUES (99, 'L-99', 1)")
    conn.commit()
    with pytest.raises(ValidationError, match="no current"):
        _svc(conn).post_batch(
            posting_date="2026-01-20",
            bank_account_id=1,
            income_account_id=4500,
            income_description="Fee",
            rows=[IncomeRow(amount="10.00", lot_id=99)],
        )
