"""Vendor expenses report — expense lines grouped by vendor."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.reporting.dto import VendorExpensesReport, VendorExpensesRow
from hoa_accounting.validators.common import q2


class VendorExpensesReportService:
    """Produce a vendor expenses report for a date range.

    When ``vendor_id`` is ``None`` all vendors are included.
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
            "je.status IN ('POSTED', 'REVERSED')",
            "at.code = 'EXPENSE'",
            "je.entry_date >= ?",
            "je.entry_date <= ?",
        ]
        params: list[object] = [from_date, to_date]

        if vendor_id is not None:
            conditions.append("jel.vendor_id = ?")
            params.append(vendor_id)

        where_sql = " AND ".join(conditions)

        rows = self.conn.execute(
            f"""
            SELECT
                COALESCE(v.vendor_name, '(No Vendor)') AS vendor_name,
                je.entry_date,
                je.entry_number,
                a.account_number,
                a.account_name,
                COALESCE(a.group_code, '') AS group_code,
                COALESCE(je.memo, COALESCE(jel.description, '')) AS memo,
                COALESCE(jel.debit_amount, 0) - COALESCE(jel.credit_amount, 0) AS net_amount
            FROM journal_entry_lines jel
            JOIN journal_entries je ON je.id = jel.journal_entry_id
            JOIN accounts a ON a.id = jel.account_id
            JOIN account_types at ON at.id = a.account_type_id
            LEFT JOIN vendors v ON v.id = jel.vendor_id
            WHERE {where_sql}
            ORDER BY v.vendor_name, je.entry_date, je.entry_number, jel.line_number
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

        # Resolve vendor name for report header when a specific vendor was requested
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
