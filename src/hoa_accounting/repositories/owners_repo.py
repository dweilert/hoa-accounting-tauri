"""Repository for owner lookups."""

from __future__ import annotations

import sqlite3

from .base import BaseRepository


class OwnersRepository(BaseRepository):
    """Database access for owners."""

    def list_owners(self, *, active_only: bool = True) -> list[sqlite3.Row]:
        """Return owners for a master-data list page."""
        predicates = []
        if active_only:
            predicates.append("active_flag = 1")
        where_sql = f"WHERE {' AND '.join(predicates)}" if predicates else ""
        return list(
            self.conn.execute(
                f"""
                SELECT id, owner_type, display_name, first_name, last_name,
                       entity_name, email, phone,
                       city, state, postal_code, active_flag
                FROM owners
                {where_sql}
                ORDER BY display_name COLLATE NOCASE
                """
            ).fetchall()
        )
