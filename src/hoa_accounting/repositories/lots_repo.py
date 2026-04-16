"""Repository for lot lookups."""

from __future__ import annotations

import sqlite3

from .base import BaseRepository


class LotsRepository(BaseRepository):
    """Database access for lots and their current owners."""

    def list_lots(self, *, active_only: bool = True) -> list[sqlite3.Row]:
        """Return lots with their current primary-contact owner, if any.

        Joins ``lot_ownership`` on ``end_date IS NULL`` (still held) and
        ``is_primary_contact = 1`` so each row shows who you'd contact for
        that lot. A lot with no current primary owner still appears.
        """
        predicates = []
        if active_only:
            predicates.append("l.active_flag = 1")
        where_sql = f"WHERE {' AND '.join(predicates)}" if predicates else ""
        return list(
            self.conn.execute(
                f"""
                SELECT
                    l.id,
                    l.lot_number,
                    l.street_address_1,
                    l.street_address_2,
                    l.city,
                    l.state,
                    l.postal_code,
                    l.active_flag,
                    o.id AS owner_id,
                    o.display_name AS owner_name
                FROM lots l
                LEFT JOIN lot_ownership lo
                  ON lo.lot_id = l.id
                 AND lo.end_date IS NULL
                 AND lo.is_primary_contact = 1
                LEFT JOIN owners o
                  ON o.id = lo.owner_id
                {where_sql}
                ORDER BY l.lot_number COLLATE NOCASE
                """
            ).fetchall()
        )
