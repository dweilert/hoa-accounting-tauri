"""Example usage of the reporting services."""

from __future__ import annotations

from hoa_accounting.config.loader import load_config
from hoa_accounting.db.connection import connect_sqlite
from hoa_accounting.reporting.general_ledger import GeneralLedgerReportService
from hoa_accounting.reporting.trial_balance import TrialBalanceReportService


def main() -> None:
    config = load_config("config.yaml")
    conn = connect_sqlite(config.database.path)

    tb_service = TrialBalanceReportService(conn)
    gl_service = GeneralLedgerReportService(conn)

    trial_balance = tb_service.generate(as_of_date="2026-01-31")
    print(f"Trial Balance for {config.hoa.name}")
    print("Debits :", trial_balance.total_debits)
    print("Credits:", trial_balance.total_credits)
    for row in trial_balance.rows:
        print(row)

    print()
    ledger = gl_service.generate(account_id=1000, from_date="2026-01-01", to_date="2026-01-31")
    print(f"General Ledger for {ledger.account_number} - {ledger.account_name}")
    for row in ledger.rows:
        print(row)

    conn.close()


if __name__ == "__main__":
    main()
