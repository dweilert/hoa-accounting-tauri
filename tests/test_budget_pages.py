"""Tests for budget pages.

Covers:
- render_list: empty, shows budgets with status
- render_new_form: renders OK
- handle_new: creates budget, duplicate year+fund rejected
- render_edit_form: shows grid with account rows, loads saved amounts
- handle_save: upserts lines, zeros are removed
- handle_approve: DRAFT → APPROVED
- handle_archive: APPROVED → ARCHIVED
- handle_delete: removes DRAFT, blocks non-DRAFT
"""

from __future__ import annotations

import sqlite3

import pytest

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.web.budget_pages import BudgetPages


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
        [
            (1, "ASSET", "Asset", "DEBIT"),
            (5, "EXPENSE", "Expense", "DEBIT"),
        ],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO accounts "
        "(id, account_number, account_name, account_type_id, fund_code, group_code, is_bank_account, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1000, "1000", "Cash",       1, "OPERATING", None,        1, 1),
            (6100, "6100", "Mow & Blow", 5, "OPERATING", "LANDSCAPE", 0, 1),
            (6200, "6200", "Sewer Fee",  5, "OPERATING", "SEWER",     0, 1),
        ],
    )
    conn.commit()


def _make_budget(conn: sqlite3.Connection, fiscal_year: int = 2025,
                 fund_code: str = "OPERATING", status: str = "DRAFT") -> int:
    cur = conn.execute(
        "INSERT INTO budgets (fiscal_year, fund_code, status) VALUES (?, ?, ?)",
        (fiscal_year, fund_code, status),
    )
    conn.commit()
    return int(cur.lastrowid)


# ── render_list ────────────────────────────────────────────────────

