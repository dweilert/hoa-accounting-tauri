"""Database administration page.

Panels
------
1. Health Check  — PRAGMA integrity_check / foreign_key_check / quick_check
2. Maintenance   — REINDEX, VACUUM, WAL checkpoint
3. Backup / Restore — consistent snapshot download; drag-and-drop restore
"""

from __future__ import annotations
from typing import Any

import logging
import os
import sqlite3
import tempfile

_log = logging.getLogger(__name__)
from dataclasses import dataclass, field
from datetime import datetime
from http import HTTPStatus
from pathlib import Path

from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.web.template_engine import render_template


@dataclass
class DbStats:
    file_path: str
    file_size_bytes: int
    page_size: int
    page_count: int
    freelist_count: int
    journal_mode: str
    wal_autocheckpoint: int | None

    @property
    def file_size_mb(self) -> str:
        mb = self.file_size_bytes / (1024 * 1024)
        if mb < 0.1:
            return f"{self.file_size_bytes / 1024:.1f} KB"
        return f"{mb:.2f} MB"

    @property
    def used_pages(self) -> int:
        return self.page_count - self.freelist_count

    @property
    def fragmentation_pct(self) -> float:
        if self.page_count == 0:
            return 0.0
        return round(self.freelist_count / self.page_count * 100, 1)


@dataclass
class HealthResult:
    integrity_ok: bool
    integrity_errors: list[str]
    fk_violations: list[dict[str, Any]]  # table, rowid, parent, fkid
    checked_at: str = ""  # human-readable timestamp, e.g. "2:47:05 PM"

    @property
    def all_ok(self) -> bool:
        return self.integrity_ok and not self.fk_violations


@dataclass
class DatabaseAdminPageResponse:
    status_code: int
    body_html: str


