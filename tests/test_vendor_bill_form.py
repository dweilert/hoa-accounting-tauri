"""Tests for the vendor-bill form and list pages.

Covers (a) the service-layer addition of ``expense_classification``,
(b) the HTTP flow — GET empty form, POST valid, POST with validation
error, POST with duplicate invoice — via Flask's test client, and
(c) the list page rendering with a success banner.
"""

from __future__ import annotations

import sqlite3

import pytest
from flask import Flask

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.web.vendor_bill_pages import VendorBillPages


# ── Shared fixtures ──────────────────────────────────────────────────


def _build_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    Migrator().apply_all(conn)

    # Seed the minimum reference data the vendor-bill posting path needs:
    # an open accounting period, a liability account (Accounts Payable),
    # a vendor, and rely on the migration's seeded expense accounts.
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
    return conn


def _expense_account_id(conn: sqlite3.Connection, number: str) -> int:
    """Look up one of the 0002-migration-seeded expense accounts."""
    row = conn.execute(
        "SELECT id FROM accounts WHERE account_number = ?", (number,)
    ).fetchone()
    return int(row["id"])


_ORG = {
    "name": "Test HOA",
    "legal_name": "Test HOA Inc.",
    "environment": "test",
    "fiscal_year_start_month": 1,
    "theme": "warm",
}


# ── Service: expense_classification parameter ───────────────────────


def test_post_vendor_bill_stores_classification_on_expense_line() -> None:
    """The expense line carries the classification; the payable line does not."""
    from hoa_accounting.services.factory import ServiceFactory

    conn = _build_conn()
    landscape_mow = _expense_account_id(conn, "6101")

    factory = ServiceFactory(conn)
    result = factory.vendor_bill_service().post_vendor_bill(
        entry_date="2026-04-15",
        vendor_id=1,
        amount="365.00",
        description="April mowing",
        expense_account_id=landscape_mow,
        payable_account_id=2000,
        invoice_number="GY-APR-01",
        invoice_date="2026-04-10",
        fund_code="OPERATING",
        expense_classification="OPERATING",
    )

    rows = conn.execute(
        "SELECT account_id, debit_amount, credit_amount, expense_classification "
        "FROM journal_entry_lines WHERE journal_entry_id = ? ORDER BY line_number",
        (result.journal_entry_id,),
    ).fetchall()
    # Line 1 = debit to expense account; line 2 = credit to payable.
    expense_line = next(r for r in rows if int(r["account_id"]) == landscape_mow)
    payable_line = next(r for r in rows if int(r["account_id"]) == 2000)
    assert str(expense_line["expense_classification"]) == "OPERATING"
    assert payable_line["expense_classification"] is None


def test_post_vendor_bill_accepts_improvement_classification() -> None:
    from hoa_accounting.services.factory import ServiceFactory

    conn = _build_conn()
    gate_account = _expense_account_id(conn, "6501")

    factory = ServiceFactory(conn)
    result = factory.vendor_bill_service().post_vendor_bill(
        entry_date="2026-04-15",
        vendor_id=1,
        amount="1500.00",
        description="Gate controller upgrade",
        expense_account_id=gate_account,
        payable_account_id=2000,
        invoice_number="GY-UPG-01",
        invoice_date="2026-04-11",
        expense_classification="IMPROVEMENT",
    )
    row = conn.execute(
        "SELECT expense_classification FROM journal_entry_lines "
        "WHERE journal_entry_id = ? AND debit_amount > 0",
        (result.journal_entry_id,),
    ).fetchone()
    assert str(row["expense_classification"]) == "IMPROVEMENT"


def test_post_vendor_bill_rejects_unknown_classification() -> None:
    from hoa_accounting.exceptions import ValidationError
    from hoa_accounting.services.factory import ServiceFactory

    conn = _build_conn()
    acct = _expense_account_id(conn, "6601")
    factory = ServiceFactory(conn)
    with pytest.raises(ValidationError, match="Invalid expense classification"):
        factory.vendor_bill_service().post_vendor_bill(
            entry_date="2026-04-15",
            vendor_id=1,
            amount="50.00",
            description="utilities",
            expense_account_id=acct,
            payable_account_id=2000,
            invoice_number="U-01",
            invoice_date="2026-04-01",
            expense_classification="BOGUS",
        )


# ── Pages: direct (service-level) ───────────────────────────────────


