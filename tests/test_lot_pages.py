"""Tests for the lot management pages.

Covers:
- GET /lots: renders list, empty state, lot rows, flash message
- GET /lots/add: renders blank form
- POST /lots/add: inserts lot, redirects with flash
- POST /lots/add: missing lot_number returns error
- POST /lots/add: duplicate lot_number returns error
- GET /lots/<id>/edit: form pre-filled from DB
- POST /lots/<id>/edit: updates lot, redirects with flash
- POST /lots/<id>/edit: duplicate lot_number (other lot) returns error
- POST /lots/<id>/edit: can keep same lot_number
- GET /lots/<id>/edit for unknown id returns 404
- POST /lots/<id>/delete: removes lot, redirects with flash
- POST /lots/<id>/delete: lot with current owner returns error
"""

from __future__ import annotations

import sqlite3

import pytest

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.web.lot_pages import LotPages


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    Migrator().apply_all(c)
    return c


def _seed_lot(
    conn: sqlite3.Connection,
    lot_number: str = "L-1",
    street: str = "100 Pine St",
) -> int:
    cur = conn.execute(
        "INSERT INTO lots (lot_number, street_address_1, city, state, "
        "postal_code, active_flag) VALUES (?, ?, 'Austin', 'TX', '78701', 1)",
        (lot_number, street),
    )
    conn.commit()
    return int(cur.lastrowid)


def _seed_owner_on_lot(conn: sqlite3.Connection, lot_id: int) -> int:
    cur = conn.execute(
        "INSERT INTO owners (owner_type, display_name, active_flag) "
        "VALUES ('PERSON', 'Test Owner', 1)"
    )
    owner_id = int(cur.lastrowid)
    conn.execute(
        "INSERT INTO lot_ownership (lot_id, owner_id, start_date) "
        "VALUES (?, ?, '2020-01-01')",
        (lot_id, owner_id),
    )
    conn.commit()
    return owner_id


_ORG = {"name": "Test HOA", "environment": "test",
        "fiscal_year_start_month": 1, "theme": "warm"}


# ── render_list ────────────────────────────────────────────────────────


