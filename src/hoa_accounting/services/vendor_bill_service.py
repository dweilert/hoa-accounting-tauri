"""Vendor bill posting workflow."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.db.transaction import transaction
from hoa_accounting.models.dto import VendorBillResult
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.vendors_repo import VendorsRepository
from hoa_accounting.validators.common import require_positive_amount
from hoa_accounting.validators.entity_validator import EntityValidator


class VendorBillService:
    """Workflow for posting vendor bills."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        vendors_repo: VendorsRepository,
        audit_repo: AuditRepository,
        entity_validator: EntityValidator,
    ) -> None:
        self.conn = conn
        self.vendors_repo = vendors_repo
        self.audit_repo = audit_repo
        self.entity_validator = entity_validator

    def post_vendor_bill(
        self,
        *,
        entry_date: str,
        vendor_id: int,
        amount: Decimal | str | int | float,
        description: str,
        invoice_number: str,
        invoice_date: str,
        due_date: str | None = None,
        fund_code: str = "OPERATING",
        category_id: int | None = None,
        created_by_user_id: int | None = None,
        expense_classification: str = "OPERATING",
    ) -> VendorBillResult:
        """Post a vendor bill atomically."""
        with transaction(self.conn):
            amount_dec = require_positive_amount(amount, "Vendor bill amount")
            self.entity_validator.require_exists("vendors", vendor_id)

            effective_due_date = due_date or invoice_date
            vendor_bill_id = self.vendors_repo.insert_vendor_bill(
                vendor_id=vendor_id,
                invoice_number=invoice_number,
                invoice_date=invoice_date,
                due_date=effective_due_date,
                amount=str(amount_dec),
                fund_code=fund_code,
                description=description,
                category_id=category_id,
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
                    "fund_code": fund_code,
                },
            )
            return VendorBillResult(vendor_bill_id=vendor_bill_id)
