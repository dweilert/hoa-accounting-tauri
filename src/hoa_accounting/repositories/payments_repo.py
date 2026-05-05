"""Repository for payments."""

from __future__ import annotations

import sqlite3

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
        notes: str,
        deposit_batch_id: int | None = None,
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
                notes,
                deposit_batch_id
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
                notes,
                deposit_batch_id,
            ),
        )
        return int(cur.lastrowid or 0)

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

    def list_payments(self, *, limit: int = 500) -> list[sqlite3.Row]:
        """Return recent homeowner payments joined to owner name, bank, and
        first lot (for visual context). Ordered newest-first by payment_date."""
        return list(
            self.conn.execute(
                """
                SELECT
                    p.id,
                    p.receipt_number,
                    p.owner_id,
                    p.payment_date,
                    p.amount,
                    p.payment_method,
                    p.reference_number,
                    p.bank_account_id,
                    p.notes,
                    p.deposit_batch_id,
                    p.category_id,
                    TRIM(COALESCE(o.first_name, '') || ' ' || COALESCE(o.last_name, ''))
                        AS owner_name,
                    ba.account_name AS bank_account_name,
                    ba.account_last4 AS bank_account_last4
                FROM payments p
                JOIN owners       o  ON o.id  = p.owner_id
                JOIN bank_accounts ba ON ba.id = p.bank_account_id
                ORDER BY p.payment_date DESC, p.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )

    def get_payment(self, payment_id: int) -> sqlite3.Row | None:
        return self.conn.execute(  # type: ignore[no-any-return]
            """
            SELECT id, receipt_number, owner_id, payment_date, amount,
                   payment_method, reference_number, bank_account_id,
                   notes, deposit_batch_id, category_id
            FROM payments WHERE id = ?
            """,
            (payment_id,),
        ).fetchone()

    def payment_has_applications(self, payment_id: int) -> bool:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM payment_applications WHERE payment_id = ?",
            (payment_id,),
        ).fetchone()
        return int(row[0]) > 0

    def update_payment(
        self,
        payment_id: int,
        *,
        receipt_number: str,
        payment_date: str,
        amount: str | None,
        payment_method: str,
        reference_number: str | None,
        bank_account_id: int,
        notes: str,
        category_id: int | None,
    ) -> None:
        """Update editable fields. Pass amount=None to skip the amount
        column when applications are attached (the amount must stay in
        sync with payment_applications.applied_amount)."""
        if amount is None:
            self.conn.execute(
                """
                UPDATE payments
                   SET receipt_number = ?, payment_date = ?,
                       payment_method = ?, reference_number = ?,
                       bank_account_id = ?, notes = ?, category_id = ?
                 WHERE id = ?
                """,
                (
                    receipt_number,
                    payment_date,
                    payment_method,
                    reference_number,
                    bank_account_id,
                    notes,
                    category_id,
                    payment_id,
                ),
            )
        else:
            self.conn.execute(
                """
                UPDATE payments
                   SET receipt_number = ?, payment_date = ?, amount = ?,
                       payment_method = ?, reference_number = ?,
                       bank_account_id = ?, notes = ?, category_id = ?
                 WHERE id = ?
                """,
                (
                    receipt_number,
                    payment_date,
                    amount,
                    payment_method,
                    reference_number,
                    bank_account_id,
                    notes,
                    category_id,
                    payment_id,
                ),
            )
        self.conn.commit()

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

    def get_unapplied_credits_for_owner(self, owner_id: int) -> list[dict]:
        """Return payments for this owner that have an unapplied balance.

        Unapplied balance = payment.amount − SUM(applied_amount across all
        payment_applications for that payment).  Only payments with a
        positive unapplied balance are returned, ordered oldest-first so
        credits drain in the order they were received.
        """
        rows = self.conn.execute(
            """
            SELECT
                p.id,
                p.receipt_number,
                p.payment_date,
                p.amount,
                COALESCE(SUM(pa.applied_amount), 0)                        AS applied_total,
                p.amount - COALESCE(SUM(pa.applied_amount), 0)             AS unapplied_amount
            FROM payments p
            LEFT JOIN payment_applications pa ON pa.payment_id = p.id
            WHERE p.owner_id = ?
            GROUP BY p.id, p.receipt_number, p.payment_date, p.amount
            HAVING p.amount - COALESCE(SUM(pa.applied_amount), 0) > 0.005
            ORDER BY p.payment_date ASC, p.id ASC
            """,
            (owner_id,),
        ).fetchall()
        return [dict(r) for r in rows]
