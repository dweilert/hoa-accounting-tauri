"""VendorPaymentService — single-entry contract.

Posts a payment against an existing vendor bill. After payment, the bill's
status should roll up to PAID (or PARTIAL when under-paid).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from hoa_accounting.exceptions import NotFoundError, ValidationError
from hoa_accounting.services.factory import ServiceFactory

from tests._service_fixtures import build_seeded_conn


def _factory(conn):
    return ServiceFactory(conn)


def _post_bill(conn, ids, amount="200.00", invoice_number="INV-PAY"):
    return (
        _factory(conn)
        .vendor_bill_service()
        .post_vendor_bill(
            entry_date="2026-01-10",
            vendor_id=ids.vendor1_id,
            amount=amount,
            description="Test bill",
            invoice_number=invoice_number,
            invoice_date="2026-01-05",
            category_id=ids.cat_landscape_id,
        )
        .vendor_bill_id
    )


def test_post_payment_marks_bill_paid_in_full():
    conn, ids = build_seeded_conn()
    bill_id = _post_bill(conn, ids, amount="200.00")

    res = (
        _factory(conn)
        .vendor_payment_service()
        .post_vendor_payment(
            entry_date="2026-01-12",
            vendor_bill_id=bill_id,
            amount="200.00",
            description="cleared",
            bank_account_id=ids.bank_op_id,
            check_number="1001",
        )
    )
    pay = conn.execute(
        "SELECT amount, bank_account_id, check_number FROM bill_payments WHERE id = ?",
        (res.bill_payment_id,),
    ).fetchone()
    assert Decimal(str(pay["amount"])) == Decimal("200.00")
    assert pay["bank_account_id"] == ids.bank_op_id
    assert pay["check_number"] == "1001"

    bill_status = conn.execute(
        "SELECT status FROM vendor_bills WHERE id = ?", (bill_id,)
    ).fetchone()["status"]
    assert bill_status == "PAID"


def test_partial_payment_marks_bill_partial():
    conn, ids = build_seeded_conn()
    bill_id = _post_bill(conn, ids, amount="200.00", invoice_number="INV-P2")

    _factory(conn).vendor_payment_service().post_vendor_payment(
        entry_date="2026-01-12",
        vendor_bill_id=bill_id,
        amount="50.00",
        description="partial",
        bank_account_id=ids.bank_op_id,
    )
    bill_status = conn.execute(
        "SELECT status FROM vendor_bills WHERE id = ?", (bill_id,)
    ).fetchone()["status"]
    assert bill_status == "PARTIAL"


def test_post_payment_rejects_unknown_bill():
    conn, ids = build_seeded_conn()
    with pytest.raises(NotFoundError):
        _factory(conn).vendor_payment_service().post_vendor_payment(
            entry_date="2026-01-12",
            vendor_bill_id=9999,
            amount="50",
            description="x",
            bank_account_id=ids.bank_op_id,
        )


def test_post_payment_rejects_unknown_bank():
    conn, ids = build_seeded_conn()
    bill_id = _post_bill(conn, ids, invoice_number="INV-P3")
    with pytest.raises(NotFoundError):
        _factory(conn).vendor_payment_service().post_vendor_payment(
            entry_date="2026-01-12",
            vendor_bill_id=bill_id,
            amount="50",
            description="x",
            bank_account_id=9999,
        )


def test_post_payment_rejects_zero_amount():
    conn, ids = build_seeded_conn()
    bill_id = _post_bill(conn, ids, invoice_number="INV-P4")
    with pytest.raises(ValidationError):
        _factory(conn).vendor_payment_service().post_vendor_payment(
            entry_date="2026-01-12",
            vendor_bill_id=bill_id,
            amount="0",
            description="x",
            bank_account_id=ids.bank_op_id,
        )
