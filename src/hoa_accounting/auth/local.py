"""Local SQLite authentication backend."""

from __future__ import annotations
from typing import Any

import logging
import sqlite3
import threading
from datetime import datetime, timezone

from hoa_accounting.auth.base import ROLE_ADMIN, ROLE_REPORTS, AuthUser

_log = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    import bcrypt

    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _check_password(plain: str, hashed: str) -> bool:
    import bcrypt

    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception as exc:
        _log.warning("bcrypt check failed (corrupted hash?): %s", exc)
        return False


class LocalBackend:
    supports_password = True
    supports_oauth = False

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._tl = threading.local()

    @property
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._tl, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 5000")
            self._tl.conn = conn
        return conn

    # ── AuthBackend protocol ──────────────────────────────────────────────

    def authenticate(self, email: str, password: str) -> AuthUser | None:
        row = self._conn.execute(
            "SELECT id, email, display_name, role, password_hash, is_active "
            "FROM local_users WHERE email = ? COLLATE NOCASE",
            (email,),
        ).fetchone()
        if row is None or not row["is_active"]:
            return None
        if not _check_password(password, row["password_hash"]):
            return None
        self._conn.execute(
            "UPDATE local_users SET last_login_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), row["id"]),
        )
        self._conn.commit()
        role = self._resolve_role(email, row["role"])
        return AuthUser(
            email=row["email"],
            display_name=row["display_name"] or row["email"],
            role=role,
            backend="local",
        )

    def get_login_url(self, redirect_uri: str) -> str | None:
        return None

    def handle_callback(self, code: str, redirect_uri: str) -> AuthUser | None:
        return None

    # ── Role resolution ───────────────────────────────────────────────────

    def _resolve_role(self, email: str, base_role: str) -> str:
        override = self._conn.execute(
            "SELECT role FROM local_role_overrides WHERE email = ? COLLATE NOCASE",
            (email,),
        ).fetchone()
        return override["role"] if override else base_role

    # ── User management ───────────────────────────────────────────────────

    def list_users(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, email, display_name, role, is_active, last_login_at, created_at "
            "FROM local_users ORDER BY email"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT id, email, display_name, role, is_active, last_login_at, created_at "
            "FROM local_users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT id, email, display_name, role, is_active FROM local_users "
            "WHERE email = ? COLLATE NOCASE",
            (email,),
        ).fetchone()
        return dict(row) if row else None

    def create_user(
        self, email: str, display_name: str, role: str, password: str
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO local_users (email, display_name, role, password_hash) VALUES (?, ?, ?, ?)",
            (
                email.strip().lower(),
                display_name.strip(),
                role,
                hash_password(password),
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def update_user(
        self, user_id: int, display_name: str, role: str, is_active: bool
    ) -> None:
        self._conn.execute(
            "UPDATE local_users SET display_name = ?, role = ?, is_active = ? WHERE id = ?",
            (display_name.strip(), role, 1 if is_active else 0, user_id),
        )
        self._conn.commit()

    def set_password(self, user_id: int, password: str) -> None:
        self._conn.execute(
            "UPDATE local_users SET password_hash = ? WHERE id = ?",
            (hash_password(password), user_id),
        )
        self._conn.commit()

    def delete_user(self, user_id: int) -> None:
        self._conn.execute("DELETE FROM local_users WHERE id = ?", (user_id,))
        self._conn.commit()

    # ── Role overrides ────────────────────────────────────────────────────

    def list_overrides(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, email, role, note, created_at FROM local_role_overrides ORDER BY email"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_override(self, email: str, role: str, note: str = "") -> None:
        self._conn.execute(
            """INSERT INTO local_role_overrides (email, role, note)
               VALUES (?, ?, ?)
               ON CONFLICT(email) DO UPDATE SET role = excluded.role, note = excluded.note""",
            (email.strip().lower(), role, note.strip()),
        )
        self._conn.commit()

    def delete_override(self, override_id: int) -> None:
        self._conn.execute(
            "DELETE FROM local_role_overrides WHERE id = ?", (override_id,)
        )
        self._conn.commit()
