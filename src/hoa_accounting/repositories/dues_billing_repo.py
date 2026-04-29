"""Dues billing history — last record and insert."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class DuesBillingRecord:
    """One ``dues_billing_history`` row."""

    id: int
    cycle_type: str
    period_label: str
    period_year: int
    period_sequence: int
    amount: Decimal
    owner_count: int
    billed_at: str

    # Backwards-compat: callers historically used dict-subscript access
    # (``row["amount"]``). Keep that working while we migrate to attr
    # access.
    def __getitem__(self, key: str) -> Any:  # pragma: no cover — trivial passthrough
        return getattr(self, key)


def _row_to_record(row: sqlite3.Row) -> DuesBillingRecord:
    return DuesBillingRecord(
        id=int(row["id"]),
        cycle_type=str(row["cycle_type"]),
        period_label=str(row["period_label"]),
        period_year=int(row["period_year"]),
        period_sequence=int(row["period_sequence"]),
        amount=Decimal(str(row["amount"])),
        owner_count=int(row["owner_count"]),
        billed_at=str(row["billed_at"]),
    )


class DuesBillingRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_last_billing(self) -> DuesBillingRecord | None:
        """Return the most recent billing history record, or None."""
        row = self.conn.execute(
            "SELECT * FROM dues_billing_history ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return _row_to_record(row) if row else None

    def get_billing_for_period(
        self, *, cycle_type: str, period_year: int, period_sequence: int
    ) -> DuesBillingRecord | None:
        """Return the existing history row for this period, or None."""
        row = self.conn.execute(
            """
            SELECT * FROM dues_billing_history
            WHERE cycle_type = ? AND period_year = ? AND period_sequence = ?
            LIMIT 1
            """,
            (cycle_type, period_year, period_sequence),
        ).fetchone()
        return _row_to_record(row) if row else None

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
            (
                cycle_type,
                period_label,
                period_year,
                period_sequence,
                str(amount),
                owner_count,
            ),
        )
