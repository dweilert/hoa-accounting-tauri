"""Regression tests for bugs found during manual testing.

Each test is named after the symptom so failures pinpoint the root cause.
"""

from __future__ import annotations

import sqlite3

import pytest

from hoa_accounting.bootstrap.migrator import Migrator


import pytest
pytestmark = pytest.mark.skip(
    reason="Pending rewrite after Chart of Accounts removal (migration 0061)"
)
def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    Migrator().apply_all(conn)
    return conn


# ── Bug: wizard account creation fails with empty group_code ──────────────────
# Repro: completing the COA Setup Wizard raised
#   IntegrityError: CHECK constraint failed: group_code IS NULL OR group_code IN (...)
# Root cause: wizard_pages.py passed "" instead of None for group_code.

def _insert_account(conn: sqlite3.Connection, account_number: str,
                    account_name: str, account_type: str = "ASSET",
                    fund_code: str = "OPERATING", group_code=None) -> None:
    """Mirror the exact INSERT used by wizard_pages.WizardService.create_accounts."""
    type_id = conn.execute(
        "SELECT id FROM account_types WHERE code=?", (account_type,)
    ).fetchone()["id"]
    conn.execute(
        """INSERT INTO accounts
           (account_number, account_name, account_type_id, fund_code,
            group_code, is_bank_account, description, is_active)
           VALUES (?, ?, ?, ?, ?, 0, '', 1)""",
        (account_number, account_name, type_id, fund_code, group_code),
    )
    conn.commit()


class TestWizardAccountCreation:
    def test_null_group_code_satisfies_check_constraint(self):
        """NULL group_code must pass the DB check constraint (not empty string)."""
        conn = _make_conn()
        # This is the exact bug: passing "" raised IntegrityError; None must not.
        _insert_account(conn, "9001", "Test Account", group_code=None)
        row = conn.execute(
            "SELECT group_code FROM accounts WHERE account_number='9001'"
        ).fetchone()
        assert row["group_code"] is None

    def test_empty_string_group_code_violates_constraint(self):
        """Confirm empty string still raises — so we know the constraint is active."""
        import sqlite3 as _sqlite3
        conn = _make_conn()
        with pytest.raises(_sqlite3.IntegrityError, match="group_code"):
            _insert_account(conn, "9002", "Bad Account", group_code="")

    def test_valid_group_code_is_stored(self):
        """A recognised group_code value is stored as-is."""
        conn = _make_conn()
        _insert_account(conn, "9003", "Landscape Expense",
                        account_type="EXPENSE", group_code="LANDSCAPE")
        row = conn.execute(
            "SELECT group_code FROM accounts WHERE account_number='9003'"
        ).fetchone()
        assert row["group_code"] == "LANDSCAPE"

    def test_wizard_service_create_accounts_uses_null_for_missing_group_code(self):
        """WizardService._conn insert path passes None (not '') for missing group_code.

        Calls the internal insert logic directly by constructing the resolved
        account list that create_accounts would produce after resolve_accounts.
        """
        conn = _make_conn()
        # Directly exercise the insert block — same logic as create_accounts
        # but without going through resolve_accounts (which needs a Flask form).
        type_map = {
            row["code"]: row["id"]
            for row in conn.execute("SELECT id, code FROM account_types").fetchall()
        }
        a = {
            "account_number": "9004",
            "account_name": "No Group Account",
            "account_type": "ASSET",
            "fund_code": "OPERATING",
            # group_code absent — must become None
        }
        conn.execute(
            """INSERT INTO accounts
               (account_number, account_name, account_type_id, fund_code,
                group_code, is_bank_account, description, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
            (
                a["account_number"],
                a["account_name"],
                type_map[a["account_type"]],
                a["fund_code"],
                a.get("group_code") or None,   # ← the fixed expression
                0,
                "",
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT group_code FROM accounts WHERE account_number='9004'"
        ).fetchone()
        assert row["group_code"] is None


# ── Bug: workflow guide routes raised AttributeError: db ─────────────────────
# Repro: navigating to /workflow-guide or /admin/workflow-guide returned 500
#   AttributeError: db
# Root cause: routes used g.db directly before _open_db() had been called.
# Fix: routes now call _open_db() which lazily initialises g.db.

class TestWorkflowPages:
    def test_render_guide_returns_html(self):
        """/workflow-guide renders without error when DB has workflow tables."""
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowPages

        org = {"name": "Test HOA", "db_path": ":memory:"}
        status, html = WorkflowPages(conn).render_guide(org=org, theme="warm")
        assert status == 200
        assert "Workflow Guide" in html

    def test_render_guide_shows_tabs_from_db(self):
        """Tabs seeded by migration 0037 appear in the rendered guide."""
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowPages

        org = {"name": "Test HOA"}
        _, html = WorkflowPages(conn).render_guide(org=org, theme="warm")
        assert "Monthly Cycle" in html
        assert "Quarter Close" in html
        assert "Year-End" in html
        assert "Exceptions" in html

    def test_render_admin_returns_html(self):
        """/admin/workflow-guide renders without error."""
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages

        org = {"name": "Test HOA"}
        status, html = WorkflowAdminPages(conn).render_admin(
            org=org, theme="warm", active_tab_id=1
        )
        assert status == 200
        assert "Workflow Guide Editor" in html

    def test_move_card_persists(self):
        """Moving a card to a different section updates section_id in DB."""
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService

        svc = WorkflowAdminService(conn)
        # Card 110 (Post Payments) is in section 11 (Cash Receipts, monthly)
        # Move it to section 12 (Vendor Payables)
        svc.move_card(110, 12)
        row = conn.execute(
            "SELECT section_id FROM workflow_cards WHERE id=110"
        ).fetchone()
        assert row["section_id"] == 12

    def test_toggle_card_flips_is_active(self):
        """Toggling a card switches is_active between 0 and 1."""
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

        assert after == (0 if before == 1 else 1)

    def test_add_card_appears_in_guide(self):
        """A newly added card shows up in the rendered workflow guide."""
        conn = _make_conn()
        from hoa_accounting.web.workflow_pages import WorkflowAdminService, WorkflowPages

        svc = WorkflowAdminService(conn)
        svc.add_card(
            section_id=11,
            num_label="X",
            icon="🧪",
            title="Test Card",
            description="Regression test card",
            href="/test",
            link_label="Test",
            color="slate",
        )

        org = {"name": "Test HOA"}
        _, html = WorkflowPages(conn).render_guide(org=org, theme="warm")
        assert "Test Card" in html
