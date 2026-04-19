"""Homeowner contact list report — owners and current renters by lot."""

from __future__ import annotations

import sqlite3

from hoa_accounting.reporting.dto import HomeownerContactListReport, HomeownerContactRow


class HomeownerContactListReportService:
    """Produce a directory of active owners and current renters by lot."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def generate(self, *, sort_by: str = "name") -> HomeownerContactListReport:
        if sort_by == "address":
            order_clause = "address, sort_name, first_name"
        else:
            order_clause = "sort_name, first_name"

        rows = self.conn.execute(
            f"""
            SELECT
                'OWNER'                           AS role,
                COALESCE(o.first_name, '')        AS first_name,
                COALESCE(o.last_name, '')         AS last_name,
                COALESCE(o.mailing_address_1, '') AS address,
                COALESCE(o.phone, '')             AS cell_phone,
                COALESCE(o.home_phone, '')        AS home_phone,
                COALESCE(o.email, '')             AS email,
                o.last_name AS sort_name
            FROM owners o
            WHERE o.active_flag = 1

            UNION ALL

            SELECT
                'RENTER'                          AS role,
                COALESCE(lr.first_name, '')       AS first_name,
                COALESCE(lr.last_name, '')        AS last_name,
                COALESCE(l.street_address_1, '')  AS address,
                COALESCE(lr.phone, '')            AS cell_phone,
                ''                                AS home_phone,
                COALESCE(lr.email, '')            AS email,
                lr.last_name AS sort_name
            FROM lot_renters lr
            JOIN lots l ON l.id = lr.lot_id
            WHERE lr.end_date IS NULL

            ORDER BY {order_clause}
            """
        ).fetchall()

        report_rows = [
            HomeownerContactRow(
                role=str(row["role"]),
                first_name=str(row["first_name"]),
                last_name=str(row["last_name"]),
                address=str(row["address"]),
                cell_phone=str(row["cell_phone"]),
                home_phone=str(row["home_phone"]),
                email=str(row["email"]),
            )
            for row in rows
        ]

        return HomeownerContactListReport(rows=report_rows)
