"""Vendor payment posting workflow."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.db.transaction import transaction
from hoa_accounting.models.dto import JournalLineInput, VendorPaymentResult
from hoa_accounting.models.enums import SourceType
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.journal_repo import JournalRepository
from hoa_accounting.repositories.vendors_repo import VendorsRepository
from hoa_accounting.services.journal_service import JournalService
from hoa_accounting.validators.account_role_validator import AccountRoleValidator
from hoa_accounting.validators.account_validator import AccountValidator
from hoa_accounting.validators.common import require_positive_amount
from hoa_accounting.validators.entity_validator import EntityValidator


class VendorPaymentService:
    """Workflow for posting vendor bill payments."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        vendors_repo: VendorsRepository,
        audit_repo: AuditRepository,
        journal_repo: JournalRepository,
        journal_service: JournalService,
        entity_validator: EntityValidator,
        account_validator: AccountValidator,
        account_role_validator: AccountRoleValidator,
    ) -> None:
        self.conn = conn
        self.vendors_repo = vendors_repo
        self.audit_repo = audit_repo
        self.journal_repo = journal_repo
        self.journal_service = journal_service
        self.entity_validator = entity_validator
        self.account_validator = account_validator
        self.account_role_validator = account_role_validator

    def post_vendor_payment(
        self,
        *,
        entry_date: str,
        vendor_bill_id: int,
        amount: Decimal | str | int | float,
        description: str,
        payable_account_id: int,
        cash_account_id: int,
        bank_account_id: int,
        check_number: str | None = None,
        created_by_user_id: int | None = None,
    ) -> VendorPaymentResult:
        """Post payment of a vendor bill atomically."""
        with transaction(self.conn):
            amount_dec = require_positive_amount(amount, "Vendor payment amount")
            self.entity_validator.require_exists("vendor_bills", vendor_bill_id)
            self.entity_validator.require_exists("bank_accounts", bank_account_id)
            self.account_validator.require_active_account(payable_account_id)
            self.account_validator.require_active_account(cash_account_id)
            self.account_role_validator.require_liability_account(payable_account_id, "accounts payable")
            self.account_role_validator.require_asset_account(cash_account_id, "cash disbursement")

            journal = self.journal_service.post_journal_entry(
                entry_date=entry_date,
                source_type=SourceType.BILL_PAYMENT.value,
                memo=description,
                created_by_user_id=created_by_user_id,
                lines=[
                    JournalLineInput(
                        account_id=payable_account_id,
                        description=description,
                        debit_amount=amount_dec,
                    ),
                    JournalLineInput(
                        account_id=cash_account_id,
                        description=description,
                        credit_amount=amount_dec,
                    ),
                ],
            )

            bill_payment_id = self.vendors_repo.insert_bill_payment(
                vendor_bill_id=vendor_bill_id,
                payment_date=entry_date,
                amount=str(amount_dec),
                bank_account_id=bank_account_id,
                check_number=check_number,
                journal_entry_id=journal.journal_entry_id,
                notes=description,
            )
            self.journal_repo.set_source_id(
                journal_entry_id=journal.journal_entry_id,
                source_id=bill_payment_id,
            )
            self.audit_repo.write(
                entity_type="bill_payments",
                entity_id=bill_payment_id,
                action="CREATE_AND_POST",
                user_id=created_by_user_id,
                after_json={
                    "vendor_bill_id": vendor_bill_id,
                    "amount": str(amount_dec),
                    "journal_entry_id": journal.journal_entry_id,
                },
            )
            return VendorPaymentResult(
                bill_payment_id=bill_payment_id,
                journal_entry_id=journal.journal_entry_id,
                entry_number=journal.entry_number,
            )
