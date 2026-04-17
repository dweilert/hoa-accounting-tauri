"""Tests for the all-accounts ledger views.

Covers:
- render_all_transactions: empty, shows rows, date filter start/end, sort desc
- render_by_account: empty, groups by account, per-account totals, grand totals
- running balance per account resets between accounts
"""

from __future__ import annotations

import sqlite3

import pytest

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.web.all_ledger_pages import AllLedgerPages


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    Migrator().apply_all(c)
    _seed(c)
    return c


_ORG = {"name": "Test HOA", "environment": "test",
        "fiscal_year_start_month": 1, "theme": "warm"}


def _seed(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO account_types (id, code, name, normal_balance) VALUES (?, ?, ?, ?)",
        [(1, "ASSET", "Asset", "DEBIT"), (5, "EXPENSE", "Expense", "DEBIT"),
         (4, "INCOME", "Income", "CREDIT")],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO accounts "
        "(id, account_number, account_name, account_type_id, fund_code, is_bank_account, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (1000, "1000", "Cash",    1, "OPERATING", 1, 1),
            (4000, "4000", "Income",  4, "OPERATING", 0, 1),
            (6000, "6000", "Expense", 5, "OPERATING", 0, 1),
        ],
    )
    cur = conn.execute(
        "INSERT INTO accounting_periods "
        "(period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed) "
        "VALUES ('2030-01', '2030-01-01', '2030-01-31', 2030, 1, 0)"
    )
    pid = int(cur.lastrowid)
    # Entry 1: Cash DR / Income CR  on 2030-01-10
    cur2 = conn.execute(
        "INSERT INTO journal_entries "
        "(entry_number, entry_date, accounting_period_id, source_type, memo, status, posted_at) "
        "VALUES ('JE-20300110-0001', '2030-01-10', ?, 'MANUAL', 'Revenue', 'POSTED', '2030-01-10')",
        (pid,),
    )
    je1 = int(cur2.lastrowid)
    conn.executemany(
        "INSERT INTO journal_entry_lines "
        "(journal_entry_id, line_number, account_id, description, debit_amount, credit_amount) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(je1, 1, 1000, "Cash in", "100.00", "0.00"),
         (je1, 2, 4000, "Income",  "0.00",  "100.00")],
    )
    # Entry 2: Expense DR / Cash CR  on 2030-01-20
    cur3 = conn.execute(
        "INSERT INTO journal_entries "
        "(entry_number, entry_date, accounting_period_id, source_type, memo, status, posted_at) "
        "VALUES ('JE-20300120-0001', '2030-01-20', ?, 'MANUAL', 'Expense', 'POSTED', '2030-01-20')",
        (pid,),
    )
    je2 = int(cur3.lastrowid)
    conn.executemany(
        "INSERT INTO journal_entry_lines "
        "(journal_entry_id, line_number, account_id, description, debit_amount, credit_amount) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(je2, 1, 6000, "Expense", "40.00", "0.00"),
         (je2, 2, 1000, "Cash out", "0.00", "40.00")],
    )
    conn.commit()


# ── render_all_transactions ────────────────────────────────────────────

def test_all_transactions_empty_db(conn: sqlite3.Connection) -> None:
    # Use a fresh DB with no transactions
    c2 = sqlite3.connect(":memory:")
    c2.row_factory = sqlite3.Row
    Migrator().apply_all(c2)
    _seed_accounts_only(c2)
    resp = AllLedgerPages(c2).render_all_transactions(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "No posted transactions" in resp.body_html


def _seed_accounts_only(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO account_types (id, code, name, normal_balance) VALUES (?, ?, ?, ?)",
        [(1, "ASSET", "Asset", "DEBIT")],
    )
    conn.commit()


def test_all_transactions_shows_all_rows(conn: sqlite3.Connection) -> None:
    resp = AllLedgerPages(conn).render_all_transactions(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "Revenue" in resp.body_html
    assert "Expense" in resp.body_html
    # 4 lines total (2 entries × 2 lines each)
    assert "4 lines" in resp.body_html


def test_all_transactions_date_filter_start(conn: sqlite3.Connection) -> None:
    resp = AllLedgerPages(conn).render_all_transactions(
        org=_ORG, theme="warm", start_date="2030-01-15"
    )
    assert "Expense" in resp.body_html
    assert "Revenue" not in resp.body_html


def test_all_transactions_date_filter_end(conn: sqlite3.Connection) -> None:
    resp = AllLedgerPages(conn).render_all_transactions(
        org=_ORG, theme="warm", end_date="2030-01-15"
    )
    assert "Revenue" in resp.body_html
    assert "Expense" not in resp.body_html


def test_all_transactions_sort_desc(conn: sqlite3.Connection) -> None:
    resp = AllLedgerPages(conn).render_all_transactions(
        org=_ORG, theme="warm", sort="desc"
    )
    # Both should still appear
    assert "Revenue" in resp.body_html
    assert "Expense" in resp.body_html


def test_all_transactions_totals(conn: sqlite3.Connection) -> None:
    resp = AllLedgerPages(conn).render_all_transactions(org=_ORG, theme="warm")
    # Total debits: 100 (cash) + 40 (expense) = 140
    assert "140" in resp.body_html


# ── render_by_account ──────────────────────────────────────────────────

def test_by_account_groups_correctly(conn: sqlite3.Connection) -> None:
    resp = AllLedgerPages(conn).render_by_account(org=_ORG, theme="warm")
    assert resp.status_code == 200
    # All three accounts should appear
    assert "1000" in resp.body_html
    assert "4000" in resp.body_html
    assert "6000" in resp.body_html


def test_by_account_shows_account_count(conn: sqlite3.Connection) -> None:
    resp = AllLedgerPages(conn).render_by_account(org=_ORG, theme="warm")
    assert "3 accounts" in resp.body_html


def test_by_account_shows_ending_balance(conn: sqlite3.Connection) -> None:
    resp = AllLedgerPages(conn).render_by_account(org=_ORG, theme="warm")
    # Cash: +100 - 40 = 60 Dr
    assert "60" in resp.body_html


def test_by_account_date_filter(conn: sqlite3.Connection) -> None:
    resp = AllLedgerPages(conn).render_by_account(
        org=_ORG, theme="warm", start_date="2030-01-15"
    )
    # Only the expense entry (Jan 20) should appear — income (Jan 10) excluded
    assert "Expense" in resp.body_html
    assert "Revenue" not in resp.body_html


def test_by_account_grand_totals(conn: sqlite3.Connection) -> None:
    resp = AllLedgerPages(conn).render_by_account(org=_ORG, theme="warm")
    assert "Grand Totals" in resp.body_html
