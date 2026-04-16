"""Owner ledger detail report."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.exceptions import NotFoundError
from hoa_accounting.reporting.dto import OwnerLedgerReport, OwnerLedgerRow
from hoa_accounting.validators.common import q2


class OwnerLedgerReportService:
    """Produce owner receivable subledger detail for one owner."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def generate(
        self,
        *,
        owner_id: int,
        receivable_account_id: int,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> OwnerLedgerReport:
        """Generate owner ledger detail with opening and running balance.

        The report is based on posted journal lines in a designated owner
        receivable account. Positive balances mean the owner owes the HOA.
        Negative balances mean the owner has a credit balance.
        """
        owner = self.conn.execute(
            """
            SELECT id, display_name
            FROM owners
            WHERE id = ?
            """,
            (owner_id,),
        ).fetchone()
        if owner is None:
            raise NotFoundError(f"Owner {owner_id} was not found.")

        account = self.conn.execute(
            """
            SELECT id, account_number, account_name
            FROM accounts
            WHERE id = ?
            """,
            (receivable_account_id,),
        ).fetchone()
        if account is None:
            raise NotFoundError(
                f"Receivable account {receivable_account_id} was not found."
            )

        opening_balance = self._load_opening_balance(
            owner_id=owner_id,
            receivable_account_id=receivable_account_id,
            from_date=from_date,
        )

        conditions = [
            "jel.owner_id = ?",
            "jel.account_id = ?",
            "je.status = 'POSTED'",
        ]
        params: list[object] = [owner_id, receivable_account_id]

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
                je.source_id,
                COALESCE(je.memo, '') AS memo,
                COALESCE(jel.description, '') AS line_description,
                COALESCE(jel.debit_amount, 0) AS debit_amount,
                COALESCE(jel.credit_amount, 0) AS credit_amount,
                jel.lot_id,
                l.lot_number,
                a.id AS assessment_id,
                a.due_date AS assessment_due_date,
                p.id AS payment_id,
                p.receipt_number,
                p.payment_method,
                oa.id AS owner_adjustment_id,
                oa.adjustment_type
            FROM journal_entry_lines jel
            JOIN journal_entries je
              ON je.id = jel.journal_entry_id
            LEFT JOIN lots l
              ON l.id = jel.lot_id
            LEFT JOIN assessments a
              ON je.source_type = 'ASSESSMENT'
             AND je.source_id = a.id
            LEFT JOIN payments p
              ON je.source_type = 'PAYMENT'
             AND je.source_id = p.id
            LEFT JOIN owner_adjustments oa
              ON je.source_type = 'ADJUSTMENT'
             AND je.source_id = oa.id
            WHERE {where_sql}
            ORDER BY je.entry_date, je.entry_number, jel.line_number
            """,
            params,
        ).fetchall()

        running_balance = opening_balance
        report_rows: list[OwnerLedgerRow] = []

        for row in rows:
            debit_amount = q2(row["debit_amount"])
            credit_amount = q2(row["credit_amount"])
            running_balance += debit_amount - credit_amount

            report_rows.append(
                OwnerLedgerRow(
                    entry_date=str(row["entry_date"]),
                    entry_number=str(row["entry_number"]),
                    source_type=str(row["source_type"]),
                    source_id=int(row["source_id"]) if row["source_id"] is not None else None,
                    memo=str(row["memo"]),
                    line_description=str(row["line_description"]),
                    debit_amount=debit_amount,
                    credit_amount=credit_amount,
                    running_balance=q2(running_balance),
                    lot_id=int(row["lot_id"]) if row["lot_id"] is not None else None,
                    lot_number=str(row["lot_number"]) if row["lot_number"] is not None else None,
                    due_date=str(row["assessment_due_date"])
                    if row["assessment_due_date"] is not None
                    else None,
                    assessment_id=int(row["assessment_id"])
                    if row["assessment_id"] is not None
                    else None,
                    payment_id=int(row["payment_id"]) if row["payment_id"] is not None else None,
                    receipt_number=str(row["receipt_number"])
                    if row["receipt_number"] is not None
                    else None,
                    payment_method=str(row["payment_method"])
                    if row["payment_method"] is not None
                    else None,
                    owner_adjustment_id=int(row["owner_adjustment_id"])
                    if row["owner_adjustment_id"] is not None
                    else None,
                    adjustment_type=str(row["adjustment_type"])
                    if row["adjustment_type"] is not None
                    else None,
                )
            )

        return OwnerLedgerReport(
            owner_id=int(owner["id"]),
            owner_name=str(owner["display_name"]),
            receivable_account_id=int(account["id"]),
            receivable_account_number=str(account["account_number"]),
            receivable_account_name=str(account["account_name"]),
            from_date=from_date,
            to_date=to_date,
            opening_balance=q2(opening_balance),
            closing_balance=q2(running_balance),
            rows=report_rows,
        )

    def _load_opening_balance(
        self,
        *,
        owner_id: int,
        receivable_account_id: int,
        from_date: str | None,
    ) -> Decimal:
        if from_date is None:
            return Decimal("0.00")

        row = self.conn.execute(
            """
            SELECT
                COALESCE(SUM(jel.debit_amount), 0) AS debit_total,
                COALESCE(SUM(jel.credit_amount), 0) AS credit_total
            FROM journal_entry_lines jel
            JOIN journal_entries je
              ON je.id = jel.journal_entry_id
            WHERE jel.owner_id = ?
              AND jel.account_id = ?
              AND je.status = 'POSTED'
              AND je.entry_date < ?
            """,
            (owner_id, receivable_account_id, from_date),
        ).fetchone()

        return q2(row["debit_total"]) - q2(row["credit_total"])