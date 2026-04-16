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
        deposit_batch_id: int | None = None,
    ) -> int:
        """Insert a payment and return its id.

        ``deposit_batch_id`` is optional: standalone payments (legacy
        single-payment entry, future imports) leave it NULL; payments
        entered via the batch deposit form point at their batch.
        """
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
                notes,
                deposit_batch_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                deposit_batch_id,
            ),
        )
        return int(cur.lastrowid)

    def next_receipt_number(self, payment_date: str) -> str:
        """Generate a unique receipt number for a given date.

        Mirrors the JE-number convention (prefix-YYYYMMDD-NNNN). Callers
        still need to handle UNIQUE-collision retries the same way
        JournalRepository does when concurrent posters land on the same
        base number.
        """
        date_part = payment_date.replace("-", "")
        prefix = f"RCT-{date_part}-"
        row = self.conn.execute(
            """
            SELECT receipt_number FROM payments
            WHERE receipt_number LIKE ?
            ORDER BY receipt_number DESC
            LIMIT 1
            """,
            (f"{prefix}%",),
        ).fetchone()
        if row is None:
            nxt = 1
        else:
            nxt = int(str(row["receipt_number"]).split("-")[-1]) + 1
        return f"{prefix}{nxt:04d}"

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
