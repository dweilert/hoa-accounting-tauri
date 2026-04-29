"""Reserve transfer posting workflow."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.db.transaction import transaction
from hoa_accounting.exceptions import ValidationError
from hoa_accounting.models.dto import ReserveTransferResult
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.reserve_transfers_repo import (
    ReserveTransfersRepository,
)
from hoa_accounting.validators.common import require_positive_amount


class ReserveTransferService:
    """Workflow for posting reserve transfers."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        audit_repo: AuditRepository,
        reserve_transfers_repo: ReserveTransfersRepository,
    ) -> None:
        self.conn = conn
        self.audit_repo = audit_repo
        self.reserve_transfers_repo = reserve_transfers_repo

    def post_reserve_transfer(
        self,
        *,
        entry_date: str,
        amount: Decimal | str | int | float,
        description: str,
        transfer_type: str | None = None,
        purpose: str | None = None,
        from_account_id: int | None = None,
        to_account_id: int | None = None,
        created_by_user_id: int | None = None,
    ) -> ReserveTransferResult:
        """Post a reserve transfer atomically."""
        with transaction(self.conn):
            amount_dec = require_positive_amount(amount, "Reserve transfer amount")
            if from_account_id is not None and from_account_id == to_account_id:
                raise ValidationError("From and to accounts must be different.")

            reserve_transfer_id = self.reserve_transfers_repo.insert_transfer(
                transfer_date=entry_date,
                from_account_id=from_account_id,
                to_account_id=to_account_id,
                amount=str(amount_dec),
                notes=description,
                transfer_type=transfer_type,
                purpose=purpose,
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
                },
            )
            return ReserveTransferResult(reserve_transfer_id=reserve_transfer_id)
