"""Tests for the bank account management pages.

Covers:
- GET /bank-accounts: renders list, empty state, account rows, flash message
- GET /bank-accounts/add: renders blank form with GL account options
- POST /bank-accounts/add: inserts account, redirects with flash
- POST /bank-accounts/add: missing required fields return errors
- GET /bank-accounts/<id>/edit: form pre-filled from DB
- POST /bank-accounts/<id>/edit: updates account, redirects with flash
- GET /bank-accounts/<id>/edit for unknown id returns 404
- POST /bank-accounts/<id>/delete: removes account, redirects with flash
- POST /bank-accounts/<id>/delete: account with transactions returns error
"""

from __future__ import annotations

import sqlite3

import pytest

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.repositories.bank_accounts_repo import BankAccountsRepository
from hoa_accounting.web.bank_account_pages import BankAccountPages


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    Migrator().apply_all(c)
    return c


def _seed_gl_account(
    conn: sqlite3.Connection,
    account_id: int = 100,
    account_number: str = "1000",
    account_name: str = "Cash - Operating",
) -> int:
    """Insert an active bank-type GL account and return its id."""
    conn.execute(
        "INSERT INTO accounts (id, account_number, account_name, account_type_id, "
        "fund_code, is_bank_account, is_active) "
        "VALUES (?, ?, ?, 1, 'OPERATING', 1, 1)",
        (account_id, account_number, account_name),
    )
    conn.commit()
    return account_id


def _seed_bank_account(
    conn: sqlite3.Connection,
    *,
    gl_account_id: int | None = None,
    account_name: str = "Operating Checking",
    institution_name: str = "Big Bank",
    account_type: str = "CHECKING",
    account_last4: str = "1234",
) -> int:
    if gl_account_id is None:
        gl_account_id = _seed_gl_account(conn)
    cur = conn.execute(
        "INSERT INTO bank_accounts "
        "(account_name, institution_name, account_last4, account_type, gl_account_id, active_flag) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (account_name, institution_name, account_last4, account_type, gl_account_id),
    )
    conn.commit()
    return int(cur.lastrowid)


_ORG = {"name": "Test HOA", "environment": "test",
        "fiscal_year_start_month": 1, "theme": "warm"}


# ── render_list ────────────────────────────────────────────────────────


