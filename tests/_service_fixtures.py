"""Shared in-memory fixture for service-level tests.

Builds a fresh SQLite DB with all migrations applied and a minimal seed:
two lots, two owners (linked to lots), two vendors, two bank accounts,
two income categories, two expense categories, and one accounting period.

Service tests should call ``build_seeded_conn()`` and reference the IDs
exposed in the returned dataclass.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from hoa_accounting.bootstrap.migrator import Migrator


@dataclass(frozen=True)
class SeedIds:
    user_id: int
    period_id: int
    lot1_id: int
    lot2_id: int
    owner1_id: int
    owner2_id: int
    vendor1_id: int
    vendor2_id: int
    bank_op_id: int
    bank_res_id: int
    cat_dues_id: int
    cat_late_id: int
    cat_resale_id: int
    cat_landscape_id: int
    cat_utilities_id: int


def build_seeded_conn() -> tuple[sqlite3.Connection, SeedIds]:
    """Return (conn, ids). Apply all migrations + seed enough rows for
    every service to post a happy-path record.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Audit triggers added in migrations 0049+ call audit_user(); register
    # the UDF before migrations run.
    conn.create_function("audit_user", 0, lambda: "test")
    Migrator().apply_all(conn)

    # ── Local user ─────────────────────────────────────────────────
    conn.execute(
        "INSERT INTO local_users (id, email, password_hash, display_name, role, is_active) "
        "VALUES (1, 'test@example.com', 'x', 'Tester', 'admin', 1)"
    )
    # ``audit_log.user_id`` FKs to legacy ``users.id``; seed it too so
    # services that record an audit row don't trip the foreign key.
    conn.execute(
        "INSERT INTO users (id, email, full_name, password_hash, is_active) "
        "VALUES (1, 'test@example.com', 'Tester', 'x', 1)"
    )

    # ── Accounting period ──────────────────────────────────────────
    conn.execute(
        "INSERT INTO accounting_periods "
        "(id, period_name, start_date, end_date, fiscal_year, fiscal_period, is_closed) "
        "VALUES (1, '2026-01', '2026-01-01', '2026-01-31', 2026, 1, 0)"
    )

    # ── Lots + owners + ownership ──────────────────────────────────
    conn.execute("INSERT INTO lots (id, lot_number, active_flag) VALUES (1,'L-1',1),(2,'L-2',1)")
    conn.execute(
        "INSERT INTO owners (id, owner_type, display_name, first_name, last_name, "
        "active_flag) VALUES (1,'PERSON','Alice Park','Alice','Park',1),"
        "(2,'PERSON','Bob Lee','Bob','Lee',1)"
    )
    conn.execute(
        "INSERT INTO lot_ownership (lot_id, owner_id, start_date) "
        "VALUES (1, 1, '2024-01-01'), (2, 2, '2024-01-01')"
    )

    # ── Vendors ────────────────────────────────────────────────────
    conn.execute(
        "INSERT INTO vendors (id, vendor_name, active_flag) "
        "VALUES (1,'Acme Lawn',1),(2,'City Water',1)"
    )

    # ── Bank accounts (one per fund) ──────────────────────────────
    conn.execute(
        "INSERT INTO bank_accounts (id, account_name, institution_name, account_last4, "
        "account_type, fund_code, opening_balance, active_flag) VALUES "
        "(1,'Operating Checking','Test Bank','0001','CHECKING','OPERATING','0',1),"
        "(2,'Reserve Savings','Test Bank','0002','SAVINGS','RESERVE','0',1)"
    )

    # ── Categories ──────────────────────────────────────────────────
    # Migrations seed the standard categories already; just resolve their
    # IDs by code rather than inserting our own (avoids UNIQUE clashes).
    def _cat(code: str) -> int:
        row = conn.execute(
            "SELECT id FROM categories WHERE code = ?", (code,)
        ).fetchone()
        if row:
            return int(row["id"])
        # Fallback: code wasn't seeded by migrations; create it.
        cur = conn.execute(
            "INSERT INTO categories (code, name, category_type, fund_code, active_flag) "
            "VALUES (?, ?, ?, 'OPERATING', 1)",
            (code, code.replace("_", " ").title(),
             "EXPENSE" if code in {"LANDSCAPE", "UTILITIES"} else "INCOME"),
        )
        return int(cur.lastrowid)

    cat_dues_id      = _cat("DUES")
    cat_late_id      = _cat("LATE_FEES")
    cat_resale_id    = _cat("RESALE_FEE")
    cat_landscape_id = _cat("LANDSCAPE")
    cat_utilities_id = _cat("UTILITIES")

    conn.commit()
    return conn, SeedIds(
        user_id=1, period_id=1,
        lot1_id=1, lot2_id=2,
        owner1_id=1, owner2_id=2,
        vendor1_id=1, vendor2_id=2,
        bank_op_id=1, bank_res_id=2,
        cat_dues_id=cat_dues_id,
        cat_late_id=cat_late_id,
        cat_resale_id=cat_resale_id,
        cat_landscape_id=cat_landscape_id,
        cat_utilities_id=cat_utilities_id,
    )
