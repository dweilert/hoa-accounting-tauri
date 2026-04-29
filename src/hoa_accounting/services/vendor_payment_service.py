"""Vendor payment posting workflow."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.db.transaction import transaction
from hoa_accounting.models.dto import VendorPaymentResult
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.vendors_repo import VendorsRepository
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
        entity_validator: EntityValidator,
    ) -> None:
        self.conn = conn
        self.vendors_repo = vendors_repo
        self.audit_repo = audit_repo
        self.entity_validator = entity_validator

    def post_vendor_payment(
        self,
        *,
        entry_date: str,
        vendor_bill_id: int,
        amount: Decimal | str | int | float,
        description: str,
        bank_account_id: int,
        check_number: str | None = None,
        created_by_user_id: int | None = None,
    ) -> VendorPaymentResult:
        """Post payment of a vendor bill atomically."""
        with transaction(self.conn):
            amount_dec = require_positive_amount(amount, "Vendor payment amount")
            self.entity_validator.require_exists("vendor_bills", vendor_bill_id)
            self.entity_validator.require_exists("bank_accounts", bank_account_id)

            bill_payment_id = self.vendors_repo.insert_bill_payment(
                vendor_bill_id=vendor_bill_id,
                payment_date=entry_date,
                amount=str(amount_dec),
                bank_account_id=bank_account_id,
                check_number=check_number,
                notes=description,
            )

            # Roll up the bill's status. PAID when paid in full, PARTIAL
            # otherwise. Single-entry cash-basis: status is purely derived
            # from the sum of bill_payments against the bill.
            paid_row = self.conn.execute(
                """SELECT vb.amount AS bill_amount,
                          COALESCE((SELECT SUM(amount) FROM bill_payments
                                     WHERE vendor_bill_id = vb.id), 0) AS paid
                     FROM vendor_bills vb
                    WHERE vb.id = ?""",
                (vendor_bill_id,),
            ).fetchone()
            if paid_row is not None:
                bill_amount = Decimal(str(paid_row["bill_amount"]))
                paid = Decimal(str(paid_row["paid"]))
                new_status = "PAID" if paid >= bill_amount else "PARTIAL"
                self.conn.execute(
                    "UPDATE vendor_bills SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (new_status, vendor_bill_id),
                )
            self.audit_repo.write(
                entity_type="bill_payments",
                entity_id=bill_payment_id,
                action="CREATE_AND_POST",
                user_id=created_by_user_id,
                after_json={
                    "vendor_bill_id": vendor_bill_id,
                    "amount": str(amount_dec),
                },
            )
            return VendorPaymentResult(bill_payment_id=bill_payment_id)
