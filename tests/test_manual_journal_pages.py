"""Tests for the manual journal entry pages.

Covers:
- render_list: empty state, seeded entries, flash message
- render_new_form: blank form renders, account dropdown populated
- handle_new: success redirect, missing date, missing memo,
              too few lines, unbalanced entry, closed period, view after post
- render_view: shows entry + lines, 404 fallback for missing id
"""

from __future__ import annotations

import sqlite3

import pytest

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.repositories.journal_repo import JournalRepository
from hoa_accounting.web.manual_journal_pages import ManualJournalPages


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
    """Seed the minimum account_types + accounts rows for tests."""
    conn.executemany(
        "INSERT OR IGNORE INTO account_types (id, code, name, normal_balance) VALUES (?, ?, ?, ?)",
        [
            (1, "ASSET",     "Asset",     "DEBIT"),
            (2, "LIABILITY", "Liability", "CREDIT"),
            (3, "EQUITY",    "Equity",    "CREDIT"),
            (4, "INCOME",    "Income",    "CREDIT"),
            (5, "EXPENSE",   "Expense",   "DEBIT"),
        ],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO accounts "
        "(id, account_number, account_name, account_type_id, fund_code, is_bank_account, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (1000, "1000", "Operating Cash",      1, "OPERATING", 1, 1),
            (1100, "1100", "Dues Receivable",      1, "OPERATING", 0, 1),
            (4000, "4000", "Assessment Income",   4, "OPERATING", 0, 1),
            (6000, "6000", "Landscaping Expense", 5, "OPERATING", 0, 1),
        ],
    )
    conn.commit()


def _seed_open_period(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "INSERT INTO accounting_periods "
        "(period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed) "
        "VALUES ('2030-01', '2030-01-01', '2030-01-31', 2030, 1, 0)",
    )
    conn.commit()
    return int(cur.lastrowid)


def _seed_closed_period(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "INSERT INTO accounting_periods "
        "(period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed, closed_at) "
        "VALUES ('2029-12', '2029-12-01', '2029-12-31', 2029, 12, 1, '2030-01-01 00:00:00')",
    )
    conn.commit()
    return int(cur.lastrowid)


def _post_entry(conn: sqlite3.Connection) -> str:
    """Post a balanced MANUAL journal entry; return its redirect URL."""
    _seed_open_period(conn)
    pages = ManualJournalPages(conn)
    redirect_url, _ = pages.handle_new(
        form_data={
            "entry_date": "2030-01-15",
            "memo": "Test adjustment",
            "line_count": "2",
            "account_id_1": "1000",
            "description_1": "Cash in",
            "debit_1": "100.00",
            "credit_1": "",
            "account_id_2": "4000",
            "description_2": "Income",
            "debit_2": "",
            "credit_2": "100.00",
        },
        org=_ORG, theme="warm",
    )
    return redirect_url  # type: ignore[return-value]


# ── render_list ────────────────────────────────────────────────────────


