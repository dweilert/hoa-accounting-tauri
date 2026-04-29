"""Database initializer tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from hoa_accounting.bootstrap.initializer import DatabaseInitializer
from hoa_accounting.config.models import (
    AccountingConfig,
    AppConfig,
    Config,
    DatabaseConfig,
    HOAConfig,
)


def test_initializer_creates_database(tmp_path: Path) -> None:
    """Initializer creates a configured SQLite database."""
    db_path = tmp_path / "hoa_accounting.db"
    config = Config(
        hoa=HOAConfig(
            name="Test HOA",
            legal_name="Test HOA, Inc.",
            tax_id_federal="11-1111111",
            tax_id_state="TX-1",
        ),
        database=DatabaseConfig(type="sqlite", path=str(db_path)),
        app=AppConfig(environment="local", debug=True),
        accounting=AccountingConfig(
            fiscal_year_start_month=1, default_fund="OPERATING"
        ),
    )

    initializer = DatabaseInitializer(config)
    created_path = initializer.initialize(
        admin_name="Admin User",
        admin_email="admin@example.com",
        admin_password="super-secure-password",
        overwrite=False,
        seed_demo_data=True,
    )

    assert created_path == db_path
    assert db_path.exists()

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT display_name FROM hoa_profile WHERE id = 1"
        ).fetchone()
        assert row is not None
        assert row[0] == "Test HOA"

        lot_row = conn.execute("SELECT lot_number FROM lots WHERE id = 1").fetchone()
        owner_row = conn.execute(
            "SELECT display_name FROM owners WHERE id = 1"
        ).fetchone()
        vendor_row = conn.execute(
            "SELECT vendor_name FROM vendors WHERE id = 1"
        ).fetchone()

        assert lot_row is not None
        assert owner_row is not None
        assert vendor_row is not None
    finally:
        conn.close()
