"""Repository for bank-account data access."""

from __future__ import annotations

import sqlite3

from .base import BaseRepository


class BankAccountsRepository(BaseRepository):
    """Database access for bank accounts."""

    def list_bank_accounts(
        self, *, active_only: bool = True
    ) -> list[sqlite3.Row]:
        predicates = []
        if active_only:
            predicates.append("active_flag = 1")
        where_sql = f"WHERE {' AND '.join(predicates)}" if predicates else ""
        return list(
            self.conn.execute(
                f"""
                SELECT
                    id,
                    account_name,
                    institution_name,
                    account_last4,
                    account_type,
                    fund_code,
                    active_flag,
                    opening_balance,
                    opening_balance_date
                FROM bank_accounts
                {where_sql}
                ORDER BY account_name COLLATE NOCASE
                """
            ).fetchall()
        )

    def get_bank_account(self, bank_account_id: int) -> sqlite3.Row | None:
        return self.conn.execute(  # type: ignore[no-any-return]
            """
            SELECT
                id,
                account_name,
                institution_name,
                account_last4,
                account_type,
                fund_code,
                active_flag,
                opening_balance,
                opening_balance_date
            FROM bank_accounts
            WHERE id = ?
            """,
            (bank_account_id,),
        ).fetchone()

    _BANK_ACCOUNT_REF_TABLES: list[str] = [
        "payments",
        "bill_payments",
        "deposit_batches",
        "income_batches",
        "bank_transactions",
        "bank_import_batches",
        "bank_reconciliations",
    ]

    def has_transactions(self, bank_account_id: int) -> bool:
        for table in self._BANK_ACCOUNT_REF_TABLES:
            row = self.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE bank_account_id = ? LIMIT 1",  # noqa: S608
                (bank_account_id,),
            ).fetchone()
            if int(row[0]) > 0:
                return True
        return False

    def insert_bank_account(
        self,
        *,
        account_name: str,
        institution_name: str,
        account_last4: str | None,
        account_type: str,
        fund_code: str = "OPERATING",
        opening_balance: str = "0",
        opening_balance_date: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO bank_accounts
                (account_name, institution_name, account_last4, account_type,
                 fund_code, opening_balance, opening_balance_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (account_name, institution_name, account_last4, account_type,
             fund_code, opening_balance, opening_balance_date),
        )
        return cur.lastrowid  # type: ignore[return-value]

    def update_bank_account(
        self,
        bank_account_id: int,
        *,
        account_name: str,
        institution_name: str,
        account_last4: str | None,
        account_type: str,
        fund_code: str = "OPERATING",
        active_flag: bool = True,
        opening_balance: str | None = None,
        opening_balance_date: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE bank_accounts
               SET account_name         = ?,
                   institution_name     = ?,
                   account_last4        = ?,
                   account_type         = ?,
                   fund_code            = ?,
                   active_flag          = ?,
                   opening_balance      = COALESCE(?, opening_balance),
                   opening_balance_date = ?,
                   updated_at           = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (
                account_name,
                institution_name,
                account_last4,
                account_type,
                fund_code,
                1 if active_flag else 0,
                opening_balance,
                opening_balance_date,
                bank_account_id,
            ),
        )

    def delete_bank_account(self, bank_account_id: int) -> None:
        self.conn.execute(
            "DELETE FROM bank_accounts WHERE id = ?", (bank_account_id,)
        )
