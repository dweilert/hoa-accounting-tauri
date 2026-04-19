"""Repository for account lookups and mutations."""

from __future__ import annotations

import sqlite3

from .base import BaseRepository

_GROUP_CODES = [
    "LANDSCAPE", "SEWER", "ROAD", "WALL", "ENTRANCE",
    "UTILITIES", "INSURANCE", "MISC", "FIREWISE",
]

_FUND_CODES = ["OPERATING", "RESERVE", "SPECIAL"]


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

    def get_account(self, account_id: int) -> sqlite3.Row | None:
        """Return full account detail joined to its type, or None."""
        return self.conn.execute(
            """
            SELECT
                a.id,
                a.account_number,
                a.account_name,
                a.account_type_id,
                a.fund_code,
                a.group_code,
                a.is_bank_account,
                a.is_active,
                a.description,
                at.code  AS account_type_code,
                at.name  AS account_type_name
            FROM accounts a
            JOIN account_types at ON at.id = a.account_type_id
            WHERE a.id = ?
            """,
            (account_id,),
        ).fetchone()

    def get_by_number(self, account_number: str):
        """Return account id + name for a given account_number, or None.

        Used by the transaction pages when they need to resolve a
        config-specified account number (e.g. dues_receivable_account_number)
        into a live account id at post time.
        """
        return self.conn.execute(
            """
            SELECT id, account_number, account_name, is_active, fund_code
            FROM accounts
            WHERE account_number = ?
            """,
            (account_number,),
        ).fetchone()

    def list_account_types(self) -> list[sqlite3.Row]:
        """Return all account types ordered by id (ASSET → LIABILITY → EQUITY → INCOME → EXPENSE)."""
        return list(
            self.conn.execute(
                "SELECT id, code, name FROM account_types ORDER BY id"
            ).fetchall()
        )

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

    def account_number_exists(
        self, account_number: str, *, exclude_id: int | None = None
    ) -> bool:
        """Return True if account_number is already taken by another account."""
        if exclude_id is not None:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM accounts WHERE account_number = ? AND id != ?",
                (account_number, exclude_id),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM accounts WHERE account_number = ?",
                (account_number,),
            ).fetchone()
        return int(row[0]) > 0

    # Exhaustive list of (table, column) pairs that reference accounts.id.
    # These are module-level constants — never user-supplied — so the
    # f-string interpolation below is safe.
    _ACCOUNT_REF_CHECKS: list[tuple[str, str]] = [
        ("journal_entry_lines", "account_id"),
        ("assessment_rules",    "income_account_id"),
        ("assessment_rules",    "receivable_account_id"),
        ("vendor_bills",        "expense_account_id"),
        ("vendor_bills",        "payable_account_id"),
        ("bank_accounts",       "gl_account_id"),
        ("budget_lines",        "account_id"),
        ("reserve_transfers",   "from_account_id"),
        ("reserve_transfers",   "to_account_id"),
    ]

    def has_activity(self, account_id: int) -> bool:
        """Return True if any records reference this account."""
        for table, col in self._ACCOUNT_REF_CHECKS:
            row = self.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {col} = ? LIMIT 1",  # noqa: S608 — table/col from constant above
                (account_id,),
            ).fetchone()
            if int(row[0]) > 0:
                return True
        return False

    # ── Mutations ──────────────────────────────────────────────────────

    def insert_account(
        self,
        *,
        account_number: str,
        account_name: str,
        account_type_id: int,
        fund_code: str,
        group_code: str | None,
        is_bank_account: bool,
        description: str | None,
    ) -> int:
        """Insert a new account and return its new id."""
        cur = self.conn.execute(
            """
            INSERT INTO accounts
                (account_number, account_name, account_type_id, fund_code,
                 group_code, is_bank_account, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_number,
                account_name,
                account_type_id,
                fund_code,
                group_code,
                1 if is_bank_account else 0,
                description,
            ),
        )
        return cur.lastrowid  # type: ignore[return-value]

    def update_account(
        self,
        account_id: int,
        *,
        account_number: str,
        account_name: str,
        account_type_id: int,
        fund_code: str,
        group_code: str | None,
        is_bank_account: bool,
        is_active: bool,
        description: str | None,
    ) -> None:
        """Update an existing account."""
        self.conn.execute(
            """
            UPDATE accounts
               SET account_number  = ?,
                   account_name    = ?,
                   account_type_id = ?,
                   fund_code       = ?,
                   group_code      = ?,
                   is_bank_account = ?,
                   is_active       = ?,
                   description     = ?,
                   updated_at      = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (
                account_number,
                account_name,
                account_type_id,
                fund_code,
                group_code,
                1 if is_bank_account else 0,
                1 if is_active else 0,
                description,
                account_id,
            ),
        )

    def delete_account(self, account_id: int) -> None:
        """Hard-delete an account with no activity."""
        self.conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
