"""Service-level tests for :class:`AssessmentBillingService`.

Covers the two public methods plus the validation paths the audit
flagged as risky (no owner on a lot → bill-all rejection;
duplicate-lot in bill-individual; blank description; empty rows).

The legacy ``test_assessment_billing.py`` file is skipped pending a
post-Chart-of-Accounts rewrite — this file is the rewrite, scoped to
the service layer (the page-flow integration is covered by
``test_form_happy_paths``).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from hoa_accounting.exceptions import ValidationError
from hoa_accounting.services.assessment_billing_service import (
    AssessmentBillingService,
    IndividualAssessmentRow,
)
from hoa_accounting.services.factory import ServiceFactory
from tests._service_fixtures import build_seeded_conn


def _svc(conn) -> AssessmentBillingService:
    factory = ServiceFactory(conn)
    return factory.assessment_billing_service()


# ── bill_all_at_same_amount ────────────────────────────────────────────


def test_bill_all_happy_path():
    """Both seeded lots are billed at the same amount; result totals
    reflect the per-lot amount × lot count."""
    conn, ids = build_seeded_conn()
    result = _svc(conn).bill_all_at_same_amount(
        entry_date="2026-04-01",
        amount="100.00",
        description="April dues",
        category_id=ids.cat_dues_id,
        due_date="2026-04-15",
    )
    assert result.owner_count == 2
    assert result.total_amount == Decimal("200.00")
    assert len(result.assessments) == 2
    rows = conn.execute(
        "SELECT lot_id, amount, description FROM assessments ORDER BY lot_id"
    ).fetchall()
    assert [
        (r["lot_id"], Decimal(str(r["amount"])), r["description"]) for r in rows
    ] == [
        (1, Decimal("100.00"), "April dues"),
        (2, Decimal("100.00"), "April dues"),
    ]


def test_bill_all_rejects_blank_description():
    conn, ids = build_seeded_conn()
    with pytest.raises(ValidationError, match="description"):
        _svc(conn).bill_all_at_same_amount(
            entry_date="2026-04-01",
            amount="100.00",
            description="   ",
            category_id=ids.cat_dues_id,
        )


def test_bill_all_rejects_non_positive_amount():
    conn, ids = build_seeded_conn()
    with pytest.raises(ValidationError):
        _svc(conn).bill_all_at_same_amount(
            entry_date="2026-04-01",
            amount="0",
            description="April dues",
            category_id=ids.cat_dues_id,
        )


def test_bill_all_rejects_lot_with_no_current_owner():
    """If any active lot lacks a current owner, the whole batch is
    refused — the service treats it as a data-integrity issue rather
    than silently skipping that lot."""
    conn, ids = build_seeded_conn()
    # End lot 2's ownership so it has no current owner.
    conn.execute(
        "UPDATE lot_ownership SET end_date = '2024-12-31' "
        "WHERE lot_id = 2 AND end_date IS NULL"
    )
    conn.commit()

    with pytest.raises(ValidationError, match="no current.*owner"):
        _svc(conn).bill_all_at_same_amount(
            entry_date="2026-04-01",
            amount="100.00",
            description="April dues",
            category_id=ids.cat_dues_id,
        )

    # And nothing landed — failed lot lookup must abort the whole batch.
    n = conn.execute("SELECT COUNT(*) FROM assessments").fetchone()[0]
    assert n == 0


# ── bill_individual_amounts ────────────────────────────────────────────


def test_bill_individual_happy_path():
    conn, ids = build_seeded_conn()
    result = _svc(conn).bill_individual_amounts(
        entry_date="2026-04-01",
        description="Special assessment",
        rows=[
            IndividualAssessmentRow(lot_id=ids.lot1_id, amount="50.00"),
            IndividualAssessmentRow(lot_id=ids.lot2_id, amount="75.50"),
        ],
        category_id=ids.cat_dues_id,
    )
    assert result.owner_count == 2
    assert result.total_amount == Decimal("125.50")


def test_bill_individual_rejects_duplicate_lot():
    conn, ids = build_seeded_conn()
    with pytest.raises(ValidationError, match="duplicate|same lot|once"):
        _svc(conn).bill_individual_amounts(
            entry_date="2026-04-01",
            description="Special assessment",
            rows=[
                IndividualAssessmentRow(lot_id=ids.lot1_id, amount="50.00"),
                IndividualAssessmentRow(lot_id=ids.lot1_id, amount="60.00"),
            ],
            category_id=ids.cat_dues_id,
        )
    # Nothing should land — the duplicate check fires before any insert.
    n = conn.execute("SELECT COUNT(*) FROM assessments").fetchone()[0]
    assert n == 0


def test_bill_individual_rejects_empty_rows():
    conn, ids = build_seeded_conn()
    with pytest.raises(ValidationError, match="at least one"):
        _svc(conn).bill_individual_amounts(
            entry_date="2026-04-01",
            description="Special assessment",
            rows=[],
            category_id=ids.cat_dues_id,
        )


def test_bill_individual_rejects_blank_description():
    conn, ids = build_seeded_conn()
    with pytest.raises(ValidationError, match="description"):
        _svc(conn).bill_individual_amounts(
            entry_date="2026-04-01",
            description="",
            rows=[IndividualAssessmentRow(lot_id=ids.lot1_id, amount="50.00")],
            category_id=ids.cat_dues_id,
        )
