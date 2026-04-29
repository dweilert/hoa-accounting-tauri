"""PaymentService — single-entry contract.

Posts an owner payment, optionally applying it against open assessments.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from hoa_accounting.exceptions import NotFoundError, ValidationError
from hoa_accounting.services.factory import ServiceFactory
from tests._service_fixtures import build_seeded_conn


def _factory(conn):
    return ServiceFactory(conn)


def _post_assessment(conn, ids, *, amount: str):
    return (
        _factory(conn)
        .assessment_service()
        .post_assessment(
            entry_date="2026-01-01",
            lot_id=ids.lot1_id,
            owner_id=ids.owner1_id,
            amount=amount,
            description="dues",
            category_id=ids.cat_dues_id,
            charge_type="DUES",
            due_date="2026-01-15",
        )
        .assessment_id
    )


def test_post_payment_no_application_creates_row():
    conn, ids = build_seeded_conn()
    res = (
        _factory(conn)
        .payment_service()
        .post_payment(
            entry_date="2026-01-20",
            owner_id=ids.owner1_id,
            amount="125.00",
            bank_account_id=ids.bank_op_id,
            payment_method="CHECK",
            receipt_number="RCT-001",
            description="dues payment",
        )
    )
    row = conn.execute(
        "SELECT amount, payment_method, receipt_number, bank_account_id "
        "FROM payments WHERE id = ?",
        (res.payment_id,),
    ).fetchone()
    assert Decimal(str(row["amount"])) == Decimal("125.00")
    assert row["payment_method"] == "CHECK"
    assert row["receipt_number"] == "RCT-001"
    assert row["bank_account_id"] == ids.bank_op_id


def test_post_payment_applies_to_assessment_marks_paid():
    conn, ids = build_seeded_conn()
    a_id = _post_assessment(conn, ids, amount="100.00")

    res = (
        _factory(conn)
        .payment_service()
        .post_payment(
            entry_date="2026-01-20",
            owner_id=ids.owner1_id,
            amount="100.00",
            bank_account_id=ids.bank_op_id,
            payment_method="CHECK",
            receipt_number="RCT-002",
            description="x",
            apply_to_assessment_ids=[a_id],
        )
    )
    apps = list(
        conn.execute(
            "SELECT applied_amount FROM payment_applications WHERE payment_id = ?",
            (res.payment_id,),
        )
    )
    assert len(apps) == 1
    assert Decimal(str(apps[0]["applied_amount"])) == Decimal("100.00")
    status = conn.execute(
        "SELECT status FROM assessments WHERE id = ?", (a_id,)
    ).fetchone()["status"]
    assert status == "PAID"


def test_post_payment_partial_application_marks_partial():
    conn, ids = build_seeded_conn()
    a_id = _post_assessment(conn, ids, amount="100.00")

    _factory(conn).payment_service().post_payment(
        entry_date="2026-01-20",
        owner_id=ids.owner1_id,
        amount="40.00",
        bank_account_id=ids.bank_op_id,
        payment_method="CHECK",
        receipt_number="RCT-003",
        description="x",
        apply_to_assessment_ids=[a_id],
    )
    status = conn.execute(
        "SELECT status FROM assessments WHERE id = ?", (a_id,)
    ).fetchone()["status"]
    assert status == "PARTIAL"


def test_post_payment_rejects_zero_amount():
    conn, ids = build_seeded_conn()
    with pytest.raises(ValidationError):
        _factory(conn).payment_service().post_payment(
            entry_date="2026-01-20",
            owner_id=ids.owner1_id,
            amount="0",
            bank_account_id=ids.bank_op_id,
            payment_method="CHECK",
            receipt_number="RCT-004",
            description="x",
        )


def test_post_payment_rejects_unknown_owner():
    conn, ids = build_seeded_conn()
    with pytest.raises(NotFoundError):
        _factory(conn).payment_service().post_payment(
            entry_date="2026-01-20",
            owner_id=9999,
            amount="50",
            bank_account_id=ids.bank_op_id,
            payment_method="CHECK",
            receipt_number="RCT-005",
            description="x",
        )


def test_post_payment_rejects_unknown_bank():
    conn, ids = build_seeded_conn()
    with pytest.raises(NotFoundError):
        _factory(conn).payment_service().post_payment(
            entry_date="2026-01-20",
            owner_id=ids.owner1_id,
            amount="50",
            bank_account_id=9999,
            payment_method="CHECK",
            receipt_number="RCT-006",
            description="x",
        )
