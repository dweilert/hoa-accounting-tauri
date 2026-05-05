"""Repository for deposit batches."""

from __future__ import annotations

import sqlite3
from typing import Any

from .base import BaseRepository


class DepositBatchesRepository(BaseRepository):
    """Database access for deposit batches."""

    def insert_deposit_batch(
        self,
        *,
        deposit_date: str,
        bank_account_id: int,
        total_amount: str,
        notes: str | None,
        created_by_user_id: int | None,
        posting_status: str = "POSTED",
    ) -> int:
        """Insert a deposit batch row and return its id."""
        cur = self.conn.execute(
            """
            INSERT INTO deposit_batches (
                deposit_date,
                bank_account_id,
                total_amount,
                notes,
                created_by_user_id,
                posting_status
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                deposit_date,
                bank_account_id,
                total_amount,
                notes,
                created_by_user_id,
                posting_status,
            ),
        )
        return int(cur.lastrowid or 0)

    def insert_batch_line(
        self,
        *,
        deposit_batch_id: int,
        lot_id: int | None,
        category_id: int | None,
        amount: str,
        reference_number: str | None,
        memo: str,
        charge_type_filter: str | None = None,
        apply_to_assessment_ids: str | None = None,
    ) -> int:
        """Insert a deposit_batch_lines row and return its id."""
        cur = self.conn.execute(
            """
            INSERT INTO deposit_batch_lines (
                deposit_batch_id, lot_id, category_id, amount,
                reference_number, memo, charge_type_filter,
                apply_to_assessment_ids
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                deposit_batch_id,
                lot_id,
                category_id,
                amount,
                reference_number,
                memo,
                charge_type_filter,
                apply_to_assessment_ids,
            ),
        )
        return int(cur.lastrowid or 0)

    def get_batch_lines(self, deposit_batch_id: int) -> list[dict[str, Any]]:
        """Return all deposit_batch_lines for a batch."""
        rows = self.conn.execute(
            """
            SELECT id, deposit_batch_id, lot_id, category_id, amount,
                   reference_number, memo, charge_type_filter,
                   apply_to_assessment_ids
            FROM deposit_batch_lines
            WHERE deposit_batch_id = ?
            ORDER BY id
            """,
            (deposit_batch_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_posting_status(self, deposit_batch_id: int) -> str | None:
        """Return the posting_status for a batch, or None if not found."""
        row = self.conn.execute(
            "SELECT posting_status FROM deposit_batches WHERE id = ?",
            (deposit_batch_id,),
        ).fetchone()
        return str(row["posting_status"]) if row else None

    def mark_posted(self, deposit_batch_id: int) -> None:
        """Flip a PENDING batch to POSTED."""
        self.conn.execute(
            "UPDATE deposit_batches SET posting_status = 'POSTED' WHERE id = ?",
            (deposit_batch_id,),
        )

    def mark_cancelled(self, deposit_batch_id: int) -> None:
        """Flip a PENDING batch to CANCELLED."""
        self.conn.execute(
            "UPDATE deposit_batches SET posting_status = 'CANCELLED' WHERE id = ?",
            (deposit_batch_id,),
        )

    def update_payment_batch_id(
        self, *, payment_id: int, deposit_batch_id: int
    ) -> None:
        """Link a payment row to the deposit batch it belongs to."""
        self.conn.execute(
            "UPDATE payments SET deposit_batch_id = ? WHERE id = ?",
            (deposit_batch_id, payment_id),
        )

    def list_batches(self, *, limit: int = 200) -> list[sqlite3.Row]:
        """Return recent deposit batches with summary info."""
        return list(
            self.conn.execute(
                """
                SELECT
                    db.id,
                    db.deposit_date,
                    db.total_amount,
                    db.notes,
                    db.posting_status,
                    NULL AS journal_entry_id,
                    b.account_name AS bank_account_name,
                    b.institution_name,
                    NULL AS entry_number,
                    (SELECT COUNT(*) FROM payments p
                     WHERE p.deposit_batch_id = db.id) AS payment_count
                FROM deposit_batches db
                JOIN bank_accounts b ON b.id = db.bank_account_id
                ORDER BY db.deposit_date DESC, db.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )

    def list_pending_batches(self) -> list[dict[str, Any]]:
        """Return all PENDING deposit batches with line counts."""
        rows = self.conn.execute("""
            SELECT
                db.id,
                db.deposit_date,
                db.total_amount,
                db.notes,
                b.account_name AS bank_account_name,
                b.account_last4,
                (SELECT COUNT(*) FROM deposit_batch_lines l
                 WHERE l.deposit_batch_id = db.id) AS line_count
            FROM deposit_batches db
            JOIN bank_accounts b ON b.id = db.bank_account_id
            WHERE db.posting_status = 'PENDING'
            ORDER BY db.deposit_date DESC, db.id DESC
            """).fetchall()
        return [dict(r) for r in rows]
