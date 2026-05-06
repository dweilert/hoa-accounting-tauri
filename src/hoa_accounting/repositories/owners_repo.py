"""Repository for owner lookups."""

from __future__ import annotations

import sqlite3

from .base import BaseRepository


class OwnersRepository(BaseRepository):
    """Database access for owners."""

    def list_owners_with_lots(self) -> list[sqlite3.Row]:
        """Return all active owners with a comma-separated list of current lots.

        Each row is one owner; lot_numbers is a comma-separated string of the
        lot numbers the owner currently holds (empty string if none).
        """
        return list(self.conn.execute("""
                SELECT o.id, o.owner_type, o.display_name, o.first_name,
                       o.last_name, o.entity_name, o.email, o.phone,
                       o.active_flag,
                       COALESCE((
                           SELECT GROUP_CONCAT(l.lot_number, ', ')
                           FROM lot_ownership lo
                           JOIN lots l ON l.id = lo.lot_id
                           WHERE lo.owner_id = o.id AND lo.end_date IS NULL
                       ), '') AS lot_numbers
                FROM owners o
                WHERE o.active_flag = 1
                ORDER BY o.last_name COLLATE NOCASE, o.first_name COLLATE NOCASE
                """).fetchall())

    def get_owner(self, owner_id: int) -> sqlite3.Row | None:
        """Return a single owner row by id, or None."""
        return self.conn.execute(  # type: ignore[no-any-return]
            """
            SELECT id, owner_type, display_name, first_name, last_name,
                   entity_name, email, phone, home_phone,
                   mailing_address_1, mailing_address_2,
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
        home_phone: str | None,
        notes: str | None,
    ) -> int:
        """Insert a new owner and return its id."""
        cur = self.conn.execute(
            """
            INSERT INTO owners
                (owner_type, display_name, first_name, last_name,
                 entity_name, email, phone, home_phone, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner_type,
                display_name,
                first_name,
                last_name,
                entity_name,
                email,
                phone,
                home_phone,
                notes,
            ),
        )
        return int(cur.lastrowid or 0)

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
        home_phone: str | None,
        notes: str | None,
    ) -> None:
        """Update editable fields on an existing owner."""
        self.conn.execute(
            """
            UPDATE owners
               SET owner_type = ?, display_name = ?, first_name = ?,
                   last_name = ?, entity_name = ?, email = ?, phone = ?,
                   home_phone = ?, notes = ?
             WHERE id = ?
            """,
            (
                owner_type,
                display_name,
                first_name,
                last_name,
                entity_name,
                email,
                phone,
                home_phone,
                notes,
                owner_id,
            ),
        )

    def has_current_lot(self, owner_id: int) -> bool:
        """Return True if the owner has a current (end_date IS NULL) lot assignment."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM lot_ownership WHERE owner_id = ? AND end_date IS NULL",
            (owner_id,),
        ).fetchone()
        return int(row[0]) > 0

    def deactivate_owner(self, owner_id: int) -> None:
        """Soft-delete an owner by setting active_flag = 0.

        Financial history (payments, assessments, journal entries) is
        intentionally preserved — posted accounting records must never be
        deleted. Any open lot-ownership records are ended as of today so
        the lot is no longer associated with this owner going forward.
        """
        today = __import__("datetime").date.today().isoformat()
        # End any open lot-ownership records rather than deleting them.
        self.conn.execute(
            "UPDATE lot_ownership SET end_date = ? WHERE owner_id = ? AND end_date IS NULL",
            (today, owner_id),
        )
        self.conn.execute(
            "UPDATE owners SET active_flag = 0 WHERE id = ?",
            (owner_id,),
        )

    def list_owners(self, *, active_only: bool = True) -> list[sqlite3.Row]:
        """Return owners for a master-data list page."""
        predicates = []
        if active_only:
            predicates.append("active_flag = 1")
        where_sql = f"WHERE {' AND '.join(predicates)}" if predicates else ""
        return list(self.conn.execute(f"""
                SELECT id, owner_type, display_name, first_name, last_name,
                       entity_name, email, phone,
                       city, state, postal_code, active_flag
                FROM owners
                {where_sql}
                ORDER BY last_name COLLATE NOCASE, first_name COLLATE NOCASE
                """).fetchall())
