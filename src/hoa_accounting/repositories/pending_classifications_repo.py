"""Repository for pending classifications.

A pending classification is the treasurer's pre-bank record of money
they expect to deposit. It captures who paid, which lot/owner, what
category, and how much — but does NOT post anything. Payment rows are
only created later, after the OFX import confirms the bank received
the deposit and the classification is matched and posted.

See migration 0063 for the table definition and lifecycle states.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .base import BaseRepository


class PendingClassificationsRepository(BaseRepository):
    """CRUD for ``pending_classifications``."""

    # ── Inserts / updates ────────────────────────────────────────────

    def insert(
        self,
        *,
        classification_date: str,
        bank_account_id: int,
        amount: str,
        payment_method: str = "CHECK",
        expected_deposit_date: str | None = None,
        lot_id: int | None = None,
        owner_id: int | None = None,
        reference_number: str | None = None,
        category_id: int | None = None,
        charge_type: str | None = None,
        memo: str | None = None,
        apply_to_assessment_ids: str | None = None,
        created_by_user_id: int | None = None,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO pending_classifications (
                classification_date, expected_deposit_date,
                bank_account_id, lot_id, owner_id,
                amount, payment_method, reference_number,
                category_id, charge_type, memo,
                apply_to_assessment_ids,
                created_by_user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                classification_date,
                expected_deposit_date,
                bank_account_id,
                lot_id,
                owner_id,
                amount,
                payment_method,
                reference_number,
                category_id,
                charge_type,
                memo,
                apply_to_assessment_ids,
                created_by_user_id,
            ),
        )
        return int(cur.lastrowid or 0)

    def update(
        self,
        pc_id: int,
        *,
        classification_date: str,
        bank_account_id: int,
        amount: str,
        payment_method: str,
        expected_deposit_date: str | None = None,
        lot_id: int | None = None,
        owner_id: int | None = None,
        reference_number: str | None = None,
        category_id: int | None = None,
        charge_type: str | None = None,
        memo: str | None = None,
        apply_to_assessment_ids: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE pending_classifications SET
                classification_date     = ?,
                expected_deposit_date   = ?,
                bank_account_id         = ?,
                lot_id                  = ?,
                owner_id                = ?,
                amount                  = ?,
                payment_method          = ?,
                reference_number        = ?,
                category_id             = ?,
                charge_type             = ?,
                memo                    = ?,
                apply_to_assessment_ids = ?,
                updated_at              = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                classification_date,
                expected_deposit_date,
                bank_account_id,
                lot_id,
                owner_id,
                amount,
                payment_method,
                reference_number,
                category_id,
                charge_type,
                memo,
                apply_to_assessment_ids,
                pc_id,
            ),
        )

    def set_status(self, pc_id: int, status: str) -> None:
        self.conn.execute(
            """
            UPDATE pending_classifications
               SET status     = ?,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (status, pc_id),
        )

    def cancel(self, pc_id: int) -> None:
        self.set_status(pc_id, "CANCELLED")

    def delete(self, pc_id: int) -> None:
        """Hard-delete. Only allowed before the row is matched/posted."""
        self.conn.execute(
            "DELETE FROM pending_classifications WHERE id = ? AND status = 'PENDING'",
            (pc_id,),
        )

    # ── Reads ────────────────────────────────────────────────────────

    def get(self, pc_id: int) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self.conn.execute(
            "SELECT * FROM pending_classifications WHERE id = ?",
            (pc_id,),
        ).fetchone()
        return row

    def list_for_display(
        self,
        *,
        status: str | None = None,
        limit: int = 500,
    ) -> list[sqlite3.Row]:
        """List classifications joined to lot/owner/bank/category labels."""
        sql = """
            SELECT
                pc.id,
                pc.classification_date,
                pc.expected_deposit_date,
                pc.amount,
                pc.payment_method,
                pc.reference_number,
                pc.charge_type,
                pc.memo,
                pc.status,
                pc.matched_bank_transaction_id,
                pc.posted_payment_id,
                pc.created_at,
                pc.bank_account_id,
                ba.account_name      AS bank_account_name,
                ba.account_last4     AS bank_account_last4,
                pc.lot_id,
                l.lot_number         AS lot_number,
                l.street_address_1   AS lot_address,
                pc.owner_id,
                o.display_name       AS owner_display_name,
                COALESCE(
                    NULLIF(TRIM(COALESCE(o.first_name,'') || ' ' || COALESCE(o.last_name,'')), ''),
                    o.display_name,
                    ''
                ) AS owner_name,
                pc.category_id,
                c.name               AS category_name,
                c.code               AS category_code
            FROM pending_classifications pc
            LEFT JOIN bank_accounts ba ON ba.id = pc.bank_account_id
            LEFT JOIN lots          l  ON l.id  = pc.lot_id
            LEFT JOIN owners        o  ON o.id  = pc.owner_id
            LEFT JOIN categories    c  ON c.id  = pc.category_id
        """
        params: tuple[Any, ...] = ()
        if status:
            sql += " WHERE pc.status = ?"
            params = (status,)
        sql += """
            ORDER BY
                CASE pc.status
                    WHEN 'PENDING'   THEN 0
                    WHEN 'MATCHED'   THEN 1
                    WHEN 'POSTED'    THEN 2
                    WHEN 'CANCELLED' THEN 3
                END,
                pc.classification_date DESC,
                pc.id DESC
            LIMIT ?
        """
        params = params + (int(limit),)
        return list(self.conn.execute(sql, params).fetchall())
