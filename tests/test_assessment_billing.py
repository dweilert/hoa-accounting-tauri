"""Tests for the assessment-billing batch service + page flow."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

import pytest

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.exceptions import ValidationError
from hoa_accounting.services.assessment_billing_service import IndividualAssessmentRow
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.web.assessment_billing_pages import AssessmentBillingPages


def _seed(conn: sqlite3.Connection) -> dict[str, int]:
    conn.execute(
        "INSERT INTO accounting_periods "
        "(id, period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed) "
        "VALUES (1, '2026-04', '2026-04-01', '2026-04-30', 2026, 4, 0)"
    )
    conn.execute(
        "INSERT INTO accounts (id, account_number, account_name, account_type_id, "
        "fund_code, is_bank_account, is_active) "
        "VALUES (1100, '1100', 'Accounts Receivable - Owners', 1, 'OPERATING', 0, 1), "
        "       (4000, '4000', 'Assessment Income',             4, 'OPERATING', 0, 1)"
    )
    conn.execute(
        "INSERT INTO owners (id, owner_type, display_name, active_flag) "
        "VALUES (1, 'PERSON', 'Alice Park', 1), "
        "       (2, 'PERSON', 'Bob Cole', 1), "
        "       (3, 'PERSON', 'Carla Nguyen', 1)"
    )
    conn.execute(
        "INSERT INTO lots (id, lot_number, active_flag) "
        "VALUES (1, 'L-1', 1), (2, 'L-2', 1), (3, 'L-3', 1)"
    )
    conn.execute(
        "INSERT INTO lot_ownership "
        "(id, lot_id, owner_id, start_date, end_date) "
        "VALUES (1, 1, 1, '2020-01-01', NULL), "
        "       (2, 2, 2, '2021-01-01', NULL), "
        "       (3, 3, 3, '2022-01-01', NULL)"
    )
    conn.commit()
    return {"ar_id": 1100, "income_id": 4000}


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


# ── Bulk billing ────────────────────────────────────────────────────


def test_bill_all_posts_one_assessment_per_active_lot(conn: sqlite3.Connection) -> None:
    ids = _seed(conn)
    factory = ServiceFactory(conn)
    result = factory.assessment_billing_service().bill_all_at_same_amount(
        entry_date="2026-04-15",
        amount="100.00",
        description="April dues",
        receivable_account_id=ids["ar_id"],
        income_account_id=ids["income_id"],
    )
    assert result.owner_count == 3
    assert result.total_amount == Decimal("300.00")
    # Every active lot got an assessment, each linked to its owner.
    rows = conn.execute(
        "SELECT lot_id, owner_id, amount FROM assessments ORDER BY lot_id"
    ).fetchall()
    assert [(int(r["lot_id"]), int(r["owner_id"]),
             Decimal(str(r["amount"]))) for r in rows] == [
        (1, 1, Decimal("100.00")),
        (2, 2, Decimal("100.00")),
        (3, 3, Decimal("100.00")),
    ]


def test_bill_all_is_atomic_when_a_lot_has_no_current_owner(conn: sqlite3.Connection) -> None:
    """One orphan lot rolls the whole batch back."""
    ids = _seed(conn)
    # Add a lot with no current primary-contact owner.
    conn.execute("INSERT INTO lots (id, lot_number, active_flag) VALUES (99, 'L-V', 1)")
    conn.commit()

    factory = ServiceFactory(conn)
    before = conn.execute("SELECT COUNT(*) c FROM assessments").fetchone()["c"]
    with pytest.raises(ValidationError, match="no current primary-contact"):
        factory.assessment_billing_service().bill_all_at_same_amount(
            entry_date="2026-04-15",
            amount="100.00",
            description="April dues",
            receivable_account_id=ids["ar_id"],
            income_account_id=ids["income_id"],
        )
    assert conn.execute("SELECT COUNT(*) c FROM assessments").fetchone()["c"] == before


def test_bill_all_rejects_blank_description(conn: sqlite3.Connection) -> None:
    ids = _seed(conn)
    with pytest.raises(ValidationError, match="description is required"):
        ServiceFactory(conn).assessment_billing_service().bill_all_at_same_amount(
            entry_date="2026-04-15",
            amount="100.00",
            description="   ",
            receivable_account_id=ids["ar_id"],
            income_account_id=ids["income_id"],
        )


# ── Individual billing ─────────────────────────────────────────────


def test_bill_individuals_only_posts_supplied_rows(conn: sqlite3.Connection) -> None:
    ids = _seed(conn)
    factory = ServiceFactory(conn)
    result = factory.assessment_billing_service().bill_individual_amounts(
        entry_date="2026-04-15",
        description="Catch-up fee",
        rows=[
            IndividualAssessmentRow(lot_id=1, amount="50.00"),
            IndividualAssessmentRow(lot_id=3, amount="75.00"),
            # L-2 omitted entirely
        ],
        receivable_account_id=ids["ar_id"],
        income_account_id=ids["income_id"],
    )
    assert result.owner_count == 2
    assert result.total_amount == Decimal("125.00")
    lot_ids = {int(r["lot_id"]) for r in
               conn.execute("SELECT lot_id FROM assessments").fetchall()}
    assert lot_ids == {1, 3}


def test_bill_individuals_rejects_empty_rows(conn: sqlite3.Connection) -> None:
    ids = _seed(conn)
    with pytest.raises(ValidationError, match="at least one"):
        ServiceFactory(conn).assessment_billing_service().bill_individual_amounts(
            entry_date="2026-04-15",
            description="Empty",
            rows=[],
            receivable_account_id=ids["ar_id"],
            income_account_id=ids["income_id"],
        )


def test_bill_individuals_rejects_duplicate_lot(conn: sqlite3.Connection) -> None:
    """Same lot can't appear twice in one batch — user error to catch early."""
    ids = _seed(conn)
    factory = ServiceFactory(conn)
    with pytest.raises(ValidationError, match="appears more than once"):
        factory.assessment_billing_service().bill_individual_amounts(
            entry_date="2026-04-15",
            description="Dup test",
            rows=[
                IndividualAssessmentRow(lot_id=1, amount="50.00"),
                IndividualAssessmentRow(lot_id=2, amount="75.00"),
                IndividualAssessmentRow(lot_id=1, amount="25.00"),  # duplicate
            ],
            receivable_account_id=ids["ar_id"],
            income_account_id=ids["income_id"],
        )
    # Nothing was persisted.
    assert conn.execute("SELECT COUNT(*) c FROM assessments").fetchone()["c"] == 0


