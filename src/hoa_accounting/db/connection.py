"""Database connection helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect_sqlite(
    db_path: str | Path,
    *,
    timeout: float = 5.0,
) -> sqlite3.Connection:
    """Open a SQLite connection with sane concurrency defaults.

    - ``foreign_keys = ON`` — SQLite's default is OFF per connection.
    - ``journal_mode = WAL`` — readers don't block writers and vice versa;
      essential the moment the system handles more than one request at a
      time. Skipped for ``:memory:`` (WAL only applies to file-backed DBs).
    - ``synchronous = NORMAL`` — the standard WAL pair. Durable across an
      OS or process crash; the small power-loss window is acceptable for
      an HOA accounting system given routine backups.
    - ``busy_timeout = 5000`` (ms) — SQLite-level wait before returning
      SQLITE_BUSY when another connection holds the write lock.
    - ``timeout`` (Python-level, seconds) — mirror of busy_timeout for the
      connect call; 5s matches the pragma value above.
    """
    conn = sqlite3.connect(str(db_path), timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(db_path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn
