"""Workflow Guide — DB-driven page handlers and admin service."""

from __future__ import annotations

import sqlite3

from hoa_accounting.web.template_engine import render_template


# ── DB helpers ────────────────────────────────────────────────────────────────

def _load_guide(conn: sqlite3.Connection) -> list[dict]:
    """Return full guide structure: tabs → sections → cards (active only)."""
    tabs = [dict(r) for r in conn.execute(
        "SELECT id, tab_key, icon, label, description FROM workflow_tabs "
        "WHERE is_active=1 ORDER BY sort_order, id"
    ).fetchall()]
    for tab in tabs:
        sections = [dict(r) for r in conn.execute(
            "SELECT id, label, tip_text FROM workflow_sections "
            "WHERE tab_id=? AND is_active=1 ORDER BY sort_order, id", (tab["id"],)
        ).fetchall()]
        for sec in sections:
            sec["cards"] = [dict(r) for r in conn.execute(
                "SELECT id, num_label, icon, title, description, href, link_label, color "
                "FROM workflow_cards WHERE section_id=? AND is_active=1 ORDER BY sort_order, id",
                (sec["id"],)
            ).fetchall()]
        tab["sections"] = sections
    return tabs


def _load_all_sections(conn: sqlite3.Connection) -> list[dict]:
    """All sections with their tab label — for the move-card dropdown."""
    rows = conn.execute(
        "SELECT s.id, s.label, t.label AS tab_label, t.sort_order AS tab_sort "
        "FROM workflow_sections s JOIN workflow_tabs t ON t.id=s.tab_id "
        "WHERE s.is_active=1 AND t.is_active=1 "
        "ORDER BY t.sort_order, s.sort_order"
    ).fetchall()
    return [dict(r) for r in rows]


# ── Admin service ─────────────────────────────────────────────────────────────

