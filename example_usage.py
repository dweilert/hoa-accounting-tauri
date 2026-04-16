"""Example usage of the refactored HOA accounting engine."""

from __future__ import annotations

from pathlib import Path

from hoa_accounting.config.loader import load_config
from hoa_accounting.db.connection import connect_sqlite
from hoa_accounting.db.transaction import transaction
from hoa_accounting.services.factory import ServiceFactory


def main() -> None:
    config = load_config(Path("config.yaml"))
    conn = connect_sqlite(config.database.path)
    factory = ServiceFactory(conn)

    with transaction(conn):
        assessment = factory.assessment_service().post_assessment(
            entry_date="2026-01-15",
            lot_id=1,
            owner_id=1,
            amount="1200.00",
            description=f"Annual HOA assessment for {config.hoa.name} Lot 1",
            receivable_account_id=1100,
            income_account_id=4000,
            created_by_user_id=1,
            due_date="2026-02-15",
        )
        print("Assessment:", assessment)

    with transaction(conn):
        payment = factory.payment_service().post_payment(
            entry_date="2026-01-20",
            owner_id=1,
            amount="1200.00",
            description="Owner payment for annual assessment",
            cash_account_id=1000,
            receivable_account_id=1100,
            bank_account_id=1,
            payment_method="CHECK",
            receipt_number="RCPT-1001",
            reference_number="Check 501",
            created_by_user_id=1,
            apply_to_assessment_ids=[assessment.assessment_id],
        )
        print("Payment:", payment)

    conn.close()


if __name__ == "__main__":
    main()
