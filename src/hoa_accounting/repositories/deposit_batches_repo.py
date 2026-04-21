"""Repository for deposit batches."""

from __future__ import annotations

import sqlite3

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
    ) -> int:
        """Insert a deposit batch row and return its id."""
        cur = self.conn.execute(
            """
            INSERT INTO deposit_batches (
                deposit_date,
                bank_account_id,
                total_amount,
                notes,
                created_by_user_id
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                deposit_date,
                bank_account_id,
                total_amount,
                notes,
                created_by_user_id,
            ),
        )
        return int(cur.lastrowid)

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
                    db.journal_entry_id,
                    b.account_name AS bank_account_name,
                    b.institution_name,
                    je.entry_number,
                    (SELECT COUNT(*) FROM payments p
                     WHERE p.deposit_batch_id = db.id) AS payment_count
                FROM deposit_batches db
                JOIN bank_accounts b ON b.id = db.bank_account_id
                LEFT JOIN journal_entries je ON je.id = db.journal_entry_id
                ORDER BY db.deposit_date DESC, db.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )
