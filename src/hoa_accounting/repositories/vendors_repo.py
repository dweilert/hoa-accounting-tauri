"""Repository for vendor bills and payments."""

from __future__ import annotations

import sqlite3

from .base import BaseRepository


class VendorsRepository(BaseRepository):
    """Database access for vendor bills and bill payments."""

    def list_vendors(self, *, active_only: bool = True) -> list[sqlite3.Row]:
        """Return vendors for a master-data list page."""
        predicates = []
        if active_only:
            predicates.append("active_flag = 1")
        where_sql = f"WHERE {' AND '.join(predicates)}" if predicates else ""
        return list(
            self.conn.execute(
                f"""
                SELECT id, vendor_name, contact_name, email, phone,
                       city, state, postal_code, active_flag
                FROM vendors
                {where_sql}
                ORDER BY vendor_name COLLATE NOCASE
                """
            ).fetchall()
        )

    def insert_vendor_bill(
        self,
        *,
        vendor_id: int,
        invoice_number: str,
        invoice_date: str,
        due_date: str,
        amount: str,
        expense_account_id: int,
        payable_account_id: int,
        fund_code: str,
        journal_entry_id: int,
        description: str,
    ) -> int:
        """Insert a vendor bill and return its id."""
        cur = self.conn.execute(
            """
            INSERT INTO vendor_bills (
                vendor_id,
                invoice_number,
                invoice_date,
                due_date,
                amount,
                expense_account_id,
                payable_account_id,
                fund_code,
                status,
                journal_entry_id,
                description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
            """,
            (
                vendor_id,
                invoice_number,
                invoice_date,
                due_date,
                amount,
                expense_account_id,
                payable_account_id,
                fund_code,
                journal_entry_id,
                description,
            ),
        )
        return int(cur.lastrowid)

    def insert_bill_payment(
        self,
        *,
        vendor_bill_id: int,
        payment_date: str,
        amount: str,
        bank_account_id: int,
        check_number: str | None,
        journal_entry_id: int,
        notes: str,
    ) -> int:
        """Insert a vendor bill payment and return its id."""
        cur = self.conn.execute(
            """
            INSERT INTO bill_payments (
                vendor_bill_id,
                payment_date,
                amount,
                bank_account_id,
                check_number,
                journal_entry_id,
                notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vendor_bill_id,
                payment_date,
                amount,
                bank_account_id,
                check_number,
                journal_entry_id,
                notes,
            ),
        )
        return int(cur.lastrowid)
