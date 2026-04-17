"""Repository for owner lookups."""

from __future__ import annotations

import sqlite3

from .base import BaseRepository


class OwnersRepository(BaseRepository):
    """Database access for owners."""

    def list_owners_with_lots(self) -> list[sqlite3.Row]:
        """Return all active owners joined to their current lot assignment.

        Columns include the lot_ownership id (for Mark as Previous), lot_number,
        is_primary_contact (role), and ownership start_date. Owners with no
        current lot show NULL for the ownership fields.
        """
        return list(
            self.conn.execute(
                """
                SELECT o.id, o.owner_type, o.display_name, o.first_name,
                       o.last_name, o.entity_name, o.email, o.phone,
                       o.active_flag,
                       lo.id AS ownership_id,
                       lo.lot_id, lo.start_date AS ownership_start,
                       lo.is_primary_contact,
                       l.lot_number, l.street_address_1
                FROM owners o
                LEFT JOIN lot_ownership lo
                  ON lo.owner_id = o.id AND lo.end_date IS NULL
                LEFT JOIN lots l ON l.id = lo.lot_id
                WHERE o.active_flag = 1
                ORDER BY o.display_name COLLATE NOCASE
                """
            ).fetchall()
        )

    def get_owner(self, owner_id: int) -> sqlite3.Row | None:
        """Return a single owner row by id, or None."""
        return self.conn.execute(
            """
            SELECT id, owner_type, display_name, first_name, last_name,
                   entity_name, email, phone, mailing_address_1, mailing_address_2,
                   city, state, postal_code, notes, active_flag
            FROM owners WHERE id = ?
            """,
            (owner_id,),
        ).fetchone()

    def insert_owner(
        self,
        *,
        owner_type: str,
        display_name: str,
        first_name: str | None,
        last_name: str | None,
        entity_name: str | None,
        email: str | None,
        phone: str | None,
        notes: str | None,
    ) -> int:
        """Insert a new owner and return its id."""
        cur = self.conn.execute(
            """
            INSERT INTO owners
                (owner_type, display_name, first_name, last_name,
                 entity_name, email, phone, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (owner_type, display_name, first_name, last_name,
             entity_name, email, phone, notes),
        )
        return int(cur.lastrowid)

    def update_owner(
        self,
        *,
        owner_id: int,
        owner_type: str,
        display_name: str,
        first_name: str | None,
        last_name: str | None,
        entity_name: str | None,
        email: str | None,
        phone: str | None,
        notes: str | None,
    ) -> None:
        """Update editable fields on an existing owner."""
        self.conn.execute(
            """
            UPDATE owners
               SET owner_type = ?, display_name = ?, first_name = ?,
                   last_name = ?, entity_name = ?, email = ?, phone = ?,
                   notes = ?
             WHERE id = ?
            """,
            (owner_type, display_name, first_name, last_name,
             entity_name, email, phone, notes, owner_id),
        )

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