class WorkflowAdminService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def load_admin_view(self) -> list[dict]:
        """Full structure including inactive items, for the admin UI."""
        tabs = [dict(r) for r in self._conn.execute(
            "SELECT id, tab_key, icon, label, description, sort_order, is_system, is_active "
            "FROM workflow_tabs ORDER BY sort_order, id"
        ).fetchall()]
        for tab in tabs:
            sections = [dict(r) for r in self._conn.execute(
                "SELECT id, label, tip_text, sort_order, is_system, is_active "
                "FROM workflow_sections WHERE tab_id=? ORDER BY sort_order, id",
                (tab["id"],)
            ).fetchall()]
            for sec in sections:
                sec["cards"] = [dict(r) for r in self._conn.execute(
                    "SELECT id, num_label, icon, title, description, href, link_label, "
                    "color, sort_order, is_system, is_active "
                    "FROM workflow_cards WHERE section_id=? ORDER BY sort_order, id",
                    (sec["id"],)
                ).fetchall()]
            tab["sections"] = sections
        return tabs

    def all_sections_for_move(self) -> list[dict]:
        return _load_all_sections(self._conn)

    # Cards
    def add_card(self, section_id: int, num_label: str, icon: str, title: str,
                 description: str, href: str, link_label: str, color: str) -> int:
        max_sort = (self._conn.execute(
            "SELECT MAX(sort_order) FROM workflow_cards WHERE section_id=?", (section_id,)
        ).fetchone()[0] or 0) + 10
        self._conn.execute(
            "INSERT INTO workflow_cards (section_id, num_label, icon, title, description, "
            "href, link_label, color, sort_order, is_system, is_active) "
            "VALUES (?,?,?,?,?,?,?,?,?,0,1)",
            (section_id, num_label, icon, title, description,
             href or '#', link_label, color, max_sort)
        )
        self._conn.commit()
        return self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def update_card(self, card_id: int, section_id: int, num_label: str, icon: str,
                    title: str, description: str, href: str, link_label: str, color: str) -> None:
        self._conn.execute(
            "UPDATE workflow_cards SET section_id=?, num_label=?, icon=?, title=?, "
            "description=?, href=?, link_label=?, color=? WHERE id=?",
            (section_id, num_label, icon, title, description,
             href or '#', link_label, color, card_id)
        )
        self._conn.commit()

    def move_card(self, card_id: int, new_section_id: int) -> None:
        max_sort = (self._conn.execute(
            "SELECT MAX(sort_order) FROM workflow_cards WHERE section_id=?", (new_section_id,)
        ).fetchone()[0] or 0) + 10
        self._conn.execute(
            "UPDATE workflow_cards SET section_id=?, sort_order=? WHERE id=?",
            (new_section_id, max_sort, card_id)
        )
        self._conn.commit()

    def toggle_card(self, card_id: int) -> None:
        self._conn.execute(
            "UPDATE workflow_cards SET is_active=CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id=?",
            (card_id,)
        )
        self._conn.commit()

    def delete_card(self, card_id: int) -> None:
        self._conn.execute("DELETE FROM workflow_cards WHERE id=? AND is_system=0", (card_id,))
        self._conn.commit()

    def reorder_card(self, card_id: int, direction: str) -> None:
        card = self._conn.execute(
            "SELECT section_id, sort_order FROM workflow_cards WHERE id=?", (card_id,)
        ).fetchone()
        if not card:
            return
        sec_id, cur_sort = card["section_id"], card["sort_order"]
        if direction == "up":
            neighbor = self._conn.execute(
                "SELECT id, sort_order FROM workflow_cards "
                "WHERE section_id=? AND sort_order<? ORDER BY sort_order DESC LIMIT 1",
                (sec_id, cur_sort)
            ).fetchone()
        else:
            neighbor = self._conn.execute(
                "SELECT id, sort_order FROM workflow_cards "
                "WHERE section_id=? AND sort_order>? ORDER BY sort_order ASC LIMIT 1",
                (sec_id, cur_sort)
            ).fetchone()
        if neighbor:
            self._conn.execute(
                "UPDATE workflow_cards SET sort_order=? WHERE id=?", (neighbor["sort_order"], card_id)
            )
            self._conn.execute(
                "UPDATE workflow_cards SET sort_order=? WHERE id=?", (cur_sort, neighbor["id"])
            )
            self._conn.commit()

    # Sections
    def add_section(self, tab_id: int, label: str, tip_text: str = "") -> int:
        max_sort = (self._conn.execute(
            "SELECT MAX(sort_order) FROM workflow_sections WHERE tab_id=?", (tab_id,)
        ).fetchone()[0] or 0) + 10
        self._conn.execute(
            "INSERT INTO workflow_sections (tab_id, label, tip_text, sort_order, is_system, is_active) "
            "VALUES (?,?,?,?,0,1)",
            (tab_id, label, tip_text, max_sort)
        )
        self._conn.commit()
        return self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def toggle_section(self, section_id: int) -> None:
        self._conn.execute(
            "UPDATE workflow_sections SET is_active=CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id=?",
            (section_id,)
        )
        self._conn.commit()

    # Tabs
    def add_tab(self, tab_key: str, icon: str, label: str, description: str) -> int:
        # Ensure unique tab_key
        existing = {r[0] for r in self._conn.execute("SELECT tab_key FROM workflow_tabs").fetchall()}
        base = tab_key
        n = 2
        while tab_key in existing:
            tab_key = f"{base}_{n}"
            n += 1
        max_sort = (self._conn.execute("SELECT MAX(sort_order) FROM workflow_tabs").fetchone()[0] or 0) + 10
        self._conn.execute(
            "INSERT INTO workflow_tabs (tab_key, icon, label, description, sort_order, is_system, is_active) "
            "VALUES (?,?,?,?,?,0,1)",
            (tab_key, icon, label, description, max_sort)
        )
        self._conn.commit()
        return self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def toggle_tab(self, tab_id: int) -> None:
        self._conn.execute(
            "UPDATE workflow_tabs SET is_active=CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id=?",
            (tab_id,)
        )
        self._conn.commit()

    def get_card(self, card_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT id, section_id, num_label, icon, title, description, href, link_label, color "
            "FROM workflow_cards WHERE id=?", (card_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_all_tabs(self) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT id, label FROM workflow_tabs WHERE is_active=1 ORDER BY sort_order"
        ).fetchall()]


# ── Page handlers ─────────────────────────────────────────────────────────────

class WorkflowPages:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def _render(self, template: str, **ctx) -> tuple[int, str]:
        return 200, render_template(template, ctx)

    def render_guide(self, org: dict, theme: str) -> tuple[int, str]:
        tabs = _load_guide(self._conn)
        return self._render(
            "workflow_guide.html",
            org=org, theme=theme,
            heading="Workflow Guide",
            page_key="workflow-guide",
            tabs=tabs,
        )


