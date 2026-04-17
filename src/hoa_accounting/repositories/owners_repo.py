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

    def has_current_lot(self, owner_id: int) -> bool:
        """Return True if the owner has a current (end_date IS NULL) lot assignment."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM lot_ownership WHERE owner_id = ? AND end_date IS NULL",
            (owner_id,),
        ).fetchone()
        return int(row[0]) > 0

    def delete_owner(self, owner_id: int) -> None:
        """Hard-delete an owner and all related records (for test data cleanup).

        Cascade order:
          payment_applications  (cascade from payments)
          payments              -> journal entries collected below
          assessments           -> journal entries collected below
          owner_adjustments     -> journal entries collected below
          journal_entry_lines   (NULL out nullable owner_id on shared entries)
          journal_entries       (dedicated 1-to-1 entries from above)
          lot_ownership
          owners
        """
        # Collect the dedicated journal entry IDs before deleting records
        je_rows = self.conn.execute(
            """
            SELECT journal_entry_id FROM assessments     WHERE owner_id = ?
            UNION ALL
            SELECT journal_entry_id FROM payments        WHERE owner_id = ?
            UNION ALL
            SELECT journal_entry_id FROM owner_adjustments WHERE owner_id = ?
            """,
            (owner_id, owner_id, owner_id),
        ).fetchall()
        je_ids = [row[0] for row in je_rows]

        # payment_applications cascade automatically from payments, but be explicit
        self.conn.execute(
            "DELETE FROM payment_applications "
            "WHERE payment_id IN (SELECT id FROM payments WHERE owner_id = ?)",
            (owner_id,),
        )
        self.conn.execute("DELETE FROM payments         WHERE owner_id = ?", (owner_id,))
        self.conn.execute("DELETE FROM assessments      WHERE owner_id = ?", (owner_id,))
        self.conn.execute("DELETE FROM owner_adjustments WHERE owner_id = ?", (owner_id,))

        # NULL out owner_id on any shared journal entry lines that still reference this owner
        self.conn.execute(
            "UPDATE journal_entry_lines SET owner_id = NULL WHERE owner_id = ?",
            (owner_id,),
        )

        # Delete the 1-to-1 journal entries (journal_entry_lines cascade from these)
        if je_ids:
            placeholders = ",".join("?" * len(je_ids))
            self.conn.execute(
                f"DELETE FROM journal_entries WHERE id IN ({placeholders})", je_ids
            )

        self.conn.execute("DELETE FROM lot_ownership WHERE owner_id = ?", (owner_id,))
        self.conn.execute("DELETE FROM owners WHERE id = ?", (owner_id,))

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
