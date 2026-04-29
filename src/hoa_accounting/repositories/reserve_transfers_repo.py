"""Repository for reserve transfers."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from .base import BaseRepository


class ReserveTransfersRepository(BaseRepository):
    """Database access for reserve transfer records."""

    # ── Queries ────────────────────────────────────────────────────────

    def list_transfers(
        self,
        *,
        type_filter: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[sqlite3.Row]:
        """Return all reserve transfers, newest first."""
        predicates = []
        params: list[object] = []
        if type_filter:
            predicates.append("rt.transfer_type = ?")
            params.append(type_filter)
        if start_date:
            predicates.append("rt.transfer_date >= ?")
            params.append(start_date)
        if end_date:
            predicates.append("rt.transfer_date <= ?")
            params.append(end_date)
        where = f"WHERE {' AND '.join(predicates)}" if predicates else ""
        return list(
            self.conn.execute(
                f"""
                SELECT
                    rt.id,
                    rt.transfer_date,
                    rt.transfer_type,
                    rt.amount,
                    rt.notes,
                    rt.purpose,
                    NULL AS journal_entry_id,
                    NULL AS entry_number,
                    NULL AS from_account_number,
                    fb.account_name   AS from_account_name,
                    fb.fund_code      AS from_fund_code,
                    NULL AS to_account_number,
                    tb.account_name   AS to_account_name,
                    tb.fund_code      AS to_fund_code
                FROM reserve_transfers rt
                LEFT JOIN bank_accounts fb ON fb.id = rt.from_bank_account_id
                LEFT JOIN bank_accounts tb ON tb.id = rt.to_bank_account_id
                {where}
                ORDER BY rt.transfer_date DESC, rt.id DESC
                """,
                params,
            ).fetchall()
        )

    def get_transfer(self, transfer_id: int) -> sqlite3.Row | None:
        """Return one transfer with full details, or None."""
        return self.conn.execute(  # type: ignore[no-any-return]
            """
            SELECT
                rt.id,
                rt.transfer_date,
                rt.transfer_type,
                rt.amount,
                rt.notes,
                rt.purpose,
                NULL AS journal_entry_id,
                NULL AS entry_number,
                NULL AS from_account_number,
                fb.account_name   AS from_account_name,
                fb.fund_code      AS from_fund_code,
                NULL AS to_account_number,
                tb.account_name   AS to_account_name,
                tb.fund_code      AS to_fund_code
            FROM reserve_transfers rt
            LEFT JOIN bank_accounts fb ON fb.id = rt.from_bank_account_id
            LEFT JOIN bank_accounts tb ON tb.id = rt.to_bank_account_id
            WHERE rt.id = ?
            """,
            (transfer_id,),
        ).fetchone()

    def get_bank_accounts_by_fund(self) -> dict[str, list[sqlite3.Row]]:
        """Return active bank accounts grouped by fund code."""
        rows = list(
            self.conn.execute(
                """
                SELECT
                    ba.id    AS bank_account_id,
                    ba.account_name,
                    ba.account_last4,
                    ba.institution_name,
                    ba.fund_code
                FROM bank_accounts ba
                WHERE ba.active_flag = 1
                ORDER BY ba.fund_code, ba.account_name COLLATE NOCASE
                """
            ).fetchall()
        )
        result: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            result.setdefault(row["fund_code"], []).append(row)
        return result

    def get_reserve_balance(self) -> str:
        """Return the current cash balance of all RESERVE bank accounts."""
        row = self.conn.execute(
            """
            SELECT
                COALESCE(SUM(ba.opening_balance), 0)
                + COALESCE((SELECT SUM(p.amount) FROM payments p
                            JOIN bank_accounts b ON b.id = p.bank_account_id
                            WHERE b.fund_code = 'RESERVE' AND b.active_flag = 1), 0)
                + COALESCE((SELECT SUM(ib.total_amount) FROM income_batches ib
                            JOIN bank_accounts b ON b.id = ib.bank_account_id
                            WHERE b.fund_code = 'RESERVE' AND b.active_flag = 1), 0)
                - COALESCE((SELECT SUM(bp.amount) FROM bill_payments bp
                            JOIN bank_accounts b ON b.id = bp.bank_account_id
                            WHERE b.fund_code = 'RESERVE' AND b.active_flag = 1), 0)
                AS balance
            FROM bank_accounts ba
            WHERE ba.fund_code = 'RESERVE' AND ba.active_flag = 1
            """
        ).fetchone()
        if row and row["balance"] is not None:
            return f"{Decimal(str(row['balance'])):,.2f}"
        return "0.00"

    def delete_transfer(self, transfer_id: int) -> None:
        """Delete a reserve transfer."""
        self.conn.execute(
            "DELETE FROM reserve_transfers WHERE id = ?",
            (transfer_id,),
        )
        self.conn.commit()

    # ── Mutations ──────────────────────────────────────────────────────

    def insert_transfer(
        self,
        *,
        transfer_date: str,
        amount: str,
        notes: str,
        from_account_id: int | None = None,
        to_account_id: int | None = None,
        transfer_type: str | None = None,
        purpose: str | None = None,
    ) -> int:
        """Insert a reserve transfer and return its id.

        The legacy parameter names (``from_account_id`` / ``to_account_id``)
        come from the chart-of-accounts era. After migration 0061 the columns
        are ``from_bank_account_id`` / ``to_bank_account_id`` — callers now
        pass bank-account IDs through the same kwargs.
        """
        cur = self.conn.execute(
            """
            INSERT INTO reserve_transfers (
                transfer_date,
                from_bank_account_id,
                to_bank_account_id,
                amount,
                notes,
                transfer_type,
                purpose
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transfer_date,
                from_account_id,
                to_account_id,
                amount,
                notes,
                transfer_type,
                purpose,
            ),
        )
        return int(cur.lastrowid or 0)
