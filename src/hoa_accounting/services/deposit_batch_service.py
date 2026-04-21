"""Deposit-batch posting workflow.

A real HOA deposit is a single trip to the bank with a stack of checks.
This service posts the batch as one deposit_batches row and individual
payment rows — one per check — with FIFO application to open assessments.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

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
    """One row in a deposit batch — a single owner's check."""

    lot_id: int
    amount: Decimal | str
    reference_number: str | None = None
    memo: str | None = None


@dataclass(frozen=True)
class DepositBatchResult:
    """Return information for a successful batch post."""

    deposit_batch_id: int
    payment_ids: list[int]
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
        # Kept for call-site compatibility during transition; unused.
        receivable_account_id: int | None = None,
    ) -> DepositBatchResult:
        """Post a deposit batch atomically."""
        with transaction(self.conn):
            if not rows:
                raise ValidationError("A deposit batch must contain at least one payment.")

            try:
                parsed_method = PaymentMethod(payment_method.upper())
            except ValueError as exc:
                raise ValidationError(f"Invalid payment method: {payment_method}") from exc

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
                self._auto_apply_to_oldest_open_assessments(
                    payment_id=payment_id,
                    owner_id=r.owner_id,
                    payment_amount=r.amount,
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

    def _resolve_bank_account(self, bank_account_id: int):
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

    def _auto_apply_to_oldest_open_assessments(
        self,
        *,
        payment_id: int,
        owner_id: int,
        payment_amount: Decimal,
    ) -> None:
        remaining = q2(payment_amount)
        for a in self.assessments_repo.list_open_for_owner(owner_id):
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
