"""Income by date report — all income in chronological order.

Sources: income_batches (non-dues income) and assessments (dues/charges).
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.reporting.dto import IncomeByDateReport, IncomeByDateRow
from hoa_accounting.validators.common import q2


class IncomeByDateReportService:
    """Produce a chronological list of income transactions."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def generate(self, *, from_date: str, to_date: str) -> IncomeByDateReport:
        rows = self.conn.execute(
            """
            SELECT
                ib.posting_date AS entry_date,
                '' AS source,
                '' AS lot_number,
                COALESCE(c.code, 'OTHER') AS account_code,
                COALESCE(c.name, ib.income_description) AS account_name,
                ib.income_description AS memo,
                COALESCE(ib.notes, '') AS comment,
                ib.total_amount AS net_amount
            FROM income_batches ib
            LEFT JOIN categories c ON c.id = ib.category_id
            WHERE ib.posting_date >= ?
              AND ib.posting_date <= ?

            UNION ALL

            SELECT
                a.assessment_date AS entry_date,
                TRIM(COALESCE(o.first_name, '') || ' ' || COALESCE(o.last_name, '')) AS source,
                COALESCE(l.lot_number, '') AS lot_number,
                COALESCE(c.code, a.charge_type) AS account_code,
                COALESCE(c.name, a.charge_type) AS account_name,
                a.description AS memo,
                '' AS comment,
                a.amount AS net_amount
            FROM assessments a
            LEFT JOIN owners o ON o.id = a.owner_id
            LEFT JOIN lots l ON l.id = a.lot_id
            LEFT JOIN categories c ON c.id = a.category_id
            WHERE a.status != 'VOID'
              AND a.assessment_date >= ?
              AND a.assessment_date <= ?

            ORDER BY entry_date
            """,
            (from_date, to_date, from_date, to_date),
        ).fetchall()

        report_rows: list[IncomeByDateRow] = []
        grand_total = Decimal("0.00")

        for row in rows:
            amount = q2(row["net_amount"])
            grand_total += amount
            report_rows.append(
                IncomeByDateRow(
                    entry_date=str(row["entry_date"]),
                    source=str(row["source"] or ""),
                    lot_number=str(row["lot_number"] or ""),
                    account_code=str(row["account_code"]),
                    account_name=str(row["account_name"]),
                    memo=str(row["memo"]),
                    comment=str(row["comment"] or ""),
                    amount=amount,
                )
            )

        return IncomeByDateReport(
            from_date=from_date,
            to_date=to_date,
            rows=report_rows,
            grand_total=q2(grand_total),
        )