def test_list_empty(conn: sqlite3.Connection) -> None:
    resp = BudgetPages(conn).render_list(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "No budgets yet" in resp.body_html


def test_list_shows_budget(conn: sqlite3.Connection) -> None:
    _make_budget(conn, 2025)
    resp = BudgetPages(conn).render_list(org=_ORG, theme="warm")
    assert "2025" in resp.body_html
    assert "OPERATING" in resp.body_html
    assert "Draft" in resp.body_html


def test_list_flash_message(conn: sqlite3.Connection) -> None:
    resp = BudgetPages(conn).render_list(org=_ORG, theme="warm",
                                         flash_message="Budget saved.")
    assert "Budget saved." in resp.body_html


# ── render_new_form ────────────────────────────────────────────────

def test_new_form_renders(conn: sqlite3.Connection) -> None:
    resp = BudgetPages(conn).render_new_form(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "Fiscal Year" in resp.body_html


# ── handle_new ────────────────────────────────────────────────────

def test_handle_new_creates_budget(conn: sqlite3.Connection) -> None:
    redirect_url, form_resp = BudgetPages(conn).handle_new(
        form_data={"fiscal_year": "2025", "fund_code": "OPERATING", "notes": ""},
        org=_ORG, theme="warm",
    )
    assert form_resp is None
    assert redirect_url is not None
    assert "/budgets/" in redirect_url
    assert "edit" in redirect_url

    row = conn.execute("SELECT * FROM budgets WHERE fiscal_year = 2025").fetchone()
    assert row is not None
    assert row["fund_code"] == "OPERATING"
    assert row["status"] == "DRAFT"


def test_handle_new_duplicate_rejected(conn: sqlite3.Connection) -> None:
    _make_budget(conn, 2025, "OPERATING")
    redirect_url, form_resp = BudgetPages(conn).handle_new(
        form_data={"fiscal_year": "2025", "fund_code": "OPERATING", "notes": ""},
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert form_resp is not None
    assert "already exists" in form_resp.body_html


def test_handle_new_invalid_year(conn: sqlite3.Connection) -> None:
    redirect_url, form_resp = BudgetPages(conn).handle_new(
        form_data={"fiscal_year": "not-a-year", "fund_code": "OPERATING", "notes": ""},
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert form_resp is not None
    assert "number" in form_resp.body_html.lower()


# ── render_edit_form ───────────────────────────────────────────────

def test_edit_form_shows_accounts(conn: sqlite3.Connection) -> None:
    bid = _make_budget(conn, 2025)
    resp = BudgetPages(conn).render_edit_form(bid, org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "6100" in resp.body_html
    assert "Mow" in resp.body_html
    assert "6200" in resp.body_html


def test_edit_form_404(conn: sqlite3.Connection) -> None:
    resp = BudgetPages(conn).render_edit_form(9999, org=_ORG, theme="warm")
    assert resp.status_code == 404


def test_edit_form_loads_saved_amounts(conn: sqlite3.Connection) -> None:
    bid = _make_budget(conn, 2025)
    conn.execute(
        "INSERT INTO budget_lines (budget_id, account_id, fiscal_period, budget_amount) VALUES (?, ?, ?, ?)",
        (bid, 6100, 3, "250.00"),
    )
    conn.commit()
    resp = BudgetPages(conn).render_edit_form(bid, org=_ORG, theme="warm")
    assert "250" in resp.body_html


# ── handle_save ───────────────────────────────────────────────────

def test_handle_save_upserts_lines(conn: sqlite3.Connection) -> None:
    bid = _make_budget(conn, 2025)
    redirect_url, form_resp = BudgetPages(conn).handle_save(
        bid,
        form_data={
            "notes": "Annual budget",
            "amt_6100_1": "300.00",
            "amt_6100_2": "300.00",
            "amt_6200_6": "150.00",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is not None
    assert form_resp is None

    lines = conn.execute(
        "SELECT account_id, fiscal_period, budget_amount FROM budget_lines WHERE budget_id = ?",
        (bid,),
    ).fetchall()
    assert len(lines) == 3
    amounts = {(r["account_id"], r["fiscal_period"]): str(r["budget_amount"]) for r in lines}
    assert float(amounts[(6100, 1)]) == 300.0
    assert float(amounts[(6200, 6)]) == 150.0


def test_handle_save_removes_zeros(conn: sqlite3.Connection) -> None:
    bid = _make_budget(conn, 2025)
    # Pre-seed a line then save with zero to remove it
    conn.execute(
        "INSERT INTO budget_lines (budget_id, account_id, fiscal_period, budget_amount) VALUES (?, ?, ?, ?)",
        (bid, 6100, 1, "100.00"),
    )
    conn.commit()
    BudgetPages(conn).handle_save(
        bid,
        form_data={"amt_6100_1": "0"},
        org=_ORG, theme="warm",
    )
    lines = conn.execute(
        "SELECT * FROM budget_lines WHERE budget_id = ?", (bid,)
    ).fetchall()
    assert len(lines) == 0


# ── handle_approve / archive / delete ─────────────────────────────

def test_handle_approve(conn: sqlite3.Connection) -> None:
    bid = _make_budget(conn, 2025)
    redirect_url, _ = BudgetPages(conn).handle_approve(bid, org=_ORG, theme="warm")
    assert redirect_url is not None
    row = conn.execute("SELECT status FROM budgets WHERE id = ?", (bid,)).fetchone()
    assert row["status"] == "APPROVED"


def test_handle_approve_already_approved(conn: sqlite3.Connection) -> None:
    bid = _make_budget(conn, 2025, status="APPROVED")
    redirect_url, _ = BudgetPages(conn).handle_approve(bid, org=_ORG, theme="warm")
    assert redirect_url is not None
    assert "approved" in redirect_url.lower()


def test_handle_archive(conn: sqlite3.Connection) -> None:
    bid = _make_budget(conn, 2025, status="APPROVED")
    BudgetPages(conn).handle_archive(bid, org=_ORG, theme="warm")
    row = conn.execute("SELECT status FROM budgets WHERE id = ?", (bid,)).fetchone()
    assert row["status"] == "ARCHIVED"


def test_handle_delete_draft(conn: sqlite3.Connection) -> None:
    bid = _make_budget(conn, 2025)
    BudgetPages(conn).handle_delete(bid, org=_ORG, theme="warm")
    row = conn.execute("SELECT id FROM budgets WHERE id = ?", (bid,)).fetchone()
    assert row is None


def test_handle_delete_blocks_approved(conn: sqlite3.Connection) -> None:
    bid = _make_budget(conn, 2025, status="APPROVED")
    redirect_url, _ = BudgetPages(conn).handle_delete(bid, org=_ORG, theme="warm")
    assert "Only+DRAFT" in (redirect_url or "")
    row = conn.execute("SELECT id FROM budgets WHERE id = ?", (bid,)).fetchone()
    assert row is not None
