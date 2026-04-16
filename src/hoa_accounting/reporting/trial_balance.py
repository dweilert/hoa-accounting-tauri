"""Trial balance report."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.reporting.dto import TrialBalanceReport, TrialBalanceRow
from hoa_accounting.validators.common import q2


class TrialBalanceReportService:
    """Produce a trial balance as of a given date."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def generate(self, *, as_of_date: str) -> TrialBalanceReport:
        """Generate a trial balance including only posted entries up to a date."""
        rows = self.conn.execute(
            """
            SELECT
                a.id AS account_id,
                a.account_number,
                a.account_name,
                a.account_type_id,
                a.fund_code,
                COALESCE(SUM(jel.debit_amount), 0) AS debit_total,
                COALESCE(SUM(jel.credit_amount), 0) AS credit_total
            FROM accounts a
            LEFT JOIN journal_entry_lines jel
                ON jel.account_id = a.id
            LEFT JOIN journal_entries je
                ON je.id = jel.journal_entry_id
               AND je.status = 'POSTED'
               AND je.entry_date <= ?
            WHERE a.is_active = 1
            GROUP BY
                a.id,
                a.account_number,
                a.account_name,
                a.account_type_id,
                a.fund_code
            ORDER BY a.account_number
            """,
            (as_of_date,),
        ).fetchall()

        report_rows: list[TrialBalanceRow] = []
        total_debits = Decimal("0.00")
        total_credits = Decimal("0.00")

        for row in rows:
            debit_total = q2(row["debit_total"])
            credit_total = q2(row["credit_total"])
            net = debit_total - credit_total
            net_debit = net if net > 0 else Decimal("0.00")
            net_credit = -net if net < 0 else Decimal("0.00")

            if debit_total == Decimal("0.00") and credit_total == Decimal("0.00"):
                continue

            report_rows.append(
                TrialBalanceRow(
                    account_id=int(row["account_id"]),
                    account_number=str(row["account_number"]),
                    account_name=str(row["account_name"]),
                    account_type_id=int(row["account_type_id"]),
                    fund_code=str(row["fund_code"]),
                    debit_total=debit_total,
                    credit_total=credit_total,
                    net_debit=q2(net_debit),
                    net_credit=q2(net_credit),
                )
            )
            total_debits += debit_total
            total_credits += credit_total

        return TrialBalanceReport(
            as_of_date=as_of_date,
            rows=report_rows,
            total_debits=q2(total_debits),
            total_credits=q2(total_credits),
        )
