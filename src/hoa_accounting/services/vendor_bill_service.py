"""Vendor bill posting workflow."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.db.transaction import transaction
from hoa_accounting.models.dto import JournalLineInput, VendorBillResult
from hoa_accounting.models.enums import SourceType
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.journal_repo import JournalRepository
from hoa_accounting.repositories.vendors_repo import VendorsRepository
from hoa_accounting.services.journal_service import JournalService
from hoa_accounting.validators.account_role_validator import AccountRoleValidator
from hoa_accounting.validators.account_validator import AccountValidator
from hoa_accounting.exceptions import ValidationError
from hoa_accounting.validators.common import require_positive_amount
from hoa_accounting.validators.entity_validator import EntityValidator


_ALLOWED_EXPENSE_CLASSIFICATIONS = frozenset({"OPERATING", "IMPROVEMENT"})


class VendorBillService:
    """Workflow for posting vendor bills."""

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

    def post_vendor_bill(
        self,
        *,
        entry_date: str,
        vendor_id: int,
        amount: Decimal | str | int | float,
        description: str,
        expense_account_id: int,
        payable_account_id: int,
        invoice_number: str,
        invoice_date: str,
        due_date: str | None = None,
        fund_code: str = "OPERATING",
        expense_classification: str = "OPERATING",
        created_by_user_id: int | None = None,
    ) -> VendorBillResult:
        """Post a vendor bill atomically.

        ``expense_classification`` tags the debit (expense) line with
        either ``OPERATING`` (the default — routine recurring spending)
        or ``IMPROVEMENT`` (enhancement/upgrade) so the variance and
        year-to-date expense reports can split the two. The credit
        (payable) line stays unclassified because the tag only applies
        to expense activity.
        """
        with transaction(self.conn):
            amount_dec = require_positive_amount(amount, "Vendor bill amount")
            self.entity_validator.require_exists("vendors", vendor_id)
            self.account_validator.require_active_account(expense_account_id)
            self.account_validator.require_active_account(payable_account_id)
            self.account_validator.require_valid_fund_code(fund_code)
            self.account_role_validator.require_expense_account(expense_account_id, "vendor expense")
            self.account_role_validator.require_liability_account(payable_account_id, "accounts payable")

            classification = (expense_classification or "OPERATING").upper()
            if classification not in _ALLOWED_EXPENSE_CLASSIFICATIONS:
                raise ValidationError(
                    f"Invalid expense classification: {expense_classification!r}. "
                    f"Expected one of {sorted(_ALLOWED_EXPENSE_CLASSIFICATIONS)}."
                )

            effective_due_date = due_date or invoice_date
            journal = self.journal_service.post_journal_entry(
                entry_date=entry_date,
                source_type=SourceType.VENDOR_BILL.value,
                memo=description,
                created_by_user_id=created_by_user_id,
                lines=[
                    JournalLineInput(
                        account_id=expense_account_id,
                        description=description,
                        debit_amount=amount_dec,
                        vendor_id=vendor_id,
                        expense_classification=classification,
                    ),
                    JournalLineInput(
                        account_id=payable_account_id,
                        description=description,
                        credit_amount=amount_dec,
                        vendor_id=vendor_id,
                    ),
                ],
            )

            vendor_bill_id = self.vendors_repo.insert_vendor_bill(
                vendor_id=vendor_id,
                invoice_number=invoice_number,
                invoice_date=invoice_date,
                due_date=effective_due_date,
                amount=str(amount_dec),
                expense_account_id=expense_account_id,
                payable_account_id=payable_account_id,
                fund_code=fund_code,
                journal_entry_id=journal.journal_entry_id,
                description=description,
            )
            self.journal_repo.set_source_id(
                journal_entry_id=journal.journal_entry_id,
                source_id=vendor_bill_id,
            )
            self.audit_repo.write(
                entity_type="vendor_bills",
                entity_id=vendor_bill_id,
                action="CREATE_AND_POST",
                user_id=created_by_user_id,
                after_json={
                    "vendor_id": vendor_id,
                    "amount": str(amount_dec),
                    "invoice_number": invoice_number,
                    "journal_entry_id": journal.journal_entry_id,
                    "expense_classification": classification,
                    "fund_code": fund_code,
                },
            )
            return VendorBillResult(
                vendor_bill_id=vendor_bill_id,
                journal_entry_id=journal.journal_entry_id,
                entry_number=journal.entry_number,
            )
