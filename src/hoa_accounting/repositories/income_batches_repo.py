"""Repository for non-dues income batches."""

from __future__ import annotations

import sqlite3

from .base import BaseRepository


class IncomeBatchesRepository(BaseRepository):
    """Database access for income batches."""

    def insert_income_batch(
        self,
        *,
        posting_date: str,
        bank_account_id: int,
        income_account_id: int | None,
        income_description: str,
        total_amount: str,
        notes: str | None,
        created_by_user_id: int | None,
        category_id: int | None = None,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO income_batches (
                posting_date,
                bank_account_id,
                income_account_id,
                income_description,
                total_amount,
                notes,
                created_by_user_id,
                category_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                posting_date,
                bank_account_id,
                income_account_id,
                income_description,
                total_amount,
                notes,
                created_by_user_id,
                category_id,
            ),
        )
        return int(cur.lastrowid)

    def list_batches(self, *, limit: int = 200) -> list[sqlite3.Row]:
        """Return recent income batches joined to their bank account and category."""
        return list(
            self.conn.execute(
                """
                SELECT
                    ib.id,
                    ib.posting_date,
                    ib.income_description,
                    ib.total_amount,
                    ib.notes,
                    ib.journal_entry_id,
                    b.account_name AS bank_account_name,
                    a.account_number AS income_account_number,
                    a.account_name AS income_account_name,
                    c.name AS category_name,
                    je.entry_number
                FROM income_batches ib
                JOIN bank_accounts b ON b.id = ib.bank_account_id
                LEFT JOIN accounts a ON a.id = ib.income_account_id
                LEFT JOIN categories c ON c.id = ib.category_id
                LEFT JOIN journal_entries je ON je.id = ib.journal_entry_id
                ORDER BY ib.posting_date DESC, ib.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )
