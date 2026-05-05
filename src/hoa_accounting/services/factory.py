"""Factory helpers to build configured services."""

from __future__ import annotations

import sqlite3

from hoa_accounting.repositories.assessments_repo import AssessmentsRepository
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.bank_accounts_repo import BankAccountsRepository
from hoa_accounting.repositories.deposit_batches_repo import DepositBatchesRepository
from hoa_accounting.repositories.entities_repo import EntitiesRepository
from hoa_accounting.repositories.income_batches_repo import IncomeBatchesRepository
from hoa_accounting.repositories.lot_ownership_repo import LotOwnershipRepository
from hoa_accounting.repositories.lot_renters_repo import LotRentersRepository
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.repositories.payments_repo import PaymentsRepository
from hoa_accounting.repositories.reserve_transfers_repo import (
    ReserveTransfersRepository,
)
from hoa_accounting.repositories.vendors_repo import VendorsRepository
from hoa_accounting.services.assessment_billing_service import AssessmentBillingService
from hoa_accounting.services.assessment_service import AssessmentService
from hoa_accounting.services.credit_service import CreditService
from hoa_accounting.services.deposit_batch_service import DepositBatchService
from hoa_accounting.services.lot_transfer_service import LotTransferService
from hoa_accounting.services.non_dues_income_service import NonDuesIncomeService
from hoa_accounting.services.payment_service import PaymentService
from hoa_accounting.services.reserve_transfer_service import ReserveTransferService
from hoa_accounting.services.vendor_bill_service import VendorBillService
from hoa_accounting.services.vendor_payment_service import VendorPaymentService
from hoa_accounting.validators.entity_validator import EntityValidator


class ServiceFactory:
    """Build ready-to-use services from a single connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

        self.assessments_repo = AssessmentsRepository(conn)
        self.audit_repo = AuditRepository(conn)
        self.bank_accounts_repo = BankAccountsRepository(conn)
        self.deposit_batches_repo = DepositBatchesRepository(conn)
        self.entities_repo = EntitiesRepository(conn)
        self.income_batches_repo = IncomeBatchesRepository(conn)
        self.lot_renters_repo = LotRentersRepository(conn)
        self.lots_repo = LotsRepository(conn)
        self.payments_repo = PaymentsRepository(conn)
        self.reserve_transfers_repo = ReserveTransfersRepository(conn)
        self.vendors_repo = VendorsRepository(conn)

        self.entity_validator = EntityValidator(self.entities_repo)

    def credit_service(self) -> CreditService:
        return CreditService(
            self.conn,
            payments_repo=self.payments_repo,
            assessments_repo=self.assessments_repo,
        )

    def assessment_service(self) -> AssessmentService:
        return AssessmentService(
            self.conn,
            assessment_repo=self.assessments_repo,
            audit_repo=self.audit_repo,
            entity_validator=self.entity_validator,
            credit_service=self.credit_service(),
        )

    def payment_service(self) -> PaymentService:
        return PaymentService(
            self.conn,
            payment_repo=self.payments_repo,
            assessment_repo=self.assessments_repo,
            audit_repo=self.audit_repo,
            entity_validator=self.entity_validator,
        )

    def vendor_bill_service(self) -> VendorBillService:
        return VendorBillService(
            self.conn,
            vendors_repo=self.vendors_repo,
            audit_repo=self.audit_repo,
            entity_validator=self.entity_validator,
        )

    def vendor_payment_service(self) -> VendorPaymentService:
        return VendorPaymentService(
            self.conn,
            vendors_repo=self.vendors_repo,
            audit_repo=self.audit_repo,
            entity_validator=self.entity_validator,
        )

    def deposit_batch_service(self) -> DepositBatchService:
        return DepositBatchService(
            self.conn,
            payments_repo=self.payments_repo,
            assessments_repo=self.assessments_repo,
            deposit_batches_repo=self.deposit_batches_repo,
            lots_repo=self.lots_repo,
            audit_repo=self.audit_repo,
        )

    def assessment_billing_service(self) -> AssessmentBillingService:
        return AssessmentBillingService(
            self.conn,
            assessment_service=self.assessment_service(),
            lots_repo=self.lots_repo,
        )

    def non_dues_income_service(self) -> NonDuesIncomeService:
        return NonDuesIncomeService(
            self.conn,
            income_batches_repo=self.income_batches_repo,
            lots_repo=self.lots_repo,
            bank_accounts_repo=self.bank_accounts_repo,
            audit_repo=self.audit_repo,
        )

    def reserve_transfer_service(self) -> ReserveTransferService:
        return ReserveTransferService(
            self.conn,
            audit_repo=self.audit_repo,
            reserve_transfers_repo=self.reserve_transfers_repo,
        )

    def lot_transfer_service(self) -> LotTransferService:
        return LotTransferService(
            self.conn,
            lots_repo=self.lots_repo,
            ownership_repo=LotOwnershipRepository(self.conn),
            assessments_repo=self.assessments_repo,
            audit_repo=self.audit_repo,
        )
