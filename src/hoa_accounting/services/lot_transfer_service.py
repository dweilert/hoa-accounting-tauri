"""Lot Sale / Transfer service — atomically hands a lot from departing owner(s)
to one or more incoming owners on a given sale date.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from hoa_accounting.db.transaction import transaction
from hoa_accounting.exceptions import NotFoundError, ValidationError
from hoa_accounting.repositories.assessments_repo import AssessmentsRepository
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.lot_ownership_repo import LotOwnershipRepository
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.validators.common import q2


@dataclass(frozen=True)
class LotTransferResult:
    lot_id: int
    lot_number: str
    departed_owner_names: list[str]
    new_owner_names: list[str]
    sale_date: str
    balance_at_transfer: Decimal  # should be 0.00 for a clean close


class LotTransferService:
    """Workflow for transferring lot ownership on a sale date."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        lots_repo: LotsRepository,
        ownership_repo: LotOwnershipRepository,
        assessments_repo: AssessmentsRepository,
        audit_repo: AuditRepository,
    ) -> None:
        self.conn = conn
        self.lots_repo = lots_repo
        self.ownership_repo = ownership_repo
        self.assessments_repo = assessments_repo
        self.audit_repo = audit_repo

    def transfer(
        self,
        *,
        lot_id: int,
        new_owner_ids: list[int],
        sale_date: str,
        created_by_user_id: int | None = None,
        force: bool = False,
    ) -> LotTransferResult:
        """Transfer lot ownership atomically.

        Business rules:
          1. Lot must exist.
          2. Lot must have at least one current owner (end_date IS NULL).
          3. new_owner_ids must be non-empty.
          4. sale_date must be a valid YYYY-MM-DD.
          5. Unless force=True, the lot's AR balance as of sale_date must be 0.
          6. In one transaction:
               a. Set end_date = sale_date - 1 day on all current ownerships.
               b. Insert new lot_ownership rows for each new_owner_id.
               c. Write an audit log entry.
        """
        # ── Rule 1: lot exists ────────────────────────────────────────────────
        lot_row = self.lots_repo.get_lot(lot_id)
        if lot_row is None:
            raise NotFoundError(f"Lot {lot_id} was not found.")

        lot_number = lot_row["lot_number"]

        # ── Rule 2: current owners ─────────────────────────────────────────
        current_ownerships = self.ownership_repo.get_current_ownerships(lot_id)
        if not current_ownerships:
            raise ValidationError(
                "This lot has no current owners. "
                "There is no active ownership to transfer from."
            )

        # ── Rule 3: incoming owners ────────────────────────────────────────
        if not new_owner_ids:
            raise ValidationError("At least one incoming owner must be selected.")

        # ── Rule 4: valid date ─────────────────────────────────────────────
        try:
            sale_date_obj = date.fromisoformat(sale_date)
        except ValueError as exc:
            raise ValidationError(
                f"Sale date '{sale_date}' is not a valid date (expected YYYY-MM-DD)."
            ) from exc

        # ── Rule 5: balance check ──────────────────────────────────────────
        balance = self._compute_balance(lot_id=lot_id, as_of=sale_date)
        if not force and balance > Decimal("0.00"):
            raise ValidationError(
                f"Departing owner has an outstanding balance of "
                f"${balance:,.2f}. Record a final payment first, or check "
                f"'Force transfer' to proceed anyway."
            )

        departed_names = [str(row["owner_name"]) for row in current_ownerships]
        departed_ids = [int(row["id"]) for row in current_ownerships]

        # The day before the new owner's start date
        end_date_str = (sale_date_obj - timedelta(days=1)).isoformat()

        # ── Rule 6: atomic transaction ─────────────────────────────────────
        with transaction(self.conn):
            # 6a. Close all current ownerships
            for ow_id in departed_ids:
                self.ownership_repo.end_ownership(
                    ownership_id=ow_id,
                    end_date=end_date_str,
                )

            # 6b. Insert new ownerships
            new_ownership_ids: list[int] = []
            for owner_id in new_owner_ids:
                ow_id = self.ownership_repo.assign_owner(
                    lot_id=lot_id,
                    owner_id=owner_id,
                    start_date=sale_date,
                )
                new_ownership_ids.append(ow_id)

            # Resolve display names for new owners
            new_owner_names: list[str] = []
            for owner_id in new_owner_ids:
                row = self.conn.execute(
                    "SELECT display_name FROM owners WHERE id = ?",
                    (owner_id,),
                ).fetchone()
                new_owner_names.append(str(row["display_name"]) if row else str(owner_id))

            # 6c. Audit log
            self.audit_repo.write(
                entity_type="lot_ownership",
                entity_id=lot_id,
                action="LOT_TRANSFER",
                user_id=created_by_user_id,
                after_json={
                    "lot_id": lot_id,
                    "lot_number": lot_number,
                    "sale_date": sale_date,
                    "departed_owner_ids": departed_ids,
                    "departed_owner_names": departed_names,
                    "new_owner_ids": new_owner_ids,
                    "new_owner_names": new_owner_names,
                    "balance_at_transfer": str(balance),
                    "force": force,
                },
            )

        return LotTransferResult(
            lot_id=lot_id,
            lot_number=lot_number,
            departed_owner_names=departed_names,
            new_owner_names=new_owner_names,
            sale_date=sale_date,
            balance_at_transfer=balance,
        )

    # ── Private helpers ────────────────────────────────────────────────────────

    def _compute_balance(self, *, lot_id: int, as_of: str) -> Decimal:
        """Return the lot's outstanding AR balance as of the given date.

        Sums assessment amounts where status is NOT VOID or PAID and due_date
        is on or before *as_of*.
        """
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM assessments
            WHERE lot_id = ?
              AND status NOT IN ('VOID', 'PAID')
              AND due_date <= ?
            """,
            (lot_id, as_of),
        ).fetchone()
        return q2(row["total"] if row else 0)
