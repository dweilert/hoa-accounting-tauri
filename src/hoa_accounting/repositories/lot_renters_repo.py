"""Repository for lot renters."""

from __future__ import annotations

import sqlite3

from .base import BaseRepository


class LotRentersRepository(BaseRepository):
    """Database access for current and historical renters on a lot."""

    def insert_renter(
        self,
        *,
        lot_id: int,
        display_name: str,
        first_name: str | None,
        last_name: str | None,
        email: str | None,
        phone: str | None,
        start_date: str,
        end_date: str | None = None,
        is_primary_contact: bool = True,
        notes: str | None = None,
    ) -> int:
        """Insert a renter row for a lot and return its id."""
        cur = self.conn.execute(
            """
            INSERT INTO lot_renters (
                lot_id, display_name, first_name, last_name,
                email, phone, start_date, end_date,
                is_primary_contact, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lot_id,
                display_name,
                first_name,
                last_name,
                email,
                phone,
                start_date,
                end_date,
                1 if is_primary_contact else 0,
                notes,
            ),
        )
        return int(cur.lastrowid)

    def end_tenancy(self, *, renter_id: int, end_date: str) -> None:
        """Close out a current renter row when a tenant moves out."""
        self.conn.execute(
            "UPDATE lot_renters SET end_date = ? WHERE id = ?",
            (end_date, renter_id),
        )

    def get_current_renters(self, lot_id: int) -> list[sqlite3.Row]:
        """Return all renters currently living at a lot (end_date IS NULL).

        Primary-contact renter is ordered first so callers that only
        want the lead renter can take row[0].
        """
        return list(
            self.conn.execute(
                """
                SELECT id, lot_id, display_name, first_name, last_name,
                       email, phone, start_date, end_date,
                       is_primary_contact, notes
                FROM lot_renters
                WHERE lot_id = ?
                  AND end_date IS NULL
                ORDER BY is_primary_contact DESC, start_date DESC, id DESC
                """,
                (lot_id,),
            ).fetchall()
        )

    def list_all_renters(self) -> list[sqlite3.Row]:
        """Return every renter row joined to its lot, current renters first.

        Columns: all lot_renters fields plus lot_number and street_address_1
        from the lots table. Within each group (current / ended), ordered by
        lot_number then start_date descending.
        """
        return list(
            self.conn.execute(
                """
                SELECT
                    r.id, r.lot_id, r.display_name, r.first_name, r.last_name,
                    r.email, r.phone, r.start_date, r.end_date, r.notes,
                    CASE WHEN r.end_date IS NULL THEN 1 ELSE 0 END AS is_current,
                    l.lot_number, l.street_address_1
                FROM lot_renters r
                JOIN lots l ON l.id = r.lot_id
                ORDER BY
                    CASE WHEN r.end_date IS NULL THEN 0 ELSE 1 END,
                    l.lot_number COLLATE NOCASE,
                    r.start_date DESC,
                    r.id DESC
                """
            ).fetchall()
        )

    def get_renter(self, renter_id: int) -> sqlite3.Row | None:
        """Return a single renter row by id, or None."""
        return self.conn.execute(
            """
            SELECT
                r.id, r.lot_id, r.display_name, r.first_name, r.last_name,
                r.email, r.phone, r.start_date, r.end_date, r.notes,
                CASE WHEN r.end_date IS NULL THEN 1 ELSE 0 END AS is_current,
                l.lot_number, l.street_address_1
            FROM lot_renters r
            JOIN lots l ON l.id = r.lot_id
            WHERE r.id = ?
            """,
            (renter_id,),
        ).fetchone()

    def update_renter(
        self,
        *,
        renter_id: int,
        lot_id: int,
        display_name: str,
        first_name: str | None,
        last_name: str | None,
        email: str | None,
        phone: str | None,
        start_date: str,
        notes: str | None,
    ) -> None:
        """Update editable fields on an existing renter row."""
        self.conn.execute(
            """
            UPDATE lot_renters
               SET lot_id = ?, display_name = ?, first_name = ?, last_name = ?,
                   email = ?, phone = ?, start_date = ?, notes = ?
             WHERE id = ?
            """,
            (
                lot_id, display_name, first_name, last_name,
                email, phone, start_date, notes, renter_id,
            ),
        )

    def list_renter_history(self, lot_id: int) -> list[sqlite3.Row]:
        """Return every renter (past + current) for a lot, newest first."""
        return list(
            self.conn.execute(
                """
                SELECT id, lot_id, display_name, first_name, last_name,
                       email, phone, start_date, end_date,
                       is_primary_contact, notes
                FROM lot_renters
                WHERE lot_id = ?
                ORDER BY COALESCE(end_date, '9999-12-31') DESC,
                         start_date DESC,
                         id DESC
                """,
                (lot_id,),
            ).fetchall()
        )
