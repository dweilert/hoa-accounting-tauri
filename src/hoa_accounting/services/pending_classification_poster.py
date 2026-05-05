"""Post matched pending classifications into real payments.

Third stage of the bank-is-boss pipeline:

  Stage 1 — Classify (treasurer captures intent, no ledger effect)
  Stage 2 — Match   (link to a bank_transactions row, status MATCHED)
  Stage 3 — POST    (this module: create payments + applications,
                     status POSTED)

The Poster reuses ``DepositBatchService.post_batch`` so a posted
classification produces the exact same shape as a manually entered
deposit (deposit_batches row + payments + payment_applications). After
posting, the bank_transactions row is wired with
``matched_source_type='PAYMENT'`` and ``matched_source_id=<payment_id>``
so the existing reconciliation engine sees it.

v1 scope: only owner payments (lot_id required). Category-only / non-
owner classifications raise ValidationError and direct the user at
Record Deposit. The lifecycle column ``posted_payment_id`` only points
at ``payments``; supporting income_batches would need a polymorphic
``posted_source_type`` column.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from hoa_accounting.exceptions import NotFoundError, ValidationError
from hoa_accounting.services.deposit_batch_service import (
    DepositBatchService,
    DepositRow,
)
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.validators.common import q2

# Default charge-type drain when a PC doesn't specify one. Matches the
# "regular owner payment" mode in Record Deposit (DUES + LATE_FEE).
DEFAULT_CHARGE_TYPES: tuple[str, ...] = ("DUES", "LATE_FEE")


@dataclass(frozen=True)
class PostPreviewRow:
    """One dry-run row showing what would be created from a PC."""

    pc_id: int
    classification_date: str
    bank_account_id: int
    bank_account_name: str
    lot_id: int | None
    lot_number: str
    owner_id: int | None
    owner_name: str
    amount: Decimal
    payment_method: str
    charge_types: tuple[str, ...]  # which open assessments will drain (default mode)
    explicit_assessment_ids: tuple[int, ...]  # specific-charges mode (if set)
    payment_date: str  # date the payment row will use
    matched_bank_transaction_id: int | None
    can_post: bool
    block_reason: str  # why can_post=False (empty if true)


@dataclass(frozen=True)
class PostResult:
    pc_id: int
    payment_id: int
    deposit_batch_id: int


@dataclass(frozen=True)
class PostBatchResult:
    posted: list[PostResult]
    skipped: list[tuple[int, str]]  # (pc_id, reason)


class PendingClassificationPoster:
    """Preview and post matched pending classifications."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.factory = ServiceFactory(conn)

    # ── Preview / dry-run ────────────────────────────────────────────

    def preview_all_matched(
        self, *, bank_account_id: int | None = None
    ) -> list[PostPreviewRow]:
        sql = """
            SELECT id FROM pending_classifications
            WHERE status = 'MATCHED'
        """
        params: tuple[Any, ...] = ()
        if bank_account_id is not None:
            sql += " AND bank_account_id = ?"
            params = (int(bank_account_id),)
        sql += " ORDER BY classification_date ASC, id ASC"
        rows = self.conn.execute(sql, params).fetchall()
        return [self._preview_one(int(r["id"])) for r in rows]

    def _preview_one(self, pc_id: int) -> PostPreviewRow:
        pc = self._load_pc(pc_id)

        bank = self.conn.execute(
            "SELECT account_name FROM bank_accounts WHERE id = ?",
            (pc["bank_account_id"],),
        ).fetchone()

        lot_number = ""
        owner_name = ""
        if pc["lot_id"]:
            lot = self.conn.execute(
                "SELECT lot_number FROM lots WHERE id = ?", (pc["lot_id"],)
            ).fetchone()
            lot_number = str(lot["lot_number"]) if lot else ""
        if pc["owner_id"]:
            owner = self.conn.execute(
                "SELECT display_name FROM owners WHERE id = ?", (pc["owner_id"],)
            ).fetchone()
            owner_name = str(owner["display_name"]) if owner else ""

        # Determine which payment_date to use: prefer the matched bank
        # transaction's date (the day the money landed), fall back to
        # the classification date if somehow unmatched.
        payment_date = pc["classification_date"]
        if pc["matched_bank_transaction_id"]:
            bt = self.conn.execute(
                "SELECT transaction_date FROM bank_transactions WHERE id = ?",
                (pc["matched_bank_transaction_id"],),
            ).fetchone()
            if bt and bt["transaction_date"]:
                payment_date = bt["transaction_date"]

        # Determine charge-type drain (used only when no explicit list is set)
        if pc["charge_type"]:
            charge_types: tuple[str, ...] = (str(pc["charge_type"]),)
        else:
            charge_types = DEFAULT_CHARGE_TYPES

        # Specific-charges mode: parse the JSON-encoded assessment-id list.
        # When non-empty, Post drains exactly these in order, ignoring the
        # charge_type drain above.
        explicit_ids: tuple[int, ...] = ()
        raw_apply = pc["apply_to_assessment_ids"]
        if raw_apply:
            try:
                parsed = json.loads(raw_apply)
                if isinstance(parsed, list):
                    explicit_ids = tuple(
                        int(x)
                        for x in parsed
                        if isinstance(x, int) or (isinstance(x, str) and x.isdigit())
                    )
            except (json.JSONDecodeError, ValueError, TypeError):
                explicit_ids = ()

        # Decide if this row is postable
        can_post = True
        block_reason = ""
        if pc["status"] != "MATCHED":
            can_post = False
            block_reason = f"Status is {pc['status']}, not MATCHED."
        elif pc["lot_id"] is None:
            can_post = False
            block_reason = (
                "Non-owner classifications aren't supported yet. "
                "Use Record Deposit for general income."
            )
        elif pc["owner_id"] is None:
            can_post = False
            block_reason = "No owner attached to this lot."

        return PostPreviewRow(
            pc_id=pc_id,
            classification_date=str(pc["classification_date"]),
            bank_account_id=int(pc["bank_account_id"]),
            bank_account_name=str(bank["account_name"]) if bank else "",
            lot_id=int(pc["lot_id"]) if pc["lot_id"] else None,
            lot_number=lot_number,
            owner_id=int(pc["owner_id"]) if pc["owner_id"] else None,
            owner_name=owner_name,
            amount=q2(pc["amount"]),
            payment_method=str(pc["payment_method"]),
            charge_types=charge_types,
            explicit_assessment_ids=explicit_ids,
            payment_date=str(payment_date),
            matched_bank_transaction_id=(
                int(pc["matched_bank_transaction_id"])
                if pc["matched_bank_transaction_id"]
                else None
            ),
            can_post=can_post,
            block_reason=block_reason,
        )

    # ── Post one ─────────────────────────────────────────────────────

    def post(self, pc_id: int, *, created_by_user_id: int | None = None) -> PostResult:
        """Post one matched classification.

        Atomic: either everything is created and the PC flips to POSTED,
        or nothing happens. Re-posting the same PC raises (idempotent
        guard via status check).
        """
        preview = self._preview_one(pc_id)
        if not preview.can_post:
            raise ValidationError(preview.block_reason or "Cannot post.")

        pc = self._load_pc(pc_id)
        deposit_service: DepositBatchService = self.factory.deposit_batch_service()

        # Single-row deposit batch — same shape the rule engine uses
        # for ACH dues_payment auto-posts. The bank line *is* the deposit.
        #
        # Two drain modes (mirrors DepositBatchService.DepositRow):
        #   - explicit_assessment_ids set → drain exactly those in order
        #   - else → drain by charge_type filter, oldest-first
        if preview.explicit_assessment_ids:
            row = DepositRow(
                lot_id=int(pc["lot_id"]),
                amount=str(q2(pc["amount"])),
                reference_number=pc["reference_number"] or None,
                memo=(pc["memo"] or "")
                + (
                    f" [PC#{pc_id}]"
                    if not (pc["memo"] or "").endswith(f"[PC#{pc_id}]")
                    else ""
                ),
                apply_to_assessment_ids=preview.explicit_assessment_ids,
            )
        else:
            row = DepositRow(
                lot_id=int(pc["lot_id"]),
                amount=str(q2(pc["amount"])),
                reference_number=pc["reference_number"] or None,
                memo=(pc["memo"] or "")
                + (
                    f" [PC#{pc_id}]"
                    if not (pc["memo"] or "").endswith(f"[PC#{pc_id}]")
                    else ""
                ),
                charge_type_filter=preview.charge_types,
            )

        result = deposit_service.post_batch(
            deposit_date=preview.payment_date,
            bank_account_id=int(pc["bank_account_id"]),
            rows=[row],
            notes=f"Posted from pending classification #{pc_id}",
            payment_method=str(pc["payment_method"]),
            created_by_user_id=created_by_user_id,
        )
        if not result.payment_ids:
            # Should never happen — post_batch raises on empty
            raise ValidationError("Posting did not produce a payment row.")
        payment_id = int(result.payment_ids[0])
        deposit_batch_id = int(result.deposit_batch_id)

        # Wire the bank transaction to the new payment so reconciliation
        # sees it as matched. Only set if the PC has a bank tx and the
        # bank tx isn't already claimed by something else (defensive —
        # the matcher already prevents this).
        if pc["matched_bank_transaction_id"]:
            self.conn.execute(
                """
                UPDATE bank_transactions
                   SET matched_source_type = 'PAYMENT',
                       matched_source_id   = ?,
                       reconciliation_status =
                           CASE WHEN reconciliation_status = 'UNMATCHED'
                                THEN 'MATCHED'
                                ELSE reconciliation_status END,
                       match_type = CASE WHEN match_type = 'UNMATCHED'
                                         THEN 'PENDING_CLASSIFICATION'
                                         ELSE match_type END
                 WHERE id = ?
                   AND (matched_source_type IS NULL OR matched_source_type = '')
                """,
                (payment_id, int(pc["matched_bank_transaction_id"])),
            )

        # Flip the PC to POSTED and record the payment id
        self.conn.execute(
            """
            UPDATE pending_classifications
               SET status            = 'POSTED',
                   posted_payment_id = ?,
                   updated_at        = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (payment_id, pc_id),
        )
        self.conn.commit()
        return PostResult(
            pc_id=pc_id,
            payment_id=payment_id,
            deposit_batch_id=deposit_batch_id,
        )

    # ── Reverse a posted classification ──────────────────────────────

    def reverse(
        self,
        pc_id: int,
        *,
        created_by_user_id: int | None = None,
    ) -> None:
        """Undo a previous Post — atomic.

        Steps:
          1. Validate PC is POSTED and the payment exists (and isn't
             part of any other deposit batch — single-row invariant).
          2. For each payment_application: revert assessment status
             (PARTIAL / PAID rolls back to OPEN or PARTIAL based on
             remaining applied total) and delete the application row.
          3. Delete the payment.
          4. Delete the deposit_batch (it was created exclusively for
             this PC; nothing else references it).
          5. Unlink the bank_transactions row — clear matched_source_*
             and roll reconciliation_status back to UNMATCHED if it was
             set by Post.
          6. Flip PC: status='MATCHED', posted_payment_id=NULL. The
             bank-tx link via matched_bank_transaction_id stays intact
             so the user can edit specifics and re-post.

        After reverse, the PC is back at MATCHED — the same state it
        was in before Post. To unmatch as well, call the matcher's
        unlink() afterwards.

        Refuses if a payment-application audit trail spans multiple
        deposit_batches or if the bank_transactions row was claimed by
        a different downstream process (defensive — should not happen
        for PCs we posted).
        """
        pc = self._load_pc(pc_id)
        if pc["status"] != "POSTED":
            raise ValidationError(
                f"Cannot reverse a classification in status {pc['status']}."
            )
        if not pc["posted_payment_id"]:
            raise ValidationError(
                "Posted classification has no posted_payment_id — data inconsistency."
            )
        payment_id = int(pc["posted_payment_id"])

        # Pull the payment + its deposit batch
        payment = self.conn.execute(
            "SELECT id, deposit_batch_id FROM payments WHERE id = ?",
            (payment_id,),
        ).fetchone()
        if payment is None:
            # Payment was already deleted out from under us. Just flip
            # the PC back so it isn't stuck in POSTED with a dangling FK.
            self.conn.execute(
                """
                UPDATE pending_classifications
                   SET status            = 'MATCHED',
                       posted_payment_id = NULL,
                       updated_at        = CURRENT_TIMESTAMP
                 WHERE id = ?
                """,
                (pc_id,),
            )
            self.conn.commit()
            return

        deposit_batch_id = payment["deposit_batch_id"]

        # Verify the deposit batch only contains this single payment —
        # invariant for PC-driven Posts. If another payment shares the
        # batch (shouldn't happen but defensive), refuse rather than
        # corrupt the deposit slip.
        if deposit_batch_id is not None:
            other = self.conn.execute(
                "SELECT COUNT(*) AS n FROM payments WHERE deposit_batch_id = ?",
                (deposit_batch_id,),
            ).fetchone()
            if other and int(other["n"]) > 1:
                raise ValidationError(
                    f"Deposit batch {deposit_batch_id} contains multiple payments. "
                    "This PC can't be reversed without disturbing other deposits — "
                    "void the payment manually instead."
                )

        # Pull every application + its assessment for status rollback
        apps = self.conn.execute(
            """
            SELECT pa.id AS app_id, pa.assessment_id, pa.applied_amount
            FROM payment_applications pa
            WHERE pa.payment_id = ?
            """,
            (payment_id,),
        ).fetchall()

        for app in apps:
            assessment_id = int(app["assessment_id"])

            # Recompute the assessment's remaining applied total after
            # we drop this application. Status: 0 → OPEN, partial → PARTIAL,
            # >= amount → PAID.
            row = self.conn.execute(
                """
                SELECT a.amount,
                       COALESCE(
                           (SELECT SUM(applied_amount)
                              FROM payment_applications
                             WHERE assessment_id = a.id
                               AND id <> ?), 0
                       ) AS other_applied
                FROM assessments a WHERE a.id = ?
                """,
                (int(app["app_id"]), assessment_id),
            ).fetchone()
            if row is None:
                # Assessment vanished — best-effort cleanup, just delete the app
                self.conn.execute(
                    "DELETE FROM payment_applications WHERE id = ?",
                    (int(app["app_id"]),),
                )
                continue

            assessment_amount = Decimal(str(row["amount"]))
            other_applied = Decimal(str(row["other_applied"] or 0))
            new_status = (
                "PAID"
                if other_applied >= assessment_amount
                else ("PARTIAL" if other_applied > Decimal("0") else "OPEN")
            )

            self.conn.execute(
                "DELETE FROM payment_applications WHERE id = ?",
                (int(app["app_id"]),),
            )
            self.conn.execute(
                "UPDATE assessments SET status = ? WHERE id = ?",
                (new_status, assessment_id),
            )

        # Delete the payment itself
        self.conn.execute("DELETE FROM payments WHERE id = ?", (payment_id,))

        # Delete the (now-empty) deposit batch
        if deposit_batch_id is not None:
            self.conn.execute(
                "DELETE FROM deposit_batches WHERE id = ?",
                (int(deposit_batch_id),),
            )

        # Unlink the bank transaction. Only clear it if it still points
        # at our payment (don't stomp something else that grabbed it).
        if pc["matched_bank_transaction_id"]:
            self.conn.execute(
                """
                UPDATE bank_transactions
                   SET matched_source_type   = NULL,
                       matched_source_id     = NULL,
                       reconciliation_status =
                           CASE WHEN reconciliation_status = 'MATCHED'
                                THEN 'UNMATCHED'
                                ELSE reconciliation_status END,
                       match_type = CASE WHEN match_type = 'PENDING_CLASSIFICATION'
                                         THEN 'UNMATCHED'
                                         ELSE match_type END
                 WHERE id = ?
                   AND matched_source_type = 'PAYMENT'
                   AND matched_source_id = ?
                """,
                (int(pc["matched_bank_transaction_id"]), payment_id),
            )

        # Flip the PC back to MATCHED — bank-tx link still stands.
        self.conn.execute(
            """
            UPDATE pending_classifications
               SET status            = 'MATCHED',
                   posted_payment_id = NULL,
                   updated_at        = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (pc_id,),
        )
        self.conn.commit()

    # ── Post all matched ─────────────────────────────────────────────

    def post_all_matched(
        self,
        *,
        bank_account_id: int | None = None,
        created_by_user_id: int | None = None,
    ) -> PostBatchResult:
        """Post every MATCHED classification (optionally filtered by bank).

        Each PC is posted in its own atomic transaction (post_batch
        already wraps in `with transaction(self.conn)`). One failure
        skips that PC but does not roll back earlier successes —
        skipped rows are reported with their reason so the treasurer
        can address them individually.
        """
        previews = self.preview_all_matched(bank_account_id=bank_account_id)
        posted: list[PostResult] = []
        skipped: list[tuple[int, str]] = []

        for p in previews:
            if not p.can_post:
                skipped.append((p.pc_id, p.block_reason))
                continue
            try:
                posted.append(self.post(p.pc_id, created_by_user_id=created_by_user_id))
            except (ValidationError, NotFoundError) as exc:
                skipped.append((p.pc_id, str(exc)))

        return PostBatchResult(posted=posted, skipped=skipped)

    # ── Helpers ──────────────────────────────────────────────────────

    def _load_pc(self, pc_id: int) -> Any:
        row = self.conn.execute(
            "SELECT * FROM pending_classifications WHERE id = ?", (pc_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"Pending classification {pc_id} not found.")
        return row
