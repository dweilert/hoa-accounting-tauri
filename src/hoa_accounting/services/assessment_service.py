"""Assessment posting workflow."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.db.transaction import transaction
from hoa_accounting.models.dto import AssessmentResult, JournalLineInput
from hoa_accounting.models.enums import SourceType
from hoa_accounting.repositories.assessments_repo import AssessmentsRepository
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.journal_repo import JournalRepository
from hoa_accounting.services.journal_service import JournalService
from hoa_accounting.validators.account_role_validator import AccountRoleValidator
from hoa_accounting.validators.account_validator import AccountValidator
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
        journal_repo: JournalRepository,
        journal_service: JournalService,
        entity_validator: EntityValidator,
        account_validator: AccountValidator,
        account_role_validator: AccountRoleValidator,
    ) -> None:
        self.conn = conn
        self.assessment_repo = assessment_repo
        self.audit_repo = audit_repo
        self.journal_repo = journal_repo
        self.journal_service = journal_service
        self.entity_validator = entity_validator
        self.account_validator = account_validator
        self.account_role_validator = account_role_validator

    def post_assessment(
        self,
        *,
        entry_date: str,
        lot_id: int,
        owner_id: int,
        amount: Decimal | str | int | float,
        description: str,
        receivable_account_id: int,
        income_account_id: int,
        created_by_user_id: int | None = None,
        assessment_rule_id: int | None = None,
        due_date: str | None = None,
        charge_type: str = "DUES",
    ) -> AssessmentResult:
        """Post an owner assessment atomically."""
        with transaction(self.conn):
            amount_dec = require_positive_amount(amount, "Assessment amount")
            self.entity_validator.require_exists("lots", lot_id)
            self.entity_validator.require_exists("owners", owner_id)
            self.account_validator.require_active_account(receivable_account_id)
            self.account_validator.require_active_account(income_account_id)
            self.account_role_validator.require_asset_account(receivable_account_id, "owner receivable")
            self.account_role_validator.require_income_account(income_account_id, "assessment income")

            effective_due_date = due_date or entry_date
            journal = self.journal_service.post_journal_entry(
                entry_date=entry_date,
                source_type=SourceType.ASSESSMENT.value,
                memo=description,
                created_by_user_id=created_by_user_id,
                lines=[
                    JournalLineInput(
                        account_id=receivable_account_id,
                        description=description,
                        debit_amount=amount_dec,
                        lot_id=lot_id,
                        owner_id=owner_id,
                    ),
                    JournalLineInput(
                        account_id=income_account_id,
                        description=description,
                        credit_amount=amount_dec,
                        lot_id=lot_id,
                        owner_id=owner_id,
                    ),
                ],
            )

            assessment_id = self.assessment_repo.insert_assessment(
                lot_id=lot_id,
                owner_id=owner_id,
                assessment_rule_id=assessment_rule_id,
                assessment_date=entry_date,
                due_date=effective_due_date,
                amount=str(amount_dec),
                description=description,
                journal_entry_id=journal.journal_entry_id,
                charge_type=charge_type,
            )
            self.journal_repo.set_source_id(
                journal_entry_id=journal.journal_entry_id,
                source_id=assessment_id,
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
                    "journal_entry_id": journal.journal_entry_id,
                },
            )
            return AssessmentResult(
                assessment_id=assessment_id,
                journal_entry_id=journal.journal_entry_id,
                entry_number=journal.entry_number,
            )
