"""Reserve transfer posting workflow."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.db.transaction import transaction
from hoa_accounting.exceptions import ValidationError
from hoa_accounting.models.dto import JournalLineInput, ReserveTransferResult
from hoa_accounting.models.enums import SourceType
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.journal_repo import JournalRepository
from hoa_accounting.repositories.reserve_transfers_repo import ReserveTransfersRepository
from hoa_accounting.services.journal_service import JournalService
from hoa_accounting.validators.account_role_validator import AccountRoleValidator
from hoa_accounting.validators.account_validator import AccountValidator
from hoa_accounting.validators.common import require_positive_amount


class ReserveTransferService:
    """Workflow for posting reserve transfers."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        audit_repo: AuditRepository,
        journal_repo: JournalRepository,
        reserve_transfers_repo: ReserveTransfersRepository,
        journal_service: JournalService,
        account_validator: AccountValidator,
        account_role_validator: AccountRoleValidator,
    ) -> None:
        self.conn = conn
        self.audit_repo = audit_repo
        self.journal_repo = journal_repo
        self.reserve_transfers_repo = reserve_transfers_repo
        self.journal_service = journal_service
        self.account_validator = account_validator
        self.account_role_validator = account_role_validator

    def post_reserve_transfer(
        self,
        *,
        entry_date: str,
        amount: Decimal | str | int | float,
        description: str,
        from_account_id: int,
        to_account_id: int,
        created_by_user_id: int | None = None,
    ) -> ReserveTransferResult:
        """Post a reserve transfer atomically."""
        with transaction(self.conn):
            amount_dec = require_positive_amount(amount, "Reserve transfer amount")
            if from_account_id == to_account_id:
                raise ValidationError("From and to accounts must be different.")
            self.account_validator.require_active_account(from_account_id)
            self.account_validator.require_active_account(to_account_id)
            self.account_role_validator.require_asset_account(from_account_id, "transfer source cash")
            self.account_role_validator.require_asset_account(to_account_id, "transfer destination cash")

            journal = self.journal_service.post_journal_entry(
                entry_date=entry_date,
                source_type=SourceType.TRANSFER.value,
                memo=description,
                created_by_user_id=created_by_user_id,
                lines=[
                    JournalLineInput(
                        account_id=to_account_id,
                        description=description,
                        debit_amount=amount_dec,
                    ),
                    JournalLineInput(
                        account_id=from_account_id,
                        description=description,
                        credit_amount=amount_dec,
                    ),
                ],
            )

            reserve_transfer_id = self.reserve_transfers_repo.insert_transfer(
                transfer_date=entry_date,
                from_account_id=from_account_id,
                to_account_id=to_account_id,
                amount=str(amount_dec),
                journal_entry_id=journal.journal_entry_id,
                notes=description,
            )
            self.journal_repo.set_source_id(
                journal_entry_id=journal.journal_entry_id,
                source_id=reserve_transfer_id,
            )
            self.audit_repo.write(
                entity_type="reserve_transfers",
                entity_id=reserve_transfer_id,
                action="CREATE_AND_POST",
                user_id=created_by_user_id,
                after_json={
                    "from_account_id": from_account_id,
                    "to_account_id": to_account_id,
                    "amount": str(amount_dec),
                    "journal_entry_id": journal.journal_entry_id,
                },
            )
            return ReserveTransferResult(
                reserve_transfer_id=reserve_transfer_id,
                journal_entry_id=journal.journal_entry_id,
                entry_number=journal.entry_number,
            )
