"""Repository for reserve transfers."""

from __future__ import annotations

from .base import BaseRepository


class ReserveTransfersRepository(BaseRepository):
    """Database access for reserve transfer records."""

    def insert_transfer(
        self,
        *,
        transfer_date: str,
        from_account_id: int,
        to_account_id: int,
        amount: str,
        journal_entry_id: int,
        notes: str,
    ) -> int:
        """Insert a reserve transfer and return its id."""
        cur = self.conn.execute(
            """
            INSERT INTO reserve_transfers (
                transfer_date,
                from_account_id,
                to_account_id,
                amount,
                journal_entry_id,
                notes
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                transfer_date,
                from_account_id,
                to_account_id,
                amount,
                journal_entry_id,
                notes,
            ),
        )
        return int(cur.lastrowid)