def test_render_list_empty(conn: sqlite3.Connection) -> None:
    resp = ManualJournalPages(conn).render_list(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "No manual journal entries" in resp.body_html


def test_render_list_flash(conn: sqlite3.Connection) -> None:
    resp = ManualJournalPages(conn).render_list(
        org=_ORG, theme="warm", flash_message="Done."
    )
    assert "Done." in resp.body_html


def test_render_list_shows_posted_entry(conn: sqlite3.Connection) -> None:
    _post_entry(conn)
    resp = ManualJournalPages(conn).render_list(org=_ORG, theme="warm")
    assert "Test adjustment" in resp.body_html
    assert "Posted" in resp.body_html


# ── render_new_form ────────────────────────────────────────────────────


def test_render_new_form_blank(conn: sqlite3.Connection) -> None:
    resp = ManualJournalPages(conn).render_new_form(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "New Manual Journal Entry" in resp.body_html
    # Account dropdown should be populated
    assert "1000" in resp.body_html
    assert "Operating Cash" in resp.body_html


def test_render_new_form_with_error(conn: sqlite3.Connection) -> None:
    resp = ManualJournalPages(conn).render_new_form(
        org=_ORG, theme="warm", error_message="Entry Date is required."
    )
    assert resp.status_code == 400
    assert "Entry Date is required." in resp.body_html


# ── handle_new ─────────────────────────────────────────────────────────


def test_handle_new_success_redirects(conn: sqlite3.Connection) -> None:
    _seed_open_period(conn)
    redirect_url, resp = ManualJournalPages(conn).handle_new(
        form_data={
            "entry_date": "2030-01-15",
            "memo": "Reclassification",
            "line_count": "2",
            "account_id_1": "1100",
            "description_1": "AR",
            "debit_1": "50.00",
            "credit_1": "",
            "account_id_2": "4000",
            "description_2": "Income",
            "debit_2": "",
            "credit_2": "50.00",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is not None
    assert resp is None
    assert "/journal-entries/" in redirect_url


def test_handle_new_posts_to_database(conn: sqlite3.Connection) -> None:
    _seed_open_period(conn)
    ManualJournalPages(conn).handle_new(
        form_data={
            "entry_date": "2030-01-20",
            "memo": "Check balance",
            "line_count": "2",
            "account_id_1": "6000",
            "description_1": "Exp",
            "debit_1": "75.00",
            "credit_1": "",
            "account_id_2": "1000",
            "description_2": "Cash",
            "debit_2": "",
            "credit_2": "75.00",
        },
        org=_ORG, theme="warm",
    )
    entries = JournalRepository(conn).list_manual_entries()
    assert len(entries) == 1
    assert entries[0]["memo"] == "Check balance"


def test_handle_new_missing_date(conn: sqlite3.Connection) -> None:
    redirect_url, resp = ManualJournalPages(conn).handle_new(
        form_data={
            "entry_date": "",
            "memo": "Test",
            "line_count": "2",
            "account_id_1": "1000", "debit_1": "10", "credit_1": "",
            "account_id_2": "4000", "debit_2": "",  "credit_2": "10",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert resp is not None
    assert resp.status_code == 400
    assert "Entry Date is required" in resp.body_html


def test_handle_new_missing_memo(conn: sqlite3.Connection) -> None:
    redirect_url, resp = ManualJournalPages(conn).handle_new(
        form_data={
            "entry_date": "2030-01-15",
            "memo": "",
            "line_count": "2",
            "account_id_1": "1000", "debit_1": "10", "credit_1": "",
            "account_id_2": "4000", "debit_2": "",  "credit_2": "10",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert resp is not None
    assert "Memo is required" in resp.body_html


def test_handle_new_too_few_lines(conn: sqlite3.Connection) -> None:
    _seed_open_period(conn)
    redirect_url, resp = ManualJournalPages(conn).handle_new(
        form_data={
            "entry_date": "2030-01-15",
            "memo": "Test",
            "line_count": "1",
            "account_id_1": "1000",
            "debit_1": "10.00",
            "credit_1": "",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert resp is not None
    assert "2" in resp.body_html  # "At least 2 non-blank lines"


def test_handle_new_unbalanced_entry(conn: sqlite3.Connection) -> None:
    _seed_open_period(conn)
    redirect_url, resp = ManualJournalPages(conn).handle_new(
        form_data={
            "entry_date": "2030-01-15",
            "memo": "Unbalanced",
            "line_count": "2",
            "account_id_1": "1000", "debit_1": "100.00", "credit_1": "",
            "account_id_2": "4000", "debit_2": "",       "credit_2": "50.00",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert resp is not None
    assert resp.status_code == 400


def test_handle_new_closed_period_returns_error(conn: sqlite3.Connection) -> None:
    _seed_closed_period(conn)
    redirect_url, resp = ManualJournalPages(conn).handle_new(
        form_data={
            "entry_date": "2029-12-15",
            "memo": "Into closed period",
            "line_count": "2",
            "account_id_1": "1000", "debit_1": "10.00", "credit_1": "",
            "account_id_2": "4000", "debit_2": "",       "credit_2": "10.00",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert resp is not None
    assert resp.status_code == 400


def test_handle_new_blank_lines_skipped(conn: sqlite3.Connection) -> None:
    """Fully blank lines should be silently skipped (not cause an error)."""
    _seed_open_period(conn)
    redirect_url, resp = ManualJournalPages(conn).handle_new(
        form_data={
            "entry_date": "2030-01-15",
            "memo": "With blanks",
            "line_count": "3",
            "account_id_1": "1000", "debit_1": "10.00", "credit_1": "",
            "account_id_2": "4000", "debit_2": "",       "credit_2": "10.00",
            # line 3 is completely blank
            "account_id_3": "",    "debit_3": "",        "credit_3": "",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is not None
    assert resp is None


# ── render_view ────────────────────────────────────────────────────────


def test_render_view_shows_entry(conn: sqlite3.Connection) -> None:
    redirect_url = _post_entry(conn)
    # Extract the journal_entry_id from the redirect URL
    je_id = int(redirect_url.split("/journal-entries/")[1].split("?")[0])
    resp = ManualJournalPages(conn).render_view(
        journal_entry_id=je_id, org=_ORG, theme="warm"
    )
    assert resp.status_code == 200
    assert "Test adjustment" in resp.body_html
    assert "100" in resp.body_html


def test_render_view_shows_totals(conn: sqlite3.Connection) -> None:
    redirect_url = _post_entry(conn)
    je_id = int(redirect_url.split("/journal-entries/")[1].split("?")[0])
    resp = ManualJournalPages(conn).render_view(
        journal_entry_id=je_id, org=_ORG, theme="warm"
    )
    assert "100" in resp.body_html


def test_render_view_missing_id(conn: sqlite3.Connection) -> None:
    resp = ManualJournalPages(conn).render_view(
        journal_entry_id=99999, org=_ORG, theme="warm"
    )
    assert resp.status_code == 404
