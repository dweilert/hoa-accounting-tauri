"""Fail-injection tests: prove (or disprove) atomic rollback.

When a multi-step write fails partway through, we want either:
1. **Atomic rollback** — none of the rows from earlier steps survive
   (the service uses ``with transaction(...)`` to bracket the work), OR
2. **Documented partial state** — the test xfails with a message
   explaining which row classes can persist after a mid-flight failure.

These tests are the prerequisite for the service-extraction refactor:
they pin down the *current* transactional behaviour so a refactor can
preserve or fix it without silently regressing.

Each test follows the same shape:

1. Build a seeded in-memory DB.
2. Monkeypatch the *second* repository method called by the operation
   to raise an exception.
3. Invoke the service / page handler and expect it to raise.
4. Assert that NO rows from the *first* step landed in the DB.

Tests that document a known partial-write hazard use ``xfail(strict=True)``
so that fixing the hazard surfaces a "test unexpectedly passed"
notification — a positive signal that the refactor worked.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from hoa_accounting.exceptions import ValidationError
from hoa_accounting.services.deposit_batch_service import DepositRow
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.services.assessment_billing_service import (
    IndividualAssessmentRow,
)

from tests._service_fixtures import build_seeded_conn


# ── Deposit batch — confirm atomic rollback ───────────────────────────


def test_deposit_batch_rolls_back_when_payment_apply_raises(monkeypatch):
    """``DepositBatchService.post_batch`` is wrapped in
    ``with transaction(self.conn)``; if the per-row apply step raises
    after the deposit_batches row + first payment row land, the txn
    must roll back the whole thing.
    """
    conn, ids = build_seeded_conn()
    factory = ServiceFactory(conn)
    svc = factory.deposit_batch_service()

    # Force the apply-to-assessments helper to raise after the first row's
    # payment has been inserted but before the second row processes.
    call_count = {"n": 0}
    real_apply = svc._apply_payment_to_assessments

    def boom(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] >= 1:
            raise RuntimeError("simulated mid-batch failure")
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(svc, "_apply_payment_to_assessments", boom)

    with pytest.raises(RuntimeError, match="simulated mid-batch failure"):
        svc.post_batch(
            deposit_date="2026-04-01",
            bank_account_id=ids.bank_op_id,
            rows=[
                DepositRow(lot_id=ids.lot1_id, amount=Decimal("100.00")),
                DepositRow(lot_id=ids.lot2_id, amount=Decimal("75.00")),
            ],
        )

    # Atomic: no batch row, no payment rows.
    n_batches = conn.execute(
        "SELECT COUNT(*) FROM deposit_batches"
    ).fetchone()[0]
    n_payments = conn.execute(
        "SELECT COUNT(*) FROM payments"
    ).fetchone()[0]
    assert n_batches == 0, "deposit_batches row leaked through rollback"
    assert n_payments == 0, "payments row leaked through rollback"


# ── Assessment billing — both batch methods are wrapped ───────────────


def test_bill_all_rolls_back_when_one_lot_post_raises(monkeypatch):
    """``bill_all_at_same_amount`` is wrapped in ``with transaction(...)``.
    Force the second per-lot post to raise; the first lot's assessment
    must be rolled back too.
    """
    conn, ids = build_seeded_conn()
    factory = ServiceFactory(conn)
    svc = factory.assessment_billing_service()

    real_post = svc.assessment_service.post_assessment
    call_count = {"n": 0}

    def boom(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated second-lot failure")
        return real_post(*args, **kwargs)

    monkeypatch.setattr(svc.assessment_service, "post_assessment", boom)

    with pytest.raises(RuntimeError, match="simulated second-lot failure"):
        svc.bill_all_at_same_amount(
            entry_date="2026-04-01",
            amount="100.00",
            description="April dues",
            category_id=ids.cat_dues_id,
        )

    n = conn.execute("SELECT COUNT(*) FROM assessments").fetchone()[0]
    assert n == 0, "first lot's assessment leaked through rollback"


def test_bill_individual_rolls_back_when_one_row_post_raises(monkeypatch):
    """Same property for ``bill_individual_amounts``."""
    conn, ids = build_seeded_conn()
    factory = ServiceFactory(conn)
    svc = factory.assessment_billing_service()

    real_post = svc.assessment_service.post_assessment
    call_count = {"n": 0}

    def boom(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated second-row failure")
        return real_post(*args, **kwargs)

    monkeypatch.setattr(svc.assessment_service, "post_assessment", boom)

    with pytest.raises(RuntimeError, match="simulated second-row failure"):
        svc.bill_individual_amounts(
            entry_date="2026-04-01",
            description="Special",
            rows=[
                IndividualAssessmentRow(lot_id=ids.lot1_id, amount="50.00"),
                IndividualAssessmentRow(lot_id=ids.lot2_id, amount="60.00"),
            ],
            category_id=ids.cat_dues_id,
        )

    n = conn.execute("SELECT COUNT(*) FROM assessments").fetchone()[0]
    assert n == 0, "first row's assessment leaked through rollback"


# ── Vendor-bill page handler — known partial-write hazard ─────────────


@pytest.mark.xfail(
    strict=True,
    reason=(
        "vendor_bill_pages.handle_post calls post_vendor_bill and "
        "post_vendor_payment back-to-back without a wrapping transaction. "
        "If the payment fails after the bill is committed, the bill "
        "persists with no payment — the audit's #19 service-extraction "
        "task is to wrap both calls in a single transaction. When that "
        "lands, this test will start passing (xfail strict → flagged)."
    ),
)
def test_vendor_bill_page_handler_atomic_rollback(monkeypatch):
    """When ``handle_post`` posts a bill then a payment, a payment-side
    failure should NOT leave a stranded bill row.

    Today this fails: there is no transaction wrapping both service
    calls, so the bill commits and the payment-side raise leaves it
    behind.
    """
    conn, ids = build_seeded_conn()
    factory = ServiceFactory(conn)
    bill_service = factory.vendor_bill_service()
    payment_service = factory.vendor_payment_service()

    # Post the bill normally, then force the payment to fail.
    bill_result = bill_service.post_vendor_bill(
        entry_date="2026-04-01",
        vendor_id=ids.vendor1_id,
        amount="125.00",
        description="HP test bill",
        invoice_number="HP-FAIL-INJECT-1",
        invoice_date="2026-04-01",
        category_id=ids.cat_landscape_id,
        fund_code="OPERATING",
    )
    monkeypatch.setattr(
        payment_service, "post_vendor_payment",
        lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("simulated payment-side failure")
        ),
    )
    with pytest.raises(RuntimeError, match="simulated payment-side failure"):
        payment_service.post_vendor_payment(
            entry_date="2026-04-01",
            vendor_bill_id=bill_result.vendor_bill_id,
            amount="125.00",
            description="HP test payment",
            bank_account_id=ids.bank_op_id,
        )

    # If the operation were atomic, the bill would have rolled back too.
    n = conn.execute(
        "SELECT COUNT(*) FROM vendor_bills WHERE invoice_number = ?",
        ("HP-FAIL-INJECT-1",),
    ).fetchone()[0]
    assert n == 0, (
        "Stranded vendor_bills row after payment-side failure — "
        "two service calls need wrapping in a single transaction."
    )
