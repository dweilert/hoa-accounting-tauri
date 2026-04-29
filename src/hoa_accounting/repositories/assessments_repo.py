"""Repository for assessments."""

from __future__ import annotations
from typing import Any

import sqlite3

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
        charge_type: str = "DUES",
        category_id: int | None = None,
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
                charge_type,
                category_id
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
                charge_type,
                category_id,
            ),
        )
        return int(cur.lastrowid or 0)

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

    def list_for_edit(self, *, limit: int = 500) -> list[sqlite3.Row]:
        """Return recent assessments with lot + owner context for editing.

        One row per assessment with the picked owner (alphabetical
        last-name first when a lot has multiple owners). Ordered
        newest-first by assessment_date.
        """
        return list(
            self.conn.execute(
                """
                WITH first_owner AS (
                    SELECT
                        lo.lot_id,
                        o.id AS owner_id,
                        TRIM(COALESCE(o.first_name, '') || ' ' ||
                             COALESCE(o.last_name, '')) AS owner_name,
                        ROW_NUMBER() OVER (
                            PARTITION BY lo.lot_id
                            ORDER BY COALESCE(o.last_name, ''),
                                     COALESCE(o.first_name, ''),
                                     o.id
                        ) AS rn
                    FROM lot_ownership lo
                    JOIN owners o ON o.id = lo.owner_id
                    WHERE lo.end_date IS NULL
                )
                SELECT
                    a.id,
                    a.lot_id,
                    a.owner_id,
                    a.assessment_date,
                    a.due_date,
                    a.amount,
                    a.description,
                    a.status,
                    a.charge_type,
                    a.category_id,
                    l.lot_number,
                    COALESCE(fo.owner_name,
                             (SELECT TRIM(COALESCE(o2.first_name,'') || ' ' ||
                                          COALESCE(o2.last_name,''))
                              FROM owners o2 WHERE o2.id = a.owner_id),
                             '') AS owner_name,
                    c.name AS category_name
                FROM assessments a
                JOIN lots l ON l.id = a.lot_id
                LEFT JOIN first_owner fo
                       ON fo.lot_id = a.lot_id AND fo.rn = 1
                LEFT JOIN categories c ON c.id = a.category_id
                ORDER BY a.assessment_date DESC, a.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )

    def get_for_edit(self, assessment_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT id, lot_id, owner_id, assessment_date, due_date, amount,
                   description, status, charge_type, category_id
            FROM assessments WHERE id = ?
            """,
            (assessment_id,),
        ).fetchone()

    def has_applications(self, assessment_id: int) -> bool:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM payment_applications WHERE assessment_id = ?",
            (assessment_id,),
        ).fetchone()
        return int(row[0]) > 0

    def update_for_edit(
        self,
        assessment_id: int,
        *,
        assessment_date: str,
        due_date: str,
        amount: str | None,
        description: str,
        category_id: int | None,
    ) -> None:
        """Update editable metadata. Pass amount=None to skip the amount
        column — required when payment_applications are attached so the
        recorded applications stay consistent with the assessment total."""
        if amount is None:
            self.conn.execute(
                """
                UPDATE assessments
                   SET assessment_date = ?, due_date = ?,
                       description = ?, category_id = ?,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = ?
                """,
                (assessment_date, due_date, description, category_id, assessment_id),
            )
        else:
            self.conn.execute(
                """
                UPDATE assessments
                   SET assessment_date = ?, due_date = ?, amount = ?,
                       description = ?, category_id = ?,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = ?
                """,
                (assessment_date, due_date, amount, description, category_id, assessment_id),
            )
        self.conn.commit()

    def list_open_for_owner(self, owner_id: int) -> list[Any]:
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
