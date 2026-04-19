"""Integration tests for the fund-balance invariant at the service layer.

The validator tests in test_validators.py cover the rule in isolation.
Here we prove it actually fires end-to-end: a cross-fund JournalService
post is rejected, and reserve transfers (which must cross funds) still
succeed via the ``inter_fund_allowed`` opt-in.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from hoa_accounting.exceptions import UnbalancedJournalError
from hoa_accounting.models.dto import JournalLineInput
from hoa_accounting.services.factory import ServiceFactory

from test_payment_service import build_conn


def test_cross_fund_journal_post_is_rejected_at_service_level() -> None:
    """Posting $10 debit to OPERATING / $10 credit to RESERVE must fail by default."""
    conn = build_conn()
    # Account 1000 = Cash (OPERATING). Seed a RESERVE account for the other side.
    conn.execute(
        "INSERT INTO accounts "
        "(id, account_number, account_name, account_type_id, fund_code, "
        "is_bank_account, is_active) "
        "VALUES (1010, '1010', 'Cash-Reserve', 1, 'RESERVE', 1, 1)"
    )
    conn.commit()

    factory = ServiceFactory(conn)
    with pytest.raises(UnbalancedJournalError, match="within fund"):
        factory.journal_service().post_journal_entry(
            entry_date="2026-01-10",
            source_type="MANUAL",
            memo="Should be rejected",
            created_by_user_id=1,
            lines=[
                JournalLineInput(
                    account_id=1000, description="op debit",
                    debit_amount=Decimal("10.00"),
                ),
                JournalLineInput(
                    account_id=1010, description="reserve credit",
                    credit_amount=Decimal("10.00"),
                ),
            ],
        )

    # No journal entry or lines persisted — transaction rolled back cleanly.
    assert conn.execute("SELECT COUNT(*) c FROM journal_entries").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM journal_entry_lines").fetchone()["c"] == 0


def test_reserve_transfer_still_works_via_opt_in() -> None:
    """ReserveTransferService uses inter_fund_allowed=True and must still succeed."""
    conn = build_conn()
    conn.execute(
        "INSERT INTO accounts "
        "(id, account_number, account_name, account_type_id, fund_code, "
        "is_bank_account, is_active) "
        "VALUES (1010, '1010', 'Cash-Reserve', 1, 'RESERVE', 1, 1)"
    )
    conn.commit()

    factory = ServiceFactory(conn)
    result = factory.reserve_transfer_service().post_reserve_transfer(
        entry_date="2026-01-10",
        amount="250.00",
        description="Monthly reserve funding",
        from_account_id=1000,
        to_account_id=1010,
        created_by_user_id=1,
    )

    # Reserve transfer journal exists and has two lines spanning funds.
    assert result.journal_entry_id > 0
    lines = conn.execute(
        """
        SELECT a.fund_code, jel.debit_amount, jel.credit_amount
        FROM journal_entry_lines jel
        JOIN accounts a ON a.id = jel.account_id
        WHERE jel.journal_entry_id = ?
        ORDER BY jel.line_number
        """,
        (result.journal_entry_id,),
    ).fetchall()
    funds = {row["fund_code"] for row in lines}
    assert funds == {"OPERATING", "RESERVE"}


def test_single_fund_journal_post_still_works() -> None:
    """An ordinary single-fund entry (e.g. an assessment) is unaffected."""
    conn = build_conn()
    factory = ServiceFactory(conn)

    # Assessment: debit AR (OPERATING), credit Assessment Income (OPERATING).
    result = factory.assessment_service().post_assessment(
        entry_date="2026-01-10",
        lot_id=1,
        owner_id=1,
        amount="100.00",
        description="Regular single-fund post",
        receivable_account_id=1100,
        income_account_id=4000,
        created_by_user_id=1,
    )
    assert result.journal_entry_id > 0
