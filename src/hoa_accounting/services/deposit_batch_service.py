"""Deposit-batch posting workflow.

A real HOA deposit is a single trip to the bank with a stack of checks.
Individually crediting each owner's AR and debiting cash separately
leaves the book one-to-many against the bank statement's single line,
which ruins reconciliation. This service posts the batch as one
consolidated journal entry:

  DR   Cash                         = batch total
  CR   AR (owner A)                 = payment A amount
  CR   AR (owner B)                 = payment B amount
  ... one AR credit per payment ...

A ``deposit_batches`` row records the deposit as a whole and carries the
id of that single JE. Each payment is inserted individually (one row per
check), links to the shared JE, and is tagged with the batch id via
``payments.deposit_batch_id``.

Each payment is also auto-applied to the owner's oldest open assessments
(FIFO) until the payment amount is exhausted, so AR Aging reflects the
deposit correctly without a separate application step.

Entire operation is inside one transaction — a validation error on any
row rejects the whole batch.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from hoa_accounting.db.transaction import transaction
from hoa_accounting.exceptions import NotFoundError, ValidationError
from hoa_accounting.models.dto import JournalLineInput
from hoa_accounting.models.enums import PaymentMethod, SourceType
from hoa_accounting.repositories.accounts_repo import AccountsRepository
from hoa_accounting.repositories.assessments_repo import AssessmentsRepository
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.bank_accounts_repo import BankAccountsRepository
from hoa_accounting.repositories.deposit_batches_repo import DepositBatchesRepository
from hoa_accounting.repositories.journal_repo import JournalRepository
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.repositories.payments_repo import PaymentsRepository
from hoa_accounting.services.journal_service import JournalService
from hoa_accounting.validators.common import q2, require_positive_amount


@dataclass(frozen=True)
class DepositRow:
    """One row in a deposit batch — a single owner's check."""

    lot_id: int
    amount: Decimal | str
    reference_number: str | None = None   # check number, ACH id, etc.
    memo: str | None = None


@dataclass(frozen=True)
class DepositBatchResult:
    """Return information for a successful batch post."""

    deposit_batch_id: int
    journal_entry_id: int
    entry_number: str
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
        accounts_repo: AccountsRepository,
        bank_accounts_repo: BankAccountsRepository,
        audit_repo: AuditRepository,
        journal_repo: JournalRepository,
        journal_service: JournalService,
    ) -> None:
        self.conn = conn
        self.payments_repo = payments_repo
        self.assessments_repo = assessments_repo
        self.deposit_batches_repo = deposit_batches_repo
        self.lots_repo = lots_repo
        self.accounts_repo = accounts_repo
        self.bank_accounts_repo = bank_accounts_repo
        self.audit_repo = audit_repo
        self.journal_repo = journal_repo
        self.journal_service = journal_service

    # ── Public API ──────────────────────────────────────────────────

    def post_batch(
        self,
        *,
        deposit_date: str,
        bank_account_id: int,
        rows: Sequence[DepositRow],
        receivable_account_id: int,
        notes: str | None = None,
        payment_method: str = "CHECK",
        created_by_user_id: int | None = None,
    ) -> DepositBatchResult:
        """Post a deposit batch atomically.

        ``receivable_account_id`` is the owner-AR GL account that each
        payment credits. Typically the seed chart's ``1100 Accounts
        Receivable - Owners``; passed in rather than hard-coded so a
        chart that evolves past the starter layout still works.
        """
        with transaction(self.conn):
            if not rows:
                raise ValidationError("A deposit batch must contain at least one payment.")

            # Resolve bank → cash GL account and validate it exists.
            bank_row = self._resolve_bank_account(bank_account_id)
            cash_account_id = int(bank_row["gl_account_id"])

            try:
                parsed_method = PaymentMethod(payment_method.upper())
            except ValueError as exc:
                raise ValidationError(f"Invalid payment method: {payment_method}") from exc

            # Per-row resolution: validate each row, resolve lot → owner.
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

            # Build the consolidated journal entry:
            #   DR Cash  = total
            #   CR AR per owner per row = row amount
            lines: list[JournalLineInput] = [
                JournalLineInput(
                    account_id=cash_account_id,
                    description=f"Deposit {deposit_date}",
                    debit_amount=total,
                )
            ]
            for r in resolved:
                lines.append(
                    JournalLineInput(
                        account_id=receivable_account_id,
                        description=r.memo or f"Lot {r.lot_id} payment",
                        credit_amount=r.amount,
                        owner_id=r.owner_id,
                        lot_id=r.lot_id,
                    )
                )

            journal = self.journal_service.post_journal_entry(
                entry_date=deposit_date,
                source_type=SourceType.PAYMENT.value,
                memo=f"Deposit batch {deposit_date}"
                    + (f" — {notes}" if notes else ""),
                created_by_user_id=created_by_user_id,
                lines=lines,
            )

            # Insert the deposit_batches row first so subsequent payment
            # rows can reference its id.
            deposit_batch_id = self.deposit_batches_repo.insert_deposit_batch(
                deposit_date=deposit_date,
                bank_account_id=bank_account_id,
                journal_entry_id=journal.journal_entry_id,
                total_amount=str(q2(total)),
                notes=notes,
                created_by_user_id=created_by_user_id,
            )

            # Insert each payment, auto-apply to the owner's oldest open
            # assessments, and update statuses.
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
                    journal_entry_id=journal.journal_entry_id,
                    notes=r.memo,
                    deposit_batch_id=deposit_batch_id,
                )
                self._auto_apply_to_oldest_open_assessments(
                    payment_id=payment_id,
                    owner_id=r.owner_id,
                    payment_amount=r.amount,
                )
                payment_ids.append(payment_id)

            # Point the JE at the batch via source_id so the audit trail
            # is navigable in both directions.
            self.journal_repo.set_source_id(
                journal_entry_id=journal.journal_entry_id,
                source_id=deposit_batch_id,
            )

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
                    "journal_entry_id": journal.journal_entry_id,
                },
            )

            return DepositBatchResult(
                deposit_batch_id=deposit_batch_id,
                journal_entry_id=journal.journal_entry_id,
                entry_number=journal.entry_number,
                payment_ids=payment_ids,
                total_amount=q2(total),
            )

    # ── Private helpers ─────────────────────────────────────────────

    def _resolve_bank_account(self, bank_account_id: int):
        rows = self.bank_accounts_repo.list_bank_accounts()
        for row in rows:
            if int(row["id"]) == int(bank_account_id):
                return row
        raise NotFoundError(f"Bank account {bank_account_id} was not found.")

    def _next_unique_receipt_number(self, date: str) -> str:
        """Generate a unique receipt number, retrying on UNIQUE collision.

        Real concurrent posters would race on this the same way the JE
        number generation does; the defensive retry is cheap and keeps
        the code safe if a caller ever parallelises batch entry.
        """
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
        """FIFO-apply a payment across the owner's open assessments.

        Stops when the payment is exhausted or the owner has no more
        open assessments (in which case the unapplied remainder sits as
        a credit on AR — the owner's ledger still balances).
        """
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
    """Internal: one deposit row after lot → owner resolution."""

    original_index: int
    lot_id: int
    owner_id: int
    amount: Decimal
    reference_number: str | None
    memo: str
