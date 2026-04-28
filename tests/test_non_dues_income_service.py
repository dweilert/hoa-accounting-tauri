"""NonDuesIncomeService — single-entry contract."""

from __future__ import annotations

from decimal import Decimal

import pytest

from hoa_accounting.exceptions import NotFoundError, ValidationError
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.services.non_dues_income_service import IncomeRow

from tests._service_fixtures import build_seeded_conn


def _svc(conn):
    return ServiceFactory(conn).non_dues_income_service()


def test_post_batch_happy_path():
    conn, ids = build_seeded_conn()
    res = _svc(conn).post_batch(
        posting_date="2026-01-31",
        bank_account_id=ids.bank_op_id,
        income_description="January misc income",
        rows=[
            IncomeRow(amount="40.00", other_source="BANK"),
            IncomeRow(amount="60.00", other_source="BANK"),
        ],
        category_id=ids.cat_late_id,
    )
    assert res.income_batch_id
    assert Decimal(str(res.total_amount)) == Decimal("100.00")

    row = conn.execute(
        "SELECT total_amount, bank_account_id, category_id FROM income_batches WHERE id = ?",
        (res.income_batch_id,),
    ).fetchone()
    assert Decimal(str(row["total_amount"])) == Decimal("100.00")
    assert row["bank_account_id"] == ids.bank_op_id
    assert row["category_id"] == ids.cat_late_id


def test_post_batch_rejects_empty_rows():
    conn, ids = build_seeded_conn()
    with pytest.raises(ValidationError):
        _svc(conn).post_batch(
            posting_date="2026-01-31",
            bank_account_id=ids.bank_op_id,
            income_description="x",
            rows=[],
            category_id=ids.cat_late_id,
        )


def test_post_batch_rejects_blank_description():
    conn, ids = build_seeded_conn()
    with pytest.raises(ValidationError):
        _svc(conn).post_batch(
            posting_date="2026-01-31",
            bank_account_id=ids.bank_op_id,
            income_description="   ",
            rows=[IncomeRow(amount="1.00", other_source="BANK")],
            category_id=ids.cat_late_id,
        )


def test_post_batch_rejects_unknown_bank():
    conn, ids = build_seeded_conn()
    with pytest.raises(NotFoundError):
        _svc(conn).post_batch(
            posting_date="2026-01-31",
            bank_account_id=9999,
            income_description="x",
            rows=[IncomeRow(amount="1.00", other_source="BANK")],
            category_id=ids.cat_late_id,
        )


def test_post_batch_row_with_neither_lot_nor_other_rejected():
    conn, ids = build_seeded_conn()
    with pytest.raises(ValidationError):
        _svc(conn).post_batch(
            posting_date="2026-01-31",
            bank_account_id=ids.bank_op_id,
            income_description="x",
            rows=[IncomeRow(amount="10.00")],  # no lot, no other_source
            category_id=ids.cat_late_id,
        )
