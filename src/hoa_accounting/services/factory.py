"""Factory helpers to build configured services."""

from __future__ import annotations

import sqlite3

from hoa_accounting.repositories.accounts_repo import AccountsRepository
from hoa_accounting.repositories.assessments_repo import AssessmentsRepository
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.bank_accounts_repo import BankAccountsRepository
from hoa_accounting.repositories.deposit_batches_repo import DepositBatchesRepository
from hoa_accounting.repositories.entities_repo import EntitiesRepository
from hoa_accounting.repositories.journal_repo import JournalRepository
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.repositories.payments_repo import PaymentsRepository
from hoa_accounting.repositories.periods_repo import PeriodsRepository
from hoa_accounting.repositories.reserve_transfers_repo import ReserveTransfersRepository
from hoa_accounting.repositories.vendors_repo import VendorsRepository
from hoa_accounting.services.assessment_service import AssessmentService
from hoa_accounting.services.deposit_batch_service import DepositBatchService
from hoa_accounting.services.journal_service import JournalService
from hoa_accounting.services.payment_service import PaymentService
from hoa_accounting.services.reserve_transfer_service import ReserveTransferService
from hoa_accounting.services.reversal_service import ReversalService
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

        self.accounts_repo = AccountsRepository(conn)
        self.assessments_repo = AssessmentsRepository(conn)
        self.audit_repo = AuditRepository(conn)
        self.bank_accounts_repo = BankAccountsRepository(conn)
        self.deposit_batches_repo = DepositBatchesRepository(conn)
        self.entities_repo = EntitiesRepository(conn)
        self.journal_repo = JournalRepository(conn)
        self.lots_repo = LotsRepository(conn)
        self.payments_repo = PaymentsRepository(conn)
        self.periods_repo = PeriodsRepository(conn)
        self.reserve_transfers_repo = ReserveTransfersRepository(conn)
        self.vendors_repo = VendorsRepository(conn)

        self.account_validator = AccountValidator(self.accounts_repo)
        self.account_role_validator = AccountRoleValidator(self.accounts_repo)
        self.entity_validator = EntityValidator(self.entities_repo)
        self.period_validator = PeriodValidator(self.periods_repo)
        self.journal_validator = JournalValidator(self.account_validator)

    def journal_service(self) -> JournalService:
        """Return a configured journal service."""
        return JournalService(
            self.conn,
            journal_repo=self.journal_repo,
            audit_repo=self.audit_repo,
            period_validator=self.period_validator,
            journal_validator=self.journal_validator,
        )

    def assessment_service(self) -> AssessmentService:
        """Return a configured assessment service."""
        return AssessmentService(
            self.conn,
            assessment_repo=self.assessments_repo,
            audit_repo=self.audit_repo,
            journal_repo=self.journal_repo,
            journal_service=self.journal_service(),
            entity_validator=self.entity_validator,
            account_validator=self.account_validator,
            account_role_validator=self.account_role_validator,
        )

    def payment_service(self) -> PaymentService:
        """Return a configured payment service."""
        return PaymentService(
            self.conn,
            payment_repo=self.payments_repo,
            assessment_repo=self.assessments_repo,
            audit_repo=self.audit_repo,
            journal_repo=self.journal_repo,
            journal_service=self.journal_service(),
            entity_validator=self.entity_validator,
            account_validator=self.account_validator,
            account_role_validator=self.account_role_validator,
        )

    def vendor_bill_service(self) -> VendorBillService:
        """Return a configured vendor bill service."""
        return VendorBillService(
            self.conn,
            vendors_repo=self.vendors_repo,
            audit_repo=self.audit_repo,
            journal_repo=self.journal_repo,
            journal_service=self.journal_service(),
            entity_validator=self.entity_validator,
            account_validator=self.account_validator,
            account_role_validator=self.account_role_validator,
        )

    def vendor_payment_service(self) -> VendorPaymentService:
        """Return a configured vendor payment service."""
        return VendorPaymentService(
            self.conn,
            vendors_repo=self.vendors_repo,
            audit_repo=self.audit_repo,
            journal_repo=self.journal_repo,
            journal_service=self.journal_service(),
            entity_validator=self.entity_validator,
            account_validator=self.account_validator,
            account_role_validator=self.account_role_validator,
        )

    def reversal_service(self) -> ReversalService:
        """Return a configured reversal service."""
        return ReversalService(
            self.conn,
            journal_repo=self.journal_repo,
            audit_repo=self.audit_repo,
            journal_service=self.journal_service(),
        )

    def deposit_batch_service(self) -> DepositBatchService:
        """Return a configured deposit-batch service."""
        return DepositBatchService(
            self.conn,
            payments_repo=self.payments_repo,
            assessments_repo=self.assessments_repo,
            deposit_batches_repo=self.deposit_batches_repo,
            lots_repo=self.lots_repo,
            accounts_repo=self.accounts_repo,
            bank_accounts_repo=self.bank_accounts_repo,
            audit_repo=self.audit_repo,
            journal_repo=self.journal_repo,
            journal_service=self.journal_service(),
        )

    def reserve_transfer_service(self) -> ReserveTransferService:
        """Return a configured reserve transfer service."""
        return ReserveTransferService(
            self.conn,
            audit_repo=self.audit_repo,
            journal_repo=self.journal_repo,
            reserve_transfers_repo=self.reserve_transfers_repo,
            journal_service=self.journal_service(),
            account_validator=self.account_validator,
            account_role_validator=self.account_role_validator,
        )
