"""AssessmentService — single-entry contract.

Posts an owner-receivable record (``assessments`` row). No GL JE; the
service just validates inputs and inserts the canonical row.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from hoa_accounting.exceptions import NotFoundError, ValidationError
from hoa_accounting.services.factory import ServiceFactory

from tests._service_fixtures import build_seeded_conn


def _svc(conn):
    return ServiceFactory(conn).assessment_service()


def test_post_assessment_happy_path():
    conn, ids = build_seeded_conn()
    result = _svc(conn).post_assessment(
        entry_date="2026-01-10",
        lot_id=ids.lot1_id,
        owner_id=ids.owner1_id,
        amount="250.00",
        description="January dues",
        category_id=ids.cat_dues_id,
        charge_type="DUES",
        due_date="2026-01-15",
        created_by_user_id=ids.user_id,
    )
    assert result.assessment_id

    row = conn.execute(
        "SELECT lot_id, owner_id, amount, status, charge_type, category_id "
        "FROM assessments WHERE id = ?",
        (result.assessment_id,),
    ).fetchone()
    assert row["lot_id"] == ids.lot1_id
    assert row["owner_id"] == ids.owner1_id
    assert Decimal(str(row["amount"])) == Decimal("250.00")
    assert row["status"] == "OPEN"
    assert row["charge_type"] == "DUES"
    assert row["category_id"] == ids.cat_dues_id


def test_post_assessment_rejects_zero_amount():
    conn, ids = build_seeded_conn()
    with pytest.raises(ValidationError):
        _svc(conn).post_assessment(
            entry_date="2026-01-10",
            lot_id=ids.lot1_id,
            owner_id=ids.owner1_id,
            amount="0.00",
            description="Bad",
            category_id=ids.cat_dues_id,
        )


def test_post_assessment_rejects_negative_amount():
    conn, ids = build_seeded_conn()
    with pytest.raises(ValidationError):
        _svc(conn).post_assessment(
            entry_date="2026-01-10",
            lot_id=ids.lot1_id,
            owner_id=ids.owner1_id,
            amount="-50",
            description="Bad",
            category_id=ids.cat_dues_id,
        )


def test_post_assessment_rejects_unknown_lot():
    conn, ids = build_seeded_conn()
    with pytest.raises(NotFoundError):
        _svc(conn).post_assessment(
            entry_date="2026-01-10",
            lot_id=9999,
            owner_id=ids.owner1_id,
            amount="100",
            description="x",
            category_id=ids.cat_dues_id,
        )


def test_post_assessment_rejects_unknown_owner():
    conn, ids = build_seeded_conn()
    with pytest.raises(NotFoundError):
        _svc(conn).post_assessment(
            entry_date="2026-01-10",
            lot_id=ids.lot1_id,
            owner_id=9999,
            amount="100",
            description="x",
            category_id=ids.cat_dues_id,
        )
