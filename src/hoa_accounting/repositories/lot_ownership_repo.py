"""Repository for lot ownership records."""

from __future__ import annotations

import sqlite3

from .base import BaseRepository


class LotOwnershipRepository(BaseRepository):
    """Database access for lot ownership — linking owners to lots."""

    def get_current_ownerships(self, lot_id: int) -> list[sqlite3.Row]:
        """Return current (end_date IS NULL) ownership rows for a lot.

        Primary contact (Owner 1) ordered first.
        """
        return list(
            self.conn.execute(
                """
                SELECT lo.id, lo.lot_id, lo.owner_id, lo.start_date,
                       lo.end_date, lo.ownership_percent, lo.is_primary_contact,
                       o.display_name AS owner_name, o.email, o.phone
                FROM lot_ownership lo
                JOIN owners o ON o.id = lo.owner_id
                WHERE lo.lot_id = ?
                  AND lo.end_date IS NULL
                ORDER BY lo.is_primary_contact DESC, lo.start_date, lo.id
                """,
                (lot_id,),
            ).fetchall()
        )

    def get_current_ownership_by_owner(
        self, owner_id: int
    ) -> sqlite3.Row | None:
        """Return the current lot_ownership row for an owner, or None."""
        return self.conn.execute(
            """
            SELECT lo.id, lo.lot_id, lo.owner_id, lo.start_date,
                   lo.end_date, lo.is_primary_contact,
                   l.lot_number, l.street_address_1
            FROM lot_ownership lo
            JOIN lots l ON l.id = lo.lot_id
            WHERE lo.owner_id = ?
              AND lo.end_date IS NULL
            ORDER BY lo.start_date DESC
            LIMIT 1
            """,
            (owner_id,),
        ).fetchone()

    def count_current_owners(self, lot_id: int) -> int:
        """Return number of current (end_date IS NULL) owners on a lot."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM lot_ownership WHERE lot_id = ? AND end_date IS NULL",
            (lot_id,),
        ).fetchone()
        return int(row[0])

    def has_current_primary(self, lot_id: int) -> bool:
        """Return True if the lot already has a current primary-contact owner."""
        row = self.conn.execute(
            """
            SELECT COUNT(*) FROM lot_ownership
            WHERE lot_id = ? AND end_date IS NULL AND is_primary_contact = 1
            """,
            (lot_id,),
        ).fetchone()
        return int(row[0]) > 0

    def assign_owner(
        self,
        *,
        lot_id: int,
        owner_id: int,
        start_date: str,
        is_primary_contact: bool,
    ) -> int:
        """Insert a lot_ownership row and return its id."""
        cur = self.conn.execute(
            """
            INSERT INTO lot_ownership
                (lot_id, owner_id, start_date, ownership_percent, is_primary_contact)
            VALUES (?, ?, ?, 100.0, ?)
            """,
            (lot_id, owner_id, start_date, 1 if is_primary_contact else 0),
        )
        return int(cur.lastrowid)

    def end_ownership(self, *, ownership_id: int, end_date: str) -> None:
        """Set end_date on a lot_ownership row (mark as previous owner)."""
        self.conn.execute(
            "UPDATE lot_ownership SET end_date = ? WHERE id = ?",
            (end_date, ownership_id),
        )