def test_render_list_empty_state(conn: sqlite3.Connection) -> None:
    resp = LotPages(conn).render_list(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "No lots on record" in resp.body_html


def test_render_list_shows_lot(conn: sqlite3.Connection) -> None:
    _seed_lot(conn, "L-42", "42 Oak Ave")
    resp = LotPages(conn).render_list(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "L-42" in resp.body_html
    assert "42 Oak Ave" in resp.body_html


def test_render_list_flash_message(conn: sqlite3.Connection) -> None:
    resp = LotPages(conn).render_list(
        org=_ORG, theme="warm", flash_message="Lot added."
    )
    assert "Lot added." in resp.body_html


def test_render_list_shows_edit_link(conn: sqlite3.Connection) -> None:
    lot_id = _seed_lot(conn)
    resp = LotPages(conn).render_list(org=_ORG, theme="warm")
    assert f"/lots/{lot_id}/edit" in resp.body_html


# ── render_form (add) ──────────────────────────────────────────────────


def test_render_add_form(conn: sqlite3.Connection) -> None:
    resp = LotPages(conn).render_form(org=_ORG, theme="warm")
    assert resp.status_code == 200
    assert "Lot Number" in resp.body_html
    assert "Street Address" in resp.body_html


# ── render_form (edit) ─────────────────────────────────────────────────


def test_render_edit_form_prefilled(conn: sqlite3.Connection) -> None:
    lot_id = _seed_lot(conn, "L-5", "500 Elm St")
    resp = LotPages(conn).render_form(org=_ORG, theme="warm", lot_id=lot_id)
    assert resp.status_code == 200
    assert "L-5" in resp.body_html
    assert "500 Elm St" in resp.body_html


def test_render_edit_form_unknown_returns_404(conn: sqlite3.Connection) -> None:
    resp = LotPages(conn).render_form(org=_ORG, theme="warm", lot_id=999)
    assert resp.status_code == 404


# ── handle_add ─────────────────────────────────────────────────────────


def test_handle_add_success(conn: sqlite3.Connection) -> None:
    redirect_url, form_resp = LotPages(conn).handle_add(
        form_data={
            "lot_number": "L-10",
            "street_address_1": "10 Cedar Ln",
            "city": "Austin",
            "state": "TX",
            "postal_code": "78702",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url == "/lots?msg=Lot+added."
    assert form_resp is None
    rows = LotsRepository(conn).list_lots(active_only=False)
    assert rows[0]["lot_number"] == "L-10"


def test_handle_add_missing_lot_number_returns_error(
    conn: sqlite3.Connection,
) -> None:
    redirect_url, form_resp = LotPages(conn).handle_add(
        form_data={"street_address_1": "10 Main St"},
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert form_resp is not None
    assert form_resp.status_code == 400
    assert "Lot Number" in form_resp.body_html


def test_handle_add_duplicate_lot_number_returns_error(
    conn: sqlite3.Connection,
) -> None:
    _seed_lot(conn, "L-1")
    redirect_url, form_resp = LotPages(conn).handle_add(
        form_data={"lot_number": "L-1"},
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert form_resp is not None
    assert form_resp.status_code == 400
    assert "already in use" in form_resp.body_html


# ── handle_edit ────────────────────────────────────────────────────────


def test_handle_edit_success(conn: sqlite3.Connection) -> None:
    lot_id = _seed_lot(conn, "L-1", "Old Street")
    redirect_url, form_resp = LotPages(conn).handle_edit(
        lot_id=lot_id,
        form_data={
            "lot_number": "L-1",
            "street_address_1": "New Street",
            "city": "Dallas",
            "state": "TX",
            "postal_code": "75201",
            "active_flag": "1",
        },
        org=_ORG, theme="warm",
    )
    assert redirect_url is not None and "Lot+updated" in redirect_url
    assert form_resp is None
    row = LotsRepository(conn).get_lot(lot_id)
    assert row["street_address_1"] == "New Street"
    assert row["city"] == "Dallas"


def test_handle_edit_can_keep_same_lot_number(conn: sqlite3.Connection) -> None:
    lot_id = _seed_lot(conn, "L-1")
    redirect_url, form_resp = LotPages(conn).handle_edit(
        lot_id=lot_id,
        form_data={"lot_number": "L-1", "street_address_1": "Same", "active_flag": "1"},
        org=_ORG, theme="warm",
    )
    assert redirect_url is not None and "Lot+updated" in redirect_url
    assert form_resp is None


def test_handle_edit_duplicate_lot_number_other_lot_returns_error(
    conn: sqlite3.Connection,
) -> None:
    _seed_lot(conn, "L-1")
    lot2_id = _seed_lot(conn, "L-2")
    redirect_url, form_resp = LotPages(conn).handle_edit(
        lot_id=lot2_id,
        form_data={"lot_number": "L-1", "active_flag": "1"},
        org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert form_resp is not None
    assert form_resp.status_code == 400
    assert "already in use" in form_resp.body_html


def test_handle_edit_deactivate_lot(conn: sqlite3.Connection) -> None:
    lot_id = _seed_lot(conn, "L-1")
    LotPages(conn).handle_edit(
        lot_id=lot_id,
        form_data={"lot_number": "L-1", "active_flag": "0"},
        org=_ORG, theme="warm",
    )
    row = LotsRepository(conn).get_lot(lot_id)
    assert row["active_flag"] == 0


# ── handle_delete ──────────────────────────────────────────────────────


def test_handle_delete_success(conn: sqlite3.Connection) -> None:
    lot_id = _seed_lot(conn, "L-99")
    redirect_url, form_resp = LotPages(conn).handle_delete(
        lot_id=lot_id, org=_ORG, theme="warm",
    )
    assert redirect_url == "/lots?msg=Lot+deleted."
    assert form_resp is None
    assert LotsRepository(conn).get_lot(lot_id) is None


def test_handle_delete_with_current_owner_returns_error(
    conn: sqlite3.Connection,
) -> None:
    lot_id = _seed_lot(conn)
    _seed_owner_on_lot(conn, lot_id)
    redirect_url, form_resp = LotPages(conn).handle_delete(
        lot_id=lot_id, org=_ORG, theme="warm",
    )
    assert redirect_url is None
    assert form_resp is not None
    assert form_resp.status_code == 400
    assert "current owner" in form_resp.body_html
