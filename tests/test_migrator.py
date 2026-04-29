"""Tests for the minimal forward-only migration runner."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.exceptions import AccountingError


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    return c


def _write(migrations_dir: Path, name: str, sql: str) -> None:
    (migrations_dir / name).write_text(sql, encoding="utf-8")


def test_apply_all_runs_each_migration_in_order(tmp_path: Path) -> None:
    """Migrations are applied in lexical order and recorded."""
    _write(
        tmp_path,
        "0001_create_foo.sql",
        "CREATE TABLE foo (id INTEGER PRIMARY KEY, val TEXT);",
    )
    _write(
        tmp_path,
        "0002_add_bar.sql",
        "CREATE TABLE bar (id INTEGER PRIMARY KEY);",
    )

    conn = _conn()
    applied = Migrator(tmp_path).apply_all(conn)

    assert applied == ["0001_create_foo.sql", "0002_add_bar.sql"]

    versions = [
        r["version"]
        for r in conn.execute("SELECT version FROM schema_version ORDER BY version")
    ]
    assert versions == ["0001_create_foo.sql", "0002_add_bar.sql"]

    # Both tables exist.
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='foo'").fetchone()
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='bar'").fetchone()


def test_apply_all_is_idempotent(tmp_path: Path) -> None:
    """A second run applies nothing when no new files appeared."""
    _write(
        tmp_path,
        "0001_one.sql",
        "CREATE TABLE one (id INTEGER PRIMARY KEY);",
    )

    conn = _conn()
    m = Migrator(tmp_path)
    first = m.apply_all(conn)
    second = m.apply_all(conn)

    assert first == ["0001_one.sql"]
    assert second == []


def test_apply_all_picks_up_new_migrations(tmp_path: Path) -> None:
    """Adding a file after a prior run applies just that file."""
    _write(tmp_path, "0001_one.sql", "CREATE TABLE one (id INTEGER PRIMARY KEY);")

    conn = _conn()
    m = Migrator(tmp_path)
    m.apply_all(conn)

    _write(tmp_path, "0002_two.sql", "CREATE TABLE two (id INTEGER PRIMARY KEY);")
    applied = m.apply_all(conn)

    assert applied == ["0002_two.sql"]


def test_rejects_badly_named_migration_files(tmp_path: Path) -> None:
    """Files that don't match NNNN_description.sql are flagged before running."""
    _write(tmp_path, "bad_name.sql", "CREATE TABLE x (id INTEGER);")

    with pytest.raises(AccountingError, match="does not match"):
        Migrator(tmp_path).apply_all(_conn())


def test_failed_migration_is_not_recorded(tmp_path: Path) -> None:
    """If the SQL raises, schema_version should not gain a row for it."""
    _write(tmp_path, "0001_ok.sql", "CREATE TABLE a (id INTEGER PRIMARY KEY);")
    _write(tmp_path, "0002_broken.sql", "CREATE TABLE ;;; invalid SQL")

    conn = _conn()
    m = Migrator(tmp_path)

    with pytest.raises(sqlite3.OperationalError):
        m.apply_all(conn)

    versions = {
        r["version"] for r in conn.execute("SELECT version FROM schema_version")
    }
    assert versions == {"0001_ok.sql"}

    # Re-running after the SQL file is fixed should apply it now.
    _write(tmp_path, "0002_broken.sql", "CREATE TABLE b (id INTEGER PRIMARY KEY);")
    applied_after_fix = m.apply_all(conn)
    assert applied_after_fix == ["0002_broken.sql"]


def test_default_migrations_dir_applies_all_packaged_migrations() -> None:
    """With the packaged migrations dir, all .sql files apply in order."""
    conn = _conn()
    applied = Migrator().apply_all(conn)

    # Must at least include the initial schema and the first follow-up.
    assert applied[0] == "0001_initial.sql"
    assert "0002_expense_classification_and_groups.sql" in applied
    # Applied in lexical order.
    assert applied == sorted(applied)

    tables = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    # accounts / account_types / journal_entries were retired in migration 0061.
    assert "schema_version" in tables
    assert "categories" in tables
    assert "bank_accounts" in tables
    assert "journal_entries" not in tables
    assert "accounts" not in tables

    # bank_accounts now carries fund_code directly (no GL pointer).
    bank_cols = {r["name"] for r in conn.execute("PRAGMA table_info(bank_accounts)")}
    assert "fund_code" in bank_cols
    assert "gl_account_id" not in bank_cols


def test_migrator_is_safe_on_existing_database() -> None:
    """Running against a DB that already has the 0001 tables doesn't error.

    Simulates a pre-existing install that was created by the old
    executescript(base_schema_sql()) path. The migrator must catch up by
    recording 0001 as applied (its statements are re-run but every
    CREATE uses IF NOT EXISTS and INSERT OR IGNORE so they no-op).
    """
    conn = _conn()
    from hoa_accounting.bootstrap.schema import base_schema_sql

    conn.executescript(base_schema_sql())

    applied = Migrator().apply_all(conn)
    # All packaged migrations land; 0001 is first.
    assert applied[0] == "0001_initial.sql"
    assert "0002_expense_classification_and_groups.sql" in applied

    # Second run is a no-op.
    assert Migrator().apply_all(conn) == []
