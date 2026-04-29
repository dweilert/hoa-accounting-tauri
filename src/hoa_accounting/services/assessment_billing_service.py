"""Assessment billing orchestration — bulk and individual.

Thin wrapper around ``AssessmentService.post_assessment`` for the two
actions on the Bill Assessments page:

- ``bill_all_at_same_amount`` — posts N assessments (one per active
  lot with a current primary-contact owner), each for the same amount.
  Used for a uniform special assessment or the monthly-dues billing.
- ``bill_individual_amounts`` — posts assessments only for the rows
  where an amount was entered. Used when the board wants to charge a
  subset of owners different amounts (catch-up bills, lot-specific
  fees, etc.).

Both are atomic: if any one assessment fails to post (no current
owner, closed period, unbalanced fund, …), the whole batch rolls
back. A partial batch would lie about the ledger.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from hoa_accounting.db.transaction import transaction
from hoa_accounting.exceptions import ValidationError
from hoa_accounting.models.dto import AssessmentResult
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.services.assessment_service import AssessmentService
from hoa_accounting.validators.common import q2, require_positive_amount


@dataclass(frozen=True)
class IndividualAssessmentRow:
    """One row on the 'bill individual amounts' form."""

    lot_id: int
    amount: Decimal | str


@dataclass(frozen=True)
class AssessmentBatchResult:
    """Return info for a batch billing operation."""

    assessments: list[AssessmentResult]
    total_amount: Decimal
    owner_count: int


class AssessmentBillingService:
    """Post assessments in bulk for every lot, or for a chosen subset."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        assessment_service: AssessmentService,
        lots_repo: LotsRepository,
    ) -> None:
        self.conn = conn
        self.assessment_service = assessment_service
        self.lots_repo = lots_repo

    def bill_all_at_same_amount(
        self,
        *,
        entry_date: str,
        amount: Decimal | str | int | float,
        description: str,
        category_id: int | None = None,
        due_date: str | None = None,
        created_by_user_id: int | None = None,
    ) -> AssessmentBatchResult:
        """Post one assessment per active lot, all at the same amount."""
        with transaction(self.conn):
            if not (description or "").strip():
                raise ValidationError("Assessment description is required.")
            amount_dec = require_positive_amount(amount, "Assessment amount")

            lots = self.lots_repo.list_lots(active_only=True)
            owner_lot_pairs: list[tuple[int, int]] = []
            for lot in lots:
                lot_id = int(lot["id"])
                owner_id = self.lots_repo.get_current_owner_id(lot_id)
                if owner_id is None:
                    raise ValidationError(
                        f"Lot {lot['lot_number']} (id {lot_id}) has no "
                        "current primary-contact owner. Assign one before "
                        "billing all homeowners, or use the individual form."
                    )
                owner_lot_pairs.append((owner_id, lot_id))

            if not owner_lot_pairs:
                raise ValidationError(
                    "No active lots with current owners were found to bill."
                )

            results = [
                self.assessment_service.post_assessment(
                    entry_date=entry_date,
                    lot_id=lot_id,
                    owner_id=owner_id,
                    amount=amount_dec,
                    description=description,
                    category_id=category_id,
                    created_by_user_id=created_by_user_id,
                    due_date=due_date,
                )
                for (owner_id, lot_id) in owner_lot_pairs
            ]

            total = q2(amount_dec) * len(results)
            return AssessmentBatchResult(
                assessments=results,
                total_amount=q2(total),
                owner_count=len(results),
            )

    def bill_individual_amounts(
        self,
        *,
        entry_date: str,
        description: str,
        rows: Sequence[IndividualAssessmentRow],
        category_id: int | None = None,
        due_date: str | None = None,
        created_by_user_id: int | None = None,
    ) -> AssessmentBatchResult:
        """Post assessments for a specific subset of lots at per-lot amounts.

        Rows with zero/blank amounts are filtered out by the caller
        (the UI parser drops them). If the caller passes them anyway,
        ``require_positive_amount`` will raise.
        """
        with transaction(self.conn):
            if not (description or "").strip():
                raise ValidationError("Assessment description is required.")
            if not rows:
                raise ValidationError(
                    "Enter at least one amount before posting individual assessments."
                )

            # Duplicate-lot check: a single batch billing the same
            # lot twice is almost always a user error. Reject it
            # up-front with a specific message rather than silently
            # creating two assessments for the same owner.
            seen_lots: set[int] = set()
            for idx, row in enumerate(rows, start=1):
                lot_id = int(row.lot_id)
                if lot_id in seen_lots:
                    raise ValidationError(
                        f"Row {idx}: lot {lot_id} appears more than once in "
                        "this batch. Remove the duplicate row before posting."
                    )
                seen_lots.add(lot_id)

            results: list[AssessmentResult] = []
            total = Decimal("0.00")

            for idx, row in enumerate(rows, start=1):
                amount = require_positive_amount(row.amount, f"Row {idx} amount")
                lot_id = int(row.lot_id)
                owner_id = self.lots_repo.get_current_owner_id(lot_id)
                if owner_id is None:
                    raise ValidationError(
                        f"Row {idx}: lot {lot_id} has no current "
                        "primary-contact owner."
                    )
                results.append(
                    self.assessment_service.post_assessment(
                        entry_date=entry_date,
                        lot_id=lot_id,
                        owner_id=owner_id,
                        amount=amount,
                        description=description,
                        category_id=category_id,
                        created_by_user_id=created_by_user_id,
                        due_date=due_date,
                    )
                )
                total += amount

            return AssessmentBatchResult(
                assessments=results,
                total_amount=q2(total),
                owner_count=len(results),
            )
