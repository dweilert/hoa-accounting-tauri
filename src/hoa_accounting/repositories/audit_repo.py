"""Repository for audit logging."""

from __future__ import annotations

import json
from typing import Any

from .base import BaseRepository


class AuditRepository(BaseRepository):
    """Database access for audit logging."""

    def write(
        self,
        *,
        entity_type: str,
        entity_id: int,
        action: str,
        user_id: int | None,
        before_json: dict[str, Any] | None = None,
        after_json: dict[str, Any] | None = None,
    ) -> None:
        """Insert an audit log row."""
        self.conn.execute(
            """
            INSERT INTO audit_log (
                user_id,
                entity_type,
                entity_id,
                action,
                before_json,
                after_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                entity_type,
                entity_id,
                action,
                json.dumps(before_json) if before_json is not None else None,
                json.dumps(after_json) if after_json is not None else None,
            ),
        )
