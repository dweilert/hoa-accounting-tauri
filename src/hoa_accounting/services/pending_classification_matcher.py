"""Match pending classifications to bank transactions.

Given a pending classification (treasurer's pre-bank record of a
payment) and a bank_transactions row (the OFX/CSV-imported entry), this
service finds candidate matches and links them.

This is the second layer of bank-line attribution. The first is the
existing ``bank_transaction_rules`` engine, which matches on
*description text patterns* and auto-posts immediately (see
BankStatementPages._apply_rule). Rules cover the cases where the OFX
line names its source — recurring ACH from a known owner, vendor wire,
etc. They can't help with paper checks, mixed-batch deposits, or
one-off transfers, because the bank text carries no identity.

Pending classifications fill that gap. The treasurer captures identity
up front (lot, owner, category) and this matcher confirms when the
dollars actually land — by *amount + date + bank account*, no text.

Order of attribution per imported bank line:

  1. Rule engine fires (text patterns). If a rule auto-posts, the
     bank_transactions row gets ``matched_source_type`` populated.
  2. This matcher sweeps everything still unmatched and still PENDING.
  3. Anything left lands on the existing Pending Validation page for
     human review.

This module deliberately ignores bank transactions whose
``matched_source_type`` is already set — those belong to rules and we
don't double-claim them.

Matching rules (v1):

- Same ``bank_account_id``.
- Bank tx amount equals classification amount (positive, deposit only).
- Bank tx date is within ±N days of the classification or its expected
  deposit date. Default N = 7 — checks usually clear within a week,
  ACH usually within 1-2 days.
- Classification.status must be ``PENDING`` to be a candidate.
- Bank tx must not already be claimed by a rule (matched_source_type
  IS NULL) or by another classification.

The matcher does not post anything to the GL or to ``payments`` — it
only flips status and stores ``matched_bank_transaction_id``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from hoa_accounting.exceptions import ValidationError

DEFAULT_DATE_WINDOW_DAYS = 7


@dataclass(frozen=True)
class MatchCandidate:
    """One candidate bank-transaction match for a pending classification."""

    bank_transaction_id: int
    transaction_date: str
    description: str
    amount: str
    bank_account_id: int


@dataclass(frozen=True)
class AutoMatchResult:
    matched_count: int
    skipped_ambiguous: int
    skipped_no_candidate: int


class PendingClassificationMatcher:
    """Find/link/unlink matches between classifications and bank transactions."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        date_window_days: int = DEFAULT_DATE_WINDOW_DAYS,
    ) -> None:
        self.conn = conn
        self.date_window_days = int(date_window_days)

    # ── Candidate finders ────────────────────────────────────────────

    def find_candidates_for_classification(self, pc_id: int) -> list[MatchCandidate]:
        """Return bank transactions that could match this classification."""
        pc = self.conn.execute(
            """
            SELECT id, bank_account_id, classification_date,
                   expected_deposit_date, amount, status
            FROM pending_classifications WHERE id = ?
            """,
            (pc_id,),
        ).fetchone()
        if pc is None:
            return []
        if pc["status"] not in ("PENDING", "MATCHED"):
            # Posted/cancelled rows have no useful candidates
            return []

        ref_date = pc["expected_deposit_date"] or pc["classification_date"]
        window = self.date_window_days

        rows = self.conn.execute(
            """
            SELECT bt.id, bt.transaction_date, bt.description, bt.amount,
                   bt.bank_account_id
            FROM bank_transactions bt
            WHERE bt.bank_account_id = ?
              AND ROUND(bt.amount, 2) = ROUND(?, 2)
              AND bt.amount > 0
              -- Skip bank txns the rules engine already claimed
              -- (rules run first; matched_source_type is set when a
              --  rule auto-posts a payment / bill / income batch).
              AND (bt.matched_source_type IS NULL OR bt.matched_source_type = '')
              AND ABS(julianday(bt.transaction_date) - julianday(?))
                  <= ?
              AND NOT EXISTS (
                    SELECT 1 FROM pending_classifications pc2
                    WHERE pc2.matched_bank_transaction_id = bt.id
                      AND pc2.id <> ?
                      AND pc2.status IN ('MATCHED', 'POSTED')
                  )
            ORDER BY ABS(julianday(bt.transaction_date) - julianday(?)) ASC,
                     bt.transaction_date ASC,
                     bt.id ASC
            LIMIT 25
            """,
            (
                int(pc["bank_account_id"]),
                str(pc["amount"]),
                ref_date,
                window,
                pc_id,
                ref_date,
            ),
        ).fetchall()
        return [
            MatchCandidate(
                bank_transaction_id=int(r["id"]),
                transaction_date=str(r["transaction_date"]),
                description=str(r["description"] or ""),
                amount=str(r["amount"]),
                bank_account_id=int(r["bank_account_id"]),
            )
            for r in rows
        ]

    # ── Link / Unlink ────────────────────────────────────────────────

    def link(
        self,
        *,
        pc_id: int,
        bank_transaction_id: int,
        commit: bool = True,
    ) -> None:
        """Link a classification to a bank transaction.

        Validates that:
          - both rows exist and share the same bank account
          - amounts match
          - the classification is PENDING (or already linked to this same bt — idempotent)
          - the bank tx is not already linked to a different MATCHED/POSTED classification
        """
        pc = self.conn.execute(
            "SELECT * FROM pending_classifications WHERE id = ?", (pc_id,)
        ).fetchone()
        if pc is None:
            raise ValidationError(f"Classification {pc_id} not found.")
        bt = self.conn.execute(
            "SELECT * FROM bank_transactions WHERE id = ?", (bank_transaction_id,)
        ).fetchone()
        if bt is None:
            raise ValidationError(f"Bank transaction {bank_transaction_id} not found.")

        if int(pc["bank_account_id"]) != int(bt["bank_account_id"]):
            raise ValidationError(
                "Classification and bank transaction belong to different bank accounts."
            )
        if bt["matched_source_type"]:
            raise ValidationError(
                f"Bank transaction {bank_transaction_id} is already claimed by a "
                f"transaction rule ({bt['matched_source_type']}). "
                "Unmatch it from the rule first if you want to re-attribute it."
            )
        if round(float(pc["amount"]), 2) != round(float(bt["amount"]), 2):
            raise ValidationError(
                f"Amount mismatch: classification {pc['amount']} vs "
                f"bank transaction {bt['amount']}."
            )
        if pc["status"] == "POSTED":
            raise ValidationError("Cannot re-link a posted classification.")
        if pc["status"] == "CANCELLED":
            raise ValidationError("Cannot link a cancelled classification.")
        if (
            pc["status"] == "MATCHED"
            and pc["matched_bank_transaction_id"] is not None
            and int(pc["matched_bank_transaction_id"]) != int(bank_transaction_id)
        ):
            raise ValidationError(
                "Classification is already matched to a different bank transaction. "
                "Unmatch it first."
            )

        # Reject if the bank tx is already claimed by some other live classification
        clash = self.conn.execute(
            """
            SELECT id FROM pending_classifications
            WHERE matched_bank_transaction_id = ?
              AND id <> ?
              AND status IN ('MATCHED', 'POSTED')
            """,
            (bank_transaction_id, pc_id),
        ).fetchone()
        if clash:
            raise ValidationError(
                f"Bank transaction {bank_transaction_id} is already linked to "
                f"classification {clash['id']}."
            )

        self.conn.execute(
            """
            UPDATE pending_classifications
               SET matched_bank_transaction_id = ?,
                   status = 'MATCHED',
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (bank_transaction_id, pc_id),
        )
        if commit:
            self.conn.commit()

    def unlink(self, *, pc_id: int, commit: bool = True) -> None:
        pc = self.conn.execute(
            "SELECT status FROM pending_classifications WHERE id = ?", (pc_id,)
        ).fetchone()
        if pc is None:
            raise ValidationError(f"Classification {pc_id} not found.")
        if pc["status"] == "POSTED":
            raise ValidationError(
                "Cannot unlink a posted classification — void the resulting payment instead."
            )
        if pc["status"] != "MATCHED":
            # Already unlinked / cancelled — nothing to do.
            return

        self.conn.execute(
            """
            UPDATE pending_classifications
               SET matched_bank_transaction_id = NULL,
                   status = 'PENDING',
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (pc_id,),
        )
        if commit:
            self.conn.commit()

    # ── Auto-match sweep ─────────────────────────────────────────────

    def auto_match_for_bank_account(self, bank_account_id: int) -> AutoMatchResult:
        """Sweep all PENDING classifications on this bank account.

        For each one with exactly one valid candidate bank transaction,
        link them. Ambiguous matches (>1 candidate) are left for manual
        review. No candidates is also left as-is.
        """
        pcs = self.conn.execute(
            """
            SELECT id FROM pending_classifications
            WHERE bank_account_id = ? AND status = 'PENDING'
            ORDER BY id ASC
            """,
            (int(bank_account_id),),
        ).fetchall()

        matched = 0
        ambiguous = 0
        no_candidate = 0
        for r in pcs:
            pc_id = int(r["id"])
            candidates = self.find_candidates_for_classification(pc_id)
            if len(candidates) == 1:
                try:
                    self.link(
                        pc_id=pc_id,
                        bank_transaction_id=candidates[0].bank_transaction_id,
                        commit=False,
                    )
                    matched += 1
                except ValidationError:
                    # Candidate became invalid mid-sweep (e.g. claimed by
                    # an earlier link in this same loop). Treat as ambiguous.
                    ambiguous += 1
            elif len(candidates) > 1:
                ambiguous += 1
            else:
                no_candidate += 1

        if matched:
            self.conn.commit()
        return AutoMatchResult(
            matched_count=matched,
            skipped_ambiguous=ambiguous,
            skipped_no_candidate=no_candidate,
        )

    # ── Display helpers ──────────────────────────────────────────────

    def get_matched_bank_tx(self, pc_id: int) -> dict[str, Any] | None:
        """Pull the bank-tx row a classification is matched to (for display)."""
        row = self.conn.execute(
            """
            SELECT bt.id, bt.transaction_date, bt.description, bt.amount,
                   bt.external_reference, bt.bank_account_id
            FROM bank_transactions bt
            JOIN pending_classifications pc
              ON pc.matched_bank_transaction_id = bt.id
            WHERE pc.id = ?
            """,
            (pc_id,),
        ).fetchone()
        return dict(row) if row else None
