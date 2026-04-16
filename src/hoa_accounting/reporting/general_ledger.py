"""General ledger detail report."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.exceptions import NotFoundError
from hoa_accounting.reporting.dto import GeneralLedgerReport, GeneralLedgerRow
from hoa_accounting.validators.common import q2


class GeneralLedgerReportService:
    """Produce general ledger detail for one account."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def generate(
        self,
        *,
        account_id: int,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> GeneralLedgerReport:
        """Generate general ledger detail with running balance."""
        account = self.conn.execute(
            """
            SELECT id, account_number, account_name
            FROM accounts
            WHERE id = ?
            """,
            (account_id,),
        ).fetchone()
        if account is None:
            raise NotFoundError(f"Account {account_id} was not found.")

        conditions = ["jel.account_id = ?", "je.status = 'POSTED'"]
        params: list[object] = [account_id]

        if from_date is not None:
            conditions.append("je.entry_date >= ?")
            params.append(from_date)
        if to_date is not None:
            conditions.append("je.entry_date <= ?")
            params.append(to_date)

        where_sql = " AND ".join(conditions)

        rows = self.conn.execute(
            f"""
            SELECT
                je.entry_date,
                je.entry_number,
                je.source_type,
                COALESCE(je.memo, '') AS memo,
                COALESCE(jel.description, '') AS line_description,
                COALESCE(jel.debit_amount, 0) AS debit_amount,
                COALESCE(jel.credit_amount, 0) AS credit_amount,
                jel.lot_id,
                jel.owner_id,
                jel.vendor_id
            FROM journal_entry_lines jel
            JOIN journal_entries je
              ON je.id = jel.journal_entry_id
            WHERE {where_sql}
            ORDER BY je.entry_date, je.entry_number, jel.line_number
            """,
            params,
        ).fetchall()

        running_balance = Decimal("0.00")
        report_rows: list[GeneralLedgerRow] = []

        for row in rows:
            debit_amount = q2(row["debit_amount"])
            credit_amount = q2(row["credit_amount"])
            running_balance += debit_amount - credit_amount

            report_rows.append(
                GeneralLedgerRow(
                    entry_date=str(row["entry_date"]),
                    entry_number=str(row["entry_number"]),
                    source_type=str(row["source_type"]),
                    memo=str(row["memo"]),
                    line_description=str(row["line_description"]),
                    debit_amount=debit_amount,
                    credit_amount=credit_amount,
                    running_balance=q2(running_balance),
                    lot_id=int(row["lot_id"]) if row["lot_id"] is not None else None,
                    owner_id=int(row["owner_id"]) if row["owner_id"] is not None else None,
                    vendor_id=int(row["vendor_id"]) if row["vendor_id"] is not None else None,
                )
            )

        return GeneralLedgerReport(
            account_id=int(account["id"]),
            account_number=str(account["account_number"]),
            account_name=str(account["account_name"]),
            from_date=from_date,
            to_date=to_date,
            rows=report_rows,
        )
