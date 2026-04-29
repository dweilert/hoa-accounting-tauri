"""Board Members CRUD — list, add, edit, delete."""

from __future__ import annotations
from typing import Any

import sqlite3
from dataclasses import dataclass
from http import HTTPStatus

from hoa_accounting.web.template_engine import render_template


@dataclass
class BoardMemberPageResponse:
    status_code: int
    body_html: str


class BoardMemberPages:
    LIST_TEMPLATE = "board_members_list.html"
    FORM_TEMPLATE = "board_members_form.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ── List ─────────────────────────────────────────────────────────────

    def render_list(
        self, *, org: dict[str, Any], theme: str, flash_message: str = ""
    ) -> BoardMemberPageResponse:
        rows = self.conn.execute(
            """SELECT id, full_name, title, email, phone,
                      start_date, end_date, is_active, notes
               FROM board_members
               ORDER BY is_active DESC, title, full_name"""
        ).fetchall()
        ctx = {
            "heading": "Board Members",
            "org": org,
            "theme": theme,
            "page_key": "board-members",
            "breadcrumb": "Manage",
            "members": [dict(r) for r in rows],
            "flash_message": flash_message,
        }
        return BoardMemberPageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.LIST_TEMPLATE, ctx),
        )

    # ── Add / Edit form ─────────────────────────────────────────────────

    def render_form(
        self,
        *,
        org: dict[str, Any],
        theme: str,
        member: dict[str, Any] | None = None,
        error_message: str = "",
    ) -> BoardMemberPageResponse:
        ctx = {
            "heading": "Edit Board Member" if member else "Add Board Member",
            "org": org,
            "theme": theme,
            "page_key": "board-members",
            "breadcrumb": "Manage · Board Members",
            "parent_url": "/board-members",
            "member": member or {},
            "error_message": error_message,
        }
        return BoardMemberPageResponse(
            status_code=HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK,
            body_html=render_template(self.FORM_TEMPLATE, ctx),
        )

    # ── Add ──────────────────────────────────────────────────────────────

    def handle_add(self, *, form: dict[str, Any], org: dict[str, Any], theme: str) -> tuple[str | None, BoardMemberPageResponse | None]:
        full_name = (form.get("full_name") or "").strip()
        title = (form.get("title") or "").strip()
        if not full_name or not title:
            resp = self.render_form(
                org=org, theme=theme,
                member=dict(form),
                error_message="Full Name and Title are required.",
            )
            return (None, resp)
        self.conn.execute(
            """INSERT INTO board_members
               (full_name, title, email, phone, start_date, end_date, is_active, notes)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                full_name,
                title,
                (form.get("email") or "").strip() or None,
                (form.get("phone") or "").strip() or None,
                (form.get("start_date") or "").strip() or None,
                (form.get("end_date") or "").strip() or None,
                1 if (form.get("is_active") or "1") == "1" else 0,
                (form.get("notes") or "").strip() or None,
            ),
        )
        self.conn.commit()
        return ("/board-members?msg=Board+member+added.", None)

    # ── Edit ─────────────────────────────────────────────────────────────

    def render_edit(
        self, member_id: int, *, org: dict[str, Any], theme: str
    ) -> BoardMemberPageResponse:
        row = self.conn.execute(
            "SELECT * FROM board_members WHERE id = ?", (member_id,)
        ).fetchone()
        if row is None:
            return BoardMemberPageResponse(
                status_code=HTTPStatus.NOT_FOUND,
                body_html="<h1>Board member not found</h1>",
            )
        return self.render_form(org=org, theme=theme, member=dict(row))

    def handle_edit(
        self, member_id: int, *, form: dict[str, Any], org: dict[str, Any], theme: str
    ) -> tuple[str | None, BoardMemberPageResponse | None]:
        row = self.conn.execute(
            "SELECT id FROM board_members WHERE id = ?", (member_id,)
        ).fetchone()
        if row is None:
            return ("/board-members?msg=Board+member+not+found.", None)
        full_name = (form.get("full_name") or "").strip()
        title = (form.get("title") or "").strip()
        if not full_name or not title:
            merged = dict(form)
            merged["id"] = member_id
            resp = self.render_form(
                org=org, theme=theme,
                member=merged,
                error_message="Full Name and Title are required.",
            )
            return (None, resp)
        self.conn.execute(
            """UPDATE board_members
                  SET full_name=?, title=?, email=?, phone=?,
                      start_date=?, end_date=?, is_active=?, notes=?
                WHERE id=?""",
            (
                full_name,
                title,
                (form.get("email") or "").strip() or None,
                (form.get("phone") or "").strip() or None,
                (form.get("start_date") or "").strip() or None,
                (form.get("end_date") or "").strip() or None,
                1 if (form.get("is_active") or "1") == "1" else 0,
                (form.get("notes") or "").strip() or None,
                member_id,
            ),
        )
        self.conn.commit()
        return ("/board-members?msg=Board+member+updated.", None)

    # ── Delete ───────────────────────────────────────────────────────────

    def handle_delete(self, member_id: int) -> str:
        self.conn.execute("DELETE FROM board_members WHERE id = ?", (member_id,))
        self.conn.commit()
        return "/board-members?msg=Board+member+deleted."
