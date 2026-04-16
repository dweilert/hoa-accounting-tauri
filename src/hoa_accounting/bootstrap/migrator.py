"""Minimal forward-only SQL migration runner.

Migrations live as ``.sql`` files in a directory, named so they sort into
order (e.g. ``0001_initial.sql``, ``0002_add_indexes.sql``). Applied
migrations are tracked in a ``schema_version`` table. On each run, the
migrator compares files on disk against the table and executes any that
haven't been applied yet, then records an ISO-8601 timestamp.

Each migration file is responsible for its own atomicity: start with
``BEGIN TRANSACTION;`` and end with ``COMMIT;`` if you want all-or-nothing
semantics on its DDL. ``sqlite3.Connection.executescript`` will issue a
COMMIT on any pending transaction before running the script.

Scope is deliberately small:
- forward-only (no down-migrations)
- no SQL templating, no checksums, no dry-run

Enough to stop schema drift without pulling in Alembic.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from hoa_accounting.exceptions import AccountingError

_DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
_MIGRATION_FILENAME_RE = re.compile(r"^\d{4}_[A-Za-z0-9_\-]+\.sql$")


class Migrator:
    """Apply ordered SQL migration files to a SQLite connection."""

    def __init__(self, migrations_dir: Path | str | None = None) -> None:
        self.migrations_dir = Path(migrations_dir) if migrations_dir else _DEFAULT_MIGRATIONS_DIR

    def ensure_schema_version_table(self, conn: sqlite3.Connection) -> None:
        """Create schema_version if it doesn't already exist."""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        conn.commit()

    def applied_versions(self, conn: sqlite3.Connection) -> set[str]:
        """Return the set of migration filenames already applied."""
        self.ensure_schema_version_table(conn)
        rows = conn.execute("SELECT version FROM schema_version").fetchall()
        return {str(row[0]) for row in rows}

    def discover_migrations(self) -> list[Path]:
        """Return migration files in lexical order, validating filenames."""
        if not self.migrations_dir.exists():
            return []
        files = sorted(p for p in self.migrations_dir.iterdir() if p.suffix == ".sql")
        for f in files:
            if not _MIGRATION_FILENAME_RE.match(f.name):
                raise AccountingError(
                    f"Migration file name does not match NNNN_description.sql: {f.name}"
                )
        return files

    def pending(self, conn: sqlite3.Connection) -> list[Path]:
        """Return migration files present on disk but not yet recorded."""
        applied = self.applied_versions(conn)
        return [f for f in self.discover_migrations() if f.name not in applied]

    def apply_all(self, conn: sqlite3.Connection) -> list[str]:
        """Apply every pending migration and return the filenames that ran.

        Each migration's SQL is run via ``executescript``, which commits any
        outer transaction first and then runs the script. If the file
        contains its own ``BEGIN TRANSACTION ... COMMIT`` wrapper, the DDL
        inside is atomic; otherwise each statement autocommits.

        The ``schema_version`` row is inserted in a separate committed
        statement after the migration runs. A failure during the migration
        raises immediately and the schema_version row is not written, so a
        re-run will retry the failing migration.
        """
        applied_now: list[str] = []
        for migration_path in self.pending(conn):
            sql = migration_path.read_text(encoding="utf-8")
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (
                    migration_path.name,
                    datetime.now(UTC).isoformat(timespec="seconds"),
                ),
            )
            conn.commit()
            applied_now.append(migration_path.name)
        return applied_now
