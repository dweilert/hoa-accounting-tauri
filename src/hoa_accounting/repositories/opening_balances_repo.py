"""Repository for opening-balance sub-ledger data access."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from .base import BaseRepository


class OpeningBalancesRepository(BaseRepository):
    """Database access for opening-balance records."""

    # ── Queries ────────────────────────────────────────────────────────

    def get_bank_accounts_with_balances(self) -> list[sqlite3.Row]:
        """All active bank accounts with their opening-balance record (if any)."""
        return list(
            self.conn.execute(
                """
                SELECT
                    ba.id           AS bank_account_id,
                    ba.account_name,
                    ba.institution_name,
                    ba.account_last4,
                    a.id            AS gl_account_id,
                    a.account_number AS gl_account_number,
                    a.account_name  AS gl_account_name,
                    a.fund_code,
                    COALESCE(ob.amount, 0) AS amount,
                    ob.as_of_date,
                    ob.journal_entry_id
                FROM bank_accounts ba
                JOIN accounts a ON a.id = ba.gl_account_id
                LEFT JOIN opening_balances ob
                    ON ob.entity_type = 'BANK_ACCOUNT' AND ob.entity_id = ba.id
                WHERE ba.active_flag = 1
                ORDER BY ba.account_name COLLATE NOCASE
                """
            ).fetchall()
        )

    def get_lots_with_balances(self) -> list[sqlite3.Row]:
        """All lots with current primary owner and opening-balance record (if any)."""
        return list(
            self.conn.execute(
                """
                SELECT
                    l.id            AS lot_id,
                    l.lot_number,
                    o.display_name  AS owner_name,
                    COALESCE(ob.amount, 0) AS amount,
                    ob.as_of_date,
                    ob.journal_entry_id
                FROM lots l
                LEFT JOIN lot_ownership lo
                    ON lo.lot_id = l.id
                    AND lo.end_date IS NULL
                    AND lo.is_primary_contact = 1
                LEFT JOIN owners o ON o.id = lo.owner_id
                LEFT JOIN opening_balances ob
                    ON ob.entity_type = 'LOT' AND ob.entity_id = l.id
                ORDER BY l.lot_number COLLATE NOCASE
                """
            ).fetchall()
        )

    def get_lot_opening_balance(self, lot_id: int) -> Decimal | None:
        """Return the opening balance for a specific lot, or None if not set."""
        row = self.conn.execute(
            "SELECT amount FROM opening_balances "
            "WHERE entity_type = 'LOT' AND entity_id = ?",
            (lot_id,),
        ).fetchone()
        return Decimal(str(row["amount"])) if row else None

    def get_bank_opening_balance(
        self, bank_account_id: int
    ) -> tuple[Decimal, str] | None:
        """Return (amount, as_of_date) for a bank account opening balance, or None."""
        row = self.conn.execute(
            "SELECT amount, as_of_date FROM opening_balances "
            "WHERE entity_type = 'BANK_ACCOUNT' AND entity_id = ?",
            (bank_account_id,),
        ).fetchone()
        if row:
            return Decimal(str(row["amount"])), row["as_of_date"] or ""
        return None

    def get_current_je_id(self) -> int | None:
        """Return the shared journal_entry_id, or None if no JE has been posted."""
        row = self.conn.execute(
            "SELECT journal_entry_id FROM opening_balances "
            "WHERE journal_entry_id IS NOT NULL LIMIT 1"
        ).fetchone()
        return int(row["journal_entry_id"]) if row else None

    # ── Mutations ──────────────────────────────────────────────────────

    def ensure_offset_account(self) -> int:
        """Find or create the 'Opening Balance Offset' equity account.

        Creates the EQUITY account type first if it doesn't exist.
        Returns the account id.
        """
        eq_type = self.conn.execute(
            "SELECT id FROM account_types WHERE code = 'EQUITY'"
        ).fetchone()
        if not eq_type:
            cur = self.conn.execute(
                "INSERT INTO account_types "
                "(code, name, normal_balance, financial_statement_group) "
                "VALUES ('EQUITY', 'Equity', 'CREDIT', 'BALANCE_SHEET')"
            )
            eq_type_id = int(cur.lastrowid)  # type: ignore[arg-type]
        else:
            eq_type_id = int(eq_type["id"])

        acct = self.conn.execute(
            "SELECT id FROM accounts WHERE account_name = 'Opening Balance Offset'"
        ).fetchone()
        if acct:
            return int(acct["id"])

        # Find a free account number in the 3900 range
        used = {
            r["account_number"]
            for r in self.conn.execute(
                "SELECT account_number FROM accounts WHERE account_number LIKE '39%'"
            ).fetchall()
        }
        acct_num = next(
            n for n in (f"39{i:02d}" for i in range(100)) if n not in used
        )

        cur = self.conn.execute(
            "INSERT INTO accounts "
            "(account_number, account_name, account_type_id, "
            " fund_code, is_bank_account, is_active) "
            "VALUES (?, 'Opening Balance Offset', ?, 'OPERATING', 0, 1)",
            (acct_num, eq_type_id),
        )
        return int(cur.lastrowid)  # type: ignore[arg-type]

    def clear_all_je_references(self) -> None:
        """Null out journal_entry_id on all records before deleting an old JE."""
        self.conn.execute(
            "UPDATE opening_balances SET journal_entry_id = NULL"
        )

    def upsert_balance(
        self,
        entity_type: str,
        entity_id: int,
        as_of_date: str,
        amount: str,
        journal_entry_id: int,
    ) -> None:
        """Insert or update a single opening-balance record."""
        self.conn.execute(
            """
            INSERT INTO opening_balances
                (entity_type, entity_id, as_of_date, amount,
                 journal_entry_id, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (entity_type, entity_id) DO UPDATE SET
                as_of_date       = excluded.as_of_date,
                amount           = excluded.amount,
                journal_entry_id = excluded.journal_entry_id,
                updated_at       = CURRENT_TIMESTAMP
            """,
            (entity_type, entity_id, as_of_date, amount, journal_entry_id),
        )
