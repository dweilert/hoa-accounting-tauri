"""Categories report — full listing of income, expense, and transfer
categories along with their group, fund, and active status."""

from __future__ import annotations

import sqlite3

from hoa_accounting.reporting.dto import CategoriesReport, CategoriesReportRow


class CategoriesReportService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def generate(self) -> CategoriesReport:
        rows = self.conn.execute(
            """
            SELECT code, name, category_type,
                   COALESCE(group_name, '')  AS group_name,
                   fund_code,
                   sort_order,
                   active_flag,
                   COALESCE(description, '') AS description
            FROM categories
            ORDER BY category_type, name COLLATE NOCASE
            """
        ).fetchall()

        report_rows: list[CategoriesReportRow] = []
        for row in rows:
            report_rows.append(
                CategoriesReportRow(
                    code=str(row["code"] or ""),
                    name=str(row["name"] or ""),
                    category_type=str(row["category_type"] or ""),
                    group_name=str(row["group_name"] or ""),
                    fund_code=str(row["fund_code"] or ""),
                    sort_order=int(row["sort_order"] or 0),
                    active="Yes" if int(row["active_flag"] or 0) == 1 else "No",
                    description=str(row["description"] or ""),
                )
            )

        return CategoriesReport(rows=report_rows)
