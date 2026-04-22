"""Repository for bank reconciliation data access (single-entry model).

The reconciliation view rows are polymorphic single-entry records
(payments, income_batches, bill_payments, reserve_transfers) keyed by
``(source_type, source_id)``. Each row carries whether a bank_transaction
has linked it (``has_bank_match``) and whether it is cleared in this or
a prior reconciliation.

Cleared state is tracked in ``reconciliation_clears`` with the same
polymorphic key. OFX imports no longer auto-insert clears — that is
reserved for the monthly reconciliation workflow.
"""

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
                br.statement_beginning_balance,
                br.statement_ending_date,
                br.statement_ending_balance,
                br.book_balance,
                br.status,
                br.reconciled_at,
                br.created_at,
                ba.account_name,
                ba.institution_name,
                ba.account_last4,
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

    def get_expected_beginning_balance(
        self, bank_account_id: int
    ) -> tuple[Decimal, str]:
        """Return (expected_beginning_balance, source_label).

        Uses the most recent FINALIZED reconciliation's stored book_balance
        when available, then falls back to the bank account's opening
        balance (stored on bank_accounts or opening_balances).
        """
        prior = self.conn.execute(
            """
            SELECT book_balance
            FROM bank_reconciliations
            WHERE bank_account_id = ? AND status = 'FINALIZED'
            ORDER BY statement_ending_date DESC, id DESC
            LIMIT 1
            """,
            (bank_account_id,),
        ).fetchone()
        if prior and prior["book_balance"] is not None:
            return Decimal(str(prior["book_balance"])), "prior reconciliation"

        row = self.conn.execute(
            "SELECT opening_balance, opening_balance_date FROM bank_accounts WHERE id = ?",
            (bank_account_id,),
        ).fetchone()
        if row and row["opening_balance"] is not None:
            label = (
                f"account opening balance ({row['opening_balance_date']})"
                if row["opening_balance_date"]
                else "account opening balance"
            )
            return Decimal(str(row["opening_balance"])), label

        ob = self.conn.execute(
            "SELECT amount, as_of_date FROM opening_balances "
            "WHERE entity_type = 'BANK_ACCOUNT' AND entity_id = ?",
            (bank_account_id,),
        ).fetchone()
        if ob:
            label = (
                f"account opening balance ({ob['as_of_date']})"
                if ob["as_of_date"]
                else "account opening balance"
            )
            return Decimal(str(ob["amount"])), label

        return Decimal("0"), "account opening balance"

    def list_active_bank_accounts(self) -> list[sqlite3.Row]:
        """Return active bank accounts for the new-recon form."""
        return list(
            self.conn.execute(
                """
                SELECT
                    ba.id,
                    ba.account_name,
                    ba.institution_name,
                    ba.account_last4,
                    COALESCE(ba.opening_balance, 0) AS opening_balance,
                    ba.opening_balance_date,
                    a.account_number         AS gl_account_number,
                    a.account_name           AS gl_account_name
                FROM bank_accounts ba
                JOIN accounts a ON a.id = ba.gl_account_id
                WHERE ba.active_flag = 1
                ORDER BY ba.account_name COLLATE NOCASE
                """
            ).fetchall()
        )

    def get_working_rows(self, reconciliation_id: int) -> list[sqlite3.Row]:
        """Return every single-entry record posted against this bank account
        up through the statement date, annotated with bank-match and
        cleared state.

        Columns:
          source_type    PAYMENT | INCOME_BATCH | BILL_PAYMENT | RESERVE_TRANSFER
          source_id      int
          item_date      YYYY-MM-DD
          amount         signed (+deposit, -withdrawal)
          description    short text
          has_bank_match 1 if a bank_transaction links to this row, else 0
          bank_txn_date  date of the matched bank_transaction (or NULL)
          cleared_this   1 if in this recon's clears, else 0
          cleared_prior  1 if in any other finalized recon's clears
        """
        return list(
            self.conn.execute(
                """
                WITH ctx AS (
                    SELECT br.id                   AS recon_id,
                           br.bank_account_id,
                           br.statement_ending_date,
                           ba.gl_account_id
                    FROM bank_reconciliations br
                    JOIN bank_accounts ba ON ba.id = br.bank_account_id
                    WHERE br.id = ?
                ),
                matched AS (
                    SELECT bt.matched_source_type AS source_type,
                           bt.matched_source_id   AS source_id,
                           MAX(bt.transaction_date) AS last_txn_date
                    FROM bank_transactions bt
                    JOIN ctx ON ctx.bank_account_id = bt.bank_account_id
                    WHERE bt.matched_source_type IS NOT NULL
                      AND bt.matched_source_id   IS NOT NULL
                      AND bt.matched_source_type <> 'DEPOSIT_BATCH'
                    GROUP BY bt.matched_source_type, bt.matched_source_id
                ),
                matched_batches AS (
                    -- Deposit batches matched as a unit → surface each member
                    -- payment as "has_bank_match"
                    SELECT 'PAYMENT'  AS source_type,
                           p.id       AS source_id,
                           MAX(bt.transaction_date) AS last_txn_date
                    FROM bank_transactions bt
                    JOIN payments p ON p.deposit_batch_id = bt.matched_source_id
                    JOIN ctx ON ctx.bank_account_id = bt.bank_account_id
                    WHERE bt.matched_source_type = 'DEPOSIT_BATCH'
                    GROUP BY p.id
                ),
                cleared_this AS (
                    SELECT source_type, source_id
                    FROM reconciliation_clears
                    WHERE reconciliation_id = (SELECT recon_id FROM ctx)
                ),
                cleared_prior AS (
                    SELECT rc.source_type, rc.source_id
                    FROM reconciliation_clears rc
                    JOIN bank_reconciliations br2
                        ON br2.id = rc.reconciliation_id
                    JOIN ctx ON ctx.bank_account_id = br2.bank_account_id
                    WHERE br2.id != (SELECT recon_id FROM ctx)
                      AND br2.status = 'FINALIZED'
                ),
                all_items AS (
                    SELECT 'PAYMENT' AS source_type, p.id AS source_id,
                           p.payment_date AS item_date,
                           CAST(p.amount AS REAL) AS amount,
                           COALESCE(p.notes, '') AS description
                    FROM payments p, ctx
                    WHERE p.bank_account_id = ctx.bank_account_id
                      AND p.payment_date <= ctx.statement_ending_date
                    UNION ALL
                    SELECT 'INCOME_BATCH', ib.id,
                           ib.posting_date,
                           CAST(ib.total_amount AS REAL),
                           COALESCE(ib.income_description, '')
                    FROM income_batches ib, ctx
                    WHERE ib.bank_account_id = ctx.bank_account_id
                      AND ib.posting_date <= ctx.statement_ending_date
                    UNION ALL
                    SELECT 'BILL_PAYMENT', bp.id,
                           bp.payment_date,
                           -CAST(bp.amount AS REAL),
                           COALESCE(bp.notes, '')
                    FROM bill_payments bp, ctx
                    WHERE bp.bank_account_id = ctx.bank_account_id
                      AND bp.payment_date <= ctx.statement_ending_date
                    UNION ALL
                    SELECT 'RESERVE_TRANSFER', rt.id,
                           rt.transfer_date,
                           CASE WHEN rt.to_account_id = ctx.gl_account_id
                                THEN  CAST(rt.amount AS REAL)
                                ELSE -CAST(rt.amount AS REAL) END,
                           COALESCE(rt.notes, '')
                    FROM reserve_transfers rt, ctx
                    WHERE (rt.from_account_id = ctx.gl_account_id
                           OR rt.to_account_id = ctx.gl_account_id)
                      AND rt.transfer_date <= ctx.statement_ending_date
                )
                SELECT
                    ai.source_type,
                    ai.source_id,
                    ai.item_date,
                    ai.amount,
                    ai.description,
                    CASE WHEN m.source_id IS NOT NULL
                         OR mb.source_id IS NOT NULL
                         THEN 1 ELSE 0 END AS has_bank_match,
                    COALESCE(m.last_txn_date, mb.last_txn_date) AS bank_txn_date,
                    CASE WHEN ct.source_id IS NOT NULL THEN 1 ELSE 0 END
                        AS cleared_this,
                    CASE WHEN cp.source_id IS NOT NULL THEN 1 ELSE 0 END
                        AS cleared_prior
                FROM all_items ai
                LEFT JOIN matched m
                    ON m.source_type = ai.source_type AND m.source_id = ai.source_id
                LEFT JOIN matched_batches mb
                    ON mb.source_type = ai.source_type AND mb.source_id = ai.source_id
                LEFT JOIN cleared_this ct
                    ON ct.source_type = ai.source_type AND ct.source_id = ai.source_id
                LEFT JOIN cleared_prior cp
                    ON cp.source_type = ai.source_type AND cp.source_id = ai.source_id
                ORDER BY ai.item_date ASC, ai.source_type, ai.source_id
                """,
                (reconciliation_id,),
            ).fetchall()
        )

    def get_balance_summary(
        self, reconciliation_id: int
    ) -> dict[str, str | bool | int]:
        """Compute book balance, cleared balance, and difference.

        - book_balance    = opening + sum of *all* single-entry activity
                            through the statement date
        - cleared_balance = opening + sum of activity cleared (this + prior)
        - difference      = statement_balance - cleared_balance
        - balanced        = difference is zero
        """
        recon = self.get_reconciliation(reconciliation_id)
        if not recon:
            return {}

        statement = Decimal(str(recon["statement_ending_balance"]))
        opening, _ = self.get_expected_beginning_balance(
            int(recon["bank_account_id"])
        )

        rows = self.get_working_rows(reconciliation_id)
        book_balance = opening
        cleared_balance = opening
        cleared_count = 0
        outstanding_count = 0

        for row in rows:
            amt = Decimal(str(row["amount"]))
            book_balance += amt
            if row["cleared_this"] or row["cleared_prior"]:
                cleared_balance += amt
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
        statement_beginning_balance: str | None = None,
    ) -> int:
        """Insert a new OPEN reconciliation and return its id."""
        cur = self.conn.execute(
            """
            INSERT INTO bank_reconciliations
                (bank_account_id, statement_ending_date,
                 statement_ending_balance, statement_beginning_balance,
                 book_balance, status)
            VALUES (?, ?, ?, ?, 0, 'OPEN')
            """,
            (
                bank_account_id,
                statement_ending_date,
                statement_ending_balance,
                statement_beginning_balance,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)  # type: ignore[arg-type]

    def clear_item(
        self,
        reconciliation_id: int,
        source_type: str,
        source_id: int,
    ) -> None:
        """Mark a single-entry record as cleared in this reconciliation."""
        self.conn.execute(
            """
            INSERT OR IGNORE INTO reconciliation_clears
                (reconciliation_id, source_type, source_id)
            VALUES (?, ?, ?)
            """,
            (reconciliation_id, source_type, source_id),
        )
        self.conn.commit()

    def unclear_item(
        self,
        reconciliation_id: int,
        source_type: str,
        source_id: int,
    ) -> None:
        """Remove a record's cleared status from this reconciliation."""
        self.conn.execute(
            """
            DELETE FROM reconciliation_clears
             WHERE reconciliation_id = ?
               AND source_type = ?
               AND source_id   = ?
            """,
            (reconciliation_id, source_type, source_id),
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