def test_render_form_lists_seeded_vendors_and_expense_accounts() -> None:
    conn = _build_conn()
    pages = VendorBillPages(conn)
    resp = pages.render_form(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "Green Yard Services" in resp.body_html
    # A couple of the seeded expense categories must appear in the dropdown.
    assert "Sprinkler System" in resp.body_html
    assert "Utilities" in resp.body_html
    # OPERATING is the default selected classification.
    assert 'value="OPERATING"' in resp.body_html
    assert 'value="IMPROVEMENT"' in resp.body_html


def test_render_list_shows_empty_state_with_no_bills() -> None:
    conn = _build_conn()
    pages = VendorBillPages(conn)
    resp = pages.render_list(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "No bills posted yet" in resp.body_html


def test_handle_post_valid_returns_redirect() -> None:
    conn = _build_conn()
    pages = VendorBillPages(conn)
    acct = _expense_account_id(conn, "6101")

    redirect_url, form_resp = pages.handle_post(
        form_data={
            "vendor_id": "1",
            "invoice_number": "GY-001",
            "invoice_date": "2026-04-10",
            "entry_date": "2026-04-15",
            "due_date": "",
            "amount": "365.00",
            "expense_account_id": str(acct),
            "expense_classification": "OPERATING",
            "payable_account_id": "2000",
            "fund_code": "OPERATING",
            "description": "April mow",
        },
        org=_ORG,
        theme="warm",
    )
    assert form_resp is None
    assert redirect_url is not None
    assert redirect_url.startswith("/vendor-bills?created=JE-")


def test_handle_post_missing_required_re_renders_form_with_error() -> None:
    conn = _build_conn()
    pages = VendorBillPages(conn)
    redirect_url, form_resp = pages.handle_post(
        form_data={
            "vendor_id": "",  # missing
            "invoice_number": "",
            "invoice_date": "2026-04-10",
            "entry_date": "2026-04-15",
            "amount": "365.00",
        },
        org=_ORG,
        theme="warm",
    )
    assert redirect_url is None
    assert form_resp is not None
    assert form_resp.status_code == 400
    # Either missing-invoice or missing-vendor surfaces first; both acceptable.
    body = form_resp.body_html
    assert "required" in body.lower()


def test_handle_post_duplicate_invoice_number_is_friendly_error() -> None:
    conn = _build_conn()
    pages = VendorBillPages(conn)
    acct = _expense_account_id(conn, "6101")

    form_data = {
        "vendor_id": "1",
        "invoice_number": "GY-DUP",
        "invoice_date": "2026-04-10",
        "entry_date": "2026-04-15",
        "due_date": "",
        "amount": "100.00",
        "expense_account_id": str(acct),
        "expense_classification": "OPERATING",
        "payable_account_id": "2000",
        "fund_code": "OPERATING",
        "description": "",
    }
    redirect_url, _ = pages.handle_post(form_data=form_data, org=_ORG, theme="warm")
    assert redirect_url is not None  # first post succeeds

    redirect_url2, form_resp = pages.handle_post(
        form_data=form_data, org=_ORG, theme="warm"
    )
    assert redirect_url2 is None
    assert form_resp is not None
    assert "already exists" in form_resp.body_html


# ── End-to-end through Flask ────────────────────────────────────────


def _build_app_with_conn(conn: sqlite3.Connection) -> Flask:
    """Mirror the real create_app for the subset we want to test."""
    from flask import Flask, Response, request, redirect

    app = Flask(__name__)
    org = dict(_ORG)

    @app.get("/vendor-bills")
    def list_():
        pages = VendorBillPages(conn)
        created = (request.args.get("created") or "").strip() or None
        r = pages.render_list(org=org, theme="warm", created_entry_number=created)
        return Response(r.body_html, status=r.status_code, mimetype="text/html")

    @app.get("/vendor-bills/new")
    def form():
        pages = VendorBillPages(conn)
        r = pages.render_form(org=org, theme="warm")
        return Response(r.body_html, status=r.status_code, mimetype="text/html")

    @app.post("/vendor-bills/new")
    def submit():
        pages = VendorBillPages(conn)
        form_data = {k: v for k, v in request.form.items()}
        red, resp = pages.handle_post(form_data=form_data, org=org, theme="warm")
        if red is not None:
            return redirect(red, code=303)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html")

    return app


def test_end_to_end_form_flow() -> None:
    """GET empty form → POST valid → follow redirect → banner shows JE number."""
    conn = _build_conn()
    app = _build_app_with_conn(conn)
    acct = _expense_account_id(conn, "6101")
    client = app.test_client()

    # 1. Empty form renders.
    r = client.get("/vendor-bills/new")
    assert r.status_code == 200

    # 2. Submit a valid bill.
    r = client.post("/vendor-bills/new", data={
        "vendor_id": "1",
        "invoice_number": "E2E-001",
        "invoice_date": "2026-04-10",
        "entry_date": "2026-04-15",
        "amount": "365.00",
        "expense_account_id": str(acct),
        "expense_classification": "OPERATING",
        "payable_account_id": "2000",
        "fund_code": "OPERATING",
        "description": "End-to-end test",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["Location"].startswith("/vendor-bills?created=JE-")

    # 3. Follow the redirect; the success banner shows the JE number.
    r = client.get(r.headers["Location"])
    assert r.status_code == 200
    assert "Posted journal entry" in r.get_data(as_text=True)
    assert "E2E-001" in r.get_data(as_text=True)
