"""Verify that posting services are atomic — a mid-flow failure rolls back.

These tests prove the transaction boundary around each public posting method:
if any step raises after writes have already happened, no partial state is
left in the database.
"""

from __future__ import annotations

import pytest

from hoa_accounting.exceptions import NotFoundError
from hoa_accounting.services.factory import ServiceFactory

from test_payment_service import build_conn


def _count(conn, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
    return int(row["c"])


def test_payment_rolls_back_when_assessment_not_found() -> None:
    """A post_payment that fails during assessment application leaves no rows."""
    conn = build_conn()
    factory = ServiceFactory(conn)

    before_journals = _count(conn, "journal_entries")
    before_lines = _count(conn, "journal_entry_lines")
    before_payments = _count(conn, "payments")
    before_audit = _count(conn, "audit_log")

    with pytest.raises(NotFoundError):
        factory.payment_service().post_payment(
            entry_date="2026-01-11",
            owner_id=1,
            amount="100.00",
            description="Payment",
            cash_account_id=1000,
            receivable_account_id=1100,
            bank_account_id=1,
            payment_method="CHECK",
            receipt_number="R-ROLLBACK",
            created_by_user_id=1,
            apply_to_assessment_ids=[99999],  # no such assessment
        )

    # All tables must be unchanged — no orphan journal entry, no orphan payment.
    assert _count(conn, "journal_entries") == before_journals
    assert _count(conn, "journal_entry_lines") == before_lines
    assert _count(conn, "payments") == before_payments
    assert _count(conn, "audit_log") == before_audit


@pytest.mark.skip(reason="pending single-entry rewrite (double-entry contract retired)")
def test_payment_succeeds_without_application() -> None:
    """Baseline: a valid payment commits (sanity check that rollback isn't over-triggered)."""
    conn = build_conn()
    factory = ServiceFactory(conn)

    factory.payment_service().post_payment(
        entry_date="2026-01-11",
        owner_id=1,
        amount="100.00",
        description="Payment",
        cash_account_id=1000,
        receivable_account_id=1100,
        bank_account_id=1,
        payment_method="CHECK",
        receipt_number="R-OK",
        created_by_user_id=1,
    )

    assert _count(conn, "journal_entries") == 1
    assert _count(conn, "payments") == 1


def test_nested_transaction_savepoint_isolates_inner_failure() -> None:
    """An outer transaction is not rolled back by an inner service failure the caller catches."""
    conn = build_conn()
    factory = ServiceFactory(conn)

    from hoa_accounting.db.transaction import transaction

    # Caller wraps two service calls. The first succeeds; the second fails.
    # The caller catches the failure, then commits the outer transaction.
    # The first call's writes must survive; the second must be fully reverted.
    with transaction(conn):
        assessment = factory.assessment_service().post_assessment(
            entry_date="2026-01-10",
            lot_id=1,
            owner_id=1,
            amount="100.00",
            description="Assessment",
            receivable_account_id=1100,
            income_account_id=4000,
            created_by_user_id=1,
        )

        try:
            factory.payment_service().post_payment(
                entry_date="2026-01-11",
                owner_id=1,
                amount="100.00",
                description="Payment",
                cash_account_id=1000,
                receivable_account_id=1100,
                bank_account_id=1,
                payment_method="CHECK",
                receipt_number="R-NESTED",
                created_by_user_id=1,
                apply_to_assessment_ids=[99999],
            )
        except NotFoundError:
            pass  # caller handles the inner failure

    # Outer committed: assessment survives. Inner rolled back: no payment row.
    row = conn.execute(
        "SELECT status FROM assessments WHERE id = ?",
        (assessment.assessment_id,),
    ).fetchone()
    assert row is not None
    assert _count(conn, "payments") == 0
