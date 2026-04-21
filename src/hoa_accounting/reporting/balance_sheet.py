"""Balance sheet report (cash basis, single-entry).

Assets are derived from bank account balances at the as-of date. Equity is
opening bank balances plus cumulative net income (payments + income_batches
received, less bill_payments made). Liabilities are not tracked on a cash
basis for this HOA, so that section is empty.
"""

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
    """Produce a cash-basis balance sheet as of a given date."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def generate(self, *, as_of_date: str) -> BalanceSheetReport:
        bank_rows = self._bank_balances(as_of_date=as_of_date)

        assets_rows: list[BalanceSheetRow] = []
        total_assets = Decimal("0.00")
        for row in bank_rows:
            amount = q2(row["balance"])
            if amount == Decimal("0.00"):
                continue
            assets_rows.append(
                BalanceSheetRow(
                    account_id=int(row["gl_account_id"]),
                    account_number=str(row["account_number"] or ""),
                    account_name=str(row["bank_account_name"]),
                    fund_code=str(row["fund_code"] or ""),
                    amount=amount,
                    is_system=False,
                )
            )
            total_assets += amount

        opening_equity = self._opening_equity()
        net_income = self._net_income(as_of_date=as_of_date)

        equity_rows: list[BalanceSheetRow] = []
        if opening_equity != Decimal("0.00"):
            equity_rows.append(
                BalanceSheetRow(
                    account_id=None,
                    account_number=None,
                    account_name="Opening Equity",
                    fund_code=None,
                    amount=q2(opening_equity),
                    is_system=True,
                )
            )
        if net_income != Decimal("0.00"):
            equity_rows.append(
                BalanceSheetRow(
                    account_id=None,
                    account_number=None,
                    account_name="Net Income (Cash Basis)",
                    fund_code=None,
                    amount=q2(net_income),
                    is_system=True,
                )
            )
        total_equity = q2(opening_equity + net_income)

        total_assets = q2(total_assets)
        total_liabilities = Decimal("0.00")
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
                rows=[],
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

    def _bank_balances(self, *, as_of_date: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT
                b.id                     AS bank_id,
                b.account_name           AS bank_account_name,
                b.gl_account_id          AS gl_account_id,
                a.account_number         AS account_number,
                a.fund_code              AS fund_code,
                COALESCE(b.opening_balance, 0)
                + COALESCE((
                    SELECT SUM(p.amount) FROM payments p
                    WHERE p.bank_account_id = b.id
                      AND p.payment_date <= ?
                      AND (b.opening_balance_date IS NULL
                           OR p.payment_date >= b.opening_balance_date)
                  ), 0)
                + COALESCE((
                    SELECT SUM(ib.total_amount) FROM income_batches ib
                    WHERE ib.bank_account_id = b.id
                      AND ib.posting_date <= ?
                      AND (b.opening_balance_date IS NULL
                           OR ib.posting_date >= b.opening_balance_date)
                  ), 0)
                + COALESCE((
                    SELECT SUM(rt.amount) FROM reserve_transfers rt
                    WHERE rt.to_account_id = b.gl_account_id
                      AND rt.transfer_date <= ?
                      AND (b.opening_balance_date IS NULL
                           OR rt.transfer_date >= b.opening_balance_date)
                  ), 0)
                - COALESCE((
                    SELECT SUM(bp.amount) FROM bill_payments bp
                    WHERE bp.bank_account_id = b.id
                      AND bp.payment_date <= ?
                      AND (b.opening_balance_date IS NULL
                           OR bp.payment_date >= b.opening_balance_date)
                  ), 0)
                - COALESCE((
                    SELECT SUM(rt.amount) FROM reserve_transfers rt
                    WHERE rt.from_account_id = b.gl_account_id
                      AND rt.transfer_date <= ?
                      AND (b.opening_balance_date IS NULL
                           OR rt.transfer_date >= b.opening_balance_date)
                  ), 0)
                AS balance
            FROM bank_accounts b
            JOIN accounts a ON a.id = b.gl_account_id
            WHERE b.active_flag = 1
            ORDER BY a.fund_code, a.account_number
            """,
            (as_of_date, as_of_date, as_of_date, as_of_date, as_of_date),
        ).fetchall()

    def _opening_equity(self) -> Decimal:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(opening_balance), 0) AS total
            FROM bank_accounts
            WHERE active_flag = 1
            """
        ).fetchone()
        return q2(Decimal(str(row["total"] or 0)))

    def _net_income(self, *, as_of_date: str) -> Decimal:
        """Cash-basis net income from the earliest opening date through as_of_date.

        Income = payments received + income_batches posted.
        Expenses = bill_payments. Reserve transfers are intra-entity cash moves
        and net to zero at the entity level, so they are excluded.
        """
        income_row = self.conn.execute(
            """
            SELECT
                COALESCE((
                    SELECT SUM(p.amount) FROM payments p
                    JOIN bank_accounts b ON b.id = p.bank_account_id
                    WHERE p.payment_date <= ?
                      AND (b.opening_balance_date IS NULL
                           OR p.payment_date >= b.opening_balance_date)
                ), 0)
                + COALESCE((
                    SELECT SUM(ib.total_amount) FROM income_batches ib
                    JOIN bank_accounts b ON b.id = ib.bank_account_id
                    WHERE ib.posting_date <= ?
                      AND (b.opening_balance_date IS NULL
                           OR ib.posting_date >= b.opening_balance_date)
                ), 0) AS income,
                COALESCE((
                    SELECT SUM(bp.amount) FROM bill_payments bp
                    JOIN bank_accounts b ON b.id = bp.bank_account_id
                    WHERE bp.payment_date <= ?
                      AND (b.opening_balance_date IS NULL
                           OR bp.payment_date >= b.opening_balance_date)
                ), 0) AS expense
            """,
            (as_of_date, as_of_date, as_of_date),
        ).fetchone()
        income = Decimal(str(income_row["income"] or 0))
        expense = Decimal(str(income_row["expense"] or 0))
        return q2(income - expense)
