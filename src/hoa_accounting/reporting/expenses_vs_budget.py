"""Expenses vs Budget report — actual expenses compared to approved budget."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from decimal import Decimal

from hoa_accounting.exceptions import NotFoundError
from hoa_accounting.reporting.dto import (
    ExpenseVsBudgetGroup,
    ExpenseVsBudgetReport,
    ExpenseVsBudgetRow,
)
from hoa_accounting.validators.common import q2


class ExpenseVsBudgetReportService:
    """Compare actual expenses against an approved budget."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def generate(self, *, fiscal_year: int, fund_code: str) -> ExpenseVsBudgetReport:
        # ARCHIVED budgets are still authoritative for their own fiscal
        # year — they're "previously approved, now historical" — so the
        # report covers them too. Only DRAFT budgets are excluded.
        budget = self.conn.execute(
            """
            SELECT id FROM budgets
            WHERE fiscal_year = ? AND fund_code = ?
              AND status IN ('APPROVED', 'ARCHIVED')
            ORDER BY CASE status WHEN 'APPROVED' THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (fiscal_year, fund_code),
        ).fetchone()

        if budget is None:
            raise NotFoundError(
                f"No approved budget found for {fiscal_year} / {fund_code}."
            )

        budget_id = int(budget["id"])
        from_date = f"{fiscal_year}-01-01"
        to_date = f"{fiscal_year}-12-31"

        # Show every active EXPENSE category whose fund matches this budget's
        # fund — even if it has no budget line (budget = 0) and even if it has
        # no actual expenses (actual = 0). This makes un-budgeted spend and
        # un-spent categories both visible in one report.
        rows = self.conn.execute(
            """
            SELECT
                c.name                              AS category_name,
                COALESCE(c.group_name, '')          AS group_code,
                COALESCE(c.sort_order, 0)           AS sort_order,
                COALESCE(bl_sum.budget_amount, 0)   AS budget_amount,
                COALESCE(actual.actual_amount, 0)   AS actual_amount
            FROM categories c
            LEFT JOIN (
                SELECT category_id, SUM(budget_amount) AS budget_amount
                FROM budget_lines
                WHERE budget_id = ?
                GROUP BY category_id
            ) bl_sum ON bl_sum.category_id = c.id
            LEFT JOIN (
                SELECT category_id, SUM(amount) AS actual_amount
                FROM vendor_bills
                WHERE invoice_date >= ?
                  AND invoice_date <= ?
                  AND status != 'VOID'
                GROUP BY category_id
            ) actual ON actual.category_id = c.id
            WHERE c.category_type = 'EXPENSE'
              AND c.active_flag = 1
              AND (c.fund_code = ? OR c.fund_code IS NULL OR c.fund_code = '')
            ORDER BY c.group_name, c.sort_order, c.name
            """,
            (budget_id, from_date, to_date, fund_code),
        ).fetchall()

        rows_by_group: dict[str, list[ExpenseVsBudgetRow]] = defaultdict(list)
        group_budget: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
        group_actual: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
        total_budget = Decimal("0.00")
        total_actual = Decimal("0.00")

        for row in rows:
            budget_amount = q2(row["budget_amount"])
            actual_amount = q2(row["actual_amount"])
            variance = q2(budget_amount - actual_amount)
            group_code = str(row["group_code"])

            rows_by_group[group_code].append(
                ExpenseVsBudgetRow(
                    category_name=str(row["category_name"]),
                    group_code=group_code,
                    budget_amount=budget_amount,
                    actual_amount=actual_amount,
                    variance=variance,
                )
            )
            group_budget[group_code] += budget_amount
            group_actual[group_code] += actual_amount
            total_budget += budget_amount
            total_actual += actual_amount

        # Order groups by first appearance (categories are already sorted by
        # group_name / sort_order / name from the SQL ORDER BY)
        seen_groups: list[str] = []
        seen_set: set[str] = set()
        for row in rows:
            gc = str(row["group_code"])
            if gc not in seen_set:
                seen_groups.append(gc)
                seen_set.add(gc)

        groups: list[ExpenseVsBudgetGroup] = []
        for group_code in seen_groups:
            gb = q2(group_budget[group_code])
            ga = q2(group_actual[group_code])
            groups.append(
                ExpenseVsBudgetGroup(
                    group_code=group_code,
                    rows=rows_by_group[group_code],
                    group_budget=gb,
                    group_actual=ga,
                    group_variance=q2(gb - ga),
                )
            )

        return ExpenseVsBudgetReport(
            fiscal_year=fiscal_year,
            fund_code=fund_code,
            from_date=from_date,
            to_date=to_date,
            groups=groups,
            total_budget=q2(total_budget),
            total_actual=q2(total_actual),
            total_variance=q2(total_budget - total_actual),
        )
