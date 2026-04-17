"""Tests for the owner management pages.

Uses OwnerPages directly against an in-memory database seeded by the
real migrations. Covers:

- GET /owners: renders list, empty state, owner with lot, flash message
- GET /owners/add: renders blank form with lot dropdown
- POST /owners/add: inserts owner only, redirects with flash
- POST /owners/add: inserts owner with lot assignment
- POST /owners/add: validation error re-renders form
- POST /owners/add: 2-owner limit enforced
- POST /owners/add: Owner 1 conflict enforced
- GET /owners/<id>/edit: form pre-filled from DB
- POST /owners/<id>/edit: updates contact info, redirects with flash
- POST /owners/<id>/edit: validation error re-renders form
- GET /owners/<id>/edit for unknown id returns 404
- POST /owners/<id>/mark-previous: ends ownership, redirects with flash
- POST /owners/<id>/mark-previous: missing end_date returns error
- POST /owners/<id>/mark-previous: no current ownership returns error
"""

from __future__ import annotations

import sqlite3

import pytest

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.repositories.lot_ownership_repo import LotOwnershipRepository
from hoa_accounting.repositories.owners_repo import OwnersRepository
from hoa_accounting.web.owner_pages import OwnerPages


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    Migrator().apply_all(c)
    return c


def _seed_lot(conn: sqlite3.Connection, lot_number: str = "L-1") -> int:
    """Seed one lot and return its id."""
    cur = conn.execute(
        "INSERT INTO lots (lot_number, street_address_1, city, state, "
        "postal_code, active_flag) VALUES (?, '100 Pine St', 'Austin', "
        "'TX', '78701', 1)",
        (lot_number,),
    )
    conn.commit()
    return int(cur.lastrowid)


def _seed_owner(conn: sqlite3.Connection, display_name: str = "Alice Park") -> int:
    """Seed one owner and return its id."""
    cur = conn.execute(
        "INSERT INTO owners (owner_type, display_name, active_flag) "
        "VALUES ('PERSON', ?, 1)",
        (display_name,),
    )
    conn.commit()
    return int(cur.lastrowid)


def _assign(
    conn: sqlite3.Connection,
    lot_id: int,
    owner_id: int,
    is_primary: bool = True,
) -> int:
    cur = conn.execute(
        "INSERT INTO lot_ownership (lot_id, owner_id, start_date, "
        "ownership_percent, is_primary_contact) VALUES (?, ?, '2020-01-01', 100.0, ?)",
        (lot_id, owner_id, 1 if is_primary else 0),
    )
    conn.commit()
    return int(cur.lastrowid)


_ORG = {"name": "Test HOA", "environment": "test",
        "fiscal_year_start_month": 1, "theme": "warm"}


# ── render_list ────────────────────────────────────────────────────────


