"""Income statement report."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.reporting.dto import (
    IncomeStatementReport,
    IncomeStatementRow,
    IncomeStatementSection,
)
from hoa_accounting.validators.common import q2


class IncomeStatementReportService:
    """Produce an income statement for a date range."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def generate(
        self,
        *,
        from_date: str,
        to_date: str,
    ) -> IncomeStatementReport:
        """Generate income and expense totals for a period."""
        rows = self.conn.execute(
            """
            SELECT
                a.id AS account_id,
                a.account_number,
                a.account_name,
                a.fund_code,
                at.code AS account_type_code,
                at.normal_balance,
                at.financial_statement_group,
                COALESCE(SUM(x.debit_amount), 0) AS debit_total,
                COALESCE(SUM(x.credit_amount), 0) AS credit_total
            FROM accounts a
            JOIN account_types at
              ON at.id = a.account_type_id
            LEFT JOIN (
                SELECT
                    jel.account_id,
                    jel.debit_amount,
                    jel.credit_amount
                FROM journal_entry_lines jel
                JOIN journal_entries je
                  ON je.id = jel.journal_entry_id
                WHERE je.status = 'POSTED'
                  AND je.entry_date >= ?
                  AND je.entry_date <= ?
            ) x
              ON x.account_id = a.id
            WHERE a.is_active = 1
              AND at.financial_statement_group = 'INCOME_STATEMENT'
            GROUP BY
                a.id,
                a.account_number,
                a.account_name,
                a.fund_code,
                at.code,
                at.normal_balance,
                at.financial_statement_group
            ORDER BY a.account_number
            """,
            (from_date, to_date),
        ).fetchall()

        income_rows: list[IncomeStatementRow] = []
        expense_rows: list[IncomeStatementRow] = []

        total_income = Decimal("0.00")
        total_expenses = Decimal("0.00")

        for row in rows:
            amount = self._signed_balance(
                debit_total=q2(row["debit_total"]),
                credit_total=q2(row["credit_total"]),
                normal_balance=str(row["normal_balance"]),
            )
            amount = q2(amount)

            if amount == Decimal("0.00"):
                continue

            item = IncomeStatementRow(
                account_id=int(row["account_id"]),
                account_number=str(row["account_number"]),
                account_name=str(row["account_name"]),
                fund_code=str(row["fund_code"]),
                amount=amount,
            )

            account_type_code = str(row["account_type_code"])
            if account_type_code == "INCOME":
                income_rows.append(item)
                total_income += amount
            elif account_type_code == "EXPENSE":
                expense_rows.append(item)
                total_expenses += amount

        total_income = q2(total_income)
        total_expenses = q2(total_expenses)
        net_income = q2(total_income - total_expenses)

        return IncomeStatementReport(
            from_date=from_date,
            to_date=to_date,
            income=IncomeStatementSection(
                section_name="Income",
                rows=income_rows,
                total_amount=total_income,
            ),
            expenses=IncomeStatementSection(
                section_name="Expenses",
                rows=expense_rows,
                total_amount=total_expenses,
            ),
            total_income=total_income,
            total_expenses=total_expenses,
            net_income=net_income,
        )

    def _signed_balance(
        self,
        *,
        debit_total: Decimal,
        credit_total: Decimal,
        normal_balance: str,
    ) -> Decimal:
        if normal_balance == "DEBIT":
            return debit_total - credit_total
        return credit_total - debit_total