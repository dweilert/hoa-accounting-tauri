"""Repository for lot ownership records."""

from __future__ import annotations

import sqlite3

from .base import BaseRepository


class LotOwnershipRepository(BaseRepository):
    """Database access for lot ownership — linking owners to lots."""

    def get_current_ownerships(self, lot_id: int) -> list[sqlite3.Row]:
        """Return current (end_date IS NULL) ownership rows for a lot.

        Ordered by start_date ascending so the earliest owner is first —
        that is the owner used by billing/payment services.
        """
        return list(
            self.conn.execute(
                """
                SELECT lo.id, lo.lot_id, lo.owner_id, lo.start_date, lo.end_date,
                       o.display_name AS owner_name, o.email, o.phone
                FROM lot_ownership lo
                JOIN owners o ON o.id = lo.owner_id
                WHERE lo.lot_id = ?
                  AND lo.end_date IS NULL
                ORDER BY lo.start_date ASC, lo.id ASC
                """,
                (lot_id,),
            ).fetchall()
        )

    def get_all_ownerships(self, lot_id: int) -> list[sqlite3.Row]:
        """Return all ownership rows for a lot (current and historical)."""
        return list(
            self.conn.execute(
                """
                SELECT lo.id, lo.lot_id, lo.owner_id, lo.start_date, lo.end_date,
                       o.display_name AS owner_name, o.email, o.phone
                FROM lot_ownership lo
                JOIN owners o ON o.id = lo.owner_id
                WHERE lo.lot_id = ?
                ORDER BY lo.end_date IS NULL DESC,
                         lo.start_date ASC,
                         lo.id ASC
                """,
                (lot_id,),
            ).fetchall()
        )

    def get_ownership(self, ownership_id: int) -> sqlite3.Row | None:
        """Return a single ownership row by id, or None."""
        return self.conn.execute(
            """
            SELECT lo.id, lo.lot_id, lo.owner_id, lo.start_date, lo.end_date,
                   o.display_name AS owner_name,
                   l.lot_number
            FROM lot_ownership lo
            JOIN owners o ON o.id = lo.owner_id
            JOIN lots   l ON l.id = lo.lot_id
            WHERE lo.id = ?
            """,
            (ownership_id,),
        ).fetchone()

    def get_all_lots_for_owner(self, owner_id: int) -> list[sqlite3.Row]:
        """Return all lot_ownership rows for an owner (current and historical)."""
        return list(
            self.conn.execute(
                """
                SELECT lo.id, lo.lot_id, lo.owner_id, lo.start_date, lo.end_date,
                       l.lot_number, l.street_address_1
                FROM lot_ownership lo
                JOIN lots l ON l.id = lo.lot_id
                WHERE lo.owner_id = ?
                ORDER BY lo.end_date IS NULL DESC,
                         lo.start_date DESC,
                         lo.id DESC
                """,
                (owner_id,),
            ).fetchall()
        )

    def get_current_ownership_by_owner(
        self, owner_id: int
    ) -> sqlite3.Row | None:
        """Return the most recent current lot_ownership row for an owner, or None.

        An owner can have multiple current lots; this returns one for callers
        that only need to know if the owner is linked anywhere.
        """
        return self.conn.execute(
            """
            SELECT lo.id, lo.lot_id, lo.owner_id, lo.start_date, lo.end_date,
                   l.lot_number, l.street_address_1
            FROM lot_ownership lo
            JOIN lots l ON l.id = lo.lot_id
            WHERE lo.owner_id = ?
              AND lo.end_date IS NULL
            ORDER BY lo.start_date DESC, lo.id DESC
            LIMIT 1
            """,
            (owner_id,),
        ).fetchone()

    def owner_already_linked(self, lot_id: int, owner_id: int) -> bool:
        """Return True if the owner is already a current owner of this lot."""
        row = self.conn.execute(
            """
            SELECT COUNT(*) FROM lot_ownership
            WHERE lot_id = ? AND owner_id = ? AND end_date IS NULL
            """,
            (lot_id, owner_id),
        ).fetchone()
        return int(row[0]) > 0

    def assign_owner(
        self,
        *,
        lot_id: int,
        owner_id: int,
        start_date: str,
    ) -> int:
        """Insert a lot_ownership row and return its id."""
        cur = self.conn.execute(
            """
            INSERT INTO lot_ownership (lot_id, owner_id, start_date)
            VALUES (?, ?, ?)
            """,
            (lot_id, owner_id, start_date),
        )
        return int(cur.lastrowid)

    def update_ownership_dates(
        self,
        *,
        ownership_id: int,
        start_date: str,
        end_date: str | None,
    ) -> None:
        """Update the start and/or end date of an ownership record."""
        self.conn.execute(
            "UPDATE lot_ownership SET start_date = ?, end_date = ? WHERE id = ?",
            (start_date, end_date or None, ownership_id),
        )

    def end_ownership(self, *, ownership_id: int, end_date: str) -> None:
        """Set end_date on a lot_ownership row (mark as previous owner)."""
        self.conn.execute(
            "UPDATE lot_ownership SET end_date = ? WHERE id = ?",
            (end_date, ownership_id),
        )
