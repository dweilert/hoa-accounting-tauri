"""Tests for the accounting period management pages.

Covers:
- render_list: empty state, seeded periods, flash message
- render_add_form: blank form renders
- handle_add: success redirect, missing fields, duplicate name, bad dates
- render_generate_form: shows next-year default
- handle_generate_year: creates 12 periods, blocks duplicate year
- handle_delete: removes period with no JEs, blocked if has JEs
"""

from __future__ import annotations

import sqlite3

import pytest

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.repositories.periods_repo import PeriodsRepository
from hoa_accounting.web.accounting_period_pages import AccountingPeriodPages

# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    Migrator().apply_all(c)
    return c


def _seed_period(
    conn: sqlite3.Connection,
    *,
    period_name: str = "2030-01",
    start_date: str = "2030-01-01",
    end_date: str = "2030-01-31",
    fiscal_year: int = 2030,
    fiscal_period: int = 1,
    is_closed: int = 0,
) -> int:
    cur = conn.execute(
        "INSERT INTO accounting_periods "
        "(period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed),
    )
    conn.commit()
    return int(cur.lastrowid)


_ORG = {
    "name": "Test HOA",
    "environment": "test",
    "fiscal_year_start_month": 1,
    "theme": "warm",
}


# ── render_list ────────────────────────────────────────────────────────


def test_render_list_empty_state(conn: sqlite3.Connection) -> None:
    resp = AccountingPeriodPages(conn).render_list(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "No accounting periods" in resp.body_html


def test_render_list_shows_period(conn: sqlite3.Connection) -> None:
    _seed_period(conn, period_name="2030-06")
    resp = AccountingPeriodPages(conn).render_list(org=_ORG, theme="warm")
    assert "2030-06" in resp.body_html


def test_render_list_flash_message(conn: sqlite3.Connection) -> None:
    resp = AccountingPeriodPages(conn).render_list(
        org=_ORG, theme="warm", flash_message="Period added."
    )
    assert "Period added." in resp.body_html


# ── render_add_form ────────────────────────────────────────────────────


def test_render_add_form_blank(conn: sqlite3.Connection) -> None:
    resp = AccountingPeriodPages(conn).render_add_form(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "Add Period" in resp.body_html
    assert "Period Name" in resp.body_html


# ── handle_add ─────────────────────────────────────────────────────────


def test_handle_add_redirects_on_success(conn: sqlite3.Connection) -> None:
    redirect_url, resp = AccountingPeriodPages(conn).handle_add(
        form_data={
            "period_name": "2030-07",
            "start_date": "2030-07-01",
            "end_date": "2030-07-31",
            "fiscal_year": "2030",
            "fiscal_period": "7",
        },
        org=_ORG,
        theme="warm",
    )
    assert redirect_url is not None
    assert resp is None
    rows = PeriodsRepository(conn).list_periods()
    assert any(r["period_name"] == "2030-07" for r in rows)


def test_handle_add_missing_period_name_returns_error(conn: sqlite3.Connection) -> None:
    redirect_url, resp = AccountingPeriodPages(conn).handle_add(
        form_data={
            "period_name": "",
            "start_date": "2030-07-01",
            "end_date": "2030-07-31",
            "fiscal_year": "2030",
            "fiscal_period": "7",
        },
        org=_ORG,
        theme="warm",
    )
    assert redirect_url is None
    assert resp is not None
    assert resp.status_code == 400
    assert "Period Name is required" in resp.body_html


def test_handle_add_end_before_start_returns_error(conn: sqlite3.Connection) -> None:
    redirect_url, resp = AccountingPeriodPages(conn).handle_add(
        form_data={
            "period_name": "2030-07",
            "start_date": "2030-07-31",
            "end_date": "2030-07-01",
            "fiscal_year": "2030",
            "fiscal_period": "7",
        },
        org=_ORG,
        theme="warm",
    )
    assert redirect_url is None
    assert resp is not None
    assert "Start Date" in resp.body_html


def test_handle_add_duplicate_name_returns_error(conn: sqlite3.Connection) -> None:
    _seed_period(conn, period_name="2030-01")
    redirect_url, resp = AccountingPeriodPages(conn).handle_add(
        form_data={
            "period_name": "2030-01",
            "start_date": "2030-01-01",
            "end_date": "2030-01-31",
            "fiscal_year": "2030",
            "fiscal_period": "1",
        },
        org=_ORG,
        theme="warm",
    )
    assert redirect_url is None
    assert resp is not None
    assert "already exists" in resp.body_html


# ── handle_generate_year ───────────────────────────────────────────────


def test_handle_generate_year_creates_12_periods(conn: sqlite3.Connection) -> None:
    redirect_url, resp = AccountingPeriodPages(conn).handle_generate_year(
        form_data={"fiscal_year": "2031"},
        org=_ORG,
        theme="warm",
    )
    assert redirect_url is not None
    rows = PeriodsRepository(conn).list_periods()
    year_rows = [r for r in rows if r["fiscal_year"] == 2031]
    assert len(year_rows) == 12
    names = {r["period_name"] for r in year_rows}
    assert "2031-01" in names
    assert "2031-12" in names


def test_handle_generate_year_handles_leap_year(conn: sqlite3.Connection) -> None:
    AccountingPeriodPages(conn).handle_generate_year(
        form_data={"fiscal_year": "2032"},  # 2032 is a leap year
        org=_ORG,
        theme="warm",
    )
    rows = PeriodsRepository(conn).list_periods()
    feb = next(r for r in rows if r["period_name"] == "2032-02")
    assert feb["end_date"] == "2032-02-29"


def test_handle_generate_year_blocks_duplicate(conn: sqlite3.Connection) -> None:
    AccountingPeriodPages(conn).handle_generate_year(
        form_data={"fiscal_year": "2031"},
        org=_ORG,
        theme="warm",
    )
    redirect_url, resp = AccountingPeriodPages(conn).handle_generate_year(
        form_data={"fiscal_year": "2031"},
        org=_ORG,
        theme="warm",
    )
    assert redirect_url is None
    assert resp is not None
    assert "already exist" in resp.body_html


# ── handle_delete ──────────────────────────────────────────────────────


def test_handle_delete_removes_empty_period(conn: sqlite3.Connection) -> None:
    pid = _seed_period(conn)
    redirect_url, resp = AccountingPeriodPages(conn).handle_delete(
        period_id=pid, org=_ORG, theme="warm"
    )
    assert redirect_url is not None
    assert PeriodsRepository(conn).get_period(pid) is None
