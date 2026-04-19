"""Tests for AssessmentService.

Covers:
- post_assessment: posts JE + assessments row, returns result
- post_assessment: rejects zero/negative amount
- post_assessment: rejects unknown lot
- post_assessment: rejects unknown owner
- post_assessment: rejects wrong account roles
- post_assessment: JE lines balance
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
        "(1100, '1100', 'AR', 1, 'OPERATING', 0, 1), "
        "(4000, '4000', 'Assessment Income', 4, 'OPERATING', 0, 1), "
        "(2000, '2000', 'AP', 2, 'OPERATING', 0, 1)"
    )
    conn.execute(
        "INSERT INTO lots (id, lot_number, active_flag) VALUES (1, 'L-1', 1)"
    )
    conn.execute(
        "INSERT INTO owners (id, owner_type, display_name, active_flag) "
        "VALUES (1, 'PERSON', 'Alice Park', 1)"
    )
    conn.commit()
    return conn


def _svc(conn):
    return ServiceFactory(conn).assessment_service()


def test_post_assessment_success() -> None:
    conn = build_conn()
    result = _svc(conn).post_assessment(
        entry_date="2026-01-10",
        lot_id=1,
        owner_id=1,
        amount="250.00",
        description="January dues",
        receivable_account_id=1100,
        income_account_id=4000,
        created_by_user_id=1,
    )
    assert result.assessment_id is not None
    assert result.journal_entry_id is not None
    row = conn.execute(
        "SELECT amount, status FROM assessments WHERE id=?", (result.assessment_id,)
    ).fetchone()
    assert Decimal(str(row["amount"])) == Decimal("250.00")
    assert row["status"] == "OPEN"


def test_post_assessment_je_balances() -> None:
    conn = build_conn()
    result = _svc(conn).post_assessment(
        entry_date="2026-01-10",
        lot_id=1,
        owner_id=1,
        amount="175.00",
        description="Fee",
        receivable_account_id=1100,
        income_account_id=4000,
        created_by_user_id=1,
    )
    lines = conn.execute(
        "SELECT debit_amount, credit_amount FROM journal_entry_lines "
        "WHERE journal_entry_id=?",
        (result.journal_entry_id,),
    ).fetchall()
    assert sum(Decimal(str(l["debit_amount"])) for l in lines) == Decimal("175.00")
    assert sum(Decimal(str(l["credit_amount"])) for l in lines) == Decimal("175.00")


def test_post_assessment_rejects_zero_amount() -> None:
    conn = build_conn()
    with pytest.raises(ValidationError, match="greater than zero"):
        _svc(conn).post_assessment(
            entry_date="2026-01-10",
            lot_id=1,
            owner_id=1,
            amount="0.00",
            description="Zero",
            receivable_account_id=1100,
            income_account_id=4000,
        )


def test_post_assessment_rejects_unknown_lot() -> None:
    conn = build_conn()
    with pytest.raises(NotFoundError):
        _svc(conn).post_assessment(
            entry_date="2026-01-10",
            lot_id=999,
            owner_id=1,
            amount="250.00",
            description="Bad lot",
            receivable_account_id=1100,
            income_account_id=4000,
        )


def test_post_assessment_rejects_unknown_owner() -> None:
    conn = build_conn()
    with pytest.raises(NotFoundError):
        _svc(conn).post_assessment(
            entry_date="2026-01-10",
            lot_id=1,
            owner_id=999,
            amount="250.00",
            description="Bad owner",
            receivable_account_id=1100,
            income_account_id=4000,
        )


def test_post_assessment_rejects_wrong_account_roles() -> None:
    conn = build_conn()
    with pytest.raises(ValidationError):
        _svc(conn).post_assessment(
            entry_date="2026-01-10",
            lot_id=1,
            owner_id=1,
            amount="250.00",
            description="Swapped accounts",
            receivable_account_id=4000,  # income — wrong role
            income_account_id=1100,      # asset — wrong role
        )
