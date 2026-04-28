"""VendorBillService — single-entry contract.

Posts a vendor bill (without paying it). The pairing payment is posted by
VendorPaymentService — see test_vendor_payment_service.py.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from hoa_accounting.exceptions import NotFoundError, ValidationError
from hoa_accounting.services.factory import ServiceFactory

from tests._service_fixtures import build_seeded_conn


def _svc(conn):
    return ServiceFactory(conn).vendor_bill_service()


def test_post_vendor_bill_happy_path():
    conn, ids = build_seeded_conn()
    res = _svc(conn).post_vendor_bill(
        entry_date="2026-01-10",
        vendor_id=ids.vendor1_id,
        amount="350.00",
        description="Mowing — January",
        invoice_number="INV-001",
        invoice_date="2026-01-05",
        due_date="2026-01-31",
        category_id=ids.cat_landscape_id,
        fund_code="OPERATING",
    )
    assert res.vendor_bill_id

    row = conn.execute(
        "SELECT vendor_id, invoice_number, amount, status, fund_code, category_id "
        "FROM vendor_bills WHERE id = ?", (res.vendor_bill_id,),
    ).fetchone()
    assert row["vendor_id"] == ids.vendor1_id
    assert row["invoice_number"] == "INV-001"
    assert Decimal(str(row["amount"])) == Decimal("350.00")
    assert row["status"] == "OPEN"
    assert row["fund_code"] == "OPERATING"
    assert row["category_id"] == ids.cat_landscape_id


def test_post_vendor_bill_rejects_zero_amount():
    conn, ids = build_seeded_conn()
    with pytest.raises(ValidationError):
        _svc(conn).post_vendor_bill(
            entry_date="2026-01-10",
            vendor_id=ids.vendor1_id, amount="0",
            description="Bad", invoice_number="INV-002",
            invoice_date="2026-01-05",
            category_id=ids.cat_landscape_id,
        )


def test_post_vendor_bill_rejects_unknown_vendor():
    conn, ids = build_seeded_conn()
    with pytest.raises(NotFoundError):
        _svc(conn).post_vendor_bill(
            entry_date="2026-01-10",
            vendor_id=9999, amount="50",
            description="x", invoice_number="INV-003",
            invoice_date="2026-01-05",
            category_id=ids.cat_landscape_id,
        )


def test_post_vendor_bill_unique_invoice_per_vendor():
    """Same vendor + same invoice_number is rejected; different vendor is OK."""
    conn, ids = build_seeded_conn()
    _svc(conn).post_vendor_bill(
        entry_date="2026-01-10", vendor_id=ids.vendor1_id, amount="100",
        description="x", invoice_number="DUP", invoice_date="2026-01-05",
        category_id=ids.cat_landscape_id,
    )
    with pytest.raises(Exception):
        _svc(conn).post_vendor_bill(
            entry_date="2026-01-10", vendor_id=ids.vendor1_id, amount="100",
            description="x", invoice_number="DUP", invoice_date="2026-01-05",
            category_id=ids.cat_landscape_id,
        )
    # Same invoice number on a *different* vendor must succeed.
    res = _svc(conn).post_vendor_bill(
        entry_date="2026-01-10", vendor_id=ids.vendor2_id, amount="100",
        description="x", invoice_number="DUP", invoice_date="2026-01-05",
        category_id=ids.cat_landscape_id,
    )
    assert res.vendor_bill_id
