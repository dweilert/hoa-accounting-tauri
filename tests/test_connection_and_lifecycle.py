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

import pytest

import sqlite3
from pathlib import Path

from hoa_accounting.application.report_runner import ReportRunner
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


@pytest.mark.skip(reason="pending single-entry rewrite (double-entry contract retired)")
def test_report_runner_closes_owned_connection(tmp_path: Path) -> None:
    """A connection we open inside ReportRunner must be closed after run()."""
    # Spin up a real file-backed DB with just enough schema for a trial balance.
    db_path = tmp_path / "owned.db"
    conn = connect_sqlite(db_path)
    from hoa_accounting.bootstrap.schema import base_schema_sql
    conn.executescript(base_schema_sql())
    conn.commit()
    conn.close()

    # Write a matching config.yaml pointed at the file.
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
hoa:
  name: "Test"
  legal_name: "Test HOA"
  tax_id_federal: "00-0000000"
  tax_id_state: "TX-STATE-ID-000"
database:
  type: "sqlite"
  path: "{db_path}"
app:
  environment: "test"
  debug: true
accounting:
  fiscal_year_start_month: 1
  default_fund: "OPERATING"
""".strip(),
        encoding="utf-8",
    )

    runner = ReportRunner(config_path=config_path)
    # Monkey in a spy on connect_sqlite usage by tracking open connections.
    created: list[sqlite3.Connection] = []

    import hoa_accounting.application.report_runner as runner_mod
    original_connect = runner_mod.connect_sqlite

    def spy_connect(path, **kwargs):
        c = original_connect(path, **kwargs)
        created.append(c)
        return c

    runner_mod.connect_sqlite = spy_connect
    try:
        runner.run("trial-balance", as_of_date="2026-01-31")
    finally:
        runner_mod.connect_sqlite = original_connect

    assert len(created) == 1
    # A closed sqlite3 connection raises ProgrammingError on .execute.
    import pytest
    with pytest.raises(sqlite3.ProgrammingError):
        created[0].execute("SELECT 1")


@pytest.mark.skip(reason="pending single-entry rewrite (double-entry contract retired)")
def test_report_runner_does_not_close_borrowed_connection() -> None:
    """A caller-supplied connection factory keeps the connection alive after run()."""
    from hoa_accounting.bootstrap.schema import base_schema_sql

    conn = connect_sqlite(":memory:")
    conn.executescript(base_schema_sql())
    conn.commit()

    runner = ReportRunner(
        config_path=Path("unused.yaml"),
        connection_factory=lambda: conn,
    )
    runner.run("trial-balance", as_of_date="2026-01-31")

    # The connection must still be usable — runner didn't close it.
    row = conn.execute("SELECT 1").fetchone()
    assert row is not None
    conn.close()
