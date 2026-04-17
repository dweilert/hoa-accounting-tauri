"""Repository for accounting period lookups and mutations."""

from __future__ import annotations

import calendar
import sqlite3

from .base import BaseRepository


class PeriodsRepository(BaseRepository):
    """Database access for accounting periods."""

    # ── Queries ────────────────────────────────────────────────────────

    def get_period_for_date(self, entry_date: str) -> sqlite3.Row | None:
        """Return the accounting period row covering a posting date."""
        return self.conn.execute(
            """
            SELECT id, is_closed
            FROM accounting_periods
            WHERE ? BETWEEN start_date AND end_date
            """,
            (entry_date,),
        ).fetchone()

    def list_periods(self) -> list[sqlite3.Row]:
        """Return all periods ordered newest-first."""
        return list(
            self.conn.execute(
                """
                SELECT id, period_name, start_date, end_date,
                       fiscal_year, fiscal_period, is_closed, closed_at
                FROM accounting_periods
                ORDER BY start_date DESC
                """
            ).fetchall()
        )

    def get_period(self, period_id: int) -> sqlite3.Row | None:
        """Return one period row or None."""
        return self.conn.execute(
            """
            SELECT id, period_name, start_date, end_date,
                   fiscal_year, fiscal_period, is_closed, closed_at
            FROM accounting_periods WHERE id = ?
            """,
            (period_id,),
        ).fetchone()

    def period_name_exists(
        self, period_name: str, *, exclude_id: int | None = None
    ) -> bool:
        """Return True if period_name is already taken."""
        if exclude_id is not None:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM accounting_periods WHERE period_name = ? AND id != ?",
                (period_name, exclude_id),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM accounting_periods WHERE period_name = ?",
                (period_name,),
            ).fetchone()
        return int(row[0]) > 0

    def fiscal_year_exists(self, fiscal_year: int) -> bool:
        """Return True if any periods exist for this fiscal year."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM accounting_periods WHERE fiscal_year = ?",
            (fiscal_year,),
        ).fetchone()
        return int(row[0]) > 0

    def has_journal_entries(self, period_id: int) -> bool:
        """Return True if any journal entries are posted to this period."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM journal_entries WHERE accounting_period_id = ? LIMIT 1",
            (period_id,),
        ).fetchone()
        return int(row[0]) > 0

    # ── Mutations ──────────────────────────────────────────────────────

    def insert_period(
        self,
        *,
        period_name: str,
        start_date: str,
        end_date: str,
        fiscal_year: int,
        fiscal_period: int,
    ) -> int:
        """Insert a new accounting period and return its id."""
        cur = self.conn.execute(
            """
            INSERT INTO accounting_periods
                (period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (period_name, start_date, end_date, fiscal_year, fiscal_period),
        )
        return cur.lastrowid  # type: ignore[return-value]

    def generate_year(self, fiscal_year: int) -> list[int]:
        """Insert 12 monthly periods for fiscal_year; return list of new ids."""
        ids: list[int] = []
        for month in range(1, 13):
            _, last_day = calendar.monthrange(fiscal_year, month)
            start_date = f"{fiscal_year:04d}-{month:02d}-01"
            end_date = f"{fiscal_year:04d}-{month:02d}-{last_day:02d}"
            period_name = f"{fiscal_year:04d}-{month:02d}"
            cur = self.conn.execute(
                """
                INSERT INTO accounting_periods
                    (period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (period_name, start_date, end_date, fiscal_year, month),
            )
            ids.append(int(cur.lastrowid))
        return ids

    def close_period(self, period_id: int, closed_at: str) -> None:
        """Mark a period as closed."""
        self.conn.execute(
            """
            UPDATE accounting_periods
               SET is_closed = 1, closed_at = ?
             WHERE id = ?
            """,
            (closed_at, period_id),
        )

    def reopen_period(self, period_id: int) -> None:
        """Reopen a closed period (for corrections)."""
        self.conn.execute(
            """
            UPDATE accounting_periods
               SET is_closed = 0, closed_at = NULL
             WHERE id = ?
            """,
            (period_id,),
        )

    def delete_period(self, period_id: int) -> None:
        """Hard-delete a period with no journal entries."""
        self.conn.execute(
            "DELETE FROM accounting_periods WHERE id = ?", (period_id,)
        )
