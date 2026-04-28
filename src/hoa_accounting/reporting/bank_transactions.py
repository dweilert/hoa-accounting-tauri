"""All Bank Transactions report — every bank line in a date range,
including validated, unvalidated, and ignored rows."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.reporting.dto import (
    BankTransactionsReport,
    BankTransactionsReportRow,
)
from hoa_accounting.validators.common import q2


class BankTransactionsReportService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def generate(
        self,
        *,
        from_date: str,
        to_date: str,
        bank_account_id: int | None = None,
    ) -> BankTransactionsReport:
        where = "bt.transaction_date >= ? AND bt.transaction_date <= ?"
        params: list[object] = [from_date, to_date]
        bank_name: str | None = None
        if bank_account_id:
            where += " AND bt.bank_account_id = ?"
            params.append(bank_account_id)
            ba = self.conn.execute(
                "SELECT account_name FROM bank_accounts WHERE id = ?",
                (bank_account_id,),
            ).fetchone()
            if ba:
                bank_name = str(ba["account_name"])

        rows = self.conn.execute(
            f"""
            SELECT bt.transaction_date,
                   ba.account_name AS bank_account,
                   bt.description,
                   COALESCE(bt.memo, '') AS memo,
                   bt.amount,
                   COALESCE(bt.transaction_type, '') AS transaction_type,
                   COALESCE(bt.match_type, 'UNMATCHED') AS match_type,
                   COALESCE(bt.matched_source_type, '') AS matched_source_type,
                   COALESCE(CAST(bt.matched_source_id AS TEXT), '') AS matched_source_id,
                   bt.validation_status,
                   COALESCE(r.rule_name, '') AS rule_name
            FROM bank_transactions bt
            JOIN bank_accounts ba ON ba.id = bt.bank_account_id
            LEFT JOIN bank_transaction_rules r ON r.id = bt.rule_id
            WHERE {where}
            ORDER BY bt.transaction_date, bt.id
            """,
            params,
        ).fetchall()

        report_rows: list[BankTransactionsReportRow] = []
        total_in = Decimal("0.00")
        total_out = Decimal("0.00")
        for r in rows:
            amount = q2(r["amount"])
            if amount >= 0:
                total_in += amount
            else:
                total_out += amount
            report_rows.append(
                BankTransactionsReportRow(
                    transaction_date=str(r["transaction_date"]),
                    bank_account=str(r["bank_account"] or ""),
                    description=str(r["description"] or ""),
                    memo=str(r["memo"] or ""),
                    amount=amount,
                    transaction_type=str(r["transaction_type"] or ""),
                    match_type=str(r["match_type"] or ""),
                    matched_source_type=str(r["matched_source_type"] or ""),
                    matched_source_id=str(r["matched_source_id"] or ""),
                    validation_status=str(r["validation_status"] or ""),
                    rule_name=str(r["rule_name"] or ""),
                )
            )

        return BankTransactionsReport(
            from_date=from_date,
            to_date=to_date,
            bank_account_name=bank_name,
            rows=report_rows,
            total_in=total_in,
            total_out=total_out,
        )
