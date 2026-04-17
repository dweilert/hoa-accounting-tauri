"""Repository for bank reconciliation data access."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from .base import BaseRepository


class ReconciliationRepository(BaseRepository):
    """Database access for bank reconciliations."""

    # ── Queries ────────────────────────────────────────────────────────

    def list_reconciliations(self) -> list[sqlite3.Row]:
        """Return all reconciliations, newest statement date first."""
        return list(
            self.conn.execute(
                """
                SELECT
                    br.id,
                    br.bank_account_id,
                    br.statement_ending_date,
                    br.statement_ending_balance,
                    br.book_balance,
                    br.status,
                    br.reconciled_at,
                    br.created_at,
                    ba.account_name,
                    ba.institution_name,
                    ba.account_last4,
                    ba.opening_balance,
                    ba.opening_balance_date,
                    a.account_number AS gl_account_number
                FROM bank_reconciliations br
                JOIN bank_accounts ba ON ba.id = br.bank_account_id
                JOIN accounts a ON a.id = ba.gl_account_id
                ORDER BY br.statement_ending_date DESC, br.id DESC
                """
            ).fetchall()
        )

    def get_reconciliation(self, reconciliation_id: int) -> sqlite3.Row | None:
        """Return one reconciliation with bank-account details, or None."""
        return self.conn.execute(
            """
            SELECT
                br.id,
                br.bank_account_id,
                br.statement_ending_date,
                br.statement_ending_balance,
                br.book_balance,
                br.status,
                br.reconciled_at,
                br.created_at,
                ba.account_name,
                ba.institution_name,
                ba.account_last4,
                ba.opening_balance,
                ba.opening_balance_date,
                ba.gl_account_id,
                a.account_number AS gl_account_number,
                a.account_name   AS gl_account_name
            FROM bank_reconciliations br
            JOIN bank_accounts ba ON ba.id = br.bank_account_id
            JOIN accounts a ON a.id = ba.gl_account_id
            WHERE br.id = ?
            """,
            (reconciliation_id,),
        ).fetchone()

    def list_active_bank_accounts(self) -> list[sqlite3.Row]:
        """Return active bank accounts with opening-balance info for the new-recon form."""
        return list(
            self.conn.execute(
                """
                SELECT
                    ba.id,
                    ba.account_name,
                    ba.institution_name,
                    ba.account_last4,
                    ba.opening_balance,
                    ba.opening_balance_date,
                    a.account_number AS gl_account_number,
                    a.account_name   AS gl_account_name
                FROM bank_accounts ba
                JOIN accounts a ON a.id = ba.gl_account_id
                WHERE ba.active_flag = 1
                ORDER BY ba.account_name COLLATE NOCASE
                """
            ).fetchall()
        )

    def get_working_lines(self, reconciliation_id: int) -> list[sqlite3.Row]:
        """Return all posted JE lines for the bank account, up to the statement date.

        Each row includes:
          cleared_this  — 1 if cleared in *this* reconciliation
          cleared_prior — 1 if cleared in a prior FINALIZED reconciliation
        """
        return list(
            self.conn.execute(
                """
                SELECT
                    jel.id                          AS line_id,
                    je.id                           AS journal_entry_id,
                    je.entry_date,
                    je.memo,
                    je.source,
                    jel.description                 AS line_description,
                    CAST(jel.debit_amount  AS REAL)  AS debit_amount,
                    CAST(jel.credit_amount AS REAL)  AS credit_amount,
                    CASE WHEN rc_this.journal_entry_line_id IS NOT NULL
                         THEN 1 ELSE 0 END           AS cleared_this,
                    CASE WHEN rc_prior.journal_entry_line_id IS NOT NULL
                         THEN 1 ELSE 0 END           AS cleared_prior
                FROM journal_entry_lines jel
                JOIN journal_entries je ON je.id = jel.journal_entry_id
                -- Scope to the bank account's GL account
                JOIN bank_reconciliations br ON br.id = ?
                JOIN bank_accounts ba ON ba.id = br.bank_account_id
                    AND ba.gl_account_id = jel.account_id
                -- Cleared in this reconciliation?
                LEFT JOIN reconciliation_clears rc_this
                    ON rc_this.journal_entry_line_id = jel.id
                    AND rc_this.reconciliation_id = br.id
                -- Cleared in any prior FINALIZED reconciliation for this account?
                LEFT JOIN reconciliation_clears rc_prior
                    ON rc_prior.journal_entry_line_id = jel.id
                    AND rc_prior.reconciliation_id IN (
                        SELECT id FROM bank_reconciliations
                        WHERE bank_account_id = ba.id
                          AND status = 'FINALIZED'
                          AND id != br.id
                    )
                WHERE je.status = 'POSTED'
                  AND je.entry_date <= br.statement_ending_date
                ORDER BY je.entry_date ASC, jel.id ASC
                """,
                (reconciliation_id,),
            ).fetchall()
        )

    def get_balance_summary(
        self, reconciliation_id: int
    ) -> dict[str, str | bool]:
        """Compute book balance, cleared balance, and difference.

        Returns a dict suitable for JSON responses and template rendering.
        """
        recon = self.get_reconciliation(reconciliation_id)
        if not recon:
            return {}

        opening = Decimal(str(recon["opening_balance"] or 0))
        statement = Decimal(str(recon["statement_ending_balance"]))

        rows = self.get_working_lines(reconciliation_id)
        book_balance = opening
        cleared_balance = opening
        cleared_count = 0
        outstanding_count = 0

        for row in rows:
            net = Decimal(str(row["debit_amount"])) - Decimal(str(row["credit_amount"]))
            book_balance += net
            if row["cleared_this"] or row["cleared_prior"]:
                cleared_balance += net
                cleared_count += 1
            else:
                outstanding_count += 1

        difference = statement - cleared_balance

        def fmt(d: Decimal) -> str:
            return f"{d:,.2f}"

        return {
            "book_balance": fmt(book_balance),
            "cleared_balance": fmt(cleared_balance),
            "statement_balance": fmt(statement),
            "difference": fmt(difference),
            "balanced": difference == Decimal("0"),
            "cleared_count": cleared_count,
            "outstanding_count": outstanding_count,
        }

    # ── Mutations ──────────────────────────────────────────────────────

    def insert_reconciliation(
        self,
        *,
        bank_account_id: int,
        statement_ending_date: str,
        statement_ending_balance: str,
    ) -> int:
        """Insert a new OPEN reconciliation and return its id."""
        cur = self.conn.execute(
            """
            INSERT INTO bank_reconciliations
                (bank_account_id, statement_ending_date,
                 statement_ending_balance, book_balance, status)
            VALUES (?, ?, ?, 0, 'OPEN')
            """,
            (bank_account_id, statement_ending_date, statement_ending_balance),
        )
        self.conn.commit()
        return int(cur.lastrowid)  # type: ignore[arg-type]

    def clear_line(self, reconciliation_id: int, line_id: int) -> None:
        """Mark a JE line as cleared in this reconciliation."""
        self.conn.execute(
            """
            INSERT OR IGNORE INTO reconciliation_clears
                (reconciliation_id, journal_entry_line_id)
            VALUES (?, ?)
            """,
            (reconciliation_id, line_id),
        )
        self.conn.commit()

    def unclear_line(self, reconciliation_id: int, line_id: int) -> None:
        """Remove a JE line's cleared status from this reconciliation."""
        self.conn.execute(
            """
            DELETE FROM reconciliation_clears
             WHERE reconciliation_id = ?
               AND journal_entry_line_id = ?
            """,
            (reconciliation_id, line_id),
        )
        self.conn.commit()

    def finalize_reconciliation(
        self, reconciliation_id: int, book_balance: str
    ) -> None:
        """Finalize a reconciliation: set status, store computed book balance."""
        self.conn.execute(
            """
            UPDATE bank_reconciliations
               SET status       = 'FINALIZED',
                   book_balance = ?,
                   reconciled_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (book_balance, reconciliation_id),
        )
        self.conn.commit()

    def reopen_reconciliation(self, reconciliation_id: int) -> None:
        """Reopen a finalized reconciliation for further editing."""
        self.conn.execute(
            """
            UPDATE bank_reconciliations
               SET status        = 'OPEN',
                   book_balance  = 0,
                   reconciled_at = NULL
             WHERE id = ?
            """,
            (reconciliation_id,),
        )
        self.conn.commit()

    def delete_reconciliation(self, reconciliation_id: int) -> None:
        """Delete a reconciliation (clears cascade-delete)."""
        self.conn.execute(
            "DELETE FROM bank_reconciliations WHERE id = ?",
            (reconciliation_id,),
        )
        self.conn.commit()