def test_render_list_empty_state(conn: sqlite3.Connection) -> None:
    resp = BankAccountPages(conn).render_list(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "No bank accounts on record" in resp.body_html


def test_render_list_shows_accounts(conn: sqlite3.Connection) -> None:
    _seed_bank_account(conn)
    resp = BankAccountPages(conn).render_list(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "Operating Checking" in resp.body_html
    assert "Big Bank" in resp.body_html
    assert "CHECKING" in resp.body_html


def test_render_list_flash_message(conn: sqlite3.Connection) -> None:
    resp = BankAccountPages(conn).render_list(
        org=_ORG, theme="warm", flash_message="Bank account added."
    )
    assert "Bank account added." in resp.body_html


# ── render_form (add) ──────────────────────────────────────────────────


def test_render_form_add_blank(conn: sqlite3.Connection) -> None:
    _seed_gl_account(conn)
    resp = BankAccountPages(conn).render_form(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "Add Bank Account" in resp.body_html
    # GL account option should appear
    assert "1000" in resp.body_html
    assert "Cash - Operating" in resp.body_html


def test_render_form_add_excludes_already_assigned_gl(conn: sqlite3.Connection) -> None:
    """A GL account already linked to a bank account must not appear in the add dropdown."""
    gl_id = _seed_gl_account(conn)
    _seed_bank_account(conn, gl_account_id=gl_id)
    resp = BankAccountPages(conn).render_form(org=_ORG, theme="warm")
    # The GL account is taken — it should not appear as an option for a new bank account
    assert "Cash - Operating" not in resp.body_html


# ── render_form (edit) ─────────────────────────────────────────────────


def test_render_form_edit_prefilled(conn: sqlite3.Connection) -> None:
    ba_id = _seed_bank_account(conn)
    resp = BankAccountPages(conn).render_form(org=_ORG, theme="warm",
                                               bank_account_id=ba_id)
    assert resp.status_code == 200
    assert "Edit Bank Account" in resp.body_html
    assert "Operating Checking" in resp.body_html
    assert "Big Bank" in resp.body_html


def test_render_form_edit_includes_own_gl_in_dropdown(conn: sqlite3.Connection) -> None:
    """When editing, the account's own GL account must stay selectable."""
    ba_id = _seed_bank_account(conn)
    resp = BankAccountPages(conn).render_form(org=_ORG, theme="warm",
                                               bank_account_id=ba_id)
    assert "Cash - Operating" in resp.body_html


def test_render_form_edit_unknown_returns_404(conn: sqlite3.Connection) -> None:
    resp = BankAccountPages(conn).render_form(org=_ORG, theme="warm",
                                               bank_account_id=9999)
    assert resp.status_code == 404


# ── handle_add ─────────────────────────────────────────────────────────


def test_handle_add_redirects_on_success(conn: sqlite3.Connection) -> None:
    gl_id = _seed_gl_account(conn)
    redirect_url, resp = BankAccountPages(conn).handle_add(
        form_data={
            "account_name": "Reserve Savings",
            "institution_name": "Credit Union",
            "account_type": "SAVINGS",
            "account_last4": "5678",
            "gl_account_id": str(gl_id),
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is not None
    assert "bank-accounts" in redirect_url
    assert resp is None
    rows = BankAccountsRepository(conn).list_bank_accounts(active_only=False)
    assert any(r["account_name"] == "Reserve Savings" for r in rows)


def test_handle_add_missing_account_name_returns_error(conn: sqlite3.Connection) -> None:
    gl_id = _seed_gl_account(conn)
    redirect_url, resp = BankAccountPages(conn).handle_add(
        form_data={
            "account_name": "",
            "institution_name": "Big Bank",
            "account_type": "CHECKING",
            "gl_account_id": str(gl_id),
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert resp is not None
    assert resp.status_code == 400
    assert "Account Name is required" in resp.body_html


def test_handle_add_missing_institution_returns_error(conn: sqlite3.Connection) -> None:
    gl_id = _seed_gl_account(conn)
    redirect_url, resp = BankAccountPages(conn).handle_add(
        form_data={
            "account_name": "Operating Checking",
            "institution_name": "",
            "account_type": "CHECKING",
            "gl_account_id": str(gl_id),
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert resp is not None
    assert "Institution Name is required" in resp.body_html


def test_handle_add_missing_gl_account_returns_error(conn: sqlite3.Connection) -> None:
    redirect_url, resp = BankAccountPages(conn).handle_add(
        form_data={
            "account_name": "Operating Checking",
            "institution_name": "Big Bank",
            "account_type": "CHECKING",
            "gl_account_id": "",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert resp is not None
    assert "GL Account is required" in resp.body_html


# ── handle_edit ────────────────────────────────────────────────────────


def test_handle_edit_updates_and_redirects(conn: sqlite3.Connection) -> None:
    ba_id = _seed_bank_account(conn)
    redirect_url, resp = BankAccountPages(conn).handle_edit(
        bank_account_id=ba_id,
        form_data={
            "account_name": "Operating Checking Updated",
            "institution_name": "New Bank",
            "account_type": "CHECKING",
            "account_last4": "9999",
            "gl_account_id": "100",
            "_active_flag_present": "1",
            "active_flag": "1",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is not None
    row = BankAccountsRepository(conn).get_bank_account(ba_id)
    assert row["account_name"] == "Operating Checking Updated"
    assert row["institution_name"] == "New Bank"
    assert row["account_last4"] == "9999"


def test_handle_edit_deactivate(conn: sqlite3.Connection) -> None:
    ba_id = _seed_bank_account(conn)
    BankAccountPages(conn).handle_edit(
        bank_account_id=ba_id,
        form_data={
            "account_name": "Operating Checking",
            "institution_name": "Big Bank",
            "account_type": "CHECKING",
            "gl_account_id": "100",
            "_active_flag_present": "1",
            # active_flag omitted = unchecked
        },
        org=_ORG, theme="warm",
    )
    row = BankAccountsRepository(conn).get_bank_account(ba_id)
    assert row["active_flag"] == 0


# ── handle_delete ──────────────────────────────────────────────────────


def test_handle_delete_success(conn: sqlite3.Connection) -> None:
    ba_id = _seed_bank_account(conn)
    redirect_url, resp = BankAccountPages(conn).handle_delete(
        bank_account_id=ba_id, org=_ORG, theme="warm"
    )
    assert redirect_url is not None
    assert BankAccountsRepository(conn).get_bank_account(ba_id) is None


def test_handle_delete_blocked_when_has_transactions(conn: sqlite3.Connection) -> None:
    ba_id = _seed_bank_account(conn)
    # Seed a bank transaction referencing this bank account
    conn.execute(
        "INSERT INTO bank_transactions "
        "(bank_account_id, transaction_date, description, amount) "
        "VALUES (?, '2024-01-15', 'Test deposit', 500.00)",
        (ba_id,),
    )
    conn.commit()
    redirect_url, resp = BankAccountPages(conn).handle_delete(
        bank_account_id=ba_id, org=_ORG, theme="warm"
    )
    assert redirect_url is None
    assert resp is not None
    assert "Cannot delete" in resp.body_html
    # Row still exists
    assert BankAccountsRepository(conn).get_bank_account(ba_id) is not None
