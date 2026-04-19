"""Reversal service tests.

Cover the accounting primitive: posting a reversing JE that swaps debits
and credits, marks the original REVERSED, links the two together, and
writes an audit row. Business-record cascade (void-ing an assessment,
reversing a payment's applications, etc.) is intentionally out of scope
for this service and is not asserted here.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from hoa_accounting.exceptions import NotFoundError, ValidationError
from hoa_accounting.services.factory import ServiceFactory

from test_payment_service import build_conn


def _post_seed_assessment(factory: ServiceFactory) -> int:
    """Helper: post an assessment and return its journal_entry_id."""
    result = factory.assessment_service().post_assessment(
        entry_date="2026-01-10",
        lot_id=1,
        owner_id=1,
        amount="100.00",
        description="Seed assessment",
        receivable_account_id=1100,
        income_account_id=4000,
        created_by_user_id=1,
    )
    return result.journal_entry_id


def test_reverse_posts_mirror_entry_and_marks_original_reversed() -> None:
    """The swap JE is posted and the original flips to REVERSED with a link."""
    conn = build_conn()
    factory = ServiceFactory(conn)

    original_je_id = _post_seed_assessment(factory)

    result = factory.reversal_service().reverse_journal_entry(
        journal_entry_id=original_je_id,
        reversal_date="2026-01-15",
        memo="Mistake on the assessment",
        created_by_user_id=1,
    )

    assert result.original_journal_entry_id == original_je_id
    assert result.reversal_journal_entry_id != original_je_id
    assert result.reversal_entry_number.startswith("JE-20260115-")

    # Original is REVERSED and points at the new entry.
    orig = conn.execute(
        "SELECT status, reversal_entry_id FROM journal_entries WHERE id = ?",
        (original_je_id,),
    ).fetchone()
    assert orig["status"] == "REVERSED"
    assert int(orig["reversal_entry_id"]) == result.reversal_journal_entry_id

    # Reversal JE references the original via source_id and has source_type REVERSAL.
    rev = conn.execute(
        "SELECT source_type, source_id, status FROM journal_entries WHERE id = ?",
        (result.reversal_journal_entry_id,),
    ).fetchone()
    assert rev["source_type"] == "REVERSAL"
    assert int(rev["source_id"]) == original_je_id
    assert rev["status"] == "POSTED"


def test_reverse_swaps_debits_and_credits_line_for_line() -> None:
    """The reversal's debits equal the original's credits, and vice versa."""
    conn = build_conn()
    factory = ServiceFactory(conn)

    original_je_id = _post_seed_assessment(factory)

    result = factory.reversal_service().reverse_journal_entry(
        journal_entry_id=original_je_id,
        reversal_date="2026-01-15",
        created_by_user_id=1,
    )

    original_lines = conn.execute(
        """
        SELECT account_id, debit_amount, credit_amount
        FROM journal_entry_lines
        WHERE journal_entry_id = ?
        ORDER BY line_number
        """,
        (original_je_id,),
    ).fetchall()

    reversal_lines = conn.execute(
        """
        SELECT account_id, debit_amount, credit_amount
        FROM journal_entry_lines
        WHERE journal_entry_id = ?
        ORDER BY line_number
        """,
        (result.reversal_journal_entry_id,),
    ).fetchall()

    assert len(original_lines) == len(reversal_lines)
    for o, r in zip(original_lines, reversal_lines):
        assert int(o["account_id"]) == int(r["account_id"])
        # Swapped: reversal debit == original credit, reversal credit == original debit.
        assert Decimal(str(r["debit_amount"])) == Decimal(str(o["credit_amount"]))
        assert Decimal(str(r["credit_amount"])) == Decimal(str(o["debit_amount"]))


def test_cannot_reverse_nonexistent_entry() -> None:
    """Reversing an unknown journal entry raises NotFoundError."""
    conn = build_conn()
    factory = ServiceFactory(conn)

    with pytest.raises(NotFoundError, match="was not found"):
        factory.reversal_service().reverse_journal_entry(
            journal_entry_id=99999,
            reversal_date="2026-01-15",
            created_by_user_id=1,
        )


def test_cannot_reverse_already_reversed_entry() -> None:
    """A second reversal of the same original is rejected."""
    conn = build_conn()
    factory = ServiceFactory(conn)

    original_je_id = _post_seed_assessment(factory)
    factory.reversal_service().reverse_journal_entry(
        journal_entry_id=original_je_id,
        reversal_date="2026-01-15",
        created_by_user_id=1,
    )

    with pytest.raises(ValidationError, match="status is REVERSED"):
        factory.reversal_service().reverse_journal_entry(
            journal_entry_id=original_je_id,
            reversal_date="2026-01-16",
            created_by_user_id=1,
        )


def test_cannot_reverse_into_closed_period() -> None:
    """A reversal date in a closed period is rejected by the period validator."""
    conn = build_conn()
    factory = ServiceFactory(conn)

    original_je_id = _post_seed_assessment(factory)

    # Close January 2026 so the default reversal_date above is no longer open.
    conn.execute(
        "UPDATE accounting_periods SET is_closed = 1 WHERE period_name = '2026-01'"
    )
    conn.commit()

    from hoa_accounting.exceptions import ClosedPeriodError
    with pytest.raises(ClosedPeriodError):
        factory.reversal_service().reverse_journal_entry(
            journal_entry_id=original_je_id,
            reversal_date="2026-01-20",
            created_by_user_id=1,
        )

    # Original must remain POSTED — the failed reversal rolled back cleanly.
    row = conn.execute(
        "SELECT status, reversal_entry_id FROM journal_entries WHERE id = ?",
        (original_je_id,),
    ).fetchone()
    assert row["status"] == "POSTED"
    assert row["reversal_entry_id"] is None


def test_reversal_writes_audit_row() -> None:
    """A REVERSE action is recorded in audit_log for the original entry."""
    conn = build_conn()
    factory = ServiceFactory(conn)

    original_je_id = _post_seed_assessment(factory)
    result = factory.reversal_service().reverse_journal_entry(
        journal_entry_id=original_je_id,
        reversal_date="2026-01-15",
        created_by_user_id=1,
    )

    audit_rows = conn.execute(
        """
        SELECT action, before_json, after_json
        FROM audit_log
        WHERE entity_type = 'journal_entries'
          AND entity_id = ?
          AND action = 'REVERSE'
        """,
        (original_je_id,),
    ).fetchall()
    assert len(audit_rows) == 1
    assert '"status": "REVERSED"' in str(audit_rows[0]["after_json"])
    assert str(result.reversal_journal_entry_id) in str(audit_rows[0]["after_json"])
