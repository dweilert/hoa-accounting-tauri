"""Vendor expenses report — vendor bills grouped by vendor."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.reporting.dto import VendorExpensesReport, VendorExpensesRow
from hoa_accounting.validators.common import q2


class VendorExpensesReportService:
    """Produce a vendor expenses report for a date range.

    Reads directly from vendor_bills (single-entry). When vendor_id is None
    all vendors are included.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def generate(
        self,
        *,
        from_date: str,
        to_date: str,
        vendor_id: int | None = None,
    ) -> VendorExpensesReport:
        conditions = [
            "vb.invoice_date >= ?",
            "vb.invoice_date <= ?",
            "vb.status != 'VOID'",
        ]
        params: list[object] = [from_date, to_date]

        if vendor_id is not None:
            conditions.append("vb.vendor_id = ?")
            params.append(vendor_id)

        where_sql = " AND ".join(conditions)

        rows = self.conn.execute(
            f"""
            SELECT
                COALESCE(v.vendor_name, '(No Vendor)') AS vendor_name,
                vb.invoice_date AS entry_date,
                vb.invoice_number AS entry_number,
                COALESCE(c.code, '') AS account_number,
                COALESCE(c.name, COALESCE(vb.description, '')) AS account_name,
                COALESCE(c.group_name, '') AS group_code,
                COALESCE(vb.description, '') AS memo,
                vb.amount AS net_amount
            FROM vendor_bills vb
            LEFT JOIN vendors v ON v.id = vb.vendor_id
            LEFT JOIN categories c ON c.id = vb.category_id
            WHERE {where_sql}
            ORDER BY v.vendor_name, vb.invoice_date, vb.invoice_number
            """,
            params,
        ).fetchall()

        report_rows: list[VendorExpensesRow] = []
        grand_total = Decimal("0.00")

        for row in rows:
            amount = q2(row["net_amount"])
            grand_total += amount
            report_rows.append(
                VendorExpensesRow(
                    vendor_name=str(row["vendor_name"]),
                    entry_date=str(row["entry_date"]),
                    entry_number=str(row["entry_number"]),
                    account_number=str(row["account_number"]),
                    account_name=str(row["account_name"]),
                    group_code=str(row["group_code"]),
                    memo=str(row["memo"]),
                    amount=amount,
                )
            )

        resolved_vendor_name: str | None = None
        if vendor_id is not None:
            vendor_row = self.conn.execute(
                "SELECT vendor_name FROM vendors WHERE id = ?", (vendor_id,)
            ).fetchone()
            if vendor_row:
                resolved_vendor_name = str(vendor_row["vendor_name"])

        return VendorExpensesReport(
            from_date=from_date,
            to_date=to_date,
            vendor_id=vendor_id,
            vendor_name=resolved_vendor_name,
            rows=report_rows,
            grand_total=q2(grand_total),
        )
