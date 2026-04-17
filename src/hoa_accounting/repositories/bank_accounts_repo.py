"""Repository for bank-account data access."""

from __future__ import annotations

import sqlite3

from .base import BaseRepository


class BankAccountsRepository(BaseRepository):
    """Database access for bank accounts."""

    # ── Queries ────────────────────────────────────────────────────────

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

    def get_bank_account(self, bank_account_id: int) -> sqlite3.Row | None:
        """Return one bank account (with GL account details) or None."""
        return self.conn.execute(
            """
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
            WHERE b.id = ?
            """,
            (bank_account_id,),
        ).fetchone()

    def list_gl_account_options(
        self, *, exclude_bank_account_id: int | None = None
    ) -> list[sqlite3.Row]:
        """Return active GL accounts flagged as bank accounts not yet assigned.

        On the edit form, ``exclude_bank_account_id`` exempts the current
        bank account so its own GL account stays visible in the dropdown.
        """
        exclude_clause = ""
        params: list[object] = []
        if exclude_bank_account_id is not None:
            exclude_clause = "AND (ba.id IS NULL OR ba.id = ?)"
            params.append(exclude_bank_account_id)
        else:
            exclude_clause = "AND ba.id IS NULL"

        return list(
            self.conn.execute(
                f"""
                SELECT a.id, a.account_number, a.account_name, a.fund_code
                FROM accounts a
                LEFT JOIN bank_accounts ba ON ba.gl_account_id = a.id
                WHERE a.is_bank_account = 1
                  AND a.is_active = 1
                  {exclude_clause}
                ORDER BY a.account_number
                """,
                params,
            ).fetchall()
        )

    def has_transactions(self, bank_account_id: int) -> bool:
        """Return True if any financial records exist for this bank account."""
        tables = [
            "payments",
            "bill_payments",
            "deposit_batches",
            "income_batches",
            "bank_transactions",
            "bank_import_batches",
            "bank_reconciliations",
        ]
        for table in tables:
            row = self.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE bank_account_id = ? LIMIT 1",
                (bank_account_id,),
            ).fetchone()
            if int(row[0]) > 0:
                return True
        return False

    # ── Mutations ──────────────────────────────────────────────────────

    def insert_bank_account(
        self,
        *,
        account_name: str,
        institution_name: str,
        account_last4: str | None,
        account_type: str,
        gl_account_id: int,
    ) -> int:
        """Insert a new bank account and return its new id."""
        cur = self.conn.execute(
            """
            INSERT INTO bank_accounts
                (account_name, institution_name, account_last4, account_type, gl_account_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (account_name, institution_name, account_last4, account_type, gl_account_id),
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
        gl_account_id: int,
        active_flag: bool,
    ) -> None:
        """Update an existing bank account."""
        self.conn.execute(
            """
            UPDATE bank_accounts
               SET account_name    = ?,
                   institution_name = ?,
                   account_last4   = ?,
                   account_type    = ?,
                   gl_account_id   = ?,
                   active_flag     = ?,
                   updated_at      = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (
                account_name,
                institution_name,
                account_last4,
                account_type,
                gl_account_id,
                1 if active_flag else 0,
                bank_account_id,
            ),
        )

    def delete_bank_account(self, bank_account_id: int) -> None:
        """Hard-delete a bank account with no linked transactions."""
        self.conn.execute(
            "DELETE FROM bank_accounts WHERE id = ?", (bank_account_id,)
        )
