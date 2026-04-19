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
        charge_type: str = "DUES",
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
                journal_entry_id,
                charge_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
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
                charge_type,
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

    def list_open_for_owner(self, owner_id: int) -> list:
        """Return an owner's still-owed assessments in state-mandated payment order.

        Order: DUES first, then LATE_FEE, then LEGAL_FEE, then any other
        charge types. Within each charge type, oldest due-date first.
        This ensures payments are applied to current/past dues before
        late fees and legal fees, as required by state law.

        Each row reports the original amount plus the sum of what's been
        applied to it so callers can compute the remaining balance
        without a second lookup. Only OPEN and PARTIAL assessments are
        returned — PAID, VOID, and WRITTEN_OFF are excluded.
        """
        return list(
            self.conn.execute(
                """
                SELECT
                    a.id,
                    a.description,
                    a.amount,
                    a.assessment_date,
                    a.due_date,
                    a.status,
                    a.charge_type,
                    COALESCE(SUM(pa.applied_amount), 0) AS already_applied
                FROM assessments a
                LEFT JOIN payment_applications pa ON pa.assessment_id = a.id
                WHERE a.owner_id = ?
                  AND a.status IN ('OPEN', 'PARTIAL')
                GROUP BY a.id, a.description, a.amount, a.assessment_date,
                         a.due_date, a.status, a.charge_type
                ORDER BY
                    CASE a.charge_type
                        WHEN 'DUES'      THEN 1
                        WHEN 'LATE_FEE'  THEN 2
                        WHEN 'LEGAL_FEE' THEN 3
                        ELSE 4
                    END ASC,
                    a.due_date ASC,
                    a.id ASC
                """,
                (owner_id,),
            ).fetchall()
        )
