"""Tests for the standalone renter management pages.

Uses LotRentersPages directly against an in-memory database seeded by the
real migrations. Covers:

- GET /renters: renders list, empty state, current + ended rows
- GET /renters/add: renders blank form with lot dropdown
- POST /renters/add: inserts renter, redirects with flash
- POST /renters/add: validation error re-renders form
- GET /renters/<id>/edit: form pre-filled from DB
- POST /renters/<id>/edit: updates record, redirects with flash
- POST /renters/<id>/edit: validation error re-renders form
- POST /renters/<id>/end: sets end_date, redirects with flash
- POST /renters/<id>/end: missing end_date returns error
- GET /renters/<id>/edit for unknown id returns 404
"""

from __future__ import annotations

import sqlite3

import pytest

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.repositories.lot_renters_repo import LotRentersRepository
from hoa_accounting.web.lot_renters_pages import LotRentersPages

# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    Migrator().apply_all(c)
    return c


def _seed(conn: sqlite3.Connection) -> tuple[int, int]:
    """Seed one owner, one lot, one ownership. Return (lot_id, owner_id)."""
    conn.execute(
        "INSERT INTO owners (id, owner_type, display_name, active_flag) "
        "VALUES (1, 'PERSON', 'Alice Park', 1)"
    )
    conn.execute(
        "INSERT INTO lots (id, lot_number, street_address_1, city, state, "
        "postal_code, active_flag) VALUES (1, 'L-1', '100 Pine St', 'Austin', "
        "'TX', '78701', 1)"
    )
    conn.execute(
        "INSERT INTO lot_ownership (id, lot_id, owner_id, start_date, end_date) "
        "VALUES (1, 1, 1, '2020-01-01', NULL)"
    )
    conn.commit()
    return 1, 1


_ORG = {
    "name": "Test HOA",
    "environment": "test",
    "fiscal_year_start_month": 1,
    "theme": "warm",
}


# ── render_list ────────────────────────────────────────────────────────


