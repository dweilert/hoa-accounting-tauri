"""DepositBatchService — single-entry contract."""

from __future__ import annotations

from decimal import Decimal

import pytest

from hoa_accounting.exceptions import ValidationError
from hoa_accounting.services.deposit_batch_service import DepositRow
from hoa_accounting.services.factory import ServiceFactory
from tests._service_fixtures import build_seeded_conn


def _factory(conn):
    return ServiceFactory(conn)


def test_post_batch_two_rows_one_slip():
    conn, ids = build_seeded_conn()
    res = (
        _factory(conn)
        .deposit_batch_service()
        .post_batch(
            deposit_date="2026-01-20",
            bank_account_id=ids.bank_op_id,
            rows=[
                DepositRow(
                    lot_id=ids.lot1_id, amount="125.00", reference_number="CHK-1001"
                ),
                DepositRow(
                    lot_id=ids.lot2_id, amount="125.00", reference_number="CHK-1002"
                ),
            ],
        )
    )
    assert Decimal(res.total_amount) == Decimal("250.00")
    assert len(res.payment_ids) == 2

    slip_total = conn.execute(
        "SELECT total_amount FROM deposit_batches WHERE id = ?",
        (res.deposit_batch_id,),
    ).fetchone()["total_amount"]
    assert Decimal(str(slip_total)) == Decimal("250.00")


def test_post_batch_rejects_empty_rows():
    conn, ids = build_seeded_conn()
    with pytest.raises(ValidationError):
        _factory(conn).deposit_batch_service().post_batch(
            deposit_date="2026-01-20",
            bank_account_id=ids.bank_op_id,
            rows=[],
        )


def test_post_batch_rejects_unknown_bank():
    """Service relies on FK / validator to surface bad bank_account_id."""
    conn, ids = build_seeded_conn()
    with pytest.raises(Exception):
        _factory(conn).deposit_batch_service().post_batch(
            deposit_date="2026-01-20",
            bank_account_id=9999,
            rows=[DepositRow(lot_id=ids.lot1_id, amount="1.00")],
        )


def test_post_batch_rejects_unknown_lot():
    conn, ids = build_seeded_conn()
    with pytest.raises(Exception):
        _factory(conn).deposit_batch_service().post_batch(
            deposit_date="2026-01-20",
            bank_account_id=ids.bank_op_id,
            rows=[DepositRow(lot_id=9999, amount="1.00")],
        )
