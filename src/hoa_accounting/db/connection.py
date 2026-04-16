"""Database connection helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect_sqlite(db_path: str | Path) -> sqlite3.Connection:
    """Create a SQLite connection with row access by column name."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn
