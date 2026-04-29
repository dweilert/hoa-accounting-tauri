"""Budget summary report — annual budget amounts across 1–3 fiscal years."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from decimal import Decimal

from hoa_accounting.reporting.dto import (
    BudgetSummaryGroup,
    BudgetSummaryReport,
    BudgetSummaryRow,
)
from hoa_accounting.validators.common import q2


class BudgetSummaryReportService:
    """Produce a budget summary with optional year-over-year comparison."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def generate(
        self,
        *,
        years_mode: str,
        current_year: int,
    ) -> BudgetSummaryReport:
        years = self._years_for_mode(years_mode, current_year)
        n = len(years)
        flat_rows = self._load_flat_rows(years)

        # Group rows by group_code preserving SQL order
        group_order: list[str] = []
        group_map: dict[str, list[BudgetSummaryRow]] = defaultdict(list)
        for row in flat_rows:
            if row.group_code not in group_map:
                group_order.append(row.group_code)
            group_map[row.group_code].append(row)

        groups: list[BudgetSummaryGroup] = []
        total_amounts = [Decimal("0.00")] * n
        for gc in group_order:
            g_rows = group_map[gc]
            sub = [q2(sum(r.year_amounts[i] for r in g_rows)) for i in range(n)]
            sub_pct = [self._pct_change(sub[i], sub[i + 1]) for i in range(n - 1)]
            groups.append(
                BudgetSummaryGroup(
                    group_code=gc,
                    rows=g_rows,
                    subtotal_amounts=sub,
                    subtotal_pct_changes=sub_pct,
                )
            )
            for i in range(n):
                total_amounts[i] += sub[i]

        total_amounts = [q2(a) for a in total_amounts]
        total_pct = [
            self._pct_change(total_amounts[i], total_amounts[i + 1])
            for i in range(n - 1)
        ]

        return BudgetSummaryReport(
            years=years,
            groups=groups,
            total_amounts=total_amounts,
            total_pct_changes=total_pct,
        )

    def _years_for_mode(self, mode: str, current_year: int) -> list[int]:
        if mode == "prev_current":
            return [current_year - 1, current_year]
        if mode == "prev_current_next":
            return [current_year - 1, current_year, current_year + 1]
        return [current_year]

    def _load_flat_rows(self, years: list[int]) -> list[BudgetSummaryRow]:
        n = len(years)
        case_cols = ",\n".join(
            f"COALESCE(SUM(CASE WHEN b.fiscal_year = ? THEN bl.budget_amount ELSE 0 END), 0) AS amt_{i}"
            for i in range(n)
        )
        placeholders = ", ".join("?" * n)

        # Support both category_id (new) and account_id (legacy) budget lines
        sql = f"""
            SELECT
                COALESCE(c.name, 'Unknown') AS category_name,
                COALESCE(c.group_name, '') AS group_code,
                COALESCE(c.sort_order, 0) AS sort_order,
                {case_cols}
            FROM budget_lines bl
            JOIN budgets b
              ON b.id = bl.budget_id
             AND b.status != 'ARCHIVED'
            LEFT JOIN categories c ON c.id = bl.category_id
            WHERE b.fiscal_year IN ({placeholders})
            GROUP BY
                COALESCE(c.name, 'Unknown'),
                COALESCE(c.group_name, ''),
                COALESCE(c.sort_order, 0)
            ORDER BY group_code, sort_order, category_name
        """
        params: list[int] = list(years) + list(years)
        db_rows = self.conn.execute(sql, params).fetchall()

        result: list[BudgetSummaryRow] = []
        for row in db_rows:
            amounts = [q2(row[f"amt_{i}"]) for i in range(n)]
            if all(a == Decimal("0.00") for a in amounts):
                continue
            pct_changes = [
                self._pct_change(amounts[i], amounts[i + 1]) for i in range(n - 1)
            ]
            result.append(
                BudgetSummaryRow(
                    category_name=str(row["category_name"]),
                    group_code=str(row["group_code"]),
                    year_amounts=amounts,
                    pct_changes=pct_changes,
                )
            )
        return result

    def _pct_change(self, old: Decimal, new: Decimal) -> str:
        if old == Decimal("0.00"):
            return "new"
        pct = ((new - old) / old * 100).quantize(Decimal("0.1"))
        sign = "+" if pct > 0 else ""
        return f"{sign}{pct}%"
