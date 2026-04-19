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

_GROUP_ORDER = [
    "LANDSCAPE", "SEWER", "ROAD", "WALL", "ENTRANCE",
    "UTILITIES", "INSURANCE", "MISC", "FIREWISE",
]


class ExpenseVsBudgetReportService:
    """Compare actual expenses against an approved budget."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def generate(self, *, fiscal_year: int, fund_code: str) -> ExpenseVsBudgetReport:
        # Verify an approved budget exists
        budget = self.conn.execute(
            """
            SELECT id FROM budgets
            WHERE fiscal_year = ? AND fund_code = ? AND status = 'APPROVED'
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

        rows = self.conn.execute(
            """
            SELECT
                a.account_number,
                a.account_name,
                COALESCE(a.group_code, 'MISC') AS group_code,
                COALESCE(SUM(bl.budget_amount), 0) AS budget_amount,
                COALESCE(actual.net_amount, 0) AS actual_amount
            FROM budget_lines bl
            JOIN accounts a ON a.id = bl.account_id
            LEFT JOIN (
                SELECT jel.account_id,
                       SUM(COALESCE(jel.debit_amount, 0))
                         - SUM(COALESCE(jel.credit_amount, 0)) AS net_amount
                FROM journal_entry_lines jel
                JOIN journal_entries je ON je.id = jel.journal_entry_id
                WHERE je.status IN ('POSTED', 'REVERSED')
                  AND je.entry_date >= ?
                  AND je.entry_date <= ?
                GROUP BY jel.account_id
            ) actual ON actual.account_id = a.id
            WHERE bl.budget_id = ?
            GROUP BY a.id, a.account_number, a.account_name, a.group_code
            ORDER BY a.group_code, a.account_number
            """,
            (from_date, to_date, budget_id),
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
                    account_number=str(row["account_number"]),
                    account_name=str(row["account_name"]),
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

        # Order groups using the canonical order, then any unknown groups last
        ordered_keys = [g for g in _GROUP_ORDER if g in rows_by_group]
        ordered_keys += sorted(g for g in rows_by_group if g not in _GROUP_ORDER)

        groups: list[ExpenseVsBudgetGroup] = []
        for group_code in ordered_keys:
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
