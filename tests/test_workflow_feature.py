"""Feature tests for the Workflow Guide and Workflow Guide Editor.

Covers WorkflowAdminService (all CRUD + reorder operations) and
WorkflowPages / WorkflowAdminPages (render methods).
"""

from __future__ import annotations

import sqlite3

from hoa_accounting.bootstrap.migrator import Migrator


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    Migrator().apply_all(conn)
    return conn


# ── WorkflowAdminService: card CRUD ──────────────────────────────────────────


class TestWorkflowCardCRUD:
    def test_add_card_stored_in_db(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        svc = WorkflowAdminService(conn)
        card_id = svc.add_card(
            section_id=10,
            num_label="T1",
            icon="🧪",
            title="Test Card",
            description="desc",
            href="/test",
            link_label="Go",
            color="teal",
        )
        row = conn.execute(
            "SELECT * FROM workflow_cards WHERE id=?", (card_id,)
        ).fetchone()
        assert row is not None
        assert row["title"] == "Test Card"
        assert row["section_id"] == 10
        assert row["is_system"] == 0
        assert row["is_active"] == 1

    def test_add_card_without_link_stores_hash(self):
        """Empty href becomes '#' (manual task)."""
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        svc = WorkflowAdminService(conn)
        card_id = svc.add_card(
            section_id=10,
            num_label="",
            icon="📋",
            title="Manual Task",
            description="",
            href="",
            link_label="",
            color="slate",
        )
        row = conn.execute(
            "SELECT href FROM workflow_cards WHERE id=?", (card_id,)
        ).fetchone()
        assert row["href"] == "#"

    def test_update_card_changes_fields(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        svc = WorkflowAdminService(conn)
        svc.update_card(
            card_id=100,
            section_id=10,
            num_label="1",
            icon="🏠",
            title="Updated Title",
            description="Updated desc",
            href="/updated",
            link_label="Updated",
            color="blue",
        )
        row = conn.execute("SELECT * FROM workflow_cards WHERE id=100").fetchone()
        assert row["title"] == "Updated Title"
        assert row["description"] == "Updated desc"
        assert row["color"] == "blue"

    def test_delete_card_removes_custom_card(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        svc = WorkflowAdminService(conn)
        card_id = svc.add_card(
            section_id=10,
            num_label="",
            icon="",
            title="To Delete",
            description="",
            href="",
            link_label="",
            color="slate",
        )
        svc.delete_card(card_id)
        gone = conn.execute(
            "SELECT id FROM workflow_cards WHERE id=?", (card_id,)
        ).fetchone()
        assert gone is None

    def test_delete_system_card_is_protected(self):
        """System cards (is_system=1) must not be deleted."""
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        svc = WorkflowAdminService(conn)
        svc.delete_card(100)  # Card 100 is a system card
        still_there = conn.execute(
            "SELECT id FROM workflow_cards WHERE id=100"
        ).fetchone()
        assert still_there is not None

    def test_get_card_returns_dict(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        card = WorkflowAdminService(conn).get_card(100)
        assert card is not None
        assert card["id"] == 100
        assert "title" in card

    def test_get_card_returns_none_for_missing_id(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        card = WorkflowAdminService(conn).get_card(999999)
        assert card is None


# ── WorkflowAdminService: card toggle and move ────────────────────────────────


class TestWorkflowCardToggleAndMove:
    def test_toggle_card_flips_is_active(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        svc = WorkflowAdminService(conn)
        before = conn.execute(
            "SELECT is_active FROM workflow_cards WHERE id=100"
        ).fetchone()["is_active"]
        svc.toggle_card(100)
        after = conn.execute(
            "SELECT is_active FROM workflow_cards WHERE id=100"
        ).fetchone()["is_active"]
        assert after != before

    def test_toggle_card_twice_restores_state(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        svc = WorkflowAdminService(conn)
        original = conn.execute(
            "SELECT is_active FROM workflow_cards WHERE id=100"
        ).fetchone()["is_active"]
        svc.toggle_card(100)
        svc.toggle_card(100)
        restored = conn.execute(
            "SELECT is_active FROM workflow_cards WHERE id=100"
        ).fetchone()["is_active"]
        assert restored == original

    def test_move_card_changes_section(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        svc = WorkflowAdminService(conn)
        # Move card 110 (Cash Receipts) to Vendor Payables section
        svc.move_card(110, 12)
        row = conn.execute(
            "SELECT section_id FROM workflow_cards WHERE id=110"
        ).fetchone()
        assert row["section_id"] == 12

    def test_move_card_appended_at_end(self):
        """Moved card gets sort_order > all existing cards in target section."""
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        svc = WorkflowAdminService(conn)
        max_sort_before = (
            conn.execute(
                "SELECT MAX(sort_order) FROM workflow_cards WHERE section_id=12"
            ).fetchone()[0]
            or 0
        )

        svc.move_card(110, 12)
        new_sort = conn.execute(
            "SELECT sort_order FROM workflow_cards WHERE id=110"
        ).fetchone()["sort_order"]
        assert new_sort > max_sort_before


# ── WorkflowAdminService: card reorder ───────────────────────────────────────


class TestWorkflowCardReorder:
    def test_reorder_up_swaps_with_previous(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        svc = WorkflowAdminService(conn)
        # Cards 110 and 111 are both in section 11, sorted 10 and 20
        sort_110_before = conn.execute(
            "SELECT sort_order FROM workflow_cards WHERE id=110"
        ).fetchone()["sort_order"]
        sort_111_before = conn.execute(
            "SELECT sort_order FROM workflow_cards WHERE id=111"
        ).fetchone()["sort_order"]

        svc.reorder_card(111, "up")

        sort_110_after = conn.execute(
            "SELECT sort_order FROM workflow_cards WHERE id=110"
        ).fetchone()["sort_order"]
        sort_111_after = conn.execute(
            "SELECT sort_order FROM workflow_cards WHERE id=111"
        ).fetchone()["sort_order"]

        # They should have swapped
        assert sort_111_after == sort_110_before
        assert sort_110_after == sort_111_before

    def test_reorder_down_swaps_with_next(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        svc = WorkflowAdminService(conn)
        sort_110_before = conn.execute(
            "SELECT sort_order FROM workflow_cards WHERE id=110"
        ).fetchone()["sort_order"]
        sort_111_before = conn.execute(
            "SELECT sort_order FROM workflow_cards WHERE id=111"
        ).fetchone()["sort_order"]

        svc.reorder_card(110, "down")

        sort_110_after = conn.execute(
            "SELECT sort_order FROM workflow_cards WHERE id=110"
        ).fetchone()["sort_order"]
        sort_111_after = conn.execute(
            "SELECT sort_order FROM workflow_cards WHERE id=111"
        ).fetchone()["sort_order"]

        assert sort_110_after == sort_111_before
        assert sort_111_after == sort_110_before

    def test_reorder_first_card_up_is_noop(self):
        """Moving the first card up should not change any sort_orders."""
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        svc = WorkflowAdminService(conn)
        # Card 100 is first in section 10
        sort_before = conn.execute(
            "SELECT sort_order FROM workflow_cards WHERE id=100"
        ).fetchone()["sort_order"]

        svc.reorder_card(100, "up")

        sort_after = conn.execute(
            "SELECT sort_order FROM workflow_cards WHERE id=100"
        ).fetchone()["sort_order"]
        assert sort_after == sort_before


# ── WorkflowAdminService: sections ───────────────────────────────────────────


class TestWorkflowSections:
    def test_add_section_appears_in_admin_view(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        svc = WorkflowAdminService(conn)
        svc.add_section(tab_id=1, label="New Section", tip_text="A tip")
        tabs = svc.load_admin_view()
        monthly = next(t for t in tabs if t["tab_key"] == "monthly")
        labels = [s["label"] for s in monthly["sections"]]
        assert "New Section" in labels

    def test_toggle_section_flips_is_active(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        svc = WorkflowAdminService(conn)
        before = conn.execute(
            "SELECT is_active FROM workflow_sections WHERE id=10"
        ).fetchone()["is_active"]
        svc.toggle_section(10)
        after = conn.execute(
            "SELECT is_active FROM workflow_sections WHERE id=10"
        ).fetchone()["is_active"]
        assert after != before

    def test_toggled_off_section_removes_its_cards(self):
        """Cards in an inactive section are excluded from the rendered guide."""
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService, _load_guide

        # Confirm card 100 (Bill Dues) is in section 10 and visible before toggle
        tabs_before = _load_guide(conn)
        monthly_before = next(t for t in tabs_before if t["tab_key"] == "monthly")
        billing_before = next(s for s in monthly_before["sections"] if s["id"] == 10)
        assert any(c["id"] == 100 for c in billing_before["cards"])

        # Hide section 10 (Billing)
        WorkflowAdminService(conn).toggle_section(10)

        # Card 100 must not appear in the guide
        tabs_after = _load_guide(conn)
        monthly_after = next(t for t in tabs_after if t["tab_key"] == "monthly")
        section_ids = [s["id"] for s in monthly_after["sections"]]
        assert 10 not in section_ids

    def test_all_sections_for_move_includes_all_active(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        sections = WorkflowAdminService(conn).all_sections_for_move()
        assert len(sections) > 0
        for s in sections:
            assert "id" in s
            assert "label" in s
            assert "tab_label" in s


# ── WorkflowAdminService: tabs ────────────────────────────────────────────────


class TestWorkflowTabs:
    def test_add_tab_appears_in_admin_view(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        svc = WorkflowAdminService(conn)
        svc.add_tab(
            tab_key="custom", icon="🔧", label="Custom Tab", description="For testing"
        )
        tabs = svc.load_admin_view()
        keys = [t["tab_key"] for t in tabs]
        assert "custom" in keys

    def test_add_tab_deduplicates_key(self):
        """Adding two tabs with the same derived key produces unique keys."""
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        svc = WorkflowAdminService(conn)
        svc.add_tab(tab_key="dup", icon="", label="Dup Tab", description="")
        svc.add_tab(tab_key="dup", icon="", label="Dup Tab", description="")
        tabs = svc.load_admin_view()
        dup_tabs = [t for t in tabs if t["tab_key"].startswith("dup")]
        assert len(dup_tabs) == 2
        assert dup_tabs[0]["tab_key"] != dup_tabs[1]["tab_key"]

    def test_toggle_tab_flips_is_active(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        svc = WorkflowAdminService(conn)
        # Add a non-system tab to toggle
        tab_id = svc.add_tab(
            tab_key="togtest", icon="", label="Toggle Tab", description=""
        )
        before = conn.execute(
            "SELECT is_active FROM workflow_tabs WHERE id=?", (tab_id,)
        ).fetchone()["is_active"]
        svc.toggle_tab(tab_id)
        after = conn.execute(
            "SELECT is_active FROM workflow_tabs WHERE id=?", (tab_id,)
        ).fetchone()["is_active"]
        assert after != before

    def test_toggled_off_tab_excluded_from_guide_data(self):
        """An inactive tab is not included in the guide's tab list."""
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService, _load_guide

        WorkflowAdminService(conn).toggle_tab(4)  # hide Exceptions tab
        tabs = _load_guide(conn)
        tab_keys = [t["tab_key"] for t in tabs]
        assert "adjustments" not in tab_keys  # tab_key for Exceptions is 'adjustments'

    def test_get_all_tabs_returns_active_tabs(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        tabs = WorkflowAdminService(conn).get_all_tabs()
        assert len(tabs) > 0
        for t in tabs:
            assert "id" in t
            assert "label" in t


# ── WorkflowAdminService: load_admin_view ────────────────────────────────────


class TestWorkflowLoadAdminView:
    def test_load_admin_view_includes_inactive_items(self):
        """Admin view shows all tabs/sections/cards including inactive ones."""
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        svc = WorkflowAdminService(conn)
        # Deactivate card 100
        svc.toggle_card(100)

        tabs = svc.load_admin_view()
        all_card_ids = []
        for tab in tabs:
            for sec in tab["sections"]:
                all_card_ids.extend(c["id"] for c in sec["cards"])

        assert 100 in all_card_ids  # deactivated card still visible in admin view

    def test_load_admin_view_structure(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        tabs = WorkflowAdminService(conn).load_admin_view()
        assert len(tabs) >= 4
        for tab in tabs:
            assert "id" in tab
            assert "tab_key" in tab
            assert "sections" in tab
            for sec in tab["sections"]:
                assert "cards" in sec


# ── WorkflowAdminPages: handler redirect strings ─────────────────────────────


class TestWorkflowAdminPageHandlers:
    def _form(self, data: dict) -> dict:
        return data  # handlers call form.get() — a plain dict works

    def test_handle_add_card_redirects_to_correct_tab(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages

        url = WorkflowAdminPages(conn).handle_add_card(
            {
                "section_id": "10",
                "tab_id": "1",
                "num_label": "T",
                "icon": "🔧",
                "title": "Handler Card",
                "description": "",
                "href": "",
                "link_label": "",
                "color": "teal",
            }
        )
        assert url.startswith("/admin/workflow-guide?tab=1")
        assert "flash=" in url

    def test_handle_update_card_redirects_with_scrollto(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages

        url = WorkflowAdminPages(conn).handle_update_card(
            {
                "card_id": "100",
                "tab_id": "1",
                "section_id": "10",
                "num_label": "1",
                "icon": "🏠",
                "title": "Updated",
                "description": "",
                "href": "",
                "link_label": "",
                "color": "blue",
            }
        )
        assert "scrollto=100" in url

    def test_handle_delete_card_redirects(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import (
            WorkflowAdminPages,
            WorkflowAdminService,
        )

        # Add a custom card to delete
        card_id = WorkflowAdminService(conn).add_card(
            section_id=10,
            num_label="",
            icon="",
            title="To Delete",
            description="",
            href="",
            link_label="",
            color="slate",
        )
        url = WorkflowAdminPages(conn).handle_delete_card(
            {"card_id": str(card_id), "tab_id": "1"}
        )
        assert url.startswith("/admin/workflow-guide")

    def test_handle_add_section_redirects(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages

        url = WorkflowAdminPages(conn).handle_add_section(
            {"tab_id": "1", "label": "New Handler Section", "tip_text": ""}
        )
        assert url.startswith("/admin/workflow-guide?tab=1")

    def test_handle_add_tab_redirects_to_new_tab(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages

        url = WorkflowAdminPages(conn).handle_add_tab(
            {"label": "Handler New Tab", "icon": "🆕", "description": "Test"}
        )
        assert url.startswith("/admin/workflow-guide?tab=")

    def test_handle_add_tab_empty_label_redirects_with_error(self):
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages

        url = WorkflowAdminPages(conn).handle_add_tab(
            {"label": "", "icon": "", "description": ""}
        )
        assert "flash=" in url