def test_bill_individuals_rejects_zero_amount(conn: sqlite3.Connection) -> None:
    """Zero is not a positive amount — caller must remove the row."""
    ids = _seed(conn)
    with pytest.raises(ValidationError, match="greater than zero"):
        ServiceFactory(conn).assessment_billing_service().bill_individual_amounts(
            entry_date="2026-04-15",
            description="Zero test",
            rows=[IndividualAssessmentRow(lot_id=1, amount="0.00")],
            receivable_account_id=ids["ar_id"],
            income_account_id=ids["income_id"],
        )


# ── Page flow ──────────────────────────────────────────────────────


def test_page_renders_lot_options_in_individual_picker(conn: sqlite3.Connection) -> None:
    """All active lots + owners appear as dropdown options for the picker."""
    _seed(conn)
    pages = AssessmentBillingPages(conn)
    resp = pages.render_page(org=_ORG, theme="warm")
    assert resp.status_code == 200
    body = resp.body_html
    assert "Alice Park" in body
    assert "Bob Cole" in body
    assert "Carla Nguyen" in body
    # New dynamic-row picker: prompt option + Add row button.
    assert "Select a homeowner / lot" in body
    assert "+ Add row" in body
    # YTD columns are deliberately not on this page anymore.
    assert "YTD Billed" not in body
    assert "YTD Paid" not in body


def test_handle_bill_all_returns_redirect_on_success(conn: sqlite3.Connection) -> None:
    _seed(conn)
    pages = AssessmentBillingPages(conn)
    redirect_url, form_resp = pages.handle_bill_all(
        form_data={
            "description": "April dues",
            "bulk_amount": "100.00",
            "income_account_id": "4000",
            "entry_date": "2026-04-15",
        },
        org=_ORG, theme="warm",
    )
    assert form_resp is None
    assert redirect_url is not None
    assert "/assessments/bill?billed=" in redirect_url


def test_handle_bill_individuals_returns_redirect_on_success(conn: sqlite3.Connection) -> None:
    _seed(conn)
    pages = AssessmentBillingPages(conn)
    redirect_url, form_resp = pages.handle_bill_individuals(
        form_data={
            "description": "Late fee",
            "income_account_id": "4000",
            "entry_date": "2026-04-15",
            "row_0_lot_id": "1",
            "row_0_amount": "25.00",
            "row_1_lot_id": "2",
            "row_1_amount": "",  # blank → skipped
            "row_2_lot_id": "3",
            "row_2_amount": "50.00",
        },
        org=_ORG, theme="warm",
    )
    assert form_resp is None
    assert redirect_url is not None
    # Only two assessments posted.
    count = conn.execute("SELECT COUNT(*) c FROM assessments").fetchone()["c"]
    assert count == 2
