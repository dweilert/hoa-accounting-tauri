"""Expenses by date report — all expense journal lines ordered by date."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.reporting.dto import ExpensesByDateReport, ExpensesByDateRow
from hoa_accounting.validators.common import q2


class ExpensesByDateReportService:
    """Produce a chronological list of expense journal entries."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def generate(self, *, from_date: str, to_date: str) -> ExpensesByDateReport:
        rows = self.conn.execute(
            """
            SELECT
                je.entry_date,
                je.entry_number,
                a.account_number,
                a.account_name,
                COALESCE(a.group_code, '') AS group_code,
                a.fund_code,
                COALESCE(je.memo, COALESCE(jel.description, '')) AS memo,
                COALESCE(jel.debit_amount, 0) - COALESCE(jel.credit_amount, 0) AS net_amount
            FROM journal_entry_lines jel
            JOIN journal_entries je ON je.id = jel.journal_entry_id
            JOIN accounts a ON a.id = jel.account_id
            JOIN account_types at ON at.id = a.account_type_id
            WHERE je.status IN ('POSTED', 'REVERSED')
              AND at.code = 'EXPENSE'
              AND je.entry_date >= ?
              AND je.entry_date <= ?
            ORDER BY je.entry_date, je.entry_number, jel.line_number
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
