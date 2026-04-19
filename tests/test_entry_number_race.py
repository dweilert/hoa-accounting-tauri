"""Verify the journal-entry-number retry loop handles UNIQUE collisions.

``next_entry_number`` derives the next number from the current max, so two
concurrent posters can compute the same candidate. The repo's
``insert_journal_entry_with_generated_number`` must detect the UNIQUE
violation and retry with a fresh number instead of bubbling the error out.

Single-threaded ``next_entry_number`` never actually collides — the race
only exists between concurrent callers. We simulate a racing caller
deterministically by monkey-patching ``next_entry_number`` on the shared
repo to return an already-used number on the first call and the real
candidate on the second, then confirm the service recovers and the inserted
row carries the real number.
"""

from __future__ import annotations

import pytest

from hoa_accounting.exceptions import AccountingError
from hoa_accounting.services.factory import ServiceFactory

from test_payment_service import build_conn


def test_retry_recovers_from_one_entry_number_collision(monkeypatch: pytest.MonkeyPatch) -> None:
    """A single collision is handled silently: the final row gets the real next number."""
    conn = build_conn()
    factory = ServiceFactory(conn)

    # Pre-seed a colliding row with entry_number JE-20260110-0001 so the
    # first attempt will hit the UNIQUE constraint when our patched
    # next_entry_number hands that same number back.
    conn.execute(
        """
        INSERT INTO journal_entries (
            id, entry_number, entry_date, accounting_period_id,
            source_type, memo, status, posted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (999, "JE-20260110-0001", "2026-01-10", 1, "MANUAL",
         "Squatter", "POSTED", "2026-01-10T00:00:00+00:00"),
    )
    conn.commit()

    repo = factory.journal_repo
    real_next = repo.next_entry_number

    call_count = {"n": 0}

    def flaky_next(entry_date: str) -> str:
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Return a value we know already exists, forcing a UNIQUE violation.
            return "JE-20260110-0001"
        return real_next(entry_date)

    monkeypatch.setattr(repo, "next_entry_number", flaky_next)

    result = factory.assessment_service().post_assessment(
        entry_date="2026-01-10",
        lot_id=1,
        owner_id=1,
        amount="100.00",
        description="Retry test",
        receivable_account_id=1100,
        income_account_id=4000,
        created_by_user_id=1,
    )

    # Retry loop must have been entered.
    assert call_count["n"] >= 2
    # Final inserted row must carry a fresh unique number (not the squatter's).
    assert result.entry_number != "JE-20260110-0001"
    assert result.entry_number.startswith("JE-20260110-")

    rows = conn.execute(
        "SELECT entry_number FROM journal_entries WHERE entry_date = ? ORDER BY id",
        ("2026-01-10",),
    ).fetchall()
    # Exactly two rows: the squatter and the retried assessment post.
    numbers = sorted(r["entry_number"] for r in rows)
    assert "JE-20260110-0001" in numbers
    assert result.entry_number in numbers


def test_retry_gives_up_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    """If every attempt collides, surface AccountingError instead of hanging."""
    conn = build_conn()
    factory = ServiceFactory(conn)

    # Seed the colliding number.
    conn.execute(
        """
        INSERT INTO journal_entries (
            id, entry_number, entry_date, accounting_period_id,
            source_type, memo, status, posted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (1000, "JE-20260110-0001", "2026-01-10", 1, "MANUAL",
         "Squatter", "POSTED", "2026-01-10T00:00:00+00:00"),
    )
    conn.commit()

    # Patch next_entry_number to always return the already-taken number.
    monkeypatch.setattr(
        factory.journal_repo,
        "next_entry_number",
        lambda entry_date: "JE-20260110-0001",
    )

    with pytest.raises(AccountingError, match="unique journal entry number"):
        factory.assessment_service().post_assessment(
            entry_date="2026-01-10",
            lot_id=1,
            owner_id=1,
            amount="100.00",
            description="Exhaust retries",
            receivable_account_id=1100,
            income_account_id=4000,
            created_by_user_id=1,
        )

    # No assessment row was committed.
    row = conn.execute("SELECT COUNT(*) AS c FROM assessments").fetchone()
    assert row["c"] == 0
