"""Repository for account lookups."""

from __future__ import annotations

from .base import BaseRepository


class AccountsRepository(BaseRepository):
    """Database access for accounts."""

    def get_by_id(self, account_id: int):
        """Return a minimal account row by id."""
        return self.conn.execute(
            "SELECT id, is_active FROM accounts WHERE id = ?",
            (account_id,),
        ).fetchone()

    def get_detail_by_id(self, account_id: int):
        """Return an account detail row by id."""
        return self.conn.execute(
            """
            SELECT id, is_active, account_type_id, fund_code, is_bank_account
            FROM accounts
            WHERE id = ?
            """,
            (account_id,),
        ).fetchone()
