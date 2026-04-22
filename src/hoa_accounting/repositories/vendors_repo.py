"""Repository for vendor bills and payments."""

from __future__ import annotations

import sqlite3

from .base import BaseRepository


class VendorsRepository(BaseRepository):
    """Database access for vendor bills and bill payments."""

    def list_vendor_bills(self, *, limit: int = 200) -> list[sqlite3.Row]:
        """Return recent vendor bills joined to vendor and journal metadata.

        Ordered newest-first by invoice_date (ties broken by id) so the
        most-recently entered bills land at the top of the list page.
        ``limit`` bounds memory when the list grows over years of data;
        200 is easily enough for a typical HOA year of vendor activity.
        """
        return list(
            self.conn.execute(
                """
                SELECT
                    vb.id,
                    vb.vendor_id,
                    vb.invoice_number,
                    vb.invoice_date,
                    vb.due_date,
                    vb.amount,
                    vb.fund_code,
                    vb.status,
                    vb.description,
                    vb.category_id,
                    vb.journal_entry_id,
                    v.vendor_name,
                    je.entry_number
                FROM vendor_bills vb
                JOIN vendors v ON v.id = vb.vendor_id
                LEFT JOIN journal_entries je ON je.id = vb.journal_entry_id
                ORDER BY vb.invoice_date DESC, vb.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )

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

    def get_vendor(self, vendor_id: int) -> sqlite3.Row | None:
        """Return a single vendor row by id, or None."""
        return self.conn.execute(
            """
            SELECT id, vendor_name, contact_name, email, phone,
                   address_1, address_2, city, state, postal_code,
                   notes, active_flag
            FROM vendors WHERE id = ?
            """,
            (vendor_id,),
        ).fetchone()

    def insert_vendor(
        self,
        *,
        vendor_name: str,
        contact_name: str | None,
        email: str | None,
        phone: str | None,
        address_1: str | None,
        address_2: str | None,
        city: str | None,
        state: str | None,
        postal_code: str | None,
        notes: str | None,
    ) -> int:
        """Insert a new vendor and return its id."""
        cur = self.conn.execute(
            """
            INSERT INTO vendors
                (vendor_name, contact_name, email, phone,
                 address_1, address_2, city, state, postal_code, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (vendor_name, contact_name, email, phone,
             address_1, address_2, city, state, postal_code, notes),
        )
        return int(cur.lastrowid)

    def update_vendor(
        self,
        *,
        vendor_id: int,
        vendor_name: str,
        contact_name: str | None,
        email: str | None,
        phone: str | None,
        address_1: str | None,
        address_2: str | None,
        city: str | None,
        state: str | None,
        postal_code: str | None,
        notes: str | None,
        active_flag: bool,
    ) -> None:
        """Update editable fields on an existing vendor."""
        self.conn.execute(
            """
            UPDATE vendors
               SET vendor_name = ?, contact_name = ?, email = ?, phone = ?,
                   address_1 = ?, address_2 = ?, city = ?, state = ?,
                   postal_code = ?, notes = ?, active_flag = ?,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (vendor_name, contact_name, email, phone,
             address_1, address_2, city, state, postal_code, notes,
             1 if active_flag else 0, vendor_id),
        )

    def has_bills(self, vendor_id: int) -> bool:
        """Return True if the vendor has any vendor_bills records."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM vendor_bills WHERE vendor_id = ?",
            (vendor_id,),
        ).fetchone()
        return int(row[0]) > 0

    def delete_vendor(self, vendor_id: int) -> None:
        """Hard-delete a vendor with no bills."""
        self.conn.execute("DELETE FROM vendors WHERE id = ?", (vendor_id,))

    def insert_vendor_bill(
        self,
        *,
        vendor_id: int,
        invoice_number: str,
        invoice_date: str,
        due_date: str,
        amount: str,
        fund_code: str,
        description: str,
        category_id: int | None = None,
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
                fund_code,
                status,
                description,
                category_id
            ) VALUES (?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
            """,
            (
                vendor_id,
                invoice_number,
                invoice_date,
                due_date,
                amount,
                fund_code,
                description,
                category_id,
            ),
        )
        return int(cur.lastrowid)

    def get_vendor_bill(self, vendor_bill_id: int) -> "sqlite3.Row | None":
        return self.conn.execute(
            """
            SELECT vb.id, vb.vendor_id, vb.invoice_number, vb.invoice_date,
                   vb.due_date, vb.amount, vb.fund_code, vb.status,
                   vb.description, vb.category_id,
                   v.vendor_name
            FROM vendor_bills vb
            JOIN vendors v ON v.id = vb.vendor_id
            WHERE vb.id = ?
            """,
            (vendor_bill_id,),
        ).fetchone()

    def vendor_bill_has_payments(self, vendor_bill_id: int) -> bool:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM bill_payments WHERE vendor_bill_id = ?",
            (vendor_bill_id,),
        ).fetchone()
        return int(row[0]) > 0

    def update_vendor_bill(
        self,
        vendor_bill_id: int,
        *,
        invoice_number: str,
        invoice_date: str,
        due_date: str | None,
        amount: str | None,
        fund_code: str,
        description: str,
        category_id: int | None,
    ) -> None:
        """Update editable fields on a vendor bill.

        ``amount`` is only applied when non-None — callers must pass None when
        a payment is already attached so the recorded payment amount stays
        consistent with the bill.
        """
        if amount is None:
            self.conn.execute(
                """
                UPDATE vendor_bills
                   SET invoice_number = ?, invoice_date = ?, due_date = ?,
                       fund_code = ?, description = ?, category_id = ?,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = ?
                """,
                (invoice_number, invoice_date, due_date, fund_code,
                 description, category_id, vendor_bill_id),
            )
        else:
            self.conn.execute(
                """
                UPDATE vendor_bills
                   SET invoice_number = ?, invoice_date = ?, due_date = ?,
                       amount = ?, fund_code = ?, description = ?,
                       category_id = ?, updated_at = CURRENT_TIMESTAMP
                 WHERE id = ?
                """,
                (invoice_number, invoice_date, due_date, amount, fund_code,
                 description, category_id, vendor_bill_id),
            )
        self.conn.commit()

    def insert_bill_payment(
        self,
        *,
        vendor_bill_id: int,
        payment_date: str,
        amount: str,
        bank_account_id: int,
        check_number: str | None,
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
                notes
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                vendor_bill_id,
                payment_date,
                amount,
                bank_account_id,
                check_number,
                notes,
            ),
        )
        return int(cur.lastrowid)
