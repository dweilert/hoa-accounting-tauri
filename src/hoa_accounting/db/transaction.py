"""Transaction helpers with nesting support via SQLite savepoints."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block atomically against the given SQLite connection.

    Outermost call: begins a transaction, commits on success, rolls back on
    exception.

    Nested call (when a transaction is already active): uses a SAVEPOINT so
    the inner block is still atomic on its own — a failure inside rolls back
    only the inner work and re-raises, leaving the outer transaction's
    earlier changes intact for its own error handler to deal with.
    """
    if conn.in_transaction:
        sp_name = f"sp_{uuid.uuid4().hex}"
        conn.execute(f"SAVEPOINT {sp_name}")
        try:
            yield conn
        except Exception:
            conn.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
            conn.execute(f"RELEASE SAVEPOINT {sp_name}")
            raise
        else:
            conn.execute(f"RELEASE SAVEPOINT {sp_name}")
        return

    try:
        conn.execute("BEGIN")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
