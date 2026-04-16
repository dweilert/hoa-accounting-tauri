"""Repository for payments."""

from __future__ import annotations

from .base import BaseRepository


class PaymentsRepository(BaseRepository):
    """Database access for owner payments."""

    def insert_payment(
        self,
        *,
        receipt_number: str,
        owner_id: int,
        payment_date: str,
        amount: str,
        payment_method: str,
        reference_number: str | None,
        bank_account_id: int,
        journal_entry_id: int,
        notes: str,
    ) -> int:
        """Insert a payment and return its id."""
        cur = self.conn.execute(
            """
            INSERT INTO payments (
                receipt_number,
                owner_id,
                payment_date,
                amount,
                payment_method,
                reference_number,
                bank_account_id,
                journal_entry_id,
                notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt_number,
                owner_id,
                payment_date,
                amount,
                payment_method,
                reference_number,
                bank_account_id,
                journal_entry_id,
                notes,
            ),
        )
        return int(cur.lastrowid)

    def insert_payment_application(
        self,
        *,
        payment_id: int,
        assessment_id: int,
        applied_amount: str,
    ) -> None:
        """Insert a payment application row."""
        self.conn.execute(
            """
            INSERT INTO payment_applications (
                payment_id,
                assessment_id,
                applied_amount
            ) VALUES (?, ?, ?)
            """,
            (payment_id, assessment_id, applied_amount),
        )
