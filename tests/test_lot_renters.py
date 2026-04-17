"""Tests for migration 0007 and the renter-tracking data access layer.

Covers:
- The lot_renters table exists with the expected columns + constraints.
- LotRentersRepository.insert / end_tenancy / get_current_renters /
  list_renter_history.
- LotsRepository.list_lots_with_occupancy derives is_owner_occupied
  correctly (no current renter → 1, current renter → 0) and picks the
  primary-contact renter for the renter_name column.
"""

from __future__ import annotations

import sqlite3

import pytest

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.repositories.lot_renters_repo import LotRentersRepository
from hoa_accounting.repositories.lots_repo import LotsRepository


def _seed_two_lots(conn: sqlite3.Connection) -> dict[str, int]:
    conn.execute(
        "INSERT INTO owners (id, owner_type, display_name, active_flag) "
        "VALUES (1, 'PERSON', 'Alice Park', 1)"
    )
    conn.execute(
        "INSERT INTO lots (id, lot_number, active_flag) "
        "VALUES (1, 'L-1', 1), (2, 'L-2', 1)"
    )
    conn.execute(
        "INSERT INTO lot_ownership "
        "(id, lot_id, owner_id, start_date, end_date, ownership_percent, is_primary_contact) "
        "VALUES (1, 1, 1, '2020-01-01', NULL, 100.0, 1)"
    )
    conn.commit()
    return {"lot_alice": 1, "lot_vacant": 2, "alice": 1}


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    Migrator().apply_all(c)
    return c


# ── Schema ─────────────────────────────────────────────────────────


def test_lot_renters_table_exists_with_expected_columns(conn) -> None:
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(lot_renters)")}
    for required in [
        "id", "lot_id", "display_name", "first_name", "last_name",
        "email", "phone", "start_date", "end_date",
        "is_primary_contact", "notes", "created_at", "updated_at",
    ]:
        assert required in cols


def test_end_date_before_start_is_rejected(conn) -> None:
    _seed_two_lots(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO lot_renters "
            "(lot_id, display_name, start_date, end_date) "
            "VALUES (1, 'Bad dates', '2025-05-01', '2025-04-01')"
        )


def test_is_primary_contact_limited_to_0_or_1(conn) -> None:
    _seed_two_lots(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO lot_renters "
            "(lot_id, display_name, start_date, is_primary_contact) "
            "VALUES (1, 'Bad flag', '2025-01-01', 7)"
        )


# ── Repository operations ─────────────────────────────────────────


def test_insert_and_get_current_renter(conn) -> None:
    ids = _seed_two_lots(conn)
    repo = LotRentersRepository(conn)
    renter_id = repo.insert_renter(
        lot_id=ids["lot_vacant"],
        display_name="Dana Reeves",
        first_name="Dana",
        last_name="Reeves",
        email="dana@example.com",
        phone="555-0100",
        start_date="2025-06-01",
    )
    rows = repo.get_current_renters(ids["lot_vacant"])
    assert len(rows) == 1
    r = rows[0]
    assert int(r["id"]) == renter_id
    assert r["display_name"] == "Dana Reeves"
    assert r["email"] == "dana@example.com"
    assert r["end_date"] is None
    assert int(r["is_primary_contact"]) == 1


def test_multiple_renters_primary_first(conn) -> None:
    """Two renters at one lot — primary contact should come first in the list."""
    ids = _seed_two_lots(conn)
    repo = LotRentersRepository(conn)
    repo.insert_renter(
        lot_id=ids["lot_vacant"],
        display_name="Secondary Tenant",
        first_name=None, last_name=None, email=None, phone=None,
        start_date="2025-06-01",
        is_primary_contact=False,
    )
    repo.insert_renter(
        lot_id=ids["lot_vacant"],
        display_name="Primary Tenant",
        first_name=None, last_name=None, email=None, phone=None,
        start_date="2025-06-01",
        is_primary_contact=True,
    )
    rows = repo.get_current_renters(ids["lot_vacant"])
    assert [r["display_name"] for r in rows] == [
        "Primary Tenant", "Secondary Tenant",
    ]


