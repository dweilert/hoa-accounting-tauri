"""ReserveTransferService — single-entry contract."""

from __future__ import annotations

from decimal import Decimal

import pytest

from hoa_accounting.exceptions import ValidationError
from hoa_accounting.services.factory import ServiceFactory

from tests._service_fixtures import build_seeded_conn


def _svc(conn):
    return ServiceFactory(conn).reserve_transfer_service()


def test_post_reserve_transfer_happy_path():
    conn, ids = build_seeded_conn()
    res = _svc(conn).post_reserve_transfer(
        entry_date="2026-01-31",
        amount="500.00",
        description="Monthly reserve contribution",
        from_account_id=ids.bank_op_id,
        to_account_id=ids.bank_res_id,
        transfer_type="CONTRIBUTION",
        purpose="2026 contribution schedule",
    )
    assert res.reserve_transfer_id

    row = conn.execute(
        "SELECT amount, transfer_type, from_bank_account_id, to_bank_account_id "
        "FROM reserve_transfers WHERE id = ?",
        (res.reserve_transfer_id,),
    ).fetchone()
    assert Decimal(str(row["amount"])) == Decimal("500.00")
    assert row["transfer_type"] == "CONTRIBUTION"


def test_rejects_zero_amount():
    conn, ids = build_seeded_conn()
    with pytest.raises(ValidationError):
        _svc(conn).post_reserve_transfer(
            entry_date="2026-01-31",
            amount="0",
            description="x",
            from_account_id=ids.bank_op_id,
            to_account_id=ids.bank_res_id,
        )


def test_rejects_same_from_and_to_account():
    conn, ids = build_seeded_conn()
    with pytest.raises(ValidationError):
        _svc(conn).post_reserve_transfer(
            entry_date="2026-01-31",
            amount="100",
            description="x",
            from_account_id=ids.bank_op_id,
            to_account_id=ids.bank_op_id,
        )