class DatabaseAdminPages:
    """Render and handle the Database administration page."""

    TEMPLATE = "database_admin.html"

    def __init__(self, conn: sqlite3.Connection, db_path: str) -> None:
        self.conn = conn
        self.db_path = db_path

    # ── Stats ────────────────────────────────────────────────────────────

    # SQLite's PRAGMA syntax doesn't accept ``?`` placeholders for the
    # pragma name itself, so we have to interpolate. Whitelist the names
    # we actually invoke as **stat queries** so a future caller can't be
    # tricked into running an arbitrary PRAGMA via this helper.
    #
    # NOTE: action-form PRAGMAs that take an argument and return a tuple
    # (e.g. ``PRAGMA wal_checkpoint(TRUNCATE)``) deliberately bypass this
    # helper — they have different semantics and their full literal
    # appears at the call site, which is auditable on its own.
    _PRAGMA_WHITELIST = frozenset(
        {
            "journal_mode",
            "page_size",
            "page_count",
            "freelist_count",
            "wal_autocheckpoint",
        }
    )

    def _get_stats(self) -> DbStats:
        def pragma(name: str) -> Any:
            if name not in self._PRAGMA_WHITELIST:
                raise ValueError(f"PRAGMA {name!r} not whitelisted")
            row = self.conn.execute(f"PRAGMA {name}").fetchone()
            return row[0] if row else None

        path = Path(self.db_path)
        size = path.stat().st_size if path.exists() else 0
        journal_mode = pragma("journal_mode") or "delete"

        return DbStats(
            file_path=self.db_path,
            file_size_bytes=size,
            page_size=int(pragma("page_size") or 4096),
            page_count=int(pragma("page_count") or 0),
            freelist_count=int(pragma("freelist_count") or 0),
            journal_mode=journal_mode,
            wal_autocheckpoint=(
                int(pragma("wal_autocheckpoint")) if journal_mode == "wal" else None
            ),
        )

    # ── Health check ─────────────────────────────────────────────────────

    def run_health_check(self) -> HealthResult:
        # integrity_check returns one row per issue; 'ok' means clean.
        ic_rows = self.conn.execute("PRAGMA integrity_check").fetchall()
        integrity_errors = [r[0] for r in ic_rows if r[0] != "ok"]

        # foreign_key_check returns one row per violation (empty = clean).
        fk_rows = self.conn.execute("PRAGMA foreign_key_check").fetchall()
        fk_violations = [
            {
                "table": r[0],
                "rowid": r[1],
                "parent_table": r[2],
                "fkid": r[3],
            }
            for r in fk_rows
        ]

        return HealthResult(
            integrity_ok=len(integrity_errors) == 0,
            integrity_errors=integrity_errors,
            fk_violations=fk_violations,
            checked_at=datetime.now().strftime("%-I:%M:%S %p"),
        )

    # ── Table row counts (for the stats panel) ───────────────────────────

    def _table_counts(self) -> list[dict[str, Any]]:
        tables = [
            r[0]
            for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        counts = []
        for t in tables:
            n = self.conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            counts.append({"table": t, "rows": n})
        return counts

    # ── Render ───────────────────────────────────────────────────────────

    def render_page(
        self,
        *,
        org: dict[str, Any] | None,
        theme: str,
        health_result: HealthResult | None = None,
        flash_message: str = "",
        error_message: str = "",
        size_before: str = "",
        size_after: str = "",
    ) -> DatabaseAdminPageResponse:
        stats = self._get_stats()
        table_counts = self._table_counts()
        last_backup = self._get_last_backup()

        ctx = {
            "heading": "Database",
            "org": org or {},
            "theme": theme,
            "page_key": "database-admin",
            "breadcrumb": "System",
            "stats": stats,
            "table_counts": table_counts,
            "health_result": health_result,
            "flash_message": flash_message,
            "error_message": error_message,
            "size_before": size_before,
            "size_after": size_after,
            "last_backup": last_backup,
        }
        return DatabaseAdminPageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.TEMPLATE, ctx),
        )

    # ── POST: health check ───────────────────────────────────────────────

    def handle_check(
        self, *, org: dict[str, Any] | None, theme: str
    ) -> tuple[str | None, DatabaseAdminPageResponse | None]:
        result = self.run_health_check()
        resp = self.render_page(
            org=org,
            theme=theme,
            health_result=result,
            flash_message="Health check complete." if result.all_ok else "",
            error_message="" if result.all_ok else "Issues found — see details below.",
        )
        return None, resp

    # ── POST: REINDEX ────────────────────────────────────────────────────

    def handle_reindex(
        self, *, org: dict[str, Any] | None, theme: str
    ) -> tuple[str | None, DatabaseAdminPageResponse | None]:
        try:
            self.conn.execute("REINDEX")
        except Exception as exc:
            resp = self.render_page(
                org=org,
                theme=theme,
                error_message=f"REINDEX failed: {exc}",
            )
            return None, resp
        return "/admin/database?msg=All+indexes+rebuilt+successfully.", None

    # ── POST: VACUUM ─────────────────────────────────────────────────────

    def handle_vacuum(
        self, *, org: dict[str, Any] | None, theme: str
    ) -> tuple[str | None, DatabaseAdminPageResponse | None]:
        try:
            size_before = self._get_stats().file_size_mb
            # VACUUM must run outside a transaction; conn.isolation_level=None
            # (autocommit) is needed, or we use executescript.
            self.conn.execute("COMMIT")  # close any open txn
        except Exception:
            pass
        try:
            self.conn.isolation_level = None  # switch to autocommit
            self.conn.execute("VACUUM")
            self.conn.isolation_level = "DEFERRED"  # restore default
        except Exception as exc:
            resp = self.render_page(
                org=org,
                theme=theme,
                error_message=f"VACUUM failed: {exc}",
            )
            return None, resp
        size_after = self._get_stats().file_size_mb
        from urllib.parse import quote

        msg = f"VACUUM complete. Size: {size_before} → {size_after}."
        return f"/admin/database?msg={quote(msg)}", None

    # ── GET: Download backup ─────────────────────────────────────────────

    # ── Backup metadata helpers ──────────────────────────────────────────

    _BACKUP_METADATA_DDL = """
        CREATE TABLE IF NOT EXISTS backup_metadata (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            backed_up_at  TEXT NOT NULL,
            lot_count     INTEGER,
            owner_count   INTEGER,
            renter_count  INTEGER
        )
    """

    def _gather_backup_stats(self) -> dict[str, Any]:
        """Collect summary stats from the live DB to embed in the backup file."""

        def count(table: str) -> int | None:
            try:
                return self.conn.execute(  # type: ignore[no-any-return]
                    f'SELECT COUNT(*) FROM "{table}"'
                ).fetchone()[0]
            except Exception:
                return None

        def scalar(sql: str) -> Any:
            try:
                row = self.conn.execute(sql).fetchone()
                return row[0] if row else None
            except Exception:
                return None

        return {
            "backed_up_at": datetime.now().isoformat(timespec="seconds"),
            "lot_count": count("lots"),
            "owner_count": count("owners"),
            "renter_count": count("lot_renters"),
        }

    def _record_backup_in_live_db(self, stats: dict[str, Any]) -> None:
        """Persist the backup stats row in the live DB for display on page load."""
        try:
            self.conn.execute(self._BACKUP_METADATA_DDL)
            self.conn.execute(
                """
                INSERT INTO backup_metadata
                    (backed_up_at, lot_count, owner_count, renter_count)
                VALUES (?, ?, ?, ?)
                """,
                (
                    stats["backed_up_at"],
                    stats["lot_count"],
                    stats["owner_count"],
                    stats["renter_count"],
                ),
            )
            self.conn.commit()
        except Exception:
            pass  # Never let a metadata write break the backup

    def _get_last_backup(self) -> dict[str, Any] | None:
        """Return the most recent backup_metadata row, or None if none exists."""
        try:
            self.conn.execute(self._BACKUP_METADATA_DDL)
            self.conn.commit()
            row = self.conn.execute(
                "SELECT * FROM backup_metadata ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            try:
                dt = datetime.fromisoformat(d["backed_up_at"])
                d["backed_up_at_display"] = dt.strftime("%B %d, %Y at %-I:%M %p")
            except Exception:
                d["backed_up_at_display"] = d.get("backed_up_at", "")
            return d
        except Exception:
            return None

    # ── GET: Download backup ─────────────────────────────────────────────

    def handle_backup(self) -> tuple[bytes, str, dict[str, Any]]:
        """Create a consistent snapshot of the live database.

        Uses ``sqlite3.Connection.backup()`` which honours WAL mode and
        produces a single, self-contained ``.db`` file that can later be
        restored.  After the snapshot is taken, a ``backup_metadata`` row
        is written into the backup file (not the live DB) so the restore
        UI can display when and what was backed up.

        Returns (file_bytes, suggested_filename).
        """
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        filename = f"hoa_backup_{timestamp}.db"

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            dest = sqlite3.connect(tmp_path)
            try:
                self.conn.backup(dest)
                # Write metadata into the backup (not the live DB)
                stats = self._gather_backup_stats()
                dest.execute(self._BACKUP_METADATA_DDL)
                dest.execute(
                    """
                    INSERT INTO backup_metadata
                        (backed_up_at, lot_count, owner_count, renter_count)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        stats["backed_up_at"],
                        stats["lot_count"],
                        stats["owner_count"],
                        stats["renter_count"],
                    ),
                )
                dest.commit()
            finally:
                dest.close()
            # Also record in the live DB so the page can show it on load
            self._record_backup_in_live_db(stats)
            with open(tmp_path, "rb") as fh:
                data = fh.read()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        return data, filename, stats

    # ── POST: Restore preview (metadata only, no changes) ────────────────

    def handle_restore_preview(self, file_bytes: bytes) -> dict[str, Any]:
        """Read metadata from a backup file without modifying anything.

        Returns a dict with ``ok`` bool and either stats or an ``error``
        string.  Called by the JS restore UI before the user confirms.
        """
        if len(file_bytes) < 100 or file_bytes[:16] != self._SQLITE_MAGIC:
            return {"ok": False, "error": "Not a valid SQLite database file."}

        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name

            conn = sqlite3.connect(tmp_path)
            conn.row_factory = sqlite3.Row
            try:
                # Must be an HOA Accounting backup
                sv = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='schema_version'"
                ).fetchone()
                if sv is None:
                    return {
                        "ok": False,
                        "error": "Not an HOA Accounting backup (missing schema_version table).",
                    }

                # Read backup_metadata if present (older backups won't have it)
                meta_row: dict[str, Any] = {}
                bm = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='backup_metadata'"
                ).fetchone()
                if bm:
                    row = conn.execute(
                        "SELECT * FROM backup_metadata ORDER BY id DESC LIMIT 1"
                    ).fetchone()
                    if row:
                        meta_row = dict(row)

                def count(table: str) -> int | None:
                    try:
                        return conn.execute(  # type: ignore[no-any-return]
                            f'SELECT COUNT(*) FROM "{table}"'
                        ).fetchone()[0]
                    except Exception:
                        return None

                def scalar(sql: str) -> Any:
                    try:
                        r = conn.execute(sql).fetchone()
                        return r[0] if r else None
                    except Exception:
                        return None

                return {
                    "ok": True,
                    "backed_up_at": meta_row.get("backed_up_at"),
                    "lot_count": (
                        meta_row.get("lot_count") if meta_row else count("lots")
                    ),
                    "owner_count": (
                        meta_row.get("owner_count") if meta_row else count("owners")
                    ),
                    "renter_count": (
                        meta_row.get("renter_count")
                        if meta_row
                        else count("lot_renters")
                    ),
                }
            finally:
                conn.close()

        except Exception as exc:
            _log.warning("Could not read backup file for preview: %s", exc)
            return {
                "ok": False,
                "error": "Could not read backup file. The file may be corrupted or not a valid database.",
            }
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    # ── POST: Restore from backup ────────────────────────────────────────

    _SQLITE_MAGIC = b"SQLite format 3\x00"

    def handle_restore(
        self,
        file_bytes: bytes,
        *,
        org: dict[str, Any] | None,
        theme: str,
    ) -> tuple[str | None, "DatabaseAdminPageResponse | None", str]:
        """Validate *file_bytes* and, if valid, atomically replace the live DB.

        Validation steps (in order):
        1. SQLite magic header check
        2. PRAGMA integrity_check on the uploaded file
        3. ``schema_version`` table must exist
        4. ``0001_initial.sql`` migration must be recorded (proves origin)
        5. No unrecognised migration filenames (guards against foreign system)

        On success: checkpoint + WAL cleanup → atomic os.replace() → run
        pending migrations → return redirect URL.  On any failure: return
        an error page so the live DB is never touched.
        """
        from urllib.parse import quote

        def _err(msg: str) -> tuple[None, "DatabaseAdminPageResponse", str]:
            return None, self.render_page(org=org, theme=theme, error_message=msg), msg

        # ── 1. Magic header ───────────────────────────────────────────────
        if len(file_bytes) < 100 or file_bytes[:16] != self._SQLITE_MAGIC:
            return _err("The uploaded file is not a valid SQLite database.")

        # ── 2–5. Open uploaded file in a temp location and validate ───────
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name

            test_conn = sqlite3.connect(tmp_path)
            test_conn.row_factory = sqlite3.Row
            try:
                # Integrity check
                ic_rows = test_conn.execute("PRAGMA integrity_check").fetchall()
                ic_errors = [r[0] for r in ic_rows if r[0] != "ok"]
                if ic_errors:
                    return _err(
                        "Backup file failed integrity check: "
                        + "; ".join(ic_errors[:3])
                    )

                # schema_version table
                sv = test_conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='schema_version'"
                ).fetchone()
                if sv is None:
                    return _err(
                        "This file does not appear to be an HOA Accounting backup "
                        "(missing schema_version table)."
                    )

                # First migration recorded
                row = test_conn.execute(
                    "SELECT version FROM schema_version WHERE version = ?",
                    ("0001_initial.sql",),
                ).fetchone()
                if row is None:
                    return _err(
                        "This file does not appear to be an HOA Accounting backup "
                        "(0001_initial.sql not recorded)."
                    )

                # No migrations from a different/newer system
                known = {p.name for p in Migrator().discover_migrations()}
                applied_in_backup = {
                    r[0]
                    for r in test_conn.execute(
                        "SELECT version FROM schema_version"
                    ).fetchall()
                }
                unknown = applied_in_backup - known
                if unknown:
                    return _err(
                        "Backup contains unrecognised migrations: "
                        + ", ".join(sorted(unknown)[:5])
                        + ". This backup may be from a different or newer version."
                    )
            finally:
                test_conn.close()

            # ── Checkpoint current WAL before swap ────────────────────────
            try:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass

            # ── Atomic swap ───────────────────────────────────────────────
            db_path = Path(self.db_path)
            os.replace(tmp_path, str(db_path))
            tmp_path = None  # now the live file — don't delete in finally

            # Remove stale WAL / SHM sidecars (they belong to the old DB)
            for suffix in ("-wal", "-shm"):
                sidecar = db_path.parent / (db_path.name + suffix)
                try:
                    sidecar.unlink()
                except FileNotFoundError:
                    pass

            # ── Run any pending migrations on the restored DB ─────────────
            restore_conn = sqlite3.connect(str(db_path))
            try:
                Migrator().apply_all(restore_conn)
            finally:
                restore_conn.close()

            # ── Post-restore integrity verification ───────────────────────
            verify_conn = sqlite3.connect(str(db_path))
            try:
                post_ic = verify_conn.execute("PRAGMA integrity_check").fetchall()
                post_errors = [r[0] for r in post_ic if r[0] != "ok"]
                if post_errors:
                    return _err(
                        "Restore completed but post-restore integrity check failed: "
                        + "; ".join(post_errors[:3])
                        + ". Contact your system administrator."
                    )
            finally:
                verify_conn.close()

            msg = (
                "Database restored successfully. "
                "All previous data has been replaced with the backup."
            )
            return f"/admin/database?msg={quote(msg)}", None, ""

        except Exception as exc:
            return _err(f"Restore failed unexpectedly: {exc}")
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    # ── POST: WAL checkpoint ─────────────────────────────────────────────

    def handle_wal_checkpoint(
        self, *, org: dict[str, Any] | None, theme: str
    ) -> tuple[str | None, DatabaseAdminPageResponse | None]:
        stats = self._get_stats()
        if stats.journal_mode != "wal":
            resp = self.render_page(
                org=org,
                theme=theme,
                error_message="WAL checkpoint is only applicable when journal mode is WAL. "
                f"Current mode: {stats.journal_mode}.",
            )
            return None, resp
        try:
            result = self.conn.execute("PRAGMA wal_checkpoint(FULL)").fetchone()
            # result = (busy, log_frames, checkpointed_frames)
            msg = (
                f"WAL checkpoint complete — "
                f"{result[2]} of {result[1]} frames checkpointed."
            )
        except Exception as exc:
            resp = self.render_page(
                org=org,
                theme=theme,
                error_message=f"WAL checkpoint failed: {exc}",
            )
            return None, resp
        from urllib.parse import quote

        return f"/admin/database?msg={quote(msg)}", None