class WorkflowAdminPages:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._svc = WorkflowAdminService(conn)

    def _render(self, template: str, **ctx) -> tuple[int, str]:
        return 200, render_template(template, ctx)

    def render_admin(self, org: dict, theme: str, active_tab_id: int = 1,
                     edit_card_id: int | None = None, flash: str = "") -> tuple[int, str]:
        tabs_data = self._svc.load_admin_view()
        sections_for_move = self._svc.all_sections_for_move()
        edit_card = self._svc.get_card(edit_card_id) if edit_card_id else None
        all_tabs = self._svc.get_all_tabs()
        return self._render(
            "admin_workflow_guide.html",
            org=org, theme=theme,
            heading="Workflow Guide Editor",
            page_key="workflow-editor",
            tabs_data=tabs_data,
            active_tab_id=active_tab_id,
            sections_for_move=sections_for_move,
            edit_card=edit_card,
            all_tabs=all_tabs,
            flash=flash,
        )

    def handle_add_card(self, form) -> str:
        sec_id = int(form.get("section_id", 0))
        tab_id = int(form.get("tab_id", 1))
        self._svc.add_card(
            section_id=sec_id,
            num_label=(form.get("num_label") or "").strip(),
            icon=(form.get("icon") or "").strip(),
            title=(form.get("title") or "").strip(),
            description=(form.get("description") or "").strip(),
            href=(form.get("href") or "").strip(),
            link_label=(form.get("link_label") or "").strip(),
            color=(form.get("color") or "slate"),
        )
        return f"/admin/workflow-guide?tab={tab_id}&flash=Card+added"

    def handle_update_card(self, form) -> str:
        card_id = int(form.get("card_id", 0))
        tab_id = int(form.get("tab_id", 1))
        self._svc.update_card(
            card_id=card_id,
            section_id=int(form.get("section_id", 0)),
            num_label=(form.get("num_label") or "").strip(),
            icon=(form.get("icon") or "").strip(),
            title=(form.get("title") or "").strip(),
            description=(form.get("description") or "").strip(),
            href=(form.get("href") or "").strip(),
            link_label=(form.get("link_label") or "").strip(),
            color=(form.get("color") or "slate"),
        )
        return f"/admin/workflow-guide?tab={tab_id}&flash=Card+saved"

    def handle_move_card(self, form) -> str:
        card_id = int(form.get("card_id", 0))
        new_section = int(form.get("new_section_id", 0))
        tab_id = int(form.get("tab_id", 1))
        self._svc.move_card(card_id, new_section)
        return f"/admin/workflow-guide?tab={tab_id}&flash=Card+moved"

    def handle_toggle_card(self, card_id: int, tab_id: int) -> None:
        self._svc.toggle_card(card_id)

    def handle_delete_card(self, form) -> str:
        card_id = int(form.get("card_id", 0))
        tab_id = int(form.get("tab_id", 1))
        self._svc.delete_card(card_id)
        return f"/admin/workflow-guide?tab={tab_id}&flash=Card+deleted"

    def handle_reorder_card(self, form) -> str:
        card_id = int(form.get("card_id", 0))
        tab_id = int(form.get("tab_id", 1))
        direction = form.get("direction", "up")
        self._svc.reorder_card(card_id, direction)
        return f"/admin/workflow-guide?tab={tab_id}"

    def handle_add_section(self, form) -> str:
        tab_id = int(form.get("tab_id", 1))
        label = (form.get("label") or "").strip()
        tip = (form.get("tip_text") or "").strip()
        if label:
            self._svc.add_section(tab_id, label, tip)
        return f"/admin/workflow-guide?tab={tab_id}&flash=Section+added"

    def handle_toggle_section(self, section_id: int, tab_id: int) -> None:
        self._svc.toggle_section(section_id)

    def handle_add_tab(self, form) -> str:
        label = (form.get("label") or "").strip()
        icon = (form.get("icon") or "").strip()
        desc = (form.get("description") or "").strip()
        tab_key = label.lower().replace(" ", "_")[:30]
        if label:
            new_id = self._svc.add_tab(tab_key, icon, label, desc)
            return f"/admin/workflow-guide?tab={new_id}&flash=Tab+added"
        return "/admin/workflow-guide?flash=Tab+label+required"

    def handle_toggle_tab(self, tab_id: int) -> None:
        self._svc.toggle_tab(tab_id)
