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
                LEFT JOIN lot_renters r
                  ON r.lot_id = l.id
                 AND r.end_date IS NULL
                 AND r.is_primary_contact = 1
                {where_sql}
                ORDER BY l.lot_number COLLATE NOCASE
                """
            ).fetchall()
        )

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
