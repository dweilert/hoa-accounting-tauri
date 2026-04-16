"""Tests for the master-data list pages.

Exercise each list page via ``MasterDataListService`` against an
in-memory database seeded by the real migrations, plus a handful of
representative rows. Confirms:

- The page renders without error and returns a non-empty HTML body.
- Key column labels and seeded values show up in the rendered HTML.
- The shared empty-state renders when a table has no rows.
- Repository list methods return rows in the expected order and shape.
"""

from __future__ import annotations

import sqlite3

import pytest

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.repositories.bank_accounts_repo import BankAccountsRepository
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.repositories.owners_repo import OwnersRepository
from hoa_accounting.repositories.vendors_repo import VendorsRepository
from hoa_accounting.web.master_data_pages import MasterDataListService


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    Migrator().apply_all(c)
    return c


def _seed_owners_and_lots(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO owners (id, owner_type, display_name, first_name, last_name, "
        "email, phone, city, state, postal_code, active_flag) "
        "VALUES (1, 'PERSON', 'Alice Park', 'Alice', 'Park', "
        "'alice@example.com', '555-0100', 'Austin', 'TX', '78701', 1)"
    )
    conn.execute(
        "INSERT INTO owners (id, owner_type, display_name, active_flag) "
        "VALUES (2, 'PERSON', 'Bob Cole', 1)"
    )
    conn.execute(
        "INSERT INTO lots (id, lot_number, street_address_1, city, state, postal_code, active_flag) "
        "VALUES (1, 'L-1', '100 Pine', 'Austin', 'TX', '78701', 1)"
    )
    conn.execute(
        "INSERT INTO lot_ownership (id, lot_id, owner_id, start_date, end_date, "
        "ownership_percent, is_primary_contact) "
        "VALUES (1, 1, 1, '2020-01-01', NULL, 100.0, 1)"
    )
    conn.execute(
        "INSERT INTO lots (id, lot_number, active_flag) VALUES (2, 'L-2', 1)"
    )
    conn.commit()


def _seed_vendors(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO vendors (id, vendor_name, contact_name, email, phone, "
        "city, state, postal_code, active_flag) "
        "VALUES (1, 'Green Yard Services', 'Jo Smith', 'jo@green.example', "
        "'555-0200', 'Austin', 'TX', '78702', 1)"
    )
    conn.commit()


def _seed_bank_accounts(conn: sqlite3.Connection) -> None:
    # A new cash-type GL account (account_type_id 1 = ASSET).
    conn.execute(
        "INSERT INTO accounts (id, account_number, account_name, account_type_id, "
        "fund_code, is_bank_account, is_active) "
        "VALUES (100, '1000', 'Cash - Operating', 1, 'OPERATING', 1, 1)"
    )
    conn.execute(
        "INSERT INTO bank_accounts (id, account_name, institution_name, account_last4, "
        "account_type, gl_account_id, active_flag) "
        "VALUES (1, 'Operating Checking', 'Big Bank', '1234', 'CHECKING', 100, 1)"
    )
    conn.commit()


_ORG = {
    "name": "Test HOA",
    "legal_name": "Test HOA Inc.",
    "environment": "test",
    "fiscal_year_start_month": 1,
    "theme": "warm",
}


# ── Repository list methods ───────────────────────────────────────────


def test_owners_repo_orders_by_display_name(conn: sqlite3.Connection) -> None:
    _seed_owners_and_lots(conn)
    rows = OwnersRepository(conn).list_owners()
    names = [r["display_name"] for r in rows]
    assert names == ["Alice Park", "Bob Cole"]


def test_lots_repo_joins_current_primary_owner(conn: sqlite3.Connection) -> None:
    _seed_owners_and_lots(conn)
    rows = LotsRepository(conn).list_lots()
    by_lot = {r["lot_number"]: r for r in rows}
    # L-1 has a current primary owner, L-2 does not — repo must still return both.
    assert by_lot["L-1"]["owner_name"] == "Alice Park"
    assert by_lot["L-2"]["owner_name"] is None


def test_vendors_repo_lists_active(conn: sqlite3.Connection) -> None:
    _seed_vendors(conn)
    rows = VendorsRepository(conn).list_vendors()
    assert any(r["vendor_name"] == "Green Yard Services" for r in rows)


def test_bank_accounts_repo_joins_gl_account(conn: sqlite3.Connection) -> None:
    _seed_bank_accounts(conn)
    rows = BankAccountsRepository(conn).list_bank_accounts()
    assert rows[0]["gl_account_number"] == "1000"
    assert rows[0]["gl_account_name"] == "Cash - Operating"


# ── Page render ────────────────────────────────────────────────────────


def test_render_accounts_page_shows_seeded_chart(conn: sqlite3.Connection) -> None:
    svc = MasterDataListService(conn)
    resp = svc.render_accounts(org=_ORG, theme="warm")
    assert resp.status_code == 200
    # The migration seeds these — each must appear in the chart. 'Mow & Blow'
    # is skipped here because the ampersand is HTML-escaped on render; we
    # match unambiguous names instead.
    for name in ["Sprinkler System", "Utilities", "Firewise"]:
        assert name in resp.body_html
    # Group label shown on every expense row.
    assert "LANDSCAPE" in resp.body_html


def test_render_owners_page(conn: sqlite3.Connection) -> None:
    _seed_owners_and_lots(conn)
    resp = MasterDataListService(conn).render_owners(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "Alice Park" in resp.body_html
    assert "Bob Cole" in resp.body_html
    assert "Owners" in resp.body_html


def test_render_lots_page_shows_owner_for_lot(conn: sqlite3.Connection) -> None:
    _seed_owners_and_lots(conn)
    resp = MasterDataListService(conn).render_lots(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "L-1" in resp.body_html
    # L-1 has a primary owner.
    assert "Alice Park" in resp.body_html
    # L-2 has none — rendered as em-dash placeholder.
    assert "L-2" in resp.body_html


def test_render_vendors_page(conn: sqlite3.Connection) -> None:
    _seed_vendors(conn)
    resp = MasterDataListService(conn).render_vendors(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "Green Yard Services" in resp.body_html


def test_render_bank_accounts_page(conn: sqlite3.Connection) -> None:
    _seed_bank_accounts(conn)
    resp = MasterDataListService(conn).render_bank_accounts(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "Operating Checking" in resp.body_html
    assert "Big Bank" in resp.body_html
    assert "1234" in resp.body_html


def test_empty_owners_page_renders_empty_state(conn: sqlite3.Connection) -> None:
    """No owners seeded — page must render the empty-state message, not a table."""
    resp = MasterDataListService(conn).render_owners(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "No owners on record" in resp.body_html