def test_render_list_empty_state(conn: sqlite3.Connection) -> None:
    resp = OwnerPages(conn).render_list(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "No owners on record" in resp.body_html


def test_render_list_shows_owner_without_lot(conn: sqlite3.Connection) -> None:
    _seed_owner(conn, "Bob Buyer")
    resp = OwnerPages(conn).render_list(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "Bob Buyer" in resp.body_html


def test_render_list_shows_owner_with_lot(conn: sqlite3.Connection) -> None:
    lot_id = _seed_lot(conn)
    owner_id = _seed_owner(conn, "Carol Owner")
    _assign(conn, lot_id, owner_id)
    resp = OwnerPages(conn).render_list(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "Carol Owner" in resp.body_html
    assert "L-1" in resp.body_html
    assert "Owner 1" in resp.body_html


def test_render_list_flash_message(conn: sqlite3.Connection) -> None:
    resp = OwnerPages(conn).render_list(
        org=_ORG, theme="warm", flash_message="Owner added."
    )
    assert "Owner added." in resp.body_html


def test_render_list_mark_previous_button_shown_when_assigned(
    conn: sqlite3.Connection,
) -> None:
    lot_id = _seed_lot(conn)
    owner_id = _seed_owner(conn)
    _assign(conn, lot_id, owner_id)
    resp = OwnerPages(conn).render_list(org=_ORG, theme="warm")
    assert "Mark as Previous" in resp.body_html


def test_render_list_no_mark_previous_when_not_assigned(
    conn: sqlite3.Connection,
) -> None:
    _seed_owner(conn)
    resp = OwnerPages(conn).render_list(org=_ORG, theme="warm")
    # Button appears only for owners with a current lot assignment
    assert 'mark-previous' not in resp.body_html


# ── render_form (add) ──────────────────────────────────────────────────


def test_render_add_form_shows_lot_dropdown(conn: sqlite3.Connection) -> None:
    _seed_lot(conn)
    resp = OwnerPages(conn).render_form(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "L-1" in resp.body_html
    assert "Display Name" in resp.body_html
    assert "Owner Type" in resp.body_html


# ── render_form (edit) ─────────────────────────────────────────────────


def test_render_edit_form_prefilled(conn: sqlite3.Connection) -> None:
    owner_id = _seed_owner(conn, "Jane Owner")
    conn.execute(
        "UPDATE owners SET email='jane@example.com', phone='555-1111' WHERE id=?",
        (owner_id,),
    )
    conn.commit()
    resp = OwnerPages(conn).render_form(org=_ORG, theme="warm", owner_id=owner_id)
    assert resp.status_code == 200
    assert "Jane Owner" in resp.body_html
    assert "jane@example.com" in resp.body_html
    assert "555-1111" in resp.body_html


def test_render_edit_form_shows_current_lot(conn: sqlite3.Connection) -> None:
    lot_id = _seed_lot(conn)
    owner_id = _seed_owner(conn)
    _assign(conn, lot_id, owner_id)
    resp = OwnerPages(conn).render_form(org=_ORG, theme="warm", owner_id=owner_id)
    assert resp.status_code == 200
    assert "L-1" in resp.body_html


def test_render_edit_form_unknown_returns_404(conn: sqlite3.Connection) -> None:
    resp = OwnerPages(conn).render_form(org=_ORG, theme="warm", owner_id=999)
    assert resp.status_code == 404


# ── handle_add ─────────────────────────────────────────────────────────


def test_handle_add_owner_only_redirects(conn: sqlite3.Connection) -> None:
    redirect_url, form_resp = OwnerPages(conn).handle_add(
        form_data={
            "owner_type": "PERSON",
            "display_name": "New Owner",
            "first_name": "New",
            "last_name": "Owner",
            "email": "new@example.com",
            "phone": "555-2222",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url == "/owners?msg=Owner+added."
    assert form_resp is None
    row = OwnersRepository(conn).list_owners()[0]
    assert row["display_name"] == "New Owner"


def test_handle_add_with_lot_assignment(conn: sqlite3.Connection) -> None:
    lot_id = _seed_lot(conn)
    redirect_url, form_resp = OwnerPages(conn).handle_add(
        form_data={
            "owner_type": "PERSON",
            "display_name": "Lot Owner",
            "lot_id": str(lot_id),
            "start_date": "2026-01-01",
            "is_primary_contact": "1",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url == "/owners?msg=Owner+added."
    assert form_resp is None
    rows = OwnersRepository(conn).list_owners()
    owner_id = rows[0]["id"]
    ownership = LotOwnershipRepository(conn).get_current_ownership_by_owner(owner_id)
    assert ownership is not None
    assert ownership["lot_id"] == lot_id


def test_handle_add_missing_display_name_returns_error(
    conn: sqlite3.Connection,
) -> None:
    redirect_url, form_resp = OwnerPages(conn).handle_add(
        form_data={"owner_type": "PERSON"},
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert form_resp is not None
    assert form_resp.status_code == 400
    assert "Display Name" in form_resp.body_html


def test_handle_add_missing_owner_type_returns_error(
    conn: sqlite3.Connection,
) -> None:
    redirect_url, form_resp = OwnerPages(conn).handle_add(
        form_data={"display_name": "Test"},
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert form_resp is not None
    assert form_resp.status_code == 400


def test_handle_add_enforces_two_owner_limit(conn: sqlite3.Connection) -> None:
    lot_id = _seed_lot(conn)
    owner1_id = _seed_owner(conn, "Owner One")
    owner2_id = _seed_owner(conn, "Owner Two")
    _assign(conn, lot_id, owner1_id, is_primary=True)
    _assign(conn, lot_id, owner2_id, is_primary=False)

    redirect_url, form_resp = OwnerPages(conn).handle_add(
        form_data={
            "owner_type": "PERSON",
            "display_name": "Third Owner",
            "lot_id": str(lot_id),
            "start_date": "2026-01-01",
            "is_primary_contact": "0",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert form_resp is not None
    assert form_resp.status_code == 400
    assert "two current owners" in form_resp.body_html


def test_handle_add_enforces_owner1_conflict(conn: sqlite3.Connection) -> None:
    lot_id = _seed_lot(conn)
    existing_id = _seed_owner(conn, "Existing Primary")
    _assign(conn, lot_id, existing_id, is_primary=True)

    redirect_url, form_resp = OwnerPages(conn).handle_add(
        form_data={
            "owner_type": "PERSON",
            "display_name": "Duplicate Primary",
            "lot_id": str(lot_id),
            "start_date": "2026-01-01",
            "is_primary_contact": "1",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert form_resp is not None
    assert form_resp.status_code == 400
    assert "Owner 1" in form_resp.body_html


# ── handle_edit ────────────────────────────────────────────────────────


def test_handle_edit_success_redirects(conn: sqlite3.Connection) -> None:
    owner_id = _seed_owner(conn, "Old Name")

    redirect_url, form_resp = OwnerPages(conn).handle_edit(
        owner_id=owner_id,
        form_data={
            "owner_type": "PERSON",
            "display_name": "New Name",
            "phone": "555-9999",
            "email": "new@example.com",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url == "/owners?msg=Owner+updated."
    assert form_resp is None

    updated = OwnersRepository(conn).get_owner(owner_id)
    assert updated["display_name"] == "New Name"
    assert updated["phone"] == "555-9999"


def test_handle_edit_missing_display_name_returns_error(
    conn: sqlite3.Connection,
) -> None:
    owner_id = _seed_owner(conn)

    redirect_url, form_resp = OwnerPages(conn).handle_edit(
        owner_id=owner_id,
        form_data={"owner_type": "PERSON"},
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert form_resp is not None
    assert form_resp.status_code == 400


# ── handle_mark_previous ───────────────────────────────────────────────


def test_handle_mark_previous_success_redirects(conn: sqlite3.Connection) -> None:
    lot_id = _seed_lot(conn)
    owner_id = _seed_owner(conn)
    _assign(conn, lot_id, owner_id)

    redirect_url, form_resp = OwnerPages(conn).handle_mark_previous(
        owner_id=owner_id,
        form_data={"end_date": "2026-03-31"},
        org=_ORG, theme="warm",
    )
    assert redirect_url == "/owners?msg=Owner+marked+as+previous."
    assert form_resp is None

    ownership = LotOwnershipRepository(conn).get_current_ownership_by_owner(owner_id)
    assert ownership is None  # no longer current


def test_handle_mark_previous_missing_date_returns_error(
    conn: sqlite3.Connection,
) -> None:
    lot_id = _seed_lot(conn)
    owner_id = _seed_owner(conn)
    _assign(conn, lot_id, owner_id)

    redirect_url, form_resp = OwnerPages(conn).handle_mark_previous(
        owner_id=owner_id,
        form_data={},
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert form_resp is not None
    assert "End Date" in form_resp.body_html


def test_handle_mark_previous_no_ownership_returns_error(
    conn: sqlite3.Connection,
) -> None:
    owner_id = _seed_owner(conn)

    redirect_url, form_resp = OwnerPages(conn).handle_mark_previous(
        owner_id=owner_id,
        form_data={"end_date": "2026-03-31"},
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert form_resp is not None
    assert form_resp.status_code == 200  # re-renders list with error
