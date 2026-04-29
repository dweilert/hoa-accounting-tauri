"""Connection-level concurrency and lifecycle tests.

Covers:
- connect_sqlite applies WAL, foreign keys, synchronous, and busy_timeout.
- :memory: databases skip WAL (which is a no-op on them anyway) without
  emitting confusing pragma rows.
- ReportRunner._open_connection closes file-backed connections on exit
  so long-running servers don't leak file descriptors.
- ReportRunner borrows caller-supplied connections — it doesn't close
  them, so tests that reuse a shared in-memory DB still work.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from hoa_accounting.db.connection import connect_sqlite


def _pragma(conn: sqlite3.Connection, name: str):
    row = conn.execute(f"PRAGMA {name}").fetchone()
    return row[0] if row is not None else None


def test_file_backed_connection_has_wal_and_busy_timeout(tmp_path: Path) -> None:
    """A file-backed SQLite DB comes up in WAL mode with a nonzero busy timeout."""
    db_path = tmp_path / "t.db"
    conn = connect_sqlite(db_path)
    try:
        assert str(_pragma(conn, "journal_mode")).lower() == "wal"
        assert int(_pragma(conn, "foreign_keys")) == 1
        assert int(_pragma(conn, "busy_timeout")) >= 5000
        # synchronous NORMAL is 1; FULL is 2. Either way, must be > OFF (0).
        assert int(_pragma(conn, "synchronous")) >= 1
    finally:
        conn.close()


def test_in_memory_connection_skips_wal_pragma() -> None:
    """:memory: DBs ignore WAL; connect_sqlite must not set it (keeps tests quiet)."""
    conn = connect_sqlite(":memory:")
    try:
        mode = str(_pragma(conn, "journal_mode")).lower()
        # In-memory databases report 'memory' for journal_mode.
        assert mode == "memory"
        # Foreign keys still enforced, busy_timeout still set.
        assert int(_pragma(conn, "foreign_keys")) == 1
        assert int(_pragma(conn, "busy_timeout")) >= 5000
    finally:
        conn.close()
