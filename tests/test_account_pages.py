"""Tests for the Chart of Accounts management pages.

Covers:
- GET /accounts: renders list, empty state, account rows, flash message
- GET /accounts/add: renders blank form with account type options
- POST /accounts/add: inserts account, redirects with flash
- POST /accounts/add: missing required fields return errors
- POST /accounts/add: duplicate account_number returns error
- GET /accounts/<id>/edit: form pre-filled from DB
- POST /accounts/<id>/edit: updates account, redirects with flash
- POST /accounts/<id>/edit: duplicate account_number on another account returns error
- POST /accounts/<id>/edit: same account_number allowed on same account
- GET /accounts/<id>/edit for unknown id returns 404
- POST /accounts/<id>/delete: removes account, redirects with flash
- POST /accounts/<id>/delete: account with activity returns error
"""

from __future__ import annotations

import sqlite3

import pytest

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.repositories.accounts_repo import AccountsRepository
from hoa_accounting.web.account_pages import AccountPages


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    Migrator().apply_all(c)
    return c


def _seed_account(
    conn: sqlite3.Connection,
    *,
    account_number: str = "9001",
    account_name: str = "Test Expense",
    account_type_id: int = 5,   # EXPENSE
    fund_code: str = "OPERATING",
    group_code: str | None = "MISC",
    is_bank_account: int = 0,
    is_active: int = 1,
) -> int:
    cur = conn.execute(
        "INSERT INTO accounts "
        "(account_number, account_name, account_type_id, fund_code, "
        "group_code, is_bank_account, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (account_number, account_name, account_type_id,
         fund_code, group_code, is_bank_account, is_active),
    )
    conn.commit()
    return int(cur.lastrowid)


_ORG = {"name": "Test HOA", "environment": "test",
        "fiscal_year_start_month": 1, "theme": "warm"}


def _seed_journal_entry_line(
    conn: sqlite3.Connection, account_id: int, entry_number: str = "JE-001"
) -> None:
    """Seed a minimal accounting period → journal entry → line referencing account_id."""
    conn.execute(
        "INSERT OR IGNORE INTO accounting_periods "
        "(id, period_name, start_date, end_date, fiscal_year, fiscal_period) "
        "VALUES (1, '2024-01', '2024-01-01', '2024-01-31', 2024, 1)"
    )
    conn.execute(
        "INSERT INTO journal_entries (entry_number, entry_date, memo, "
        "accounting_period_id, source_type, status) "
        "VALUES (?, '2024-01-01', 'Test', 1, 'MANUAL', 'POSTED')",
        (entry_number,),
    )
    je_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO journal_entry_lines (journal_entry_id, line_number, account_id, "
        "debit_amount, credit_amount) VALUES (?, 1, ?, 100.00, 0)",
        (je_id, account_id),
    )
    conn.commit()


# ── render_list ────────────────────────────────────────────────────────


def test_render_list_seeded_accounts(conn: sqlite3.Connection) -> None:
    """Migrated DB already has seeded accounts — list must render them."""
    resp = AccountPages(conn).render_list(org=_ORG, theme="warm")
    assert resp.status_code == 200
    # Migrations seed many accounts; list must include something
    assert "<table" in resp.body_html


def test_render_list_shows_added_account(conn: sqlite3.Connection) -> None:
    _seed_account(conn)
    resp = AccountPages(conn).render_list(org=_ORG, theme="warm")
    assert "Test Expense" in resp.body_html
    assert "9001" in resp.body_html


def test_render_list_flash_message(conn: sqlite3.Connection) -> None:
    resp = AccountPages(conn).render_list(
        org=_ORG, theme="warm", flash_message="Account added."
    )
    assert "Account added." in resp.body_html


# ── render_form (add) ──────────────────────────────────────────────────


