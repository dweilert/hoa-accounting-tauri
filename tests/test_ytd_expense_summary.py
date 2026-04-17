"""Tests for the YTD Expense Summary report."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

import pytest

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.reporting.ytd_expense_summary import YtdExpenseSummaryReportService


def _seed_minimum(conn: sqlite3.Connection) -> dict[str, int]:
    """Seed reference data plus the AP and a vendor so we can post bills."""
    conn.execute(
        "INSERT INTO accounting_periods "
        "(id, period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed) "
        "VALUES (1, '2026-04', '2026-04-01', '2026-04-30', 2026, 4, 0)"
    )
    conn.execute(
        "INSERT INTO accounts (id, account_number, account_name, account_type_id, "
        "fund_code, is_bank_account, is_active) "
        "VALUES (2000, '2000', 'Accounts Payable', 2, 'OPERATING', 0, 1)"
    )
    conn.execute(
        "INSERT INTO vendors (id, vendor_name, active_flag) "
        "VALUES (1, 'Green Yard Services', 1)"
    )
    conn.commit()
    return {"vendor_id": 1, "ap_account_id": 2000}


def _expense_id(conn: sqlite3.Connection, number: str) -> int:
    row = conn.execute(
        "SELECT id FROM accounts WHERE account_number = ?", (number,)
    ).fetchone()
    return int(row["id"])


def _post_bill(conn, *, vendor_id, expense_account_id, payable_account_id,
               amount, invoice_number, invoice_date="2026-04-10",
               entry_date="2026-04-15"):
    from hoa_accounting.services.factory import ServiceFactory
    return ServiceFactory(conn).vendor_bill_service().post_vendor_bill(
        entry_date=entry_date,
        vendor_id=vendor_id,
        amount=str(amount),
        description="test",
        expense_account_id=expense_account_id,
        payable_account_id=payable_account_id,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
    )


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    Migrator().apply_all(c)
    return c


# ── Basic shape ─────────────────────────────────────────────────────


def test_empty_report_shows_all_groups_with_zero_amounts(conn) -> None:
    """With no postings, the report still lists every active expense group."""
    _seed_minimum(conn)
    report = YtdExpenseSummaryReportService(conn).generate(
        from_date="2026-01-01", to_date="2026-12-31"
    )
    assert report.grand_total == Decimal("0.00")
    assert report.total_record_count == 0
    # All nine expected groups appear at least as group buckets.
    group_codes = {g.group_code for g in report.groups}
    for expected in [
        "LANDSCAPE", "SEWER", "ROAD", "WALL", "ENTRANCE",
        "UTILITIES", "INSURANCE", "MISC", "FIREWISE",
    ]:
        assert expected in group_codes
    # Each group row inside shows its 18 seeded categories with 0 amount.
    all_categories = sum(len(g.rows) for g in report.groups)
    assert all_categories == 18


def test_posted_bill_appears_in_its_group(conn) -> None:
    """A vendor bill posted to 6101 shows up under LANDSCAPE with amount + count 1."""
    ids = _seed_minimum(conn)
    mow = _expense_id(conn, "6101")  # Landscape - Mow & Blow
    _post_bill(conn, vendor_id=ids["vendor_id"], expense_account_id=mow,
               payable_account_id=ids["ap_account_id"], amount="365.00",
               invoice_number="GY-1")

    report = YtdExpenseSummaryReportService(conn).generate(
        from_date="2026-01-01", to_date="2026-12-31"
    )
    assert report.grand_total == Decimal("365.00")
    assert report.total_record_count == 1
    landscape = next(g for g in report.groups if g.group_code == "LANDSCAPE")
    assert landscape.group_total == Decimal("365.00")
    assert landscape.group_record_count == 1
    mow_row = next(r for r in landscape.rows if r.account_number == "6101")
    assert mow_row.ytd_amount == Decimal("365.00")
    assert mow_row.record_count == 1
    # Other Landscape categories stay at zero.
    other_row = next(r for r in landscape.rows if r.account_number == "6104")
    assert other_row.ytd_amount == Decimal("0.00")
    assert other_row.record_count == 0


def test_multiple_bills_same_category_accumulate(conn) -> None:
    """Two bills against one account sum correctly with count = 2."""
    ids = _seed_minimum(conn)
    utilities = _expense_id(conn, "6601")
    for n, amt in enumerate(["100.00", "410.79"], start=1):
        _post_bill(conn, vendor_id=ids["vendor_id"], expense_account_id=utilities,
                   payable_account_id=ids["ap_account_id"], amount=amt,
                   invoice_number=f"U-{n}")

    report = YtdExpenseSummaryReportService(conn).generate(
        from_date="2026-01-01", to_date="2026-12-31"
    )
    util_group = next(g for g in report.groups if g.group_code == "UTILITIES")
    util_row = util_group.rows[0]
    assert util_row.ytd_amount == Decimal("510.79")
    assert util_row.record_count == 2


# ── Date range ───────────────────────────────────────────────────────


def test_activity_outside_date_range_is_excluded(conn) -> None:
    """A bill dated outside from/to does not roll into the summary."""
    ids = _seed_minimum(conn)
    # Add April and May accounting periods so the vendor bill dates are valid.
    conn.execute(
        "INSERT INTO accounting_periods "
        "(id, period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed) "
        "VALUES (5, '2026-05', '2026-05-01', '2026-05-31', 2026, 5, 0)"
    )
    conn.commit()
    mow = _expense_id(conn, "6101")
    # One bill in April, one in May.
    _post_bill(conn, vendor_id=ids["vendor_id"], expense_account_id=mow,
               payable_account_id=ids["ap_account_id"], amount="100.00",
               invoice_number="A-APR", invoice_date="2026-04-10",
               entry_date="2026-04-15")
    _post_bill(conn, vendor_id=ids["vendor_id"], expense_account_id=mow,
               payable_account_id=ids["ap_account_id"], amount="200.00",
               invoice_number="A-MAY", invoice_date="2026-05-10",
               entry_date="2026-05-15")

    # Run report for April only — only the first bill should count.
    report = YtdExpenseSummaryReportService(conn).generate(
        from_date="2026-04-01", to_date="2026-04-30"
    )
    assert report.grand_total == Decimal("100.00")
    assert report.total_record_count == 1


# ── Reversal handling ───────────────────────────────────────────────


def test_reversal_nets_to_zero(conn) -> None:
    """Reversing a bill brings its YTD contribution back to zero."""
    from hoa_accounting.services.factory import ServiceFactory

    ids = _seed_minimum(conn)
    mow = _expense_id(conn, "6101")
    result = _post_bill(conn, vendor_id=ids["vendor_id"],
                        expense_account_id=mow, payable_account_id=ids["ap_account_id"],
                        amount="150.00", invoice_number="A-REV")
    ServiceFactory(conn).reversal_service().reverse_journal_entry(
        journal_entry_id=result.journal_entry_id,
        reversal_date="2026-04-20",
    )

    report = YtdExpenseSummaryReportService(conn).generate(
        from_date="2026-01-01", to_date="2026-12-31"
    )
    # Net: 150 debit + 150 credit (from reversal) = 0. Record count = 2.
    landscape = next(g for g in report.groups if g.group_code == "LANDSCAPE")
    mow_row = next(r for r in landscape.rows if r.account_number == "6101")
    assert mow_row.ytd_amount == Decimal("0.00")
    assert mow_row.record_count == 2


# ── Report runner dispatch ─────────────────────────────────────────


def test_report_runner_dispatches_ytd_expense_summary(conn) -> None:
    """ReportRunner picks up 'ytd-expense-summary' and returns serialized data."""
    from hoa_accounting.application.report_runner import ReportRunner

    _seed_minimum(conn)
    runner = ReportRunner(
        config_path="unused.yaml",
        connection_factory=lambda: conn,
    )
    result = runner.run(
        "ytd-expense-summary",
        from_date="2026-01-01",
        to_date="2026-12-31",
    )
    assert result.report_name == "ytd-expense-summary"
    assert "groups" in result.data
    assert result.data["grand_total"] == "0.00"
