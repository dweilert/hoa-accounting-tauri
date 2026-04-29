"""Year-to-date expense summary report.

Reads from vendor_bills (single-entry). One row per active expense category,
grouped by group_name. Zero-activity categories are shown so the full picture
is always visible.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from decimal import Decimal

from hoa_accounting.reporting.dto import (
    YtdExpenseCategoryRow,
    YtdExpenseGroup,
    YtdExpenseSummaryReport,
)
from hoa_accounting.validators.common import q2


class YtdExpenseSummaryReportService:
    """Produce the YTD Expense Summary report."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def generate(
        self,
        *,
        from_date: str,
        to_date: str,
    ) -> YtdExpenseSummaryReport:
        rows = self.conn.execute(
            """
            SELECT
                c.id AS account_id,
                c.code AS account_number,
                c.name AS account_name,
                COALESCE(c.group_name, '') AS group_code,
                c.fund_code,
                COALESCE(c.description, '') AS comment,
                COALESCE(SUM(CASE WHEN vb.status != 'VOID' THEN vb.amount ELSE 0 END), 0) AS debit_total,
                0 AS credit_total,
                COALESCE(COUNT(CASE WHEN vb.status != 'VOID' THEN vb.id END), 0) AS record_count
            FROM categories c
            LEFT JOIN vendor_bills vb
                ON vb.category_id = c.id
                AND vb.invoice_date >= ?
                AND vb.invoice_date <= ?
            WHERE c.active_flag = 1
              AND c.category_type = 'EXPENSE'
            GROUP BY c.id, c.code, c.name, c.group_name, c.fund_code
            ORDER BY c.group_name, c.sort_order, c.name
            """,
            (from_date, to_date),
        ).fetchall()

        category_rows_by_group: dict[str, list[YtdExpenseCategoryRow]] = defaultdict(
            list
        )
        group_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
        group_counts: dict[str, int] = defaultdict(int)
        grand_total = Decimal("0.00")
        total_count = 0

        for row in rows:
            ytd_amount = q2(row["debit_total"])
            record_count = int(row["record_count"] or 0)
            group_code = str(row["group_code"]) or "UNCATEGORIZED"

            category_rows_by_group[group_code].append(
                YtdExpenseCategoryRow(
                    account_id=int(row["account_id"]),
                    account_number=str(row["account_number"]),
                    account_name=str(row["account_name"]),
                    group_code=group_code,
                    fund_code=str(row["fund_code"]),
                    ytd_amount=ytd_amount,
                    record_count=record_count,
                    comment=str(row["comment"] or ""),
                )
            )
            group_totals[group_code] += ytd_amount
            group_counts[group_code] += record_count
            grand_total += ytd_amount
            total_count += record_count

        groups: list[YtdExpenseGroup] = []
        for group_code in sorted(category_rows_by_group):
            groups.append(
                YtdExpenseGroup(
                    group_code=group_code,
                    rows=category_rows_by_group[group_code],
                    group_total=q2(group_totals[group_code]),
                    group_record_count=group_counts[group_code],
                )
            )

        return YtdExpenseSummaryReport(
            from_date=from_date,
            to_date=to_date,
            groups=groups,
            grand_total=q2(grand_total),
            total_record_count=total_count,
        )
