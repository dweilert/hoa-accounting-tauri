"""Factory helpers to build configured services."""

from __future__ import annotations

import sqlite3

from hoa_accounting.repositories.accounts_repo import AccountsRepository
from hoa_accounting.repositories.assessments_repo import AssessmentsRepository
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.bank_accounts_repo import BankAccountsRepository
from hoa_accounting.repositories.deposit_batches_repo import DepositBatchesRepository
from hoa_accounting.repositories.entities_repo import EntitiesRepository
from hoa_accounting.repositories.income_batches_repo import IncomeBatchesRepository
from hoa_accounting.repositories.journal_repo import JournalRepository
from hoa_accounting.repositories.lot_renters_repo import LotRentersRepository
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.repositories.payments_repo import PaymentsRepository
from hoa_accounting.repositories.periods_repo import PeriodsRepository
from hoa_accounting.repositories.reserve_transfers_repo import ReserveTransfersRepository
from hoa_accounting.repositories.vendors_repo import VendorsRepository
from hoa_accounting.repositories.year_end_close_repo import YearEndCloseRepository
from hoa_accounting.services.assessment_billing_service import AssessmentBillingService
from hoa_accounting.services.assessment_service import AssessmentService
from hoa_accounting.services.deposit_batch_service import DepositBatchService
from hoa_accounting.services.journal_service import JournalService
from hoa_accounting.services.non_dues_income_service import NonDuesIncomeService
from hoa_accounting.services.payment_service import PaymentService
from hoa_accounting.services.reserve_transfer_service import ReserveTransferService
from hoa_accounting.services.vendor_bill_service import VendorBillService
from hoa_accounting.services.vendor_payment_service import VendorPaymentService
from hoa_accounting.validators.account_role_validator import AccountRoleValidator
from hoa_accounting.validators.account_validator import AccountValidator
from hoa_accounting.validators.entity_validator import EntityValidator
from hoa_accounting.validators.journal_validator import JournalValidator
from hoa_accounting.validators.period_validator import PeriodValidator


class ServiceFactory:
    """Build ready-to-use services from a single connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

        # Core repos used by simplified transaction services.
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
        self.year_end_close_repo = YearEndCloseRepository(conn)

        self.entity_validator = EntityValidator(self.entities_repo)

        # Legacy journal infrastructure — kept for manual journal entries and
        # opening balances until those pages are reworked for single-entry.
        self.accounts_repo = AccountsRepository(conn)
        self.journal_repo = JournalRepository(conn)
        self.periods_repo = PeriodsRepository(conn)
        self.account_validator = AccountValidator(self.accounts_repo)
        self.account_role_validator = AccountRoleValidator(self.accounts_repo)
        self.journal_validator = JournalValidator(self.account_validator)
        self.period_validator = PeriodValidator(
            self.periods_repo,
            year_end_close_repo=self.year_end_close_repo,
        )

    # ── Simplified single-entry transaction services ────────────────────────

    def assessment_service(self) -> AssessmentService:
        return AssessmentService(
            self.conn,
            assessment_repo=self.assessments_repo,
            audit_repo=self.audit_repo,
            entity_validator=self.entity_validator,
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

    # ── Legacy journal service — used by manual journal + opening balances ──

    def journal_service(self) -> JournalService:
        return JournalService(
            self.conn,
            journal_repo=self.journal_repo,
            audit_repo=self.audit_repo,
            period_validator=self.period_validator,
            journal_validator=self.journal_validator,
        )
