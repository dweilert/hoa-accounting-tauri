"""Year-to-date expense summary report.

Renders the view the treasurer has in their spreadsheet today: every
active expense category row, grouped by its ``group_code`` (Landscape,
Entrance, Sewer, Road, Wall, Utilities, Insurance, Misc, Firewise),
with YTD amount and record count per category. Zero-activity rows are
deliberately shown so the treasurer can see 'everything we track is
here, and what we haven't spent on this year'.
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
        """Generate the report for the given date range (inclusive).

        One row per active expense account, grouped by ``group_code``.
        Each row reports the net debit amount (debits minus credits,
        so reversals cancel correctly) and the count of journal-entry
        lines that contributed to it.
        """
        rows = self.conn.execute(
            """
            SELECT
                a.id AS account_id,
                a.account_number,
                a.account_name,
                COALESCE(a.group_code, '') AS group_code,
                a.fund_code,
                COALESCE(SUM(x.debit_amount), 0) AS debit_total,
                COALESCE(SUM(x.credit_amount), 0) AS credit_total,
                COALESCE(COUNT(x.id), 0) AS record_count
            FROM accounts a
            JOIN account_types at
              ON at.id = a.account_type_id
            LEFT JOIN (
                SELECT
                    jel.id,
                    jel.account_id,
                    jel.debit_amount,
                    jel.credit_amount
                FROM journal_entry_lines jel
                JOIN journal_entries je
                  ON je.id = jel.journal_entry_id
                -- Include REVERSED alongside POSTED so a reversed-and-
                -- reversed pair nets correctly: the original (REVERSED)
                -- contributes its debit, the reversal (POSTED) contributes
                -- the offsetting credit, net = 0, count = 2. Excluding
                -- REVERSED would leave a ghost credit on the report.
                WHERE je.status IN ('POSTED', 'REVERSED')
                  AND je.entry_date >= ?
                  AND je.entry_date <= ?
            ) x
              ON x.account_id = a.id
            WHERE a.is_active = 1
              AND at.code = 'EXPENSE'
            GROUP BY
                a.id,
                a.account_number,
                a.account_name,
                a.group_code,
                a.fund_code
            ORDER BY a.group_code, a.account_number
            """,
            (from_date, to_date),
        ).fetchall()

        category_rows_by_group: dict[str, list[YtdExpenseCategoryRow]] = defaultdict(list)
        group_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
        group_counts: dict[str, int] = defaultdict(int)
        grand_total = Decimal("0.00")
        total_count = 0

        for row in rows:
            debit_total = q2(row["debit_total"])
            credit_total = q2(row["credit_total"])
            # Expenses are debit-normal. Net amount = debits − credits so
            # a reversal entry (credit on an expense line) subtracts
            # correctly rather than adding in absolute value.
            ytd_amount = q2(debit_total - credit_total)
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