def test_end_tenancy_excludes_from_current(conn) -> None:
    ids = _seed_two_lots(conn)
    repo = LotRentersRepository(conn)
    renter_id = repo.insert_renter(
        lot_id=ids["lot_vacant"],
        display_name="Old Tenant",
        first_name=None, last_name=None, email=None, phone=None,
        start_date="2024-01-01",
    )
    assert len(repo.get_current_renters(ids["lot_vacant"])) == 1

    repo.end_tenancy(renter_id=renter_id, end_date="2025-06-30")

    # get_current_renters now empty.
    assert repo.get_current_renters(ids["lot_vacant"]) == []
    # But history still includes them.
    history = repo.list_renter_history(ids["lot_vacant"])
    assert len(history) == 1
    assert history[0]["end_date"] == "2025-06-30"


def test_history_orders_newest_first(conn) -> None:
    ids = _seed_two_lots(conn)
    repo = LotRentersRepository(conn)
    # Old ended tenancy.
    repo.insert_renter(
        lot_id=ids["lot_vacant"],
        display_name="2023 Tenant",
        first_name=None, last_name=None, email=None, phone=None,
        start_date="2023-01-01",
        end_date="2023-12-31",
    )
    # Recent ended tenancy.
    repo.insert_renter(
        lot_id=ids["lot_vacant"],
        display_name="2024 Tenant",
        first_name=None, last_name=None, email=None, phone=None,
        start_date="2024-01-01",
        end_date="2024-12-31",
    )
    # Current tenant.
    repo.insert_renter(
        lot_id=ids["lot_vacant"],
        display_name="Current Tenant",
        first_name=None, last_name=None, email=None, phone=None,
        start_date="2025-01-01",
    )
    names = [r["display_name"] for r in repo.list_renter_history(ids["lot_vacant"])]
    assert names[0] == "Current Tenant"  # NULL end_date sorts first (9999-12-31)
    assert names == ["Current Tenant", "2024 Tenant", "2023 Tenant"]


# ── Occupancy derivation on lots ──────────────────────────────────


def test_list_lots_with_occupancy_defaults_to_owner_occupied(conn) -> None:
    """A lot with no renter row is owner-occupied (is_owner_occupied = 1)."""
    ids = _seed_two_lots(conn)
    rows = LotsRepository(conn).list_lots_with_occupancy()
    by_lot = {int(r["lot_id"]): r for r in rows}
    # L-1 has Alice as current owner and no renter → owner-occupied.
    alice_row = by_lot[ids["lot_alice"]]
    assert int(alice_row["is_owner_occupied"]) == 1
    assert alice_row["owner_name"] == "Alice Park"
    assert alice_row["renter_id"] is None
    assert alice_row["renter_name"] is None


def test_list_lots_with_occupancy_flips_when_renter_present(conn) -> None:
    """Adding a current renter flips is_owner_occupied to 0 and surfaces their info."""
    ids = _seed_two_lots(conn)
    LotRentersRepository(conn).insert_renter(
        lot_id=ids["lot_vacant"],
        display_name="Dana Reeves",
        first_name="Dana", last_name="Reeves",
        email="dana@example.com", phone="555-0100",
        start_date="2025-06-01",
    )
    rows = LotsRepository(conn).list_lots_with_occupancy()
    by_lot = {int(r["lot_id"]): r for r in rows}
    v = by_lot[ids["lot_vacant"]]
    assert int(v["is_owner_occupied"]) == 0
    assert v["renter_name"] == "Dana Reeves"
    assert v["renter_email"] == "dana@example.com"


def test_ended_tenancy_no_longer_shows_on_occupancy(conn) -> None:
    """Once a tenant's end_date is set, the lot flips back to owner-occupied."""
    ids = _seed_two_lots(conn)
    repo = LotRentersRepository(conn)
    renter_id = repo.insert_renter(
        lot_id=ids["lot_alice"],
        display_name="Past Tenant",
        first_name=None, last_name=None, email=None, phone=None,
        start_date="2023-01-01",
    )
    assert int(
        [r for r in LotsRepository(conn).list_lots_with_occupancy()
         if int(r["lot_id"]) == ids["lot_alice"]][0]["is_owner_occupied"]
    ) == 0

    repo.end_tenancy(renter_id=renter_id, end_date="2024-06-30")

    assert int(
        [r for r in LotsRepository(conn).list_lots_with_occupancy()
         if int(r["lot_id"]) == ids["lot_alice"]][0]["is_owner_occupied"]
    ) == 1
