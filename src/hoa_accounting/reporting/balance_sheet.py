"""Balance sheet report."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.reporting.dto import (
    BalanceSheetReport,
    BalanceSheetRow,
    BalanceSheetSection,
)
from hoa_accounting.validators.common import q2


class BalanceSheetReportService:
    """Produce a balance sheet as of a given date."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def generate(self, *, as_of_date: str) -> BalanceSheetReport:
        """Generate a balance sheet from posted journal activity."""
        balance_sheet_rows = self.conn.execute(
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
                  AND je.entry_date <= ?
            ) x
              ON x.account_id = a.id
            WHERE a.is_active = 1
              AND at.financial_statement_group = 'BALANCE_SHEET'
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
            (as_of_date,),
        ).fetchall()

        assets_rows: list[BalanceSheetRow] = []
        liabilities_rows: list[BalanceSheetRow] = []
        equity_rows: list[BalanceSheetRow] = []

        total_assets = Decimal("0.00")
        total_liabilities = Decimal("0.00")
        total_equity = Decimal("0.00")

        for row in balance_sheet_rows:
            amount = self._signed_balance(
                debit_total=q2(row["debit_total"]),
                credit_total=q2(row["credit_total"]),
                normal_balance=str(row["normal_balance"]),
            )
            amount = q2(amount)

            if amount == Decimal("0.00"):
                continue

            item = BalanceSheetRow(
                account_id=int(row["account_id"]),
                account_number=str(row["account_number"]),
                account_name=str(row["account_name"]),
                fund_code=str(row["fund_code"]),
                amount=amount,
                is_system=False,
            )

            account_type_code = str(row["account_type_code"])
            if account_type_code == "ASSET":
                assets_rows.append(item)
                total_assets += amount
            elif account_type_code == "LIABILITY":
                liabilities_rows.append(item)
                total_liabilities += amount
            else:
                equity_rows.append(item)
                total_equity += amount

        cumulative_earnings = self._load_cumulative_earnings(as_of_date=as_of_date)
        if cumulative_earnings != Decimal("0.00"):
            equity_rows.append(
                BalanceSheetRow(
                    account_id=None,
                    account_number=None,
                    account_name="Cumulative Earnings",
                    fund_code=None,
                    amount=q2(cumulative_earnings),
                    is_system=True,
                )
            )
            total_equity += cumulative_earnings

        total_assets = q2(total_assets)
        total_liabilities = q2(total_liabilities)
        total_equity = q2(total_equity)
        total_liabilities_and_equity = q2(total_liabilities + total_equity)
        balancing_difference = q2(total_assets - total_liabilities_and_equity)

        return BalanceSheetReport(
            as_of_date=as_of_date,
            assets=BalanceSheetSection(
                section_name="Assets",
                rows=assets_rows,
                total_amount=total_assets,
            ),
            liabilities=BalanceSheetSection(
                section_name="Liabilities",
                rows=liabilities_rows,
                total_amount=total_liabilities,
            ),
            equity=BalanceSheetSection(
                section_name="Equity",
                rows=equity_rows,
                total_amount=total_equity,
            ),
            total_assets=total_assets,
            total_liabilities=total_liabilities,
            total_equity=total_equity,
            total_liabilities_and_equity=total_liabilities_and_equity,
            balancing_difference=balancing_difference,
        )

    def _load_cumulative_earnings(self, *, as_of_date: str) -> Decimal:
        """Compute cumulative earnings when no formal close process exists."""
        row = self.conn.execute(
            """
            SELECT
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
                  AND je.entry_date <= ?
            ) x
              ON x.account_id = a.id
            WHERE a.is_active = 1
              AND at.financial_statement_group = 'INCOME_STATEMENT'
            """,
            (as_of_date,),
        ).fetchone()

        debit_total = q2(row["debit_total"])
        credit_total = q2(row["credit_total"])
        return q2(credit_total - debit_total)

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