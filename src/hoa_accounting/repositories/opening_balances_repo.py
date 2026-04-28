"""Repository for opening-balance sub-ledger data access.

After the Chart of Accounts removal (migration 0061), opening balances are
stored only against bank_accounts (cash on hand) and lots (owner balances).
There is no longer a journal-entry posting; balances are simple data rows.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from .base import BaseRepository


class OpeningBalancesRepository(BaseRepository):

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
                    ba.fund_code,
                    COALESCE(ob.amount, 0) AS amount,
                    ob.as_of_date
                FROM bank_accounts ba
                LEFT JOIN opening_balances ob
                    ON ob.entity_type = 'BANK_ACCOUNT' AND ob.entity_id = ba.id
                WHERE ba.active_flag = 1
                ORDER BY ba.account_name COLLATE NOCASE
                """
            ).fetchall()
        )

    def get_lots_with_balances(self) -> list[sqlite3.Row]:
        """One row per lot. The owner shown is the alphabetically first
        current owner (last name, then first name)."""
        return list(
            self.conn.execute(
                """
                SELECT
                    l.id               AS lot_id,
                    l.lot_number,
                    l.street_address_1 AS street_address,
                    COALESCE(
                        NULLIF(TRIM(COALESCE(o.first_name,'') || ' ' || COALESCE(o.last_name,'')), ''),
                        o.display_name,
                        ''
                    ) AS owner_name,
                    COALESCE(od.amount, 0) AS dues_amount,
                    COALESCE(oa.amount, 0) AS assessment_amount,
                    COALESCE(od.as_of_date, oa.as_of_date) AS as_of_date
                FROM lots l
                LEFT JOIN lot_ownership lo
                       ON lo.id = (
                            SELECT lo2.id
                            FROM lot_ownership lo2
                            JOIN owners o2 ON o2.id = lo2.owner_id
                            WHERE lo2.lot_id = l.id AND lo2.end_date IS NULL
                            ORDER BY o2.last_name COLLATE NOCASE,
                                     o2.first_name COLLATE NOCASE,
                                     o2.display_name COLLATE NOCASE
                            LIMIT 1
                       )
                LEFT JOIN owners o ON o.id = lo.owner_id
                LEFT JOIN opening_balances od
                    ON od.entity_type = 'LOT_DUES' AND od.entity_id = l.id
                LEFT JOIN opening_balances oa
                    ON oa.entity_type = 'LOT_ASSESSMENT' AND oa.entity_id = l.id
                ORDER BY l.lot_number COLLATE NOCASE
                """
            ).fetchall()
        )

    def get_lot_opening_balance(self, lot_id: int) -> Decimal | None:
        row = self.conn.execute(
            "SELECT SUM(amount) AS total FROM opening_balances "
            "WHERE entity_type IN ('LOT_DUES', 'LOT_ASSESSMENT') AND entity_id = ?",
            (lot_id,),
        ).fetchone()
        if row and row["total"] is not None:
            return Decimal(str(row["total"]))
        return None

    def get_bank_opening_balance(
        self, bank_account_id: int
    ) -> tuple[Decimal, str] | None:
        row = self.conn.execute(
            "SELECT amount, as_of_date FROM opening_balances "
            "WHERE entity_type = 'BANK_ACCOUNT' AND entity_id = ?",
            (bank_account_id,),
        ).fetchone()
        if row:
            return Decimal(str(row["amount"])), row["as_of_date"] or ""
        return None

    # ── Stubs for retired GL-bound interfaces ─────────────────────────────

    def get_current_je_id(self) -> int | None:
        return None

    def ensure_offset_account(self) -> int:
        return 0  # unused after GL retirement

    def upsert_balance(
        self,
        entity_type: str,
        entity_id: int,
        as_of_date: str,
        amount: str,
    ) -> None:
        """Insert or update a single opening-balance record."""
        self.conn.execute(
            """
            INSERT INTO opening_balances
                (entity_type, entity_id, as_of_date, amount, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (entity_type, entity_id) DO UPDATE SET
                as_of_date = excluded.as_of_date,
                amount     = excluded.amount,
                updated_at = CURRENT_TIMESTAMP
            """,
            (entity_type, entity_id, as_of_date, amount),
        )
