"""Non-dues income batch posting workflow.

Cash-basis income recognition for things that aren't owner dues —
bank interest (the most common), small ad-hoc fees, gate-remote sales,
etc. Each batch targets ONE income account; mixed-account batches are
deliberately not supported (the form's 'Income Description' is one
field applying to the whole batch, which enforces this naturally).

Accounting shape per batch:

  DR   Cash (bank account)          = batch total
  CR   Income account (4xxx)        = row amount  ← per owner row (owner_id + lot_id tagged)
  CR   Income account (4xxx)        = OTHER amount ← description carries the source name

No AR is touched and no auto-application runs — income is recognized
on the spot. Assessments that were pre-billed (and thus already sit in
AR) should be paid via the dues deposit flow, not this one.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from hoa_accounting.db.transaction import transaction
from hoa_accounting.exceptions import NotFoundError, ValidationError
from hoa_accounting.models.dto import JournalLineInput
from hoa_accounting.models.enums import SourceType
from hoa_accounting.repositories.accounts_repo import AccountsRepository
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.bank_accounts_repo import BankAccountsRepository
from hoa_accounting.repositories.income_batches_repo import IncomeBatchesRepository
from hoa_accounting.repositories.journal_repo import JournalRepository
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.services.journal_service import JournalService
from hoa_accounting.validators.common import q2, require_positive_amount


@dataclass(frozen=True)
class IncomeRow:
    """One row on the non-dues income form.

    Exactly one of ``lot_id`` or ``other_source`` must be populated:
      - lot row → ``lot_id`` is set, owner resolves from current primary
        contact, owner/lot attach to the JE credit line.
      - OTHER row → ``other_source`` is set (free text like
        'Bank interest'), no owner/lot tagging; the text becomes the
        JE line description.
    """

    amount: Decimal | str
    lot_id: int | None = None
    other_source: str | None = None
    memo: str | None = None


@dataclass(frozen=True)
class IncomeBatchResult:
    """Return information for a successful income batch post."""

    income_batch_id: int
    journal_entry_id: int
    entry_number: str
    total_amount: Decimal


class NonDuesIncomeService:
    """Post a batch of non-dues income entries as one consolidated JE."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        income_batches_repo: IncomeBatchesRepository,
        lots_repo: LotsRepository,
        accounts_repo: AccountsRepository,
        bank_accounts_repo: BankAccountsRepository,
        audit_repo: AuditRepository,
        journal_repo: JournalRepository,
        journal_service: JournalService,
    ) -> None:
        self.conn = conn
        self.income_batches_repo = income_batches_repo
        self.lots_repo = lots_repo
        self.accounts_repo = accounts_repo
        self.bank_accounts_repo = bank_accounts_repo
        self.audit_repo = audit_repo
        self.journal_repo = journal_repo
        self.journal_service = journal_service

    def post_batch(
        self,
        *,
        posting_date: str,
        bank_account_id: int,
        income_account_id: int,
        income_description: str,
        rows: Sequence[IncomeRow],
        notes: str | None = None,
        created_by_user_id: int | None = None,
    ) -> IncomeBatchResult:
        """Post a non-dues income batch atomically."""
        with transaction(self.conn):
            if not rows:
                raise ValidationError(
                    "An income batch must contain at least one row."
                )
            if not (income_description or "").strip():
                raise ValidationError("Income description is required.")

            # Resolve bank → GL cash account, validate income account.
            bank = self._resolve_bank_account(bank_account_id)
            cash_account_id = int(bank["gl_account_id"])
            self._validate_income_account(income_account_id)

            # Per-row resolution.
            resolved: list[_ResolvedRow] = []
            total = Decimal("0.00")
            for idx, row in enumerate(rows, start=1):
                amount = require_positive_amount(row.amount, f"Row {idx} amount")

                lot_id: int | None = None
                owner_id: int | None = None
                other_source: str | None = None

                has_lot = row.lot_id is not None
                has_other = bool((row.other_source or "").strip())
                if has_lot and has_other:
                    raise ValidationError(
                        f"Row {idx}: choose either a lot or OTHER, not both."
                    )
                if not has_lot and not has_other:
                    raise ValidationError(
                        f"Row {idx}: lot or OTHER source is required."
                    )

                if has_lot:
                    lot_id = int(row.lot_id)  # type: ignore[arg-type]
                    owner_id = self.lots_repo.get_current_owner_id(lot_id)
                    if owner_id is None:
                        raise ValidationError(
                            f"Row {idx}: lot {lot_id} has no current "
                            "primary-contact owner."
                        )
                else:
                    other_source = (row.other_source or "").strip()

                resolved.append(
                    _ResolvedRow(
                        original_index=idx,
                        amount=amount,
                        lot_id=lot_id,
                        owner_id=owner_id,
                        other_source=other_source,
                        memo=(row.memo or "") or None,
                    )
                )
                total += amount

            # Build the consolidated JE.
            lines: list[JournalLineInput] = [
                JournalLineInput(
                    account_id=cash_account_id,
                    description=f"{income_description} — {posting_date}",
                    debit_amount=total,
                )
            ]
            for r in resolved:
                description = r.memo or r.other_source or income_description
                lines.append(
                    JournalLineInput(
                        account_id=income_account_id,
                        description=description,
                        credit_amount=r.amount,
                        owner_id=r.owner_id,
                        lot_id=r.lot_id,
                    )
                )

            journal = self.journal_service.post_journal_entry(
                entry_date=posting_date,
                # Reuse the ADJUSTMENT source type — it's the closest
                # existing enum for 'income recognized without a prior
                # owner transaction'. Reports that care about source
                # type can filter to income_batches directly.
                source_type=SourceType.ADJUSTMENT.value,
                memo=income_description
                    + (f" — {notes}" if notes else ""),
                created_by_user_id=created_by_user_id,
                lines=lines,
            )

            income_batch_id = self.income_batches_repo.insert_income_batch(
                posting_date=posting_date,
                bank_account_id=bank_account_id,
                income_account_id=income_account_id,
                income_description=income_description,
                total_amount=str(q2(total)),
                notes=notes,
                journal_entry_id=journal.journal_entry_id,
                created_by_user_id=created_by_user_id,
            )

            # Back-link the JE to the batch so the audit trail is
            # navigable in both directions.
            self.journal_repo.set_source_id(
                journal_entry_id=journal.journal_entry_id,
                source_id=income_batch_id,
            )

            self.audit_repo.write(
                entity_type="income_batches",
                entity_id=income_batch_id,
                action="CREATE_AND_POST",
                user_id=created_by_user_id,
                after_json={
                    "posting_date": posting_date,
                    "bank_account_id": bank_account_id,
                    "income_account_id": income_account_id,
                    "income_description": income_description,
                    "total_amount": str(q2(total)),
                    "row_count": len(resolved),
                    "journal_entry_id": journal.journal_entry_id,
                },
            )

            return IncomeBatchResult(
                income_batch_id=income_batch_id,
                journal_entry_id=journal.journal_entry_id,
                entry_number=journal.entry_number,
                total_amount=q2(total),
            )

    # ── Helpers ─────────────────────────────────────────────────────

    def _resolve_bank_account(self, bank_account_id: int):
        for row in self.bank_accounts_repo.list_bank_accounts():
            if int(row["id"]) == int(bank_account_id):
                return row
        raise NotFoundError(f"Bank account {bank_account_id} was not found.")

    def _validate_income_account(self, income_account_id: int) -> None:
        """Reject anything that isn't an active INCOME-type account."""
        row = self.conn.execute(
            """
            SELECT a.is_active, at.code AS type_code
            FROM accounts a
            JOIN account_types at ON at.id = a.account_type_id
            WHERE a.id = ?
            """,
            (income_account_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(
                f"Income account {income_account_id} was not found."
            )
        if int(row["is_active"]) != 1:
            raise ValidationError(
                f"Income account {income_account_id} is inactive."
            )
        if str(row["type_code"]) != "INCOME":
            raise ValidationError(
                f"Account {income_account_id} is not an income account."
            )


@dataclass(frozen=True)
class _ResolvedRow:
    original_index: int
    amount: Decimal
    lot_id: int | None
    owner_id: int | None
    other_source: str | None
    memo: str | None
