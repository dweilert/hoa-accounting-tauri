"""Repository for accounting period lookups."""

from __future__ import annotations

from .base import BaseRepository


class PeriodsRepository(BaseRepository):
    """Database access for accounting periods."""

    def get_period_for_date(self, entry_date: str):
        """Return the accounting period row covering a posting date."""
        return self.conn.execute(
            """
            SELECT id, is_closed
            FROM accounting_periods
            WHERE ? BETWEEN start_date AND end_date
            """,
            (entry_date,),
        ).fetchone()
