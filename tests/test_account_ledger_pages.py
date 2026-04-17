"""Tests for the account ledger page.

Covers:
- render_ledger: account not found returns 404
- render_ledger: empty account shows no-transactions message
- render_ledger: shows header details (number, name, type, fund, normal balance)
- render_ledger: shows transactions with debit/credit/balance columns
- render_ledger: running balance labeled Dr/Cr correctly
- render_ledger: date range filter passes through to query
- render_ledger: totals row reflects all rows
"""

from __future__ import annotations

import sqlite3

import pytest

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.web.account_ledger_pages import AccountLedgerPages


# ── Fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    Migrator().apply_all(c)
    _seed_accounts(c)
    return c


_ORG = {"name": "Test HOA", "environment": "test",
        "fiscal_year_start_month": 1, "theme": "warm"}


def _seed_accounts(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO account_types (id, code, name, normal_balance) VALUES (?, ?, ?, ?)",
        [
            (1, "ASSET",   "Asset",   "DEBIT"),
            (4, "INCOME",  "Income",  "CREDIT"),
            (5, "EXPENSE", "Expense", "DEBIT"),
        ],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO accounts "
        "(id, account_number, account_name, account_type_id, fund_code, is_bank_account, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (1000, "1000", "Operating Cash",     1, "OPERATING", 1, 1),
            (4000, "4000", "Assessment Income",  4, "OPERATING", 0, 1),
            (6000, "6000", "Landscaping Expense",5, "OPERATING", 0, 1),
        ],
    )
    conn.commit()


def _seed_period(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "INSERT INTO accounting_periods "
        "(period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed) "
        "VALUES ('2030-01', '2030-01-01', '2030-01-31', 2030, 1, 0)"
    )
    conn.commit()
    return int(cur.lastrowid)


def _seed_journal_entry(
    conn: sqlite3.Connection,
    *,
    period_id: int,
    entry_date: str = "2030-01-15",
    memo: str = "Test entry",
    debit_account_id: int = 1000,
    credit_account_id: int = 4000,
    amount: str = "100.00",
) -> int:
    cur = conn.execute(
        "INSERT INTO journal_entries "
        "(entry_number, entry_date, accounting_period_id, source_type, memo, status, posted_at) "
        "VALUES (?, ?, ?, 'MANUAL', ?, 'POSTED', '2030-01-15 00:00:00')",
        (f"JE-{entry_date.replace('-','')}-0001", entry_date, period_id, memo),
    )
    je_id = int(cur.lastrowid)
    conn.executemany(
        "INSERT INTO journal_entry_lines "
        "(journal_entry_id, line_number, account_id, description, debit_amount, credit_amount) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (je_id, 1, debit_account_id,  memo, amount, "0.00"),
            (je_id, 2, credit_account_id, memo, "0.00", amount),
        ],
    )
    conn.commit()
    return je_id


# ── render_ledger ──────────────────────────────────────────────────────

def test_render_ledger_account_not_found(conn: sqlite3.Connection) -> None:
    resp = AccountLedgerPages(conn).render_ledger(
        account_id=99999, org=_ORG, theme="warm"
    )
    assert resp.status_code == 404


def test_render_ledger_empty_account(conn: sqlite3.Connection) -> None:
    resp = AccountLedgerPages(conn).render_ledger(
        account_id=1000, org=_ORG, theme="warm"
    )
    assert resp.status_code == 200
    assert "No posted transactions" in resp.body_html


def test_render_ledger_shows_account_header(conn: sqlite3.Connection) -> None:
    resp = AccountLedgerPages(conn).render_ledger(
        account_id=1000, org=_ORG, theme="warm"
    )
    assert "1000" in resp.body_html
    assert "Operating Cash" in resp.body_html
    assert "OPERATING" in resp.body_html
    assert "DEBIT" in resp.body_html  # normal balance for Asset


def test_render_ledger_income_shows_credit_normal_balance(
    conn: sqlite3.Connection,
) -> None:
    resp = AccountLedgerPages(conn).render_ledger(
        account_id=4000, org=_ORG, theme="warm"
    )
    assert "CREDIT" in resp.body_html  # normal balance for Income


def test_render_ledger_shows_transactions(conn: sqlite3.Connection) -> None:
    pid = _seed_period(conn)
    _seed_journal_entry(conn, period_id=pid, memo="Deposit")
    resp = AccountLedgerPages(conn).render_ledger(
        account_id=1000, org=_ORG, theme="warm"
    )
    assert resp.status_code == 200
    assert "Deposit" in resp.body_html
    assert "100" in resp.body_html


def test_render_ledger_debit_account_shows_dr_balance(
    conn: sqlite3.Connection,
) -> None:
    pid = _seed_period(conn)
    _seed_journal_entry(
        conn, period_id=pid,
        debit_account_id=1000, credit_account_id=4000, amount="250.00"
    )
    resp = AccountLedgerPages(conn).render_ledger(
        account_id=1000, org=_ORG, theme="warm"
    )
    # Cash (asset) debited → running balance should show "Dr"
    assert "Dr" in resp.body_html


def test_render_ledger_credit_account_shows_cr_balance(
    conn: sqlite3.Connection,
) -> None:
    pid = _seed_period(conn)
    _seed_journal_entry(
        conn, period_id=pid,
        debit_account_id=1000, credit_account_id=4000, amount="250.00"
    )
    resp = AccountLedgerPages(conn).render_ledger(
        account_id=4000, org=_ORG, theme="warm"
    )
    # Income (credit account) credited → running balance shows "Cr"
    assert "Cr" in resp.body_html


def test_render_ledger_totals_row(conn: sqlite3.Connection) -> None:
    pid = _seed_period(conn)
    _seed_journal_entry(conn, period_id=pid, amount="75.00")
    resp = AccountLedgerPages(conn).render_ledger(
        account_id=1000, org=_ORG, theme="warm"
    )
    assert "75" in resp.body_html


def test_render_ledger_date_filter_start(conn: sqlite3.Connection) -> None:
    pid = _seed_period(conn)
    _seed_journal_entry(conn, period_id=pid, entry_date="2030-01-10", memo="Early")
    _seed_journal_entry(conn, period_id=pid, entry_date="2030-01-20", memo="Late")
    resp = AccountLedgerPages(conn).render_ledger(
        account_id=1000, org=_ORG, theme="warm",
        start_date="2030-01-15",
    )
    assert "Late" in resp.body_html
    assert "Early" not in resp.body_html


def test_render_ledger_date_filter_end(conn: sqlite3.Connection) -> None:
    pid = _seed_period(conn)
    _seed_journal_entry(conn, period_id=pid, entry_date="2030-01-10", memo="Early")
    _seed_journal_entry(conn, period_id=pid, entry_date="2030-01-20", memo="Late")
    resp = AccountLedgerPages(conn).render_ledger(
        account_id=1000, org=_ORG, theme="warm",
        end_date="2030-01-15",
    )
    assert "Early" in resp.body_html
    assert "Late" not in resp.body_html


def test_render_ledger_row_count_in_topbar(conn: sqlite3.Connection) -> None:
    pid = _seed_period(conn)
    _seed_journal_entry(conn, period_id=pid)
    resp = AccountLedgerPages(conn).render_ledger(
        account_id=1000, org=_ORG, theme="warm"
    )
    assert "1 transaction" in resp.body_html
