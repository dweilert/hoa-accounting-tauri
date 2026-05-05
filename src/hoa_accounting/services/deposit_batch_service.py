"""Deposit-batch posting workflow.

A real HOA deposit is a single trip to the bank with a stack of checks.

Two posting modes:
  post_batch()        — legacy immediate mode: creates deposit_batches +
                        payments in one step. Kept for compatibility.
  save_pending()      — bank-is-boss mode: creates deposit_batches (status
                        PENDING) + deposit_batch_lines. No payments yet.
  post_pending_batch()— called by Accept All when an OFX bank line is
                        matched to a PENDING batch. Materialises payment
                        rows + payment_applications and flips the batch to
                        POSTED.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from hoa_accounting.db.transaction import transaction
from hoa_accounting.exceptions import NotFoundError, ValidationError
from hoa_accounting.models.enums import PaymentMethod
from hoa_accounting.repositories.assessments_repo import AssessmentsRepository
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.deposit_batches_repo import DepositBatchesRepository
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.repositories.payments_repo import PaymentsRepository
from hoa_accounting.validators.common import q2, require_positive_amount


@dataclass(frozen=True)
class DepositRow:
    """One row in a deposit batch — a single owner's check.

    Drain behavior is controlled by ``charge_type_filter`` and
    ``apply_to_assessment_ids``:

    - Neither set  → legacy behavior: drain ANY open assessment oldest
      first. Preserved for existing callers; new callers should always
      specify.
    - ``charge_type_filter`` set → drain only assessments whose
      ``charge_type`` is in the tuple, oldest first. This is how the
      *regular* mode of Record Deposit prevents a dues payment from
      accidentally consuming a resale fee.
    - ``apply_to_assessment_ids`` set → drain exactly those assessments
      in the given order, ignoring the filter. For the *specific
      charges* mode where the treasurer picks what the check covers.
    """

    lot_id: int
    amount: Decimal | str
    reference_number: str | None = None
    memo: str | None = None
    charge_type_filter: tuple[str, ...] | None = None
    apply_to_assessment_ids: tuple[int, ...] | None = None


@dataclass(frozen=True)
class DepositBatchResult:
    """Return information for a successful batch post."""

    deposit_batch_id: int
    payment_ids: list[int]
    total_amount: Decimal


@dataclass(frozen=True)
class PendingBatchResult:
    """Return information for a save_pending() call."""

    deposit_batch_id: int
    line_count: int
    total_amount: Decimal


class DepositBatchService:
    """Post a batch of owner payments as a single deposit."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        payments_repo: PaymentsRepository,
        assessments_repo: AssessmentsRepository,
        deposit_batches_repo: DepositBatchesRepository,
        lots_repo: LotsRepository,
        audit_repo: AuditRepository,
    ) -> None:
        self.conn = conn
        self.payments_repo = payments_repo
        self.assessments_repo = assessments_repo
        self.deposit_batches_repo = deposit_batches_repo
        self.lots_repo = lots_repo
        self.audit_repo = audit_repo

    def post_batch(
        self,
        *,
        deposit_date: str,
        bank_account_id: int,
        rows: Sequence[DepositRow],
        notes: str | None = None,
        payment_method: str = "CHECK",
        created_by_user_id: int | None = None,
    ) -> DepositBatchResult:
        """Post a deposit batch atomically."""
        with transaction(self.conn):
            if not rows:
                raise ValidationError(
                    "A deposit batch must contain at least one payment."
                )

            try:
                parsed_method = PaymentMethod(payment_method.upper())
            except ValueError as exc:
                raise ValidationError(
                    f"Invalid payment method: {payment_method}"
                ) from exc

            resolved: list[_ResolvedRow] = []
            total = Decimal("0.00")
            for idx, row in enumerate(rows, start=1):
                amount = require_positive_amount(row.amount, f"Row {idx} amount")
                owner_id = self.lots_repo.get_current_owner_id(int(row.lot_id))
                if owner_id is None:
                    raise ValidationError(
                        f"Row {idx}: lot {row.lot_id} has no current primary-contact owner."
                    )
                resolved.append(
                    _ResolvedRow(
                        original_index=idx,
                        lot_id=int(row.lot_id),
                        owner_id=owner_id,
                        amount=amount,
                        reference_number=(row.reference_number or None),
                        memo=(row.memo or ""),
                        charge_type_filter=row.charge_type_filter,
                        apply_to_assessment_ids=row.apply_to_assessment_ids,
                    )
                )
                total += amount

            deposit_batch_id = self.deposit_batches_repo.insert_deposit_batch(
                deposit_date=deposit_date,
                bank_account_id=bank_account_id,
                total_amount=str(q2(total)),
                notes=notes,
                created_by_user_id=created_by_user_id,
            )

            payment_ids: list[int] = []
            for r in resolved:
                receipt_number = self._next_unique_receipt_number(deposit_date)
                payment_id = self.payments_repo.insert_payment(
                    receipt_number=receipt_number,
                    owner_id=r.owner_id,
                    payment_date=deposit_date,
                    amount=str(q2(r.amount)),
                    payment_method=parsed_method.value,
                    reference_number=r.reference_number,
                    bank_account_id=bank_account_id,
                    notes=r.memo,
                    deposit_batch_id=deposit_batch_id,
                )
                self._apply_payment_to_assessments(
                    payment_id=payment_id,
                    owner_id=r.owner_id,
                    payment_amount=r.amount,
                    charge_type_filter=r.charge_type_filter,
                    explicit_assessment_ids=r.apply_to_assessment_ids,
                )
                payment_ids.append(payment_id)

            self.audit_repo.write(
                entity_type="deposit_batches",
                entity_id=deposit_batch_id,
                action="CREATE_AND_POST",
                user_id=created_by_user_id,
                after_json={
                    "deposit_date": deposit_date,
                    "bank_account_id": bank_account_id,
                    "total_amount": str(q2(total)),
                    "payment_count": len(payment_ids),
                },
            )

            return DepositBatchResult(
                deposit_batch_id=deposit_batch_id,
                payment_ids=payment_ids,
                total_amount=q2(total),
            )

    # ── Bank-is-boss: save pending, post later ────────────────────────────

    def save_pending(
        self,
        *,
        deposit_date: str,
        bank_account_id: int,
        owner_rows: Sequence[DepositRow],
        income_lines: Sequence[dict[str, Any]] | None = None,
        notes: str | None = None,
        payment_method: str = "CHECK",
        created_by_user_id: int | None = None,
    ) -> PendingBatchResult:
        """Save a deposit batch as PENDING without creating any payment rows.

        Each entry in ``owner_rows`` becomes a deposit_batch_lines record
        (lot_id set).  Each entry in ``income_lines`` (dicts with
        ``category_id``, ``amount``, ``description``) also becomes a line
        (lot_id NULL).  No payments or income_batches are written.

        Returns ``PendingBatchResult`` with the batch id, line count, and
        total.  Call ``post_pending_batch()`` to materialise the payments
        when the bank confirms.
        """
        with transaction(self.conn):
            if not owner_rows and not income_lines:
                raise ValidationError("A deposit batch must contain at least one row.")

            try:
                PaymentMethod(payment_method.upper())
            except ValueError as exc:
                raise ValidationError(
                    f"Invalid payment method: {payment_method}"
                ) from exc

            self._resolve_bank_account(bank_account_id)

            # Compute total from all rows upfront so it goes into
            # deposit_batches.total_amount for the OFX matcher.
            total = Decimal("0.00")
            for idx, row in enumerate(owner_rows, start=1):
                amt = require_positive_amount(row.amount, f"Row {idx} amount")
                total += amt
            for line in income_lines or []:
                total += q2(Decimal(str(line["amount"])))

            # Need at least one INCOME category to record income lines.
            # Verify the category ids exist (cheap sanity check).
            deposit_batch_id = self.deposit_batches_repo.insert_deposit_batch(
                deposit_date=deposit_date,
                bank_account_id=bank_account_id,
                total_amount=str(q2(total)),
                notes=notes,
                created_by_user_id=created_by_user_id,
                posting_status="PENDING",
            )

            line_count = 0
            # Owner-payment lines
            for row in owner_rows:
                amt = require_positive_amount(row.amount, "Row amount")
                ctf: str | None = None
                if row.charge_type_filter:
                    ctf = ",".join(row.charge_type_filter)
                aids: str | None = None
                if row.apply_to_assessment_ids:
                    aids = ",".join(str(a) for a in row.apply_to_assessment_ids)
                # category_id is NULL for owner-payment lines; posting is driven
                # by charge_type_filter (DUES/LATE_FEE/RESALE_FEE), not the
                # GL category.  Non-owner income lines carry the real category_id.
                self.deposit_batches_repo.insert_batch_line(
                    deposit_batch_id=deposit_batch_id,
                    lot_id=int(row.lot_id),
                    category_id=None,  # charge_type_filter drives owner-payment posting
                    amount=str(q2(amt)),
                    reference_number=row.reference_number,
                    memo=row.memo or "",
                    charge_type_filter=ctf,
                    apply_to_assessment_ids=aids,
                )
                line_count += 1

            # Non-owner income lines
            for line in income_lines or []:
                self.deposit_batches_repo.insert_batch_line(
                    deposit_batch_id=deposit_batch_id,
                    lot_id=None,
                    category_id=int(line["category_id"]),
                    amount=str(q2(Decimal(str(line["amount"])))),
                    reference_number=None,
                    memo=str(line.get("description") or ""),
                    charge_type_filter=None,
                    apply_to_assessment_ids=None,
                )
                line_count += 1

            self.audit_repo.write(
                entity_type="deposit_batches",
                entity_id=deposit_batch_id,
                action="CREATE_PENDING",
                user_id=created_by_user_id,
                after_json={
                    "deposit_date": deposit_date,
                    "bank_account_id": bank_account_id,
                    "total_amount": str(q2(total)),
                    "line_count": line_count,
                    "posting_status": "PENDING",
                },
            )
            return PendingBatchResult(
                deposit_batch_id=deposit_batch_id,
                line_count=line_count,
                total_amount=q2(total),
            )

    def post_pending_batch(
        self,
        deposit_batch_id: int,
        *,
        payment_method: str = "CHECK",
        created_by_user_id: int | None = None,
    ) -> DepositBatchResult:
        """Materialise payment rows for a PENDING deposit batch.

        Reads the deposit_batch_lines, creates payments + payment_applications
        for owner-payment lines, creates income_batches for non-owner income
        lines, then flips posting_status to POSTED.

        Raises ``ValidationError`` if the batch is not found or not PENDING.
        Returns a ``DepositBatchResult`` mirroring ``post_batch()``'s shape.
        """
        with transaction(self.conn):
            row = self.conn.execute(
                "SELECT id, deposit_date, bank_account_id, total_amount, notes, "
                "       posting_status "
                "FROM deposit_batches WHERE id = ?",
                (deposit_batch_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"Deposit batch {deposit_batch_id} not found.")
            if row["posting_status"] != "PENDING":
                raise ValidationError(
                    f"Deposit batch {deposit_batch_id} is not PENDING "
                    f"(status={row['posting_status']})."
                )

            deposit_date = str(row["deposit_date"])
            bank_account_id = int(row["bank_account_id"])

            try:
                parsed_method = PaymentMethod(payment_method.upper())
            except ValueError as exc:
                raise ValidationError(
                    f"Invalid payment method: {payment_method}"
                ) from exc

            lines = self.deposit_batches_repo.get_batch_lines(deposit_batch_id)
            payment_ids: list[int] = []

            for line in lines:
                lot_id = line["lot_id"]
                if lot_id is None:
                    # Non-owner income line → create income_batch
                    # (inline to avoid circular import with the factory).
                    self.conn.execute(
                        """
                        INSERT INTO income_batches (
                            posting_date, bank_account_id, total_amount,
                            income_description, deposit_batch_id, category_id
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            deposit_date,
                            bank_account_id,
                            str(line["amount"]),
                            str(line["memo"] or "Non-owner income"),
                            deposit_batch_id,
                            int(line["category_id"]) if line["category_id"] else None,
                        ),
                    )
                    continue

                # Owner-payment line → need the current owner of the lot
                owner_row = self.conn.execute(
                    """SELECT owner_id FROM lot_ownership
                       WHERE lot_id = ? AND end_date IS NULL
                       ORDER BY start_date DESC LIMIT 1""",
                    (int(lot_id),),
                ).fetchone()
                if owner_row is None:
                    raise ValidationError(
                        f"Lot {lot_id} has no current owner — "
                        f"cannot post pending batch {deposit_batch_id}."
                    )
                owner_id = int(owner_row["owner_id"])
                payment_amount = q2(Decimal(str(line["amount"])))

                # Parse stored charge_type_filter / apply_to_assessment_ids
                ctf_str = line.get("charge_type_filter") or ""
                ctf: tuple[str, ...] | None = None
                if ctf_str:
                    ctf = tuple(c.strip() for c in ctf_str.split(",") if c.strip())

                aids_str = line.get("apply_to_assessment_ids") or ""
                aids: tuple[int, ...] | None = None
                if aids_str:
                    aids = tuple(
                        int(a.strip())
                        for a in aids_str.split(",")
                        if a.strip().isdigit()
                    )

                receipt_number = self._next_unique_receipt_number(deposit_date)
                payment_id = self.payments_repo.insert_payment(
                    receipt_number=receipt_number,
                    owner_id=owner_id,
                    payment_date=deposit_date,
                    amount=str(payment_amount),
                    payment_method=parsed_method.value,
                    reference_number=line.get("reference_number"),
                    bank_account_id=bank_account_id,
                    notes=str(line.get("memo") or ""),
                    deposit_batch_id=deposit_batch_id,
                )
                self._apply_payment_to_assessments(
                    payment_id=payment_id,
                    owner_id=owner_id,
                    payment_amount=payment_amount,
                    charge_type_filter=ctf,
                    explicit_assessment_ids=aids,
                )
                payment_ids.append(payment_id)

            self.deposit_batches_repo.mark_posted(deposit_batch_id)

            self.audit_repo.write(
                entity_type="deposit_batches",
                entity_id=deposit_batch_id,
                action="POST_PENDING",
                user_id=created_by_user_id,
                after_json={
                    "deposit_date": deposit_date,
                    "bank_account_id": bank_account_id,
                    "payment_count": len(payment_ids),
                },
            )
            return DepositBatchResult(
                deposit_batch_id=deposit_batch_id,
                payment_ids=payment_ids,
                total_amount=q2(Decimal(str(row["total_amount"]))),
            )

    def _resolve_bank_account(self, bank_account_id: int) -> Any:
        row = self.conn.execute(
            "SELECT id FROM bank_accounts WHERE id = ?", (bank_account_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"Bank account {bank_account_id} was not found.")
        return row

    def _next_unique_receipt_number(self, date: str) -> str:
        for _ in range(5):
            candidate = self.payments_repo.next_receipt_number(date)
            exists = self.conn.execute(
                "SELECT 1 FROM payments WHERE receipt_number = ?",
                (candidate,),
            ).fetchone()
            if exists is None:
                return candidate
        raise ValidationError(
            "Could not allocate a unique receipt number for this batch."
        )

    def _apply_payment_to_assessments(
        self,
        *,
        payment_id: int,
        owner_id: int,
        payment_amount: Decimal,
        charge_type_filter: tuple[str, ...] | None,
        explicit_assessment_ids: tuple[int, ...] | None,
    ) -> None:
        """Drain open assessments by the payment amount.

        Ordering rules:
        - If ``explicit_assessment_ids`` is set, iterate in that exact
          order (whatever the treasurer picked). Remaining amount after
          the list is simply left as unapplied credit on the payment.
        - Otherwise, iterate the owner's open assessments oldest-first,
          filtered by ``charge_type_filter`` when present.

        In both cases an individual assessment's outstanding amount caps
        what this payment can apply to it — overflow carries to the next
        one in order.
        """
        remaining = q2(payment_amount)

        if explicit_assessment_ids:
            all_rows = self.assessments_repo.list_open_for_owner(owner_id)
            by_id = {int(r["id"]): r for r in all_rows}
            candidates = [by_id[aid] for aid in explicit_assessment_ids if aid in by_id]
        else:
            candidates = list(self.assessments_repo.list_open_for_owner(owner_id))
            if charge_type_filter:
                allowed = set(charge_type_filter)
                candidates = [
                    a for a in candidates if (a["charge_type"] or "DUES") in allowed
                ]

        for a in candidates:
            if remaining <= Decimal("0.00"):
                break
            outstanding = q2(a["amount"]) - q2(a["already_applied"])
            if outstanding <= Decimal("0.00"):
                continue
            apply_amount = outstanding if outstanding <= remaining else remaining
            self.payments_repo.insert_payment_application(
                payment_id=payment_id,
                assessment_id=int(a["id"]),
                applied_amount=str(apply_amount),
            )
            remaining -= apply_amount
            new_applied = q2(a["already_applied"]) + apply_amount
            status = "PAID" if new_applied >= q2(a["amount"]) else "PARTIAL"
            self.assessments_repo.update_status(int(a["id"]), status)


@dataclass(frozen=True)
class _ResolvedRow:
    original_index: int
    lot_id: int
    owner_id: int
    amount: Decimal
    reference_number: str | None
    memo: str
    charge_type_filter: tuple[str, ...] | None = None
    apply_to_assessment_ids: tuple[int, ...] | None = None
