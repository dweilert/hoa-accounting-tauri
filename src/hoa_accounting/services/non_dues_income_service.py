"""Non-dues income batch posting workflow."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from hoa_accounting.db.transaction import transaction
from hoa_accounting.exceptions import NotFoundError, ValidationError
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.bank_accounts_repo import BankAccountsRepository
from hoa_accounting.repositories.income_batches_repo import IncomeBatchesRepository
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.validators.common import q2, require_positive_amount


@dataclass(frozen=True)
class IncomeRow:
    """One row on the non-dues income form."""

    amount: Decimal | str
    lot_id: int | None = None
    other_source: str | None = None
    memo: str | None = None


@dataclass(frozen=True)
class IncomeBatchResult:
    """Return information for a successful income batch post."""

    income_batch_id: int
    total_amount: Decimal


class NonDuesIncomeService:
    """Post a batch of non-dues income entries."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        income_batches_repo: IncomeBatchesRepository,
        lots_repo: LotsRepository,
        bank_accounts_repo: BankAccountsRepository,
        audit_repo: AuditRepository,
    ) -> None:
        self.conn = conn
        self.income_batches_repo = income_batches_repo
        self.lots_repo = lots_repo
        self.bank_accounts_repo = bank_accounts_repo
        self.audit_repo = audit_repo

    def post_batch(
        self,
        *,
        posting_date: str,
        bank_account_id: int,
        income_description: str,
        rows: Sequence[IncomeRow],
        notes: str | None = None,
        created_by_user_id: int | None = None,
        # Kept for call-site compatibility during transition; unused.
        income_account_id: int | None = None,
        category_id: int | None = None,
        deposit_batch_id: int | None = None,
    ) -> IncomeBatchResult:
        """Post a non-dues income batch atomically."""
        with transaction(self.conn):
            if not rows:
                raise ValidationError(
                    "An income batch must contain at least one row."
                )
            if not (income_description or "").strip():
                raise ValidationError("Income description is required.")

            self._resolve_bank_account(bank_account_id)

            total = Decimal("0.00")
            for idx, row in enumerate(rows, start=1):
                amount = require_positive_amount(row.amount, f"Row {idx} amount")
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
                total += amount

            income_batch_id = self.income_batches_repo.insert_income_batch(
                posting_date=posting_date,
                bank_account_id=bank_account_id,
                income_account_id=income_account_id,
                income_description=income_description,
                total_amount=str(q2(total)),
                notes=notes,
                created_by_user_id=created_by_user_id,
                category_id=category_id,
                deposit_batch_id=deposit_batch_id,
            )

            self.audit_repo.write(
                entity_type="income_batches",
                entity_id=income_batch_id,
                action="CREATE_AND_POST",
                user_id=created_by_user_id,
                after_json={
                    "posting_date": posting_date,
                    "bank_account_id": bank_account_id,
                    "income_description": income_description,
                    "total_amount": str(q2(total)),
                    "row_count": len(rows),
                },
            )

            return IncomeBatchResult(
                income_batch_id=income_batch_id,
                total_amount=q2(total),
            )

    def _resolve_bank_account(self, bank_account_id: int):
        for row in self.bank_accounts_repo.list_bank_accounts():
            if int(row["id"]) == int(bank_account_id):
                return row
        raise NotFoundError(f"Bank account {bank_account_id} was not found.")
