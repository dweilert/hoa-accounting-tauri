"""Embedded schema accessor for local bootstrap.

The initial schema lives in ``src/hoa_accounting/migrations/0001_initial.sql``
so there is one source of truth shared by the migrator and any callers that
want the full schema as a string (tests, tooling, exports).
"""

from __future__ import annotations

from pathlib import Path

_INITIAL_MIGRATION = (
    Path(__file__).resolve().parent.parent / "migrations" / "0001_initial.sql"
)


def base_schema_sql() -> str:
    """Return the initial schema SQL as a single script."""
    return _INITIAL_MIGRATION.read_text(encoding="utf-8")
