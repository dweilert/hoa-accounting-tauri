"""Owner payment posting workflow."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from decimal import Decimal

from hoa_accounting.db.transaction import transaction
from hoa_accounting.exceptions import NotFoundError, ValidationError
from hoa_accounting.models.dto import PaymentResult
from hoa_accounting.models.enums import PaymentMethod
from hoa_accounting.repositories.assessments_repo import AssessmentsRepository
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.payments_repo import PaymentsRepository
from hoa_accounting.validators.common import q2, require_positive_amount
from hoa_accounting.validators.entity_validator import EntityValidator


class PaymentService:
    """Workflow for posting owner payments and applying them to assessments."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        payment_repo: PaymentsRepository,
        assessment_repo: AssessmentsRepository,
        audit_repo: AuditRepository,
        entity_validator: EntityValidator,
    ) -> None:
        self.conn = conn
        self.payment_repo = payment_repo
        self.assessment_repo = assessment_repo
        self.audit_repo = audit_repo
        self.entity_validator = entity_validator

    def post_payment(
        self,
        *,
        entry_date: str,
        owner_id: int,
        amount: Decimal | str | int | float,
        description: str,
        bank_account_id: int,
        payment_method: str,
        receipt_number: str,
        reference_number: str | None = None,
        created_by_user_id: int | None = None,
        apply_to_assessment_ids: Sequence[int] | None = None,
    ) -> PaymentResult:
        """Post an owner payment atomically."""
        with transaction(self.conn):
            amount_dec = require_positive_amount(amount, "Payment amount")
            self.entity_validator.require_exists("owners", owner_id)
            self.entity_validator.require_exists("bank_accounts", bank_account_id)

            try:
                parsed_method = PaymentMethod(payment_method.upper())
            except ValueError as exc:
                raise ValidationError(
                    f"Invalid payment method: {payment_method}"
                ) from exc

            payment_id = self.payment_repo.insert_payment(
                receipt_number=receipt_number,
                owner_id=owner_id,
                payment_date=entry_date,
                amount=str(amount_dec),
                payment_method=parsed_method.value,
                reference_number=reference_number,
                bank_account_id=bank_account_id,
                notes=description,
            )

            if apply_to_assessment_ids:
                self._apply_payment_to_assessments(
                    payment_id=payment_id,
                    owner_id=owner_id,
                    payment_amount=amount_dec,
                    assessment_ids=apply_to_assessment_ids,
                )

            self.audit_repo.write(
                entity_type="payments",
                entity_id=payment_id,
                action="CREATE_AND_POST",
                user_id=created_by_user_id,
                after_json={
                    "owner_id": owner_id,
                    "amount": str(amount_dec),
                    "receipt_number": receipt_number,
                },
            )
            return PaymentResult(payment_id=payment_id)

    def _apply_payment_to_assessments(
        self,
        *,
        payment_id: int,
        owner_id: int,
        payment_amount: Decimal,
        assessment_ids: Sequence[int],
    ) -> None:
        remaining = payment_amount
        for assessment_id in assessment_ids:
            row = self.assessment_repo.get_for_payment_application(assessment_id)
            if row is None:
                raise NotFoundError(f"Assessment {assessment_id} was not found.")
            if int(row["owner_id"]) != owner_id:
                raise ValidationError(
                    f"Assessment {assessment_id} does not belong to owner {owner_id}."
                )

            outstanding = q2(row["amount"]) - q2(row["already_applied"])
            if outstanding <= Decimal("0.00"):
                continue

            apply_amount = outstanding if outstanding <= remaining else remaining
            if apply_amount <= Decimal("0.00"):
                break

            self.payment_repo.insert_payment_application(
                payment_id=payment_id,
                assessment_id=assessment_id,
                applied_amount=str(apply_amount),
            )
            remaining -= apply_amount

            new_total_applied = q2(row["already_applied"]) + apply_amount
            status = "PAID" if new_total_applied >= q2(row["amount"]) else "PARTIAL"
            self.assessment_repo.update_status(assessment_id, status)
