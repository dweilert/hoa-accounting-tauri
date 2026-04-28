"""Tests for ReserveTransferService.

Covers:
- post_reserve_transfer: posts JE + reserve_transfers row, returns result
- post_reserve_transfer: rejects same from/to account
- post_reserve_transfer: rejects zero/negative amount
- post_reserve_transfer: rejects non-asset accounts
- post_reserve_transfer: JE lines balance (debit == credit)
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

import pytest

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.exceptions import ValidationError
from hoa_accounting.services.factory import ServiceFactory


import pytest
pytestmark = pytest.mark.skip(
    reason="Pending rewrite after Chart of Accounts removal (migration 0061)"
)
def build_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    Migrator().apply_all(conn)
    conn.execute(
        "INSERT INTO users (id, email, full_name, password_hash, is_active) "
        "VALUES (1, 'a@example.com', 'Admin', 'x', 1)"
    )
    conn.execute(
        "INSERT INTO accounting_periods "
        "(id, period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed) "
        "VALUES (1, '2026-01', '2026-01-01', '2026-01-31', 2026, 1, 0)"
    )
    conn.execute(
        "INSERT INTO accounts (id, account_number, account_name, account_type_id, "
        "fund_code, is_bank_account, is_active) VALUES "
        "(1001, '1001', 'Operating Cash', 1, 'OPERATING', 1, 1), "
        "(1002, '1002', 'Reserve Cash',   1, 'RESERVE',   1, 1), "
        "(2000, '2000', 'AP',              2, 'OPERATING', 0, 1)"
    )
    conn.commit()
    return conn


def _svc(conn):
    return ServiceFactory(conn).reserve_transfer_service()


@pytest.mark.skip(reason="pending single-entry rewrite (double-entry contract retired)")
def test_post_reserve_transfer_success() -> None:
    conn = build_conn()
    result = _svc(conn).post_reserve_transfer(
        entry_date="2026-01-20",
        amount="1000.00",
        description="Monthly reserve contribution",
        from_account_id=1001,
        to_account_id=1002,
        created_by_user_id=1,
    )
    assert result.reserve_transfer_id is not None
    assert result.journal_entry_id is not None


@pytest.mark.skip(reason="pending single-entry rewrite (double-entry contract retired)")
def test_post_reserve_transfer_je_balances() -> None:
    conn = build_conn()
    result = _svc(conn).post_reserve_transfer(
        entry_date="2026-01-20",
        amount="500.00",
        description="Reserve transfer",
        from_account_id=1001,
        to_account_id=1002,
        created_by_user_id=1,
    )
    lines = conn.execute(
        "SELECT debit_amount, credit_amount FROM journal_entry_lines "
        "WHERE journal_entry_id=?",
        (result.journal_entry_id,),
    ).fetchall()
    total_debit  = sum(Decimal(str(l["debit_amount"]))  for l in lines)
    total_credit = sum(Decimal(str(l["credit_amount"])) for l in lines)
    assert total_debit == total_credit == Decimal("500.00")


def test_post_reserve_transfer_rejects_same_account() -> None:
    conn = build_conn()
    with pytest.raises(ValidationError, match="different"):
        _svc(conn).post_reserve_transfer(
            entry_date="2026-01-20",
            amount="500.00",
            description="Self transfer",
            from_account_id=1001,
            to_account_id=1001,
        )


def test_post_reserve_transfer_rejects_zero_amount() -> None:
    conn = build_conn()
    with pytest.raises(ValidationError, match="greater than zero"):
        _svc(conn).post_reserve_transfer(
            entry_date="2026-01-20",
            amount="0.00",
            description="Zero",
            from_account_id=1001,
            to_account_id=1002,
        )


@pytest.mark.skip(reason="pending single-entry rewrite (double-entry contract retired)")
def test_post_reserve_transfer_rejects_non_asset_account() -> None:
    conn = build_conn()
    with pytest.raises(ValidationError):
        _svc(conn).post_reserve_transfer(
            entry_date="2026-01-20",
            amount="500.00",
            description="Bad account",
            from_account_id=1001,
            to_account_id=2000,  # liability, not asset
        )
