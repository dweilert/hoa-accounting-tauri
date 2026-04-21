"""Trial balance report (cash basis, single-entry).

Presents a foot-to-zero snapshot derived from cash activity:

  Debits:  bank balances at as-of date  +  YTD expense category totals
  Credits: opening equity                +  YTD income  category totals

By construction these foot because
    bank_end = bank_open + income - expense
so Σ bank_end + Σ expense = Σ bank_open + Σ income.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.reporting.dto import TrialBalanceReport, TrialBalanceRow
from hoa_accounting.reporting.balance_sheet import BalanceSheetReportService
from hoa_accounting.validators.common import q2


class TrialBalanceReportService:
    """Produce a cash-basis trial balance as of a given date."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def generate(self, *, as_of_date: str) -> TrialBalanceReport:
        rows: list[TrialBalanceRow] = []
        total_debits = Decimal("0.00")
        total_credits = Decimal("0.00")

        # --- Assets: current bank balances (debit) ---
        bs = BalanceSheetReportService(self.conn)
        for bank in bs._bank_balances(as_of_date=as_of_date):
            amount = q2(bank["balance"])
            if amount == Decimal("0.00"):
                continue
            rows.append(
                TrialBalanceRow(
                    account_id=int(bank["gl_account_id"]),
                    account_number=str(bank["account_number"] or ""),
                    account_name=str(bank["bank_account_name"]),
                    account_type_id=0,
                    fund_code=str(bank["fund_code"] or ""),
                    debit_total=amount,
                    credit_total=Decimal("0.00"),
                    net_debit=amount,
                    net_credit=Decimal("0.00"),
                )
            )
            total_debits += amount

        # --- Equity: opening balance (credit) ---
        opening_equity = bs._opening_equity()
        if opening_equity != Decimal("0.00"):
            amt = q2(opening_equity)
            rows.append(
                TrialBalanceRow(
                    account_id=0,
                    account_number="",
                    account_name="Opening Equity",
                    account_type_id=0,
                    fund_code="ALL",
                    debit_total=Decimal("0.00"),
                    credit_total=amt,
                    net_debit=Decimal("0.00"),
                    net_credit=amt,
                )
            )
            total_credits += amt

        # --- Income categories YTD (credit) ---
        for row in self._income_totals(as_of_date=as_of_date):
            amt = q2(Decimal(str(row["total"] or 0)))
            if amt == Decimal("0.00"):
                continue
            rows.append(
                TrialBalanceRow(
                    account_id=int(row["category_id"] or 0),
                    account_number=str(row["code"] or ""),
                    account_name=str(row["name"]),
                    account_type_id=0,
                    fund_code=str(row["fund_code"] or ""),
                    debit_total=Decimal("0.00"),
                    credit_total=amt,
                    net_debit=Decimal("0.00"),
                    net_credit=amt,
                )
            )
            total_credits += amt

        # --- Expense categories YTD (debit) ---
        for row in self._expense_totals(as_of_date=as_of_date):
            amt = q2(Decimal(str(row["total"] or 0)))
            if amt == Decimal("0.00"):
                continue
            rows.append(
                TrialBalanceRow(
                    account_id=int(row["category_id"] or 0),
                    account_number=str(row["code"] or ""),
                    account_name=str(row["name"]),
                    account_type_id=0,
                    fund_code=str(row["fund_code"] or ""),
                    debit_total=amt,
                    credit_total=Decimal("0.00"),
                    net_debit=amt,
                    net_credit=Decimal("0.00"),
                )
            )
            total_debits += amt

        return TrialBalanceReport(
            as_of_date=as_of_date,
            rows=rows,
            total_debits=q2(total_debits),
            total_credits=q2(total_credits),
        )

    def _income_totals(self, *, as_of_date: str) -> list[sqlite3.Row]:
        """Sum payments + income_batches by category through as_of_date.

        Rows missing a category_id are bucketed as 'Uncategorized'.
        Only counts cash received on/after each bank's opening_balance_date
        so we don't double-count activity already baked into the opening.
        """
        return self.conn.execute(
            """
            SELECT
                c.id           AS category_id,
                c.code         AS code,
                COALESCE(c.name, 'Uncategorized') AS name,
                COALESCE(c.fund_code, '')         AS fund_code,
                SUM(amt)       AS total
            FROM (
                SELECT p.category_id AS cat_id, p.amount AS amt
                FROM payments p
                JOIN bank_accounts b ON b.id = p.bank_account_id
                WHERE p.payment_date <= ?
                  AND (b.opening_balance_date IS NULL
                       OR p.payment_date >= b.opening_balance_date)
                UNION ALL
                SELECT ib.category_id AS cat_id, ib.total_amount AS amt
                FROM income_batches ib
                JOIN bank_accounts b ON b.id = ib.bank_account_id
                WHERE ib.posting_date <= ?
                  AND (b.opening_balance_date IS NULL
                       OR ib.posting_date >= b.opening_balance_date)
            ) src
            LEFT JOIN categories c ON c.id = src.cat_id
            GROUP BY c.id, c.code, c.name, c.fund_code
            ORDER BY c.fund_code, c.sort_order, c.name
            """,
            (as_of_date, as_of_date),
        ).fetchall()

    def _expense_totals(self, *, as_of_date: str) -> list[sqlite3.Row]:
        """Sum bill_payments by category through as_of_date.

        Falls back to the vendor_bill's category when the bill_payment has none.
        """
        return self.conn.execute(
            """
            SELECT
                c.id           AS category_id,
                c.code         AS code,
                COALESCE(c.name, 'Uncategorized') AS name,
                COALESCE(c.fund_code, '')         AS fund_code,
                SUM(bp.amount) AS total
            FROM bill_payments bp
            JOIN bank_accounts b ON b.id = bp.bank_account_id
            LEFT JOIN vendor_bills vb ON vb.id = bp.vendor_bill_id
            LEFT JOIN categories c
                   ON c.id = COALESCE(bp.category_id, vb.category_id)
            WHERE bp.payment_date <= ?
              AND (b.opening_balance_date IS NULL
                   OR bp.payment_date >= b.opening_balance_date)
            GROUP BY c.id, c.code, c.name, c.fund_code
            ORDER BY c.fund_code, c.sort_order, c.name
            """,
            (as_of_date,),
        ).fetchall()
