"""Config-driven database initialization."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from pathlib import Path

from hoa_accounting.config.models import Config
from hoa_accounting.exceptions import ValidationError

from .migrator import Migrator

PBKDF2_ITERATIONS = 600_000


def make_password_hash(password: str) -> str:
    """Create a PBKDF2 password hash."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


class DatabaseInitializer:
    """Create and seed a configured SQLite database."""

    def __init__(self, config: Config) -> None:
        self.config = config

    def initialize(
        self,
        *,
        admin_name: str,
        admin_email: str,
        admin_password: str,
        overwrite: bool = False,
        operating_bank_name: str = "Sample Bank",
        operating_last4: str = "1234",
        reserve_bank_name: str = "Sample Bank",
        reserve_last4: str = "5678",
        annual_assessment_amount: str = "1200.00",
        seed_fiscal_year: int = 2026,
        seed_demo_data: bool = True,
    ) -> Path:
        """Create and seed the configured database."""
        db_type = self.config.database.type.lower()
        if db_type != "sqlite":
            raise ValidationError(f"Unsupported database type for initializer: {db_type}")

        db_path = Path(self.config.database.path).expanduser()
        db_path.parent.mkdir(parents=True, exist_ok=True)

        if db_path.exists():
            if not overwrite:
                raise ValidationError(
                    f"Database already exists at {db_path}. Use overwrite=True to replace it."
                )
            db_path.unlink()

        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            Migrator().apply_all(conn)

            self._insert_hoa_profile(conn)
            self._insert_admin_user(
                conn,
                admin_name=admin_name,
                admin_email=admin_email,
                admin_password=admin_password,
            )
            self._seed_periods(conn, fiscal_year=seed_fiscal_year)
            self._seed_bank_accounts(
                conn,
                operating_bank_name=operating_bank_name,
                operating_last4=operating_last4,
                reserve_bank_name=reserve_bank_name,
                reserve_last4=reserve_last4,
            )
            self._seed_assessment_rule(conn, annual_assessment_amount=annual_assessment_amount)
            if seed_demo_data:
                self._seed_demo_master_data(conn)
            conn.commit()
        finally:
            conn.close()

        return db_path

    def _insert_hoa_profile(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO hoa_profile (
                id,
                legal_name,
                display_name,
                corporate_state,
                federal_tax_id,
                state_tax_id,
                fiscal_year_start_month,
                timezone,
                default_currency,
                report_header_text,
                report_footer_text
            ) VALUES (
                1, ?, ?, ?, ?, ?, ?, 'America/Chicago', 'USD', ?, ?
            )
            """,
            (
                self.config.hoa.legal_name,
                self.config.hoa.name,
                "Texas",
                self.config.hoa.tax_id_federal,
                self.config.hoa.tax_id_state,
                self.config.accounting.fiscal_year_start_month,
                f"{self.config.hoa.name} Financial Reports",
                "Confidential - For Board and Authorized Users Only",
            ),
        )

    def _insert_admin_user(
        self,
        conn: sqlite3.Connection,
        *,
        admin_name: str,
        admin_email: str,
        admin_password: str,
    ) -> None:
        password_hash = make_password_hash(admin_password)
        conn.execute(
            """
            INSERT INTO users (id, email, full_name, password_hash, is_active)
            VALUES (1, ?, ?, ?, 1)
            """,
            (admin_email, admin_name, password_hash),
        )
        conn.execute("INSERT INTO user_roles (user_id, role_id) VALUES (1, 1)")
        conn.execute("INSERT INTO user_roles (user_id, role_id) VALUES (1, 2)")

    def _seed_periods(self, conn: sqlite3.Connection, *, fiscal_year: int) -> None:
        month_lengths = {
            1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
            7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31,
        }
        leap = fiscal_year % 4 == 0 and (fiscal_year % 100 != 0 or fiscal_year % 400 == 0)
        if leap:
            month_lengths[2] = 29

        for month in range(1, 13):
            start_date = f"{fiscal_year:04d}-{month:02d}-01"
            end_date = f"{fiscal_year:04d}-{month:02d}-{month_lengths[month]:02d}"
            period_name = f"{fiscal_year:04d}-{month:02d}"
            conn.execute(
                """
                INSERT INTO accounting_periods (
                    id, period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed
                ) VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (month, period_name, start_date, end_date, fiscal_year, month),
            )

    def _seed_bank_accounts(
        self,
        conn: sqlite3.Connection,
        *,
        operating_bank_name: str,
        operating_last4: str,
        reserve_bank_name: str,
        reserve_last4: str,
    ) -> None:
        conn.executemany(
            """
            INSERT INTO bank_accounts (
                id, account_name, institution_name, account_last4, account_type, fund_code, active_flag
            ) VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            [
                (1, 'Operating Checking', operating_bank_name, operating_last4, 'CHECKING', 'OPERATING'),
                (2, 'Reserve Savings', reserve_bank_name, reserve_last4, 'SAVINGS', 'RESERVE'),
            ],
        )

    def _seed_assessment_rule(
        self,
        conn: sqlite3.Connection,
        *,
        annual_assessment_amount: str,
    ) -> None:
        # category_id is resolved by code = 'DUES' if seeded; otherwise NULL.
        cat_row = conn.execute(
            "SELECT id FROM categories WHERE code = 'DUES' LIMIT 1"
        ).fetchone()
        cat_id = int(cat_row[0]) if cat_row else None
        conn.execute(
            """
            INSERT INTO assessment_rules (
                id, rule_name, frequency, default_amount, category_id,
                effective_start_date, effective_end_date, fund_code,
                active_flag, notes
            ) VALUES (
                1, 'Annual Regular Assessment', 'ANNUAL', ?, ?,
                '2026-01-01', NULL, 'OPERATING', 1,
                'Starter annual dues assessment rule'
            )
            """,
            (annual_assessment_amount, cat_id),
        )

    def _seed_demo_master_data(self, conn: sqlite3.Connection) -> None:
        """Seed minimal demo records so example scripts can run immediately."""
        conn.execute(
            """
            INSERT INTO lots (
                id, lot_number, street_address_1, city, state, postal_code, active_flag
            ) VALUES (1, '1', '100 Sample Lane', 'Austin', 'TX', '78701', 1)
            """
        )
        conn.execute(
            """
            INSERT INTO owners (
                id, owner_type, display_name, first_name, last_name, active_flag
            ) VALUES (1, 'PERSON', 'Sample Owner', 'Sample', 'Owner', 1)
            """
        )
        conn.execute(
            """
            INSERT INTO lot_ownership (
                id, lot_id, owner_id, start_date
            ) VALUES (1, 1, 1, '2026-01-01')
            """
        )
        conn.execute(
            """
            INSERT INTO vendors (
                id, vendor_name, active_flag
            ) VALUES (1, 'Sample Vendor', 1)
            """
        )
