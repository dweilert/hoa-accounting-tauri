"""Dues billing history — last record and insert."""

from __future__ import annotations

import sqlite3
from decimal import Decimal


class DuesBillingRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_last_billing(self) -> dict | None:
        """Return the most recent billing history record, or None."""
        row = self.conn.execute(
            "SELECT * FROM dues_billing_history ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def get_billing_for_period(
        self, *, cycle_type: str, period_year: int, period_sequence: int
    ) -> dict | None:
        """Return the existing history row for this period, or None."""
        row = self.conn.execute(
            """
            SELECT * FROM dues_billing_history
            WHERE cycle_type = ? AND period_year = ? AND period_sequence = ?
            LIMIT 1
            """,
            (cycle_type, period_year, period_sequence),
        ).fetchone()
        return dict(row) if row else None

    def insert_history(
        self,
        *,
        cycle_type: str,
        period_label: str,
        period_year: int,
        period_sequence: int,
        amount: Decimal,
        owner_count: int,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO dues_billing_history
                (cycle_type, period_label, period_year, period_sequence, amount, owner_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (cycle_type, period_label, period_year, period_sequence, str(amount), owner_count),
        )
