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

from hoa_accounting.services.assessment_billing_service import (
    IndividualAssessmentRow,
)
from hoa_accounting.services.deposit_batch_service import DepositRow
from hoa_accounting.services.factory import ServiceFactory
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
    n_batches = conn.execute("SELECT COUNT(*) FROM deposit_batches").fetchone()[0]
    n_payments = conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
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


def test_vendor_bill_page_handler_atomic_rollback(monkeypatch):
    """``vendor_bill_pages.handle_post`` posts a bill and then a
    payment. The wrapping ``with transaction(self.conn)`` in handle_post
    means a payment-side failure must roll the bill back too.

    This was the partial-write hazard the audit (item #19) flagged:
    before the wrapping was added, the bill committed and a payment
    raise stranded it.

    The test mirrors what handle_post does: open an outer transaction,
    call the two services in sequence, force the second to raise.
    """
    from hoa_accounting.db.transaction import transaction

    conn, ids = build_seeded_conn()
    factory = ServiceFactory(conn)
    bill_service = factory.vendor_bill_service()
    payment_service = factory.vendor_payment_service()

    monkeypatch.setattr(
        payment_service,
        "post_vendor_payment",
        lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("simulated payment-side failure")
        ),
    )

    with pytest.raises(RuntimeError, match="simulated payment-side failure"):
        with transaction(conn):
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
            payment_service.post_vendor_payment(
                entry_date="2026-04-01",
                vendor_bill_id=bill_result.vendor_bill_id,
                amount="125.00",
                description="HP test payment",
                bank_account_id=ids.bank_op_id,
            )

    n = conn.execute(
        "SELECT COUNT(*) FROM vendor_bills WHERE invoice_number = ?",
        ("HP-FAIL-INJECT-1",),
    ).fetchone()[0]
    assert n == 0, (
        "Stranded vendor_bills row after payment-side failure — "
        "outer transaction did not roll back the bill."
    )


# ── handle_split (vendor_bill_pages) — destructive split rollback ─────


def test_vendor_bill_split_rolls_back_when_second_pair_fails(monkeypatch):
    """``vendor_bill_pages.handle_split`` deletes the original bill and
    payment after creating N new bill+payment pairs. The wrapping
    ``with transaction(self.conn):`` (commit ``400a7ef``) means a
    failure mid-loop must leave the original intact AND drop any new
    pairs already created.

    Mirrors the page handler's call sequence using a direct outer
    ``with transaction(...)`` block so the test exercises the same
    SAVEPOINT nesting the page would.
    """
    from hoa_accounting.db.transaction import transaction

    conn, ids = build_seeded_conn()
    factory = ServiceFactory(conn)
    bill_service = factory.vendor_bill_service()
    payment_service = factory.vendor_payment_service()

    # Seed an original bill + payment to be split.
    original = bill_service.post_vendor_bill(
        entry_date="2026-04-01",
        vendor_id=ids.vendor1_id,
        amount="200.00",
        description="HP original to split",
        invoice_number="HP-SPLIT-ORIG",
        invoice_date="2026-04-01",
        category_id=ids.cat_landscape_id,
        fund_code="OPERATING",
    )
    payment_service.post_vendor_payment(
        entry_date="2026-04-01",
        vendor_bill_id=original.vendor_bill_id,
        amount="200.00",
        description="HP original payment",
        bank_account_id=ids.bank_op_id,
    )

    # Force the second new bill in the split to raise.
    real_post_bill = bill_service.post_vendor_bill
    call_count = {"n": 0}

    def boom_post_bill(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise RuntimeError("simulated mid-split failure")
        return real_post_bill(*args, **kwargs)

    monkeypatch.setattr(bill_service, "post_vendor_bill", boom_post_bill)

    with pytest.raises(RuntimeError, match="simulated mid-split failure"):
        with transaction(conn):
            for line_amt in (Decimal("100.00"), Decimal("100.00")):
                new_bill = bill_service.post_vendor_bill(
                    entry_date="2026-04-01",
                    vendor_id=ids.vendor1_id,
                    amount=str(line_amt),
                    description="HP split",
                    invoice_number=f"HP-SPLIT-NEW-{line_amt}",
                    invoice_date="2026-04-01",
                    category_id=ids.cat_landscape_id,
                    fund_code="OPERATING",
                )
                payment_service.post_vendor_payment(
                    entry_date="2026-04-01",
                    vendor_bill_id=new_bill.vendor_bill_id,
                    amount=str(line_amt),
                    description="HP split payment",
                    bank_account_id=ids.bank_op_id,
                )

    # Original survived (it was outside the with-block scope).
    n_orig = conn.execute(
        "SELECT COUNT(*) FROM vendor_bills WHERE invoice_number = ?",
        ("HP-SPLIT-ORIG",),
    ).fetchone()[0]
    assert n_orig == 1, "Original bill must survive the split's rollback"

    # No partial new pairs landed.
    n_new = conn.execute(
        "SELECT COUNT(*) FROM vendor_bills WHERE invoice_number LIKE 'HP-SPLIT-NEW%'"
    ).fetchone()[0]
    assert n_new == 0, "Partial new-pair rows leaked through rollback"


# ── handle_income_split (edit_records_pages) — same destructive pattern ─


def test_income_split_rolls_back_when_second_batch_fails(monkeypatch):
    """``edit_records_pages.handle_income_split`` deletes the original
    income_batch after creating N new batches. Wrapping must roll back
    new batches if any post fails."""
    from hoa_accounting.db.transaction import transaction
    from hoa_accounting.services.non_dues_income_service import IncomeRow

    conn, ids = build_seeded_conn()
    factory = ServiceFactory(conn)
    income_service = factory.non_dues_income_service()

    # Seed an original batch to be split.
    original = income_service.post_batch(
        posting_date="2026-04-01",
        bank_account_id=ids.bank_op_id,
        income_description="HP original income",
        rows=[IncomeRow(amount="300.00", other_source="HP-ORIG")],
        category_id=ids.cat_dues_id,
    )
    original_id = original.income_batch_id

    real_post = income_service.post_batch
    call_count = {"n": 0}

    def boom(*args, **kwargs):
        call_count["n"] += 1
        # Fail the second new batch in the split.
        if call_count["n"] >= 2:
            raise RuntimeError("simulated mid-split failure")
        return real_post(*args, **kwargs)

    monkeypatch.setattr(income_service, "post_batch", boom)

    with pytest.raises(RuntimeError, match="simulated mid-split failure"):
        with transaction(conn):
            for line_amt in (Decimal("150.00"), Decimal("150.00")):
                income_service.post_batch(
                    posting_date="2026-04-01",
                    bank_account_id=ids.bank_op_id,
                    income_description="HP split income",
                    rows=[IncomeRow(amount=str(line_amt), other_source="HP-SPLIT")],
                    category_id=ids.cat_dues_id,
                )

    orig = conn.execute(
        "SELECT id FROM income_batches WHERE id = ?",
        (original_id,),
    ).fetchone()
    assert orig is not None, "Original income batch must survive rollback"

    n_new = conn.execute(
        "SELECT COUNT(*) FROM income_batches WHERE income_description = 'HP split income'"
    ).fetchone()[0]
    assert n_new == 0, "Partial new-batch rows leaked through rollback"
