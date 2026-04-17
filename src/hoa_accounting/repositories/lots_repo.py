"""Repository for lot lookups."""

from __future__ import annotations

import sqlite3

from .base import BaseRepository


class LotsRepository(BaseRepository):
    """Database access for lots and their current owners."""

    def get_current_owner_id(self, lot_id: int) -> int | None:
        """Return the owner_id of the lot's current primary contact, or None.

        A lot with no open (end_date IS NULL) primary-contact ownership
        returns None — the batch-entry service treats that as a blocker
        since the payment needs a real owner to credit AR on.
        """
        row = self.conn.execute(
            """
            SELECT owner_id FROM lot_ownership
            WHERE lot_id = ?
              AND end_date IS NULL
              AND is_primary_contact = 1
            ORDER BY start_date DESC
            LIMIT 1
            """,
            (lot_id,),
        ).fetchone()
        return int(row["owner_id"]) if row else None

    def list_lots_with_ytd_assessments(
        self,
        *,
        from_date: str,
        to_date: str,
    ) -> list[sqlite3.Row]:
        """Active lots with YTD billed / paid / balance assessment totals.

        Billed = sum of ``assessments.amount`` for the lot's assessments
        dated in the range.
        Paid = sum of ``payment_applications.applied_amount`` tied to
        those same assessments.
        Balance = Billed − Paid.

        Zero totals show when a lot had no assessment activity. Lots
        with no current primary-contact owner still appear — the
        billing UI renders their row, and the billing service rejects
        them at post time.
        """
        return list(
            self.conn.execute(
                """
                SELECT
                    l.id AS lot_id,
                    l.lot_number,
                    l.street_address_1,
                    l.active_flag,
                    o.id AS owner_id,
                    o.display_name AS owner_name,
                    COALESCE((
                        SELECT SUM(a.amount)
                        FROM assessments a
                        WHERE a.lot_id = l.id
                          AND a.assessment_date >= ?
                          AND a.assessment_date <= ?
                          AND a.status != 'VOID'
                    ), 0) AS ytd_billed,
                    COALESCE((
                        SELECT SUM(pa.applied_amount)
                        FROM payment_applications pa
                        JOIN assessments a ON a.id = pa.assessment_id
                        WHERE a.lot_id = l.id
                          AND a.assessment_date >= ?
                          AND a.assessment_date <= ?
                          AND a.status != 'VOID'
                    ), 0) AS ytd_paid
                FROM lots l
                LEFT JOIN lot_ownership lo
                  ON lo.lot_id = l.id
                 AND lo.end_date IS NULL
                 AND lo.is_primary_contact = 1
                LEFT JOIN owners o
                  ON o.id = lo.owner_id
                WHERE l.active_flag = 1
                ORDER BY l.lot_number COLLATE NOCASE
                """,
                (from_date, to_date, from_date, to_date),
            ).fetchall()
        )

    def list_lots_with_occupancy(
        self, *, active_only: bool = True
    ) -> list[sqlite3.Row]:
        """Lots joined to current primary owner AND current primary renter.

        Per-row columns:
          - lot fields + owner_id/owner_name (primary contact, same as
            list_lots)
          - renter_id / renter_name / renter_email / renter_phone —
            the lot's current primary-contact renter (NULL for owner-
            occupied lots)
          - is_owner_occupied — derived: 1 when no current renter, 0
            when a renter is present. Simpler for callers than
            computing from NULL-ness of renter_id.
        """
        predicates = []
        if active_only:
            predicates.append("l.active_flag = 1")
        where_sql = f"WHERE {' AND '.join(predicates)}" if predicates else ""
        return list(
            self.conn.execute(
                f"""
                SELECT
                    l.id AS lot_id,
                    l.lot_number,
                    l.street_address_1,
                    l.street_address_2,
                    l.city,
                    l.state,
                    l.postal_code,
                    l.active_flag,
                    o.id AS owner_id,
                    o.display_name AS owner_name,
                    o2.id AS owner2_id,
                    o2.display_name AS owner2_name,
                    r.id AS renter_id,
                    r.display_name AS renter_name,
                    r.email AS renter_email,
                    r.phone AS renter_phone,
                    CASE WHEN r.id IS NULL THEN 1 ELSE 0 END AS is_owner_occupied
                FROM lots l
                LEFT JOIN lot_ownership lo
                  ON lo.lot_id = l.id
                 AND lo.end_date IS NULL
                 AND lo.is_primary_contact = 1
                LEFT JOIN owners o
                  ON o.id = lo.owner_id
                LEFT JOIN lot_ownership lo2
                  ON lo2.lot_id = l.id
                 AND lo2.end_date IS NULL
                 AND lo2.is_primary_contact = 0
                LEFT JOIN owners o2
                  ON o2.id = lo2.owner_id
                LEFT JOIN lot_renters r
                  ON r.lot_id = l.id
                 AND r.end_date IS NULL
                 AND r.is_primary_contact = 1
                {where_sql}
                ORDER BY l.lot_number COLLATE NOCASE
                """
            ).fetchall()
        )

    def get_lot_with_owner(self, lot_id: int) -> sqlite3.Row | None:
        """Return a single lot with its current primary-contact owner, or None."""
        return self.conn.execute(
            """
            SELECT
                l.id AS lot_id,
                l.lot_number,
                l.street_address_1,
                l.street_address_2,
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
            WHERE l.id = ?
            """,
            (lot_id,),
        ).fetchone()

    def get_lot(self, lot_id: int) -> sqlite3.Row | None:
        """Return a single lot row by id, or None."""
        return self.conn.execute(
            """
            SELECT id, lot_number, street_address_1, street_address_2,
                   city, state, postal_code, legal_description, active_flag
            FROM lots WHERE id = ?
            """,
            (lot_id,),
        ).fetchone()

    def insert_lot(
        self,
        *,
        lot_number: str,
        street_address_1: str | None,
        street_address_2: str | None,
        city: str | None,
        state: str | None,
        postal_code: str | None,
        legal_description: str | None,
    ) -> int:
        """Insert a new lot and return its id."""
        cur = self.conn.execute(
            """
            INSERT INTO lots
                (lot_number, street_address_1, street_address_2,
                 city, state, postal_code, legal_description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (lot_number, street_address_1, street_address_2,
             city, state, postal_code, legal_description),
        )
        return int(cur.lastrowid)

    def update_lot(
        self,
        *,
        lot_id: int,
        lot_number: str,
        street_address_1: str | None,
        street_address_2: str | None,
        city: str | None,
        state: str | None,
        postal_code: str | None,
        legal_description: str | None,
        active_flag: bool,
    ) -> None:
        """Update editable fields on an existing lot."""
        self.conn.execute(
            """
            UPDATE lots
               SET lot_number = ?, street_address_1 = ?, street_address_2 = ?,
                   city = ?, state = ?, postal_code = ?,
                   legal_description = ?, active_flag = ?,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (lot_number, street_address_1, street_address_2,
             city, state, postal_code, legal_description,
             1 if active_flag else 0, lot_id),
        )

    def has_current_owners(self, lot_id: int) -> bool:
        """Return True if the lot has any current (end_date IS NULL) owners."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM lot_ownership WHERE lot_id = ? AND end_date IS NULL",
            (lot_id,),
        ).fetchone()
        return int(row[0]) > 0

    def has_current_renters(self, lot_id: int) -> bool:
        """Return True if the lot has any current (end_date IS NULL) renters."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM lot_renters WHERE lot_id = ? AND end_date IS NULL",
            (lot_id,),
        ).fetchone()
        return int(row[0]) > 0

    def delete_lot(self, lot_id: int) -> None:
        """Hard-delete a lot and all its ownership and renter history."""
        self.conn.execute("DELETE FROM lot_ownership WHERE lot_id = ?", (lot_id,))
        self.conn.execute("DELETE FROM lot_renters WHERE lot_id = ?", (lot_id,))
        self.conn.execute("DELETE FROM lots WHERE id = ?", (lot_id,))

    def lot_number_exists(self, lot_number: str, *, exclude_id: int | None = None) -> bool:
        """Return True if lot_number is already taken by another lot."""
        if exclude_id is not None:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM lots WHERE lot_number = ? AND id != ?",
                (lot_number, exclude_id),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM lots WHERE lot_number = ?",
                (lot_number,),
            ).fetchone()
        return int(row[0]) > 0

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
