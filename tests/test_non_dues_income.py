"""Tests for the non-dues income service + page flow.

Uses a real migrated in-memory DB so the 0004 schema (income_batches)
is in place, and seeds the minimum reference data needed to post.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

import pytest

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.exceptions import ValidationError
from hoa_accounting.services.non_dues_income_service import IncomeRow
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.web.non_dues_income_pages import NonDuesIncomePages


# ── Fixtures ───────────────────────────────────────────────────────


def _seed(conn: sqlite3.Connection) -> dict[str, int]:
    conn.execute(
        "INSERT INTO accounting_periods "
        "(id, period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed) "
        "VALUES (1, '2026-04', '2026-04-01', '2026-04-30', 2026, 4, 0)"
    )
    conn.execute(
        "INSERT INTO accounts (id, account_number, account_name, account_type_id, "
        " fund_code, is_bank_account, is_active) "
        "VALUES (1000, '1000', 'Cash - Operating', 1, 'OPERATING', 1, 1)"
    )
    conn.execute(
        "INSERT INTO bank_accounts (id, account_name, institution_name, account_last4, "
        " account_type, gl_account_id, active_flag) "
        "VALUES (1, 'Operating Checking', 'Big Bank', '1234', 'CHECKING', 1000, 1)"
    )
    # Interest income account (type 4 = INCOME per seed).
    conn.execute(
        "INSERT INTO accounts (id, account_number, account_name, account_type_id, "
        " fund_code, is_bank_account, is_active) "
        "VALUES (4200, '4200', 'Interest Income', 4, 'OPERATING', 0, 1)"
    )
    # An inactive income account for negative-path tests.
    conn.execute(
        "INSERT INTO accounts (id, account_number, account_name, account_type_id, "
        " fund_code, is_bank_account, is_active) "
        "VALUES (4999, '4999', 'Legacy Income', 4, 'OPERATING', 0, 0)"
    )
    conn.execute(
        "INSERT INTO owners (id, owner_type, display_name, active_flag) "
        "VALUES (1, 'PERSON', 'Alice Park', 1)"
    )
    conn.execute(
        "INSERT INTO lots (id, lot_number, active_flag) VALUES (1, 'L-1', 1)"
    )
    conn.execute(
        "INSERT INTO lot_ownership "
        "(id, lot_id, owner_id, start_date, end_date) "
        "VALUES (1, 1, 1, '2020-01-01', NULL)"
    )
    conn.commit()
    return {
        "bank_account_id": 1,
        "cash_account_id": 1000,
        "interest_income_id": 4200,
        "legacy_income_id": 4999,
        "alice_lot_id": 1,
        "alice_owner_id": 1,
    }


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    Migrator().apply_all(c)
    return c


_ORG = {
    "name": "Test HOA", "legal_name": "Test Inc.", "environment": "test",
    "fiscal_year_start_month": 1, "theme": "warm",
    "dues_receivable_account_number": "1100",
}


# ── Service: accounting shape ──────────────────────────────────────


def test_other_only_batch_creates_one_debit_one_credit(conn: sqlite3.Connection) -> None:
    """A bank-interest-only batch: 1 debit to cash, 1 credit to income."""
    ids = _seed(conn)
    result = ServiceFactory(conn).non_dues_income_service().post_batch(
        posting_date="2026-04-15",
        bank_account_id=ids["bank_account_id"],
        income_account_id=ids["interest_income_id"],
        income_description="Frost Bank — April interest",
        rows=[IncomeRow(amount="11.67", other_source="Bank interest")],
    )
    lines = conn.execute(
        "SELECT account_id, debit_amount, credit_amount, owner_id, description "
        "FROM journal_entry_lines WHERE journal_entry_id = ? ORDER BY line_number",
        (result.journal_entry_id,),
    ).fetchall()
    assert len(lines) == 2
    assert int(lines[0]["account_id"]) == ids["cash_account_id"]
    assert Decimal(str(lines[0]["debit_amount"])) == Decimal("11.67")
    assert int(lines[1]["account_id"]) == ids["interest_income_id"]
    assert Decimal(str(lines[1]["credit_amount"])) == Decimal("11.67")
    # OTHER row has no owner/lot but carries the source as the line description.
    assert lines[1]["owner_id"] is None
    assert "Bank interest" in str(lines[1]["description"])


def test_mixed_owner_and_other_batch(conn: sqlite3.Connection) -> None:
    """Owner row + OTHER row go into one JE with per-row attribution."""
    ids = _seed(conn)
    result = ServiceFactory(conn).non_dues_income_service().post_batch(
        posting_date="2026-04-15",
        bank_account_id=ids["bank_account_id"],
        income_account_id=ids["interest_income_id"],
        income_description="April misc",
        rows=[
            IncomeRow(amount="25.00", lot_id=ids["alice_lot_id"], memo="Gate remote"),
            IncomeRow(amount="11.67", other_source="Bank interest"),
        ],
    )
    lines = conn.execute(
        "SELECT owner_id, debit_amount, credit_amount, description "
        "FROM journal_entry_lines WHERE journal_entry_id = ? ORDER BY line_number",
        (result.journal_entry_id,),
    ).fetchall()
    assert len(lines) == 3  # 1 debit + 2 credits
    credits = lines[1:]
    # One credit tagged to Alice, one anonymous (OTHER).
    owners = [r["owner_id"] for r in credits]
    assert set(owners) == {ids["alice_owner_id"], None}
    # Totals balance.
    assert Decimal(str(lines[0]["debit_amount"])) == Decimal("36.67")
    assert sum(Decimal(str(r["credit_amount"])) for r in credits) == Decimal("36.67")


def test_income_batch_row_is_recorded(conn: sqlite3.Connection) -> None:
    ids = _seed(conn)
    result = ServiceFactory(conn).non_dues_income_service().post_batch(
        posting_date="2026-04-15",
        bank_account_id=ids["bank_account_id"],
        income_account_id=ids["interest_income_id"],
        income_description="Frost Bank",
        rows=[IncomeRow(amount="11.67", other_source="Bank interest")],
    )
    batch = conn.execute(
        "SELECT posting_date, income_description, total_amount, income_account_id, "
        "       journal_entry_id "
        "FROM income_batches WHERE id = ?",
        (result.income_batch_id,),
    ).fetchone()
    assert batch["posting_date"] == "2026-04-15"
    assert batch["income_description"] == "Frost Bank"
    assert Decimal(str(batch["total_amount"])) == Decimal("11.67")
    assert int(batch["income_account_id"]) == ids["interest_income_id"]
    assert int(batch["journal_entry_id"]) == result.journal_entry_id


# ── Service: validation ────────────────────────────────────────────


def test_rejects_non_income_account(conn: sqlite3.Connection) -> None:
    ids = _seed(conn)
    with pytest.raises(ValidationError, match="not an income account"):
        ServiceFactory(conn).non_dues_income_service().post_batch(
            posting_date="2026-04-15",
            bank_account_id=ids["bank_account_id"],
            income_account_id=ids["cash_account_id"],  # ASSET, not INCOME
            income_description="Wrong account type",
            rows=[IncomeRow(amount="10.00", other_source="x")],
        )


def test_rejects_inactive_income_account(conn: sqlite3.Connection) -> None:
    ids = _seed(conn)
    with pytest.raises(ValidationError, match="inactive"):
        ServiceFactory(conn).non_dues_income_service().post_batch(
            posting_date="2026-04-15",
            bank_account_id=ids["bank_account_id"],
            income_account_id=ids["legacy_income_id"],
            income_description="Test",
            rows=[IncomeRow(amount="10.00", other_source="x")],
        )


def test_rejects_row_with_both_lot_and_other(conn: sqlite3.Connection) -> None:
    ids = _seed(conn)
    with pytest.raises(ValidationError, match="not both"):
        ServiceFactory(conn).non_dues_income_service().post_batch(
            posting_date="2026-04-15",
            bank_account_id=ids["bank_account_id"],
            income_account_id=ids["interest_income_id"],
            income_description="Bad row",
            rows=[IncomeRow(amount="10.00", lot_id=ids["alice_lot_id"],
                            other_source="x")],
        )


def test_rejects_empty_batch(conn: sqlite3.Connection) -> None:
    ids = _seed(conn)
    with pytest.raises(ValidationError, match="at least one row"):
        ServiceFactory(conn).non_dues_income_service().post_batch(
            posting_date="2026-04-15",
            bank_account_id=ids["bank_account_id"],
            income_account_id=ids["interest_income_id"],
            income_description="Empty",
            rows=[],
        )


# ── Page flow ──────────────────────────────────────────────────────


def test_render_form_lists_only_income_accounts(conn: sqlite3.Connection) -> None:
    _seed(conn)
    resp = NonDuesIncomePages(conn).render_form(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "Interest Income" in resp.body_html
    # Cash is an asset — must not appear in the income-account dropdown.
    assert "Cash - Operating" not in resp.body_html


def test_handle_post_other_only_returns_redirect(conn: sqlite3.Connection) -> None:
    ids = _seed(conn)
    pages = NonDuesIncomePages(conn)
    redirect_url, form_resp = pages.handle_post(
        form_data={
            "posting_date": "2026-04-15",
            "bank_account_id": str(ids["bank_account_id"]),
            "income_account_id": str(ids["interest_income_id"]),
            "income_description": "April interest",
            "other_source": "Bank interest",
            "other_amount": "11.67",
        },
        org=_ORG,
        theme="warm",
    )
    assert form_resp is None
    assert redirect_url is not None
    assert redirect_url.startswith("/income?created=JE-")


def test_handle_post_missing_description_returns_error(conn: sqlite3.Connection) -> None:
    ids = _seed(conn)
    pages = NonDuesIncomePages(conn)
    redirect_url, form_resp = pages.handle_post(
        form_data={
            "posting_date": "2026-04-15",
            "bank_account_id": str(ids["bank_account_id"]),
            "income_account_id": str(ids["interest_income_id"]),
            "income_description": "",
            "other_source": "Bank interest",
            "other_amount": "11.67",
        },
        org=_ORG,
        theme="warm",
    )
    assert redirect_url is None
    assert form_resp is not None
    assert form_resp.status_code == 400
    assert "description" in form_resp.body_html.lower()
