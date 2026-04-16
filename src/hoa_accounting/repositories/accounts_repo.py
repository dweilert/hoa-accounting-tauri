"""Repository for account lookups."""

from __future__ import annotations

import sqlite3

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

    def list_accounts_by_type(
        self, *, account_type_code: str, active_only: bool = True
    ) -> list[sqlite3.Row]:
        """Return active accounts of one type, ordered by account number.

        Used to populate dropdowns on transaction-entry forms — callers
        pass ``ASSET`` for cash pickers, ``LIABILITY`` for payables,
        ``INCOME`` for assessment income pickers, ``EXPENSE`` for vendor
        bill expense pickers.
        """
        predicates = ["at.code = ?"]
        params: list[object] = [account_type_code]
        if active_only:
            predicates.append("a.is_active = 1")
        where_sql = " AND ".join(predicates)
        return list(
            self.conn.execute(
                f"""
                SELECT
                    a.id,
                    a.account_number,
                    a.account_name,
                    a.fund_code,
                    a.group_code,
                    at.code AS account_type_code
                FROM accounts a
                JOIN account_types at ON at.id = a.account_type_id
                WHERE {where_sql}
                ORDER BY a.account_number
                """,
                params,
            ).fetchall()
        )

    def list_chart(self, *, active_only: bool = True) -> list[sqlite3.Row]:
        """Return the full chart of accounts joined to account types.

        Ordered by account_number so the natural 1xxx→9xxx flow (assets,
        liabilities, equity, income, expense) lines up in the UI.
        """
        predicates = []
        if active_only:
            predicates.append("a.is_active = 1")
        where_sql = f"WHERE {' AND '.join(predicates)}" if predicates else ""
        return list(
            self.conn.execute(
                f"""
                SELECT
                    a.id,
                    a.account_number,
                    a.account_name,
                    a.fund_code,
                    a.is_bank_account,
                    a.is_active,
                    a.group_code,
                    a.description,
                    at.code AS account_type_code,
                    at.name AS account_type_name
                FROM accounts a
                JOIN account_types at ON at.id = a.account_type_id
                {where_sql}
                ORDER BY a.account_number
                """
            ).fetchall()
        )
