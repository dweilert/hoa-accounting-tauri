"""Initialize the configured SQLite database.

Usage:
    python initialize_database.py
"""

from __future__ import annotations

import getpass

from hoa_accounting.bootstrap.initializer import DatabaseInitializer
from hoa_accounting.config.loader import load_config


def main() -> None:
    config = load_config("config.yaml")

    print("HOA Accounting Database Initialization")
    print("-------------------------------------")
    print(f"HOA name     : {config.hoa.name}")
    print(f"Database path: {config.database.path}")
    print()

    admin_name = input("Initial admin full name: ").strip()
    admin_email = input("Initial admin email: ").strip()
    admin_password = getpass.getpass("Initial admin password: ")

    initializer = DatabaseInitializer(config)
    db_path = initializer.initialize(
        admin_name=admin_name,
        admin_email=admin_email,
        admin_password=admin_password,
        overwrite=False,
        operating_bank_name="Sample Bank",
        operating_last4="1234",
        reserve_bank_name="Sample Bank",
        reserve_last4="5678",
        annual_assessment_amount="1200.00",
        seed_fiscal_year=2026,
        seed_demo_data=True,
    )

    print()
    print(f"Database created successfully: {db_path}")
    print("Demo master data seeded: lot 1, owner 1, ownership row, vendor 1")


if __name__ == "__main__":
    main()
