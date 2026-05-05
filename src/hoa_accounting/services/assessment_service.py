"""Assessment posting workflow."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.db.transaction import transaction
from hoa_accounting.models.dto import AssessmentResult
from hoa_accounting.repositories.assessments_repo import AssessmentsRepository
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.validators.common import require_positive_amount
from hoa_accounting.validators.entity_validator import EntityValidator


class AssessmentService:
    """Workflow for posting owner assessments."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        assessment_repo: AssessmentsRepository,
        audit_repo: AuditRepository,
        entity_validator: EntityValidator,
        credit_service: object | None = None,
    ) -> None:
        self.conn = conn
        self.assessment_repo = assessment_repo
        self.audit_repo = audit_repo
        self.entity_validator = entity_validator
        self._credit_service = credit_service

    def post_assessment(
        self,
        *,
        entry_date: str,
        lot_id: int,
        owner_id: int,
        amount: Decimal | str | int | float,
        description: str,
        created_by_user_id: int | None = None,
        assessment_rule_id: int | None = None,
        due_date: str | None = None,
        charge_type: str = "DUES",
        category_id: int | None = None,
    ) -> AssessmentResult:
        """Post an owner assessment atomically."""
        with transaction(self.conn):
            amount_dec = require_positive_amount(amount, "Assessment amount")
            self.entity_validator.require_exists("lots", lot_id)
            self.entity_validator.require_exists("owners", owner_id)

            effective_due_date = due_date or entry_date
            assessment_id = self.assessment_repo.insert_assessment(
                lot_id=lot_id,
                owner_id=owner_id,
                assessment_rule_id=assessment_rule_id,
                assessment_date=entry_date,
                due_date=effective_due_date,
                amount=str(amount_dec),
                description=description,
                charge_type=charge_type,
                category_id=category_id,
            )

            # Auto-apply any advance-payment credits the owner has on file.
            if self._credit_service is not None:
                self._credit_service.auto_apply_to_assessment(
                    assessment_id=assessment_id,
                    owner_id=owner_id,
                    assessment_amount=amount_dec,
                )

            self.audit_repo.write(
                entity_type="assessments",
                entity_id=assessment_id,
                action="CREATE_AND_POST",
                user_id=created_by_user_id,
                after_json={
                    "lot_id": lot_id,
                    "owner_id": owner_id,
                    "amount": str(amount_dec),
                    "description": description,
                },
            )
            return AssessmentResult(assessment_id=assessment_id)
