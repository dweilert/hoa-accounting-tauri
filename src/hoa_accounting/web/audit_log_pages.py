"""Audit log viewer — browse who changed what and when."""

from __future__ import annotations
from typing import Any

import sqlite3
from dataclasses import dataclass
from http import HTTPStatus

from hoa_accounting.web.template_engine import render_template

PAGE_SIZE = 75


@dataclass(frozen=True)
class AuditLogPageResponse:
    status_code: int
    body_html: str


class AuditLogPages:
    TEMPLATE = "audit_log.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def render(
        self,
        *,
        org: dict[str, Any],
        theme: str,
        table_filter: str = "",
        action_filter: str = "",
        user_filter: str = "",
        date_from: str = "",
        date_to: str = "",
        page: int = 1,
    ) -> AuditLogPageResponse:
        where_clauses: list[str] = []
        params: list[Any] = []

        if table_filter:
            where_clauses.append("entity_type = ?")
            params.append(table_filter)
        if action_filter:
            where_clauses.append("action = ?")
            params.append(action_filter)
        if user_filter:
            where_clauses.append("changed_by LIKE ?")
            params.append(f"%{user_filter}%")
        if date_from:
            where_clauses.append("event_time >= ?")
            params.append(date_from)
        if date_to:
            where_clauses.append("event_time <= ?")
            params.append(date_to + " 23:59:59")

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        total = self.conn.execute(
            f"SELECT COUNT(*) FROM audit_log {where_sql}", params
        ).fetchone()[0]

        offset = (page - 1) * PAGE_SIZE
        rows = self.conn.execute(
            f"""
            SELECT id, entity_type, entity_id, action, changed_by, event_time,
                   before_json, after_json
            FROM audit_log
            {where_sql}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            params + [PAGE_SIZE, offset],
        ).fetchall()

        table_names = [
            r[0]
            for r in self.conn.execute(
                "SELECT DISTINCT entity_type FROM audit_log ORDER BY entity_type"
            ).fetchall()
        ]

        actions = [
            r[0]
            for r in self.conn.execute(
                "SELECT DISTINCT action FROM audit_log ORDER BY action"
            ).fetchall()
        ]

        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

        html = render_template(
            self.TEMPLATE,
            {
                "org": org,
                "theme": theme,
                "page_key": "audit-log",
                "active_nav": "system",
                "breadcrumb": "System",
                "rows": [dict(r) for r in rows],
                "total": total,
                "page": page,
                "total_pages": total_pages,
                "page_size": PAGE_SIZE,
                "table_names": table_names,
                "actions": actions,
                "table_filter": table_filter,
                "action_filter": action_filter,
                "user_filter": user_filter,
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        return AuditLogPageResponse(status_code=HTTPStatus.OK, body_html=html)
