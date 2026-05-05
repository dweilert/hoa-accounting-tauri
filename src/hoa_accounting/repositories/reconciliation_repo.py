"""Repository for bank reconciliation data access (single-entry model).

The reconciliation view rows are polymorphic single-entry records
(payments, income_batches, bill_payments, reserve_transfers) keyed by
``(source_type, source_id)``. Each row carries whether a bank_transaction
has linked it (``has_bank_match``) and whether it is cleared in this or
a prior reconciliation.

Cleared state is tracked in ``reconciliation_clears`` keyed by
``bank_transaction_id`` — the bank line is the authoritative statement
that something cleared. Clearing a ledger row in the UI resolves to its
linked bank_transaction (via ``matched_source_*`` or
``bank_transaction_links``) and records the clear against that id. A
ledger record with no bank_transaction counterpart therefore cannot be
cleared until its bank line arrives.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.validators.format import format_money

from .base import BaseRepository


class ReconciliationRepository(BaseRepository):
    """Database access for bank reconciliations."""

    # ── Queries ────────────────────────────────────────────────────────

    def list_reconciliations(self) -> list[sqlite3.Row]:
        """Return all reconciliations, newest statement date first."""
        return list(self.conn.execute("""
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
                    NULL AS gl_account_number
                FROM bank_reconciliations br
                JOIN bank_accounts ba ON ba.id = br.bank_account_id
                ORDER BY br.statement_ending_date DESC, br.id DESC
                """).fetchall())

    def get_reconciliation(self, reconciliation_id: int) -> sqlite3.Row | None:
        """Return one reconciliation with bank-account details, or None."""
        return self.conn.execute(  # type: ignore[no-any-return]
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
                NULL AS gl_account_id,
                NULL AS gl_account_number,
                ba.account_name AS gl_account_name
            FROM bank_reconciliations br
            JOIN bank_accounts ba ON ba.id = br.bank_account_id
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
        return list(self.conn.execute("""
                SELECT
                    ba.id,
                    ba.account_name,
                    ba.institution_name,
                    ba.account_last4,
                    COALESCE(ba.opening_balance, 0) AS opening_balance,
                    ba.opening_balance_date,
                    NULL                          AS gl_account_number,
                    ba.account_name               AS gl_account_name,
                    ba.fund_code                  AS fund_code
                FROM bank_accounts ba
                WHERE ba.active_flag = 1
                ORDER BY ba.account_name COLLATE NOCASE
                """).fetchall())

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
          auto_cleared   1 if linked to a VALIDATED bank transaction (OFX confirmed)
        """
        return list(
            self.conn.execute(
                """
                WITH ctx AS (
                    SELECT br.id                   AS recon_id,
                           br.bank_account_id,
                           br.statement_ending_date,
                           NULL                    AS gl_account_id
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
                -- Bank transactions cleared in THIS reconciliation (by id).
                cleared_bt_this AS (
                    SELECT rc.bank_transaction_id AS bt_id
                    FROM reconciliation_clears rc
                    WHERE rc.reconciliation_id = (SELECT recon_id FROM ctx)
                ),
                -- Bank transactions cleared in any prior FINALIZED reconciliation.
                cleared_bt_prior AS (
                    SELECT rc.bank_transaction_id AS bt_id
                    FROM reconciliation_clears rc
                    JOIN bank_reconciliations br2
                        ON br2.id = rc.reconciliation_id
                    JOIN ctx ON ctx.bank_account_id = br2.bank_account_id
                    WHERE br2.id != (SELECT recon_id FROM ctx)
                      AND br2.status = 'FINALIZED'
                ),
                -- Bank transactions confirmed by OFX import (VALIDATED) within
                -- the statement period — these auto-clear without manual ticking.
                validated_bt AS (
                    SELECT bt.id AS bt_id
                    FROM bank_transactions bt
                    JOIN ctx ON ctx.bank_account_id = bt.bank_account_id
                    WHERE bt.validation_status = 'VALIDATED'
                      AND bt.transaction_date <= ctx.statement_ending_date
                ),
                -- Map validated bank_transactions back to ledger rows using the
                -- same three-path resolution as cleared_this / cleared_prior.
                auto_cleared AS (
                    SELECT bt.matched_source_type AS source_type,
                           bt.matched_source_id   AS source_id
                    FROM bank_transactions bt
                    JOIN validated_bt vb ON vb.bt_id = bt.id
                    WHERE bt.matched_source_type IS NOT NULL
                      AND bt.matched_source_id   IS NOT NULL
                      AND bt.matched_source_type <> 'DEPOSIT_BATCH'
                    UNION
                    SELECT 'PAYMENT', p.id
                    FROM bank_transactions bt
                    JOIN validated_bt vb ON vb.bt_id = bt.id
                    JOIN payments p ON p.deposit_batch_id = bt.matched_source_id
                    WHERE bt.matched_source_type = 'DEPOSIT_BATCH'
                    UNION
                    SELECT btl.ledger_source_type, btl.ledger_source_id
                    FROM bank_transaction_links btl
                    JOIN validated_bt vb ON vb.bt_id = btl.bank_transaction_id
                ),
                -- Map cleared bank_transactions back to the ledger rows they
                -- represent, via both matched_source_* and bank_transaction_links.
                cleared_this AS (
                    SELECT bt.matched_source_type AS source_type,
                           bt.matched_source_id   AS source_id
                    FROM bank_transactions bt
                    JOIN cleared_bt_this ct ON ct.bt_id = bt.id
                    WHERE bt.matched_source_type IS NOT NULL
                      AND bt.matched_source_id   IS NOT NULL
                      AND bt.matched_source_type <> 'DEPOSIT_BATCH'
                    UNION
                    -- Deposit batches cleared as a unit → member payments cleared.
                    SELECT 'PAYMENT', p.id
                    FROM bank_transactions bt
                    JOIN cleared_bt_this ct ON ct.bt_id = bt.id
                    JOIN payments p ON p.deposit_batch_id = bt.matched_source_id
                    WHERE bt.matched_source_type = 'DEPOSIT_BATCH'
                    UNION
                    SELECT btl.ledger_source_type, btl.ledger_source_id
                    FROM bank_transaction_links btl
                    JOIN cleared_bt_this ct ON ct.bt_id = btl.bank_transaction_id
                ),
                cleared_prior AS (
                    SELECT bt.matched_source_type AS source_type,
                           bt.matched_source_id   AS source_id
                    FROM bank_transactions bt
                    JOIN cleared_bt_prior cp ON cp.bt_id = bt.id
                    WHERE bt.matched_source_type IS NOT NULL
                      AND bt.matched_source_id   IS NOT NULL
                      AND bt.matched_source_type <> 'DEPOSIT_BATCH'
                    UNION
                    SELECT 'PAYMENT', p.id
                    FROM bank_transactions bt
                    JOIN cleared_bt_prior cp ON cp.bt_id = bt.id
                    JOIN payments p ON p.deposit_batch_id = bt.matched_source_id
                    WHERE bt.matched_source_type = 'DEPOSIT_BATCH'
                    UNION
                    SELECT btl.ledger_source_type, btl.ledger_source_id
                    FROM bank_transaction_links btl
                    JOIN cleared_bt_prior cp ON cp.bt_id = btl.bank_transaction_id
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
                           CASE WHEN rt.to_bank_account_id = ctx.bank_account_id
                                THEN  CAST(rt.amount AS REAL)
                                ELSE -CAST(rt.amount AS REAL) END,
                           COALESCE(rt.notes, '')
                    FROM reserve_transfers rt, ctx
                    WHERE (rt.from_bank_account_id = ctx.bank_account_id
                           OR rt.to_bank_account_id = ctx.bank_account_id)
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
                        AS cleared_prior,
                    CASE WHEN ac.source_id IS NOT NULL THEN 1 ELSE 0 END
                        AS auto_cleared
                FROM all_items ai
                LEFT JOIN matched m
                    ON m.source_type = ai.source_type AND m.source_id = ai.source_id
                LEFT JOIN matched_batches mb
                    ON mb.source_type = ai.source_type AND mb.source_id = ai.source_id
                LEFT JOIN cleared_this ct
                    ON ct.source_type = ai.source_type AND ct.source_id = ai.source_id
                LEFT JOIN cleared_prior cp
                    ON cp.source_type = ai.source_type AND cp.source_id = ai.source_id
                LEFT JOIN auto_cleared ac
                    ON ac.source_type = ai.source_type AND ac.source_id = ai.source_id
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
        opening, _ = self.get_expected_beginning_balance(int(recon["bank_account_id"]))

        rows = self.get_working_rows(reconciliation_id)
        book_balance = opening
        cleared_balance = opening
        cleared_count = 0
        outstanding_count = 0

        for row in rows:
            amt = Decimal(str(row["amount"]))
            book_balance += amt
            if row["cleared_this"] or row["cleared_prior"] or row["auto_cleared"]:
                cleared_balance += amt
                cleared_count += 1
            else:
                outstanding_count += 1

        difference = statement - cleared_balance

        def fmt(d: Decimal) -> str:
            return format_money(d)

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

    def _resolve_bank_txn_ids(self, source_type: str, source_id: int) -> list[int]:
        """Return bank_transaction_ids that represent a ledger record.

        Resolution order — both paths are checked, and every match is
        returned so that a ledger record represented by multiple bank
        lines (rare, but possible after a correction) clears consistently:

        1. ``bank_transactions.matched_source_type/id`` — the direct link
           written at ingest time, including DEPOSIT_BATCH fan-out for
           member payments.
        2. ``bank_transaction_links`` — the canonical many-to-many link
           table, populated by the Pending Validation flow.
        """
        rows = self.conn.execute(
            """
            SELECT id FROM bank_transactions
             WHERE matched_source_type = ? AND matched_source_id = ?
            UNION
            SELECT bank_transaction_id FROM bank_transaction_links
             WHERE ledger_source_type = ? AND ledger_source_id = ?
            UNION
            -- Deposit-batch fan-in: a PAYMENT whose deposit_batch matches
            -- a bank line's matched_source_id is also covered.
            SELECT bt.id FROM bank_transactions bt
             JOIN payments p ON p.deposit_batch_id = bt.matched_source_id
             WHERE bt.matched_source_type = 'DEPOSIT_BATCH'
               AND ? = 'PAYMENT' AND p.id = ?
            """,
            (source_type, source_id, source_type, source_id, source_type, source_id),
        ).fetchall()
        return [int(r[0]) for r in rows]

    def clear_item(
        self,
        reconciliation_id: int,
        source_type: str,
        source_id: int,
    ) -> bool:
        """Mark a single-entry record as cleared in this reconciliation by
        clearing the bank_transaction(s) that represent it. Returns True
        if at least one clear row was written — False when the ledger
        record has no bank counterpart yet (the user must import the
        statement first)."""
        bt_ids = self._resolve_bank_txn_ids(source_type, source_id)
        if not bt_ids:
            return False
        self.conn.executemany(
            """
            INSERT OR IGNORE INTO reconciliation_clears
                (reconciliation_id, bank_transaction_id)
            VALUES (?, ?)
            """,
            [(reconciliation_id, bt_id) for bt_id in bt_ids],
        )
        self.conn.commit()
        return True

    def unclear_item(
        self,
        reconciliation_id: int,
        source_type: str,
        source_id: int,
    ) -> None:
        """Remove cleared status by resolving to the same bank_transaction(s)
        clear_item would write and deleting their clear rows."""
        bt_ids = self._resolve_bank_txn_ids(source_type, source_id)
        if not bt_ids:
            return
        placeholders = ",".join(["?"] * len(bt_ids))
        self.conn.execute(
            f"""
            DELETE FROM reconciliation_clears
             WHERE reconciliation_id = ?
               AND bank_transaction_id IN ({placeholders})
            """,
            (reconciliation_id, *bt_ids),
        )
        self.conn.commit()

    def clear_bank_transaction(
        self, reconciliation_id: int, bank_transaction_id: int
    ) -> None:
        """Native path — clear by bank_transaction_id. Used by new UIs that
        operate directly on the bank-line queue rather than the ledger view."""
        self.conn.execute(
            """
            INSERT OR IGNORE INTO reconciliation_clears
                (reconciliation_id, bank_transaction_id)
            VALUES (?, ?)
            """,
            (reconciliation_id, bank_transaction_id),
        )
        self.conn.commit()

    def unclear_bank_transaction(
        self, reconciliation_id: int, bank_transaction_id: int
    ) -> None:
        self.conn.execute(
            """
            DELETE FROM reconciliation_clears
             WHERE reconciliation_id = ? AND bank_transaction_id = ?
            """,
            (reconciliation_id, bank_transaction_id),
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
