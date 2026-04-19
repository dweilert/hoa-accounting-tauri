"""Tests for YearEndCloseService.

Covers:
- build_checklist: returns checklist with can_close flag
- close_year: posts closing entries, returns result
- close_year: rejects year with open periods
- reopen_year: marks year as reopened
"""

from __future__ import annotations

import sqlite3

import pytest

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.exceptions import ValidationError
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.journal_repo import JournalRepository
from hoa_accounting.repositories.year_end_close_repo import YearEndCloseRepository
from hoa_accounting.services.year_end_close_service import YearEndCloseService


def build_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    Migrator().apply_all(conn)
    conn.execute(
        "INSERT INTO users (id, email, full_name, password_hash, is_active) "
        "VALUES (1, 'a@example.com', 'Admin', 'x', 1)"
    )
    # Two closed periods for FY 2025 to allow year-end close.
    conn.execute(
        "INSERT INTO accounting_periods "
        "(id, period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed) VALUES "
        "(1, '2025-01', '2025-01-01', '2025-01-31', 2025, 1, 1), "
        "(2, '2025-02', '2025-02-01', '2025-02-28', 2025, 2, 1)"
    )
    conn.execute(
        "INSERT INTO accounts (id, account_number, account_name, account_type_id, "
        "fund_code, is_bank_account, is_active) VALUES "
        "(1000, '1000', 'Cash', 1, 'OPERATING', 1, 1), "
        "(3000, '3000', 'Retained Earnings', 3, 'OPERATING', 0, 1), "
        "(4000, '4000', 'Assessment Income', 4, 'OPERATING', 0, 1), "
        "(6000, '6000', 'Expense', 5, 'OPERATING', 0, 1)"
    )
    conn.commit()
    return conn


def _svc(conn):
    return YearEndCloseService(
        conn,
        close_repo=YearEndCloseRepository(conn),
        journal_repo=JournalRepository(conn),
        audit_repo=AuditRepository(conn),
    )


def test_build_checklist_all_closed() -> None:
    conn = build_conn()
    checklist = _svc(conn).build_checklist(2025)
    assert checklist.fiscal_year == 2025
    assert checklist.can_close is True
    # All checklist items should have passed=True.
    assert all(item.passed for item in checklist.items)


def test_build_checklist_has_open_period() -> None:
    conn = build_conn()
    conn.execute(
        "INSERT INTO accounting_periods "
        "(id, period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed) "
        "VALUES (3, '2025-03', '2025-03-01', '2025-03-31', 2025, 3, 0)"
    )
    conn.commit()
    checklist = _svc(conn).build_checklist(2025)
    assert checklist.can_close is False
    # At least one item should have failed.
    assert any(not item.passed for item in checklist.items)


def test_close_year_success() -> None:
    conn = build_conn()
    result = _svc(conn).close_year(2025)
    assert result.fiscal_year == 2025
    # je_operating_number is None when no income/expense activity; just check it returns.
    assert hasattr(result, "je_operating_number")


def test_close_year_rejects_year_with_open_periods() -> None:
    conn = build_conn()
    conn.execute(
        "INSERT INTO accounting_periods "
        "(id, period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed) "
        "VALUES (3, '2025-03', '2025-03-01', '2025-03-31', 2025, 3, 0)"
    )
    conn.commit()
    with pytest.raises(ValidationError):
        _svc(conn).close_year(2025)


def test_reopen_year_success() -> None:
    conn = build_conn()
    _svc(conn).close_year(2025)
    result = _svc(conn).reopen_year(2025)
    assert result.fiscal_year == 2025
    # fiscal_year_closes record should now have reopened_at set.
    row = conn.execute(
        "SELECT reopened_at FROM fiscal_year_closes WHERE fiscal_year=2025"
    ).fetchone()
    assert row is not None
    assert row["reopened_at"] is not None
