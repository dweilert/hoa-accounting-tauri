"""Repository for assessments."""

from __future__ import annotations

from .base import BaseRepository


class AssessmentsRepository(BaseRepository):
    """Database access for assessment records."""

    def insert_assessment(
        self,
        *,
        lot_id: int,
        owner_id: int,
        assessment_rule_id: int | None,
        assessment_date: str,
        due_date: str,
        amount: str,
        description: str,
        journal_entry_id: int,
    ) -> int:
        """Insert an assessment and return its id."""
        cur = self.conn.execute(
            """
            INSERT INTO assessments (
                lot_id,
                owner_id,
                assessment_rule_id,
                assessment_date,
                due_date,
                amount,
                description,
                status,
                journal_entry_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
            """,
            (
                lot_id,
                owner_id,
                assessment_rule_id,
                assessment_date,
                due_date,
                amount,
                description,
                journal_entry_id,
            ),
        )
        return int(cur.lastrowid)

    def get_for_payment_application(self, assessment_id: int):
        """Return assessment data used for payment application."""
        return self.conn.execute(
            """
            SELECT a.id, a.owner_id, a.amount,
                   COALESCE(SUM(pa.applied_amount), 0) AS already_applied
            FROM assessments a
            LEFT JOIN payment_applications pa ON pa.assessment_id = a.id
            WHERE a.id = ?
            GROUP BY a.id, a.owner_id, a.amount
            """,
            (assessment_id,),
        ).fetchone()

    def update_status(self, assessment_id: int, status: str) -> None:
        """Update an assessment status."""
        self.conn.execute(
            "UPDATE assessments SET status = ? WHERE id = ?",
            (status, assessment_id),
        )
