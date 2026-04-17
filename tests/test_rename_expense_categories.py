"""Verify migration 0006 rewrites the category account names cleanly.

After the migration runs (as part of apply_all), each of the eleven
affected expense accounts should carry its shorter, group-prefix-free
name. The accounts' group_code and other columns must be untouched —
the rename is purely a display-label change.
"""

from __future__ import annotations

import sqlite3

import pytest

from hoa_accounting.bootstrap.migrator import Migrator


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    Migrator().apply_all(c)
    return c


_EXPECTED = {
    "6101": "Mow & Blow",
    "6102": "Sprinkler System",
    "6103": "Lighting System",
    "6104": "Mulch",
    "6105": "Tree Trimming",
    "6106": "Bed Maintenance",
    "6107": "Hill Maintenance",
    "6108": "Plants",
    "6109": "Other",
    "6501": "Gate",
    "6502": "Mail Kiosk",
}


def test_renamed_accounts_match_expected(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT account_number, account_name FROM accounts "
        "WHERE account_number IN ({placeholders}) ORDER BY account_number".format(
            placeholders=", ".join("?" * len(_EXPECTED))
        ),
        list(_EXPECTED.keys()),
    ).fetchall()
    actual = {r["account_number"]: r["account_name"] for r in rows}
    assert actual == _EXPECTED


def test_group_codes_unchanged(conn: sqlite3.Connection) -> None:
    """Rename touches only account_name — group_code must still be set."""
    rows = conn.execute(
        "SELECT account_number, group_code FROM accounts "
        "WHERE account_number IN ('6101','6104','6109','6501','6502')"
    ).fetchall()
    expected_groups = {
        "6101": "LANDSCAPE",
        "6104": "LANDSCAPE",
        "6109": "LANDSCAPE",
        "6501": "ENTRANCE",
        "6502": "ENTRANCE",
    }
    actual = {r["account_number"]: r["group_code"] for r in rows}
    assert actual == expected_groups


def test_untouched_accounts_keep_their_names(conn: sqlite3.Connection) -> None:
    """Accounts the migration does not target must still carry 0002 names."""
    rows = conn.execute(
        "SELECT account_number, account_name FROM accounts "
        "WHERE account_number IN ('6201','6301','6401','6601','6701','6801','6901')"
    ).fetchall()
    expected = {
        "6201": "Sewer",
        "6301": "Road",
        "6401": "Wall",
        "6601": "Utilities",
        "6701": "Insurance",
        "6801": "Misc",
        "6901": "Firewise",
    }
    actual = {r["account_number"]: r["account_name"] for r in rows}
    assert actual == expected