def test_render_list_empty_state(conn: sqlite3.Connection) -> None:
    _seed(conn)
    resp = LotRentersPages(conn).render_list(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "No renters on record" in resp.body_html


def test_render_list_shows_current_renter(conn: sqlite3.Connection) -> None:
    lot_id, _ = _seed(conn)
    LotRentersRepository(conn).insert_renter(
        lot_id=lot_id,
        display_name="Bob Tenant",
        first_name="Bob",
        last_name="Tenant",
        email="bob@example.com",
        phone="555-1234",
        start_date="2025-01-01",
    )
    conn.commit()
    resp = LotRentersPages(conn).render_list(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "Bob Tenant" in resp.body_html
    assert "555-1234" in resp.body_html
    assert "L-1" in resp.body_html


def test_render_list_shows_ended_renter_with_end_date(
    conn: sqlite3.Connection,
) -> None:
    lot_id, _ = _seed(conn)
    repo = LotRentersRepository(conn)
    renter_id = repo.insert_renter(
        lot_id=lot_id,
        display_name="Old Tenant",
        first_name=None,
        last_name=None,
        email=None,
        phone=None,
        start_date="2024-01-01",
    )
    repo.end_tenancy(renter_id=renter_id, end_date="2024-12-31")
    conn.commit()

    resp = LotRentersPages(conn).render_list(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "Old Tenant" in resp.body_html
    assert "2024-12-31" in resp.body_html


def test_render_list_flash_message(conn: sqlite3.Connection) -> None:
    _seed(conn)
    resp = LotRentersPages(conn).render_list(
        org=_ORG, theme="warm", flash_message="Renter added."
    )
    assert "Renter added." in resp.body_html


# ── render_form (add) ──────────────────────────────────────────────────


def test_render_add_form_shows_lot_dropdown(conn: sqlite3.Connection) -> None:
    _seed(conn)
    resp = LotRentersPages(conn).render_form(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "L-1" in resp.body_html
    assert "Display Name" in resp.body_html
    assert "Start Date" in resp.body_html


# ── render_form (edit) ─────────────────────────────────────────────────


def test_render_edit_form_prefilled(conn: sqlite3.Connection) -> None:
    lot_id, _ = _seed(conn)
    renter_id = LotRentersRepository(conn).insert_renter(
        lot_id=lot_id,
        display_name="Jane Tenant",
        first_name="Jane",
        last_name="Tenant",
        email="jane@example.com",
        phone="555-9999",
        start_date="2025-06-01",
    )
    conn.commit()

    resp = LotRentersPages(conn).render_form(
        org=_ORG, theme="warm", renter_id=renter_id
    )
    assert resp.status_code == 200
    assert "Jane Tenant" in resp.body_html
    assert "jane@example.com" in resp.body_html
    assert "555-9999" in resp.body_html


def test_render_edit_form_unknown_returns_404(conn: sqlite3.Connection) -> None:
    resp = LotRentersPages(conn).render_form(org=_ORG, theme="warm", renter_id=999)
    assert resp.status_code == 404


# ── handle_add ─────────────────────────────────────────────────────────


def test_handle_add_success_redirects(conn: sqlite3.Connection) -> None:
    lot_id, _ = _seed(conn)
    redirect_url, form_resp = LotRentersPages(conn).handle_add(
        form_data={
            "lot_id": str(lot_id),
            "display_name": "Jane Renter",
            "first_name": "Jane",
            "last_name": "Renter",
            "email": "jane@example.com",
            "phone": "555-9999",
            "start_date": "2026-01-01",
        },
        org=_ORG,
        theme="warm",
    )
    assert redirect_url == "/renters?msg=Renter+added."
    assert form_resp is None
    rows = LotRentersRepository(conn).get_current_renters(lot_id)
    assert rows[0]["display_name"] == "Jane Renter"


def test_handle_add_missing_display_name_returns_error(
    conn: sqlite3.Connection,
) -> None:
    lot_id, _ = _seed(conn)
    redirect_url, form_resp = LotRentersPages(conn).handle_add(
        form_data={"lot_id": str(lot_id), "start_date": "2026-01-01"},
        org=_ORG,
        theme="warm",
    )
    assert redirect_url is None
    assert form_resp is not None
    assert form_resp.status_code == 400
    assert "Display Name" in form_resp.body_html


def test_handle_add_missing_lot_returns_error(conn: sqlite3.Connection) -> None:
    _seed(conn)
    redirect_url, form_resp = LotRentersPages(conn).handle_add(
        form_data={"display_name": "Jane", "start_date": "2026-01-01"},
        org=_ORG,
        theme="warm",
    )
    assert redirect_url is None
    assert form_resp is not None
    assert form_resp.status_code == 400


# ── handle_edit ────────────────────────────────────────────────────────


def test_handle_edit_success_redirects(conn: sqlite3.Connection) -> None:
    lot_id, _ = _seed(conn)
    renter_id = LotRentersRepository(conn).insert_renter(
        lot_id=lot_id,
        display_name="Old Name",
        first_name=None,
        last_name=None,
        email=None,
        phone=None,
        start_date="2025-01-01",
    )
    conn.commit()

    redirect_url, form_resp = LotRentersPages(conn).handle_edit(
        renter_id=renter_id,
        form_data={
            "lot_id": str(lot_id),
            "display_name": "New Name",
            "start_date": "2025-01-01",
            "phone": "555-0001",
            "email": "new@example.com",
        },
        org=_ORG,
        theme="warm",
    )
    assert redirect_url == "/renters?msg=Renter+updated."
    assert form_resp is None

    updated = LotRentersRepository(conn).get_renter(renter_id)
    assert updated["display_name"] == "New Name"
    assert updated["phone"] == "555-0001"


def test_handle_edit_missing_display_name_returns_error(
    conn: sqlite3.Connection,
) -> None:
    lot_id, _ = _seed(conn)
    renter_id = LotRentersRepository(conn).insert_renter(
        lot_id=lot_id,
        display_name="Test",
        first_name=None,
        last_name=None,
        email=None,
        phone=None,
        start_date="2025-01-01",
    )
    conn.commit()

    redirect_url, form_resp = LotRentersPages(conn).handle_edit(
        renter_id=renter_id,
        form_data={"lot_id": str(lot_id), "start_date": "2025-01-01"},
        org=_ORG,
        theme="warm",
    )
    assert redirect_url is None
    assert form_resp is not None
    assert form_resp.status_code == 400


# ── handle_end ─────────────────────────────────────────────────────────


def test_handle_end_success_redirects(conn: sqlite3.Connection) -> None:
    lot_id, _ = _seed(conn)
    renter_id = LotRentersRepository(conn).insert_renter(
        lot_id=lot_id,
        display_name="Bob Tenant",
        first_name=None,
        last_name=None,
        email=None,
        phone=None,
        start_date="2025-01-01",
    )
    conn.commit()

    redirect_url, form_resp = LotRentersPages(conn).handle_end(
        renter_id=renter_id,
        form_data={"end_date": "2026-03-31"},
        org=_ORG,
        theme="warm",
    )
    assert redirect_url == "/renters?msg=Tenancy+ended."
    assert form_resp is None
    assert len(LotRentersRepository(conn).get_current_renters(lot_id)) == 0


def test_handle_end_missing_date_returns_error(conn: sqlite3.Connection) -> None:
    lot_id, _ = _seed(conn)
    renter_id = LotRentersRepository(conn).insert_renter(
        lot_id=lot_id,
        display_name="Bob Tenant",
        first_name=None,
        last_name=None,
        email=None,
        phone=None,
        start_date="2025-01-01",
    )
    conn.commit()

    redirect_url, form_resp = LotRentersPages(conn).handle_end(
        renter_id=renter_id,
        form_data={},
        org=_ORG,
        theme="warm",
    )
    assert redirect_url is None
    assert form_resp is not None
    assert "End Date" in form_resp.body_html
