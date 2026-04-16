"""Repository for bank-account lookups."""

from __future__ import annotations

import sqlite3

from .base import BaseRepository


class BankAccountsRepository(BaseRepository):
    """Database access for bank accounts."""

    def list_bank_accounts(
        self, *, active_only: bool = True
    ) -> list[sqlite3.Row]:
        """Return bank accounts joined to their GL cash account."""
        predicates = []
        if active_only:
            predicates.append("b.active_flag = 1")
        where_sql = f"WHERE {' AND '.join(predicates)}" if predicates else ""
        return list(
            self.conn.execute(
                f"""
                SELECT
                    b.id,
                    b.account_name,
                    b.institution_name,
                    b.account_last4,
                    b.account_type,
                    b.active_flag,
                    a.id AS gl_account_id,
                    a.account_number AS gl_account_number,
                    a.account_name AS gl_account_name,
                    a.fund_code AS gl_fund_code
                FROM bank_accounts b
                JOIN accounts a ON a.id = b.gl_account_id
                {where_sql}
                ORDER BY b.account_name COLLATE NOCASE
                """
            ).fetchall()
        )