def test_render_form_add_shows_account_types(conn: sqlite3.Connection) -> None:
    resp = AccountPages(conn).render_form(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "Add Account" in resp.body_html
    assert "Asset" in resp.body_html
    assert "Expense" in resp.body_html


def test_render_form_add_shows_fund_codes(conn: sqlite3.Connection) -> None:
    resp = AccountPages(conn).render_form(org=_ORG, theme="warm")
    assert "OPERATING" in resp.body_html
    assert "RESERVE" in resp.body_html


def test_render_form_add_shows_group_codes(conn: sqlite3.Connection) -> None:
    resp = AccountPages(conn).render_form(org=_ORG, theme="warm")
    assert "LANDSCAPE" in resp.body_html
    assert "FIREWISE" in resp.body_html


# ── render_form (edit) ─────────────────────────────────────────────────


def test_render_form_edit_prefilled(conn: sqlite3.Connection) -> None:
    acct_id = _seed_account(conn)
    resp = AccountPages(conn).render_form(org=_ORG, theme="warm",
                                          account_id=acct_id)
    assert resp.status_code == 200
    assert "Edit Account" in resp.body_html
    assert "Test Expense" in resp.body_html
    assert "9001" in resp.body_html


def test_render_form_edit_unknown_returns_404(conn: sqlite3.Connection) -> None:
    resp = AccountPages(conn).render_form(org=_ORG, theme="warm",
                                          account_id=9999)
    assert resp.status_code == 404


def test_render_form_edit_with_activity_hides_delete(conn: sqlite3.Connection) -> None:
    """An account with journal_entry_lines activity should show the deactivate hint."""
    acct_id = _seed_account(conn, account_number="9010", is_bank_account=0)
    # Seed a journal entry line referencing the account
    _seed_journal_entry_line(conn, acct_id, "JE-001")
    resp = AccountPages(conn).render_form(org=_ORG, theme="warm",
                                          account_id=acct_id)
    assert "deactivate instead" in resp.body_html
    assert "delete" not in resp.body_html.lower().split("deactivate")[1][:50]


# ── handle_add ─────────────────────────────────────────────────────────


def test_handle_add_redirects_on_success(conn: sqlite3.Connection) -> None:
    redirect_url, resp = AccountPages(conn).handle_add(
        form_data={
            "account_number": "9500",
            "account_name": "New Expense",
            "account_type_id": "5",
            "fund_code": "OPERATING",
            "group_code": "MISC",
            "is_bank_account": "0",
            "description": "A test account",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is not None
    assert "accounts" in redirect_url
    assert resp is None
    rows = AccountsRepository(conn).list_chart(active_only=False)
    assert any(r["account_number"] == "9500" for r in rows)


def test_handle_add_missing_account_number_returns_error(conn: sqlite3.Connection) -> None:
    redirect_url, resp = AccountPages(conn).handle_add(
        form_data={
            "account_number": "",
            "account_name": "New Expense",
            "account_type_id": "5",
            "fund_code": "OPERATING",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert resp is not None
    assert resp.status_code == 400
    assert "Account Number is required" in resp.body_html


def test_handle_add_missing_account_name_returns_error(conn: sqlite3.Connection) -> None:
    redirect_url, resp = AccountPages(conn).handle_add(
        form_data={
            "account_number": "9500",
            "account_name": "",
            "account_type_id": "5",
            "fund_code": "OPERATING",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert resp is not None
    assert "Account Name is required" in resp.body_html


def test_handle_add_duplicate_number_returns_error(conn: sqlite3.Connection) -> None:
    _seed_account(conn, account_number="9001")
    redirect_url, resp = AccountPages(conn).handle_add(
        form_data={
            "account_number": "9001",
            "account_name": "Duplicate",
            "account_type_id": "5",
            "fund_code": "OPERATING",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert resp is not None
    assert "already in use" in resp.body_html


def test_handle_add_bank_account_flag(conn: sqlite3.Connection) -> None:
    AccountPages(conn).handle_add(
        form_data={
            "account_number": "1050",
            "account_name": "Savings Account",
            "account_type_id": "1",
            "fund_code": "OPERATING",
            "is_bank_account": "1",
        },
        org=_ORG, theme="warm",
    )
    row = AccountsRepository(conn).get_by_number("1050")
    assert row is not None
    detail = AccountsRepository(conn).get_account(row["id"])
    assert detail["is_bank_account"] == 1


# ── handle_edit ────────────────────────────────────────────────────────


def test_handle_edit_updates_and_redirects(conn: sqlite3.Connection) -> None:
    acct_id = _seed_account(conn)
    redirect_url, resp = AccountPages(conn).handle_edit(
        account_id=acct_id,
        form_data={
            "account_number": "9001",
            "account_name": "Updated Expense",
            "account_type_id": "5",
            "fund_code": "RESERVE",
            "group_code": "ROAD",
            "_is_active_present": "1",
            "is_active": "1",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is not None
    row = AccountsRepository(conn).get_account(acct_id)
    assert row["account_name"] == "Updated Expense"
    assert row["fund_code"] == "RESERVE"
    assert row["group_code"] == "ROAD"


def test_handle_edit_same_number_allowed(conn: sqlite3.Connection) -> None:
    acct_id = _seed_account(conn, account_number="9001")
    redirect_url, resp = AccountPages(conn).handle_edit(
        account_id=acct_id,
        form_data={
            "account_number": "9001",  # unchanged
            "account_name": "Test Expense Renamed",
            "account_type_id": "5",
            "fund_code": "OPERATING",
            "_is_active_present": "1",
            "is_active": "1",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is not None


def test_handle_edit_duplicate_number_other_account_returns_error(
    conn: sqlite3.Connection,
) -> None:
    _seed_account(conn, account_number="9001")
    acct2_id = _seed_account(conn, account_number="9002", account_name="Other")
    redirect_url, resp = AccountPages(conn).handle_edit(
        account_id=acct2_id,
        form_data={
            "account_number": "9001",  # taken by first account
            "account_name": "Other",
            "account_type_id": "5",
            "fund_code": "OPERATING",
            "_is_active_present": "1",
            "is_active": "1",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert resp is not None
    assert "already in use" in resp.body_html


def test_handle_edit_deactivate(conn: sqlite3.Connection) -> None:
    acct_id = _seed_account(conn)
    AccountPages(conn).handle_edit(
        account_id=acct_id,
        form_data={
            "account_number": "9001",
            "account_name": "Test Expense",
            "account_type_id": "5",
            "fund_code": "OPERATING",
            "_is_active_present": "1",
            # is_active omitted = unchecked
        },
        org=_ORG, theme="warm",
    )
    row = AccountsRepository(conn).get_account(acct_id)
    assert row["is_active"] == 0


# ── handle_delete ──────────────────────────────────────────────────────


def test_handle_delete_success(conn: sqlite3.Connection) -> None:
    acct_id = _seed_account(conn)
    redirect_url, resp = AccountPages(conn).handle_delete(
        account_id=acct_id, org=_ORG, theme="warm"
    )
    assert redirect_url is not None
    assert AccountsRepository(conn).get_account(acct_id) is None


def test_handle_delete_blocked_when_has_activity(conn: sqlite3.Connection) -> None:
    acct_id = _seed_account(conn, account_number="9010")
    _seed_journal_entry_line(conn, acct_id, "JE-001")
    redirect_url, resp = AccountPages(conn).handle_delete(
        account_id=acct_id, org=_ORG, theme="warm"
    )
    assert redirect_url is None
    assert resp is not None
    assert "Cannot delete" in resp.body_html
    assert AccountsRepository(conn).get_account(acct_id) is not None
