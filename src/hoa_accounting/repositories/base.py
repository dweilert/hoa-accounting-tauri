"""Shared repository helpers."""

from __future__ import annotations

import sqlite3


class BaseRepository:
    """Base repository with shared connection access."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
