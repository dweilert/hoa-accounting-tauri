"""Expenses by date report — vendor bills in chronological order."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.reporting.dto import ExpensesByDateReport, ExpensesByDateRow
from hoa_accounting.validators.common import q2


class ExpensesByDateReportService:
    """Produce a chronological list of vendor bill expenses."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def generate(self, *, from_date: str, to_date: str) -> ExpensesByDateReport:
        rows = self.conn.execute(
            """
            SELECT
                vb.invoice_date AS entry_date,
                vb.invoice_number AS entry_number,
                COALESCE(c.code, '') AS account_number,
                COALESCE(c.name, COALESCE(vb.description, '')) AS account_name,
                COALESCE(c.group_name, '') AS group_code,
                vb.fund_code,
                COALESCE(vb.description, '') AS memo,
                vb.amount AS net_amount
            FROM vendor_bills vb
            LEFT JOIN categories c ON c.id = vb.category_id
            WHERE vb.status != 'VOID'
              AND vb.invoice_date >= ?
              AND vb.invoice_date <= ?
            ORDER BY vb.invoice_date, vb.invoice_number
            """,
            (from_date, to_date),
        ).fetchall()

        report_rows: list[ExpensesByDateRow] = []
        grand_total = Decimal("0.00")

        for row in rows:
            amount = q2(row["net_amount"])
            grand_total += amount
            report_rows.append(
                ExpensesByDateRow(
                    entry_date=str(row["entry_date"]),
                    entry_number=str(row["entry_number"]),
                    account_number=str(row["account_number"]),
                    account_name=str(row["account_name"]),
                    group_code=str(row["group_code"]),
                    fund_code=str(row["fund_code"]),
                    memo=str(row["memo"]),
                    amount=amount,
                )
            )

        return ExpensesByDateReport(
            from_date=from_date,
            to_date=to_date,
            rows=report_rows,
            grand_total=q2(grand_total),
        )
