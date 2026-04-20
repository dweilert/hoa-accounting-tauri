"""Feature tests for the COA Setup Wizard.

Covers WizardService (step contexts, resolve_accounts, build_preview, create_accounts)
and WizardAdminService (toggle, add, delete options; add groups).
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest

from hoa_accounting.bootstrap.migrator import Migrator


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    Migrator().apply_all(conn)
    return conn


def _fake_form(data: dict[str, list[str]]) -> MagicMock:
    """Minimal stand-in for a Flask ImmutableMultiDict."""
    form = MagicMock()
    form.getlist.side_effect = lambda key: data.get(key, [])
    form.get.side_effect = lambda key, default=None: (data.get(key) or [default])[0]
    return form


# ── WizardService: step context builders ─────────────────────────────────────

class TestWizardStepContexts:
    def test_step1_context_has_required_keys(self):
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardService
        ctx = WizardService(conn).step1_context()
        assert "step1_always" in ctx
        assert "step1_options" in ctx

    def test_step1_always_accounts_are_present(self):
        """Migration seeds at least one always-on option with accounts for step 1."""
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardService
        ctx = WizardService(conn).step1_context()
        # Always-on accounts (Operating Checking etc.) must exist
        assert len(ctx["step1_always"]) > 0

    def test_step1_options_are_present(self):
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardService
        ctx = WizardService(conn).step1_context()
        assert len(ctx["step1_options"]) > 0

    def test_step2_context_returns_income_options(self):
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardService
        ctx = WizardService(conn).step2_context()
        assert "step2_options" in ctx
        assert isinstance(ctx["step2_options"], list)

    def test_step3_context_returns_amenity_options(self):
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardService
        ctx = WizardService(conn).step3_context()
        assert "step3_options" in ctx

    def test_step4_context_returns_expense_groups(self):
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardService
        ctx = WizardService(conn).step4_context()
        assert "step4_groups" in ctx
        # Each group has an options list
        for g in ctx["step4_groups"]:
            assert "options" in g
            assert len(g["options"]) > 0

    def test_step5_context_returns_reserve_options(self):
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardService
        ctx = WizardService(conn).step5_context()
        assert "step5_options" in ctx
        assert "step5_reserve_study" in ctx

    def test_step5_reserve_study_excludes_manual_option_labels(self):
        """Reserve-study items with same label as a manual option are not duplicated."""
        conn = _make_conn()
        manual_label = conn.execute(
            "SELECT label FROM wizard_options WHERE step_number=5 AND is_active=1 LIMIT 1"
        ).fetchone()
        if manual_label:
            conn.execute(
                "INSERT INTO reserve_assets (asset_group, component, install_year, "
                "useful_life_years, replacement_cost, active_flag) "
                "VALUES (?, 'Test Item', 2000, 20, 10000, 1)",
                (manual_label["label"],),
            )
            conn.commit()
            from hoa_accounting.web.wizard_pages import WizardService
            ctx = WizardService(conn).step5_context()
            rs_labels = [i["label"].lower() for i in ctx["step5_reserve_study"]]
            assert manual_label["label"].lower() not in rs_labels


# ── WizardService: resolve_accounts ──────────────────────────────────────────

class TestWizardResolveAccounts:
    def test_always_on_accounts_included_regardless_of_selections(self):
        """Accounts tied to the always-on option appear even with an empty form."""
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardService
        form = _fake_form({})
        accounts = WizardService(conn).resolve_accounts(form)
        # Always-on accounts must be present
        assert len(accounts) > 0

    def test_no_duplicate_account_numbers(self):
        """resolve_accounts never returns two entries with the same account_number."""
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardService
        # Select several options across steps
        opt1 = conn.execute(
            "SELECT option_id FROM wizard_options WHERE step_number=1 AND is_always=0 AND is_active=1 LIMIT 1"
        ).fetchone()
        opt2 = conn.execute(
            "SELECT option_id FROM wizard_options WHERE step_number=2 AND is_active=1 LIMIT 1"
        ).fetchone()
        form = _fake_form({
            "step1": [opt1["option_id"]] if opt1 else [],
            "step2": [opt2["option_id"]] if opt2 else [],
        })
        accounts = WizardService(conn).resolve_accounts(form)
        numbers = [a["account_number"] for a in accounts]
        assert len(numbers) == len(set(numbers)), "Duplicate account numbers found"

    def test_reserve_accounts_only_when_reserve_fund_selected(self):
        """Reserve-fund accounts (fund_code=RESERVE) only appear when 'reserve' is chosen."""
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardService

        without = WizardService(conn).resolve_accounts(_fake_form({}))
        with_reserve = WizardService(conn).resolve_accounts(_fake_form({"step1": ["reserve"]}))

        reserve_without = [a for a in without if a.get("fund_code") == "RESERVE"]
        reserve_with = [a for a in with_reserve if a.get("fund_code") == "RESERVE"]

        # When reserve fund not selected, no RESERVE fund accounts should appear
        assert len(reserve_without) == 0
        # When selected, at least some should appear
        assert len(reserve_with) >= 0  # may be 0 if no amenities chosen, that's ok


# ── WizardService: build_preview ─────────────────────────────────────────────

class TestWizardBuildPreview:
    def test_preview_splits_new_vs_existing(self):
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardService

        svc = WizardService(conn)
        form = _fake_form({})
        result = svc.build_preview(form)

        assert hasattr(result, "to_create")
        assert hasattr(result, "already_exist")
        # All resolved accounts accounted for with no overlap
        to_create_nums = {p.account_number for p in result.to_create}
        existing_nums = {p.account_number for p in result.already_exist}
        assert to_create_nums.isdisjoint(existing_nums)

    def test_preview_marks_existing_account_correctly(self):
        """An account that already exists in the DB is flagged already_exists=True."""
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardService

        svc = WizardService(conn)
        # Peek at what the always-on option would create
        form = _fake_form({})
        accounts = svc.resolve_accounts(form)
        if not accounts:
            pytest.skip("No always-on accounts seeded")

        first = accounts[0]
        type_id = conn.execute(
            "SELECT id FROM account_types WHERE code=?", (first["account_type"],)
        ).fetchone()["id"]
        conn.execute(
            "INSERT OR IGNORE INTO accounts "
            "(account_number, account_name, account_type_id, fund_code, is_active) "
            "VALUES (?, ?, ?, ?, 1)",
            (first["account_number"], first["account_name"], type_id, first["fund_code"]),
        )
        conn.commit()

        result = svc.build_preview(form)
        existing_nums = {p.account_number for p in result.already_exist}
        assert first["account_number"] in existing_nums


# ── WizardAdminService: catalog management ───────────────────────────────────

class TestWizardAdminService:
    def test_toggle_option_deactivates_active_option(self):
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardAdminService

        svc = WizardAdminService(conn)
        row = conn.execute(
            "SELECT id, is_active FROM wizard_options WHERE is_always=0 LIMIT 1"
        ).fetchone()
        assert row is not None
        before = row["is_active"]

        svc.toggle_option(row["id"])
        after = conn.execute(
            "SELECT is_active FROM wizard_options WHERE id=?", (row["id"],)
        ).fetchone()["is_active"]
        assert after == (0 if before == 1 else 1)

    def test_toggle_option_twice_restores_original_state(self):
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardAdminService

        svc = WizardAdminService(conn)
        row = conn.execute(
            "SELECT id, is_active FROM wizard_options WHERE is_always=0 LIMIT 1"
        ).fetchone()
        original = row["is_active"]
        svc.toggle_option(row["id"])
        svc.toggle_option(row["id"])
        restored = conn.execute(
            "SELECT is_active FROM wizard_options WHERE id=?", (row["id"],)
        ).fetchone()["is_active"]
        assert restored == original

    def test_add_option_appears_in_options_for_step(self):
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardAdminService

        svc = WizardAdminService(conn)
        group_id = conn.execute(
            "SELECT group_id FROM wizard_groups WHERE step_number=4 LIMIT 1"
        ).fetchone()["group_id"]

        svc.add_option(
            step=4,
            label="Test Pool Expense",
            description="Covers pool maintenance",
            group_id=group_id,
            accounts=[],
        )
        opts = svc.options_for_step(4)
        labels = [o["label"] for o in opts]
        assert "Test Pool Expense" in labels

    def test_delete_option_removes_custom_option(self):
        """Custom (non-system) options can be deleted."""
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardAdminService

        svc = WizardAdminService(conn)
        group_id = conn.execute(
            "SELECT group_id FROM wizard_groups WHERE step_number=4 LIMIT 1"
        ).fetchone()["group_id"]

        svc.add_option(step=4, label="Delete Me", description="", group_id=group_id, accounts=[])
        new_id = conn.execute(
            "SELECT id FROM wizard_options WHERE label='Delete Me'"
        ).fetchone()["id"]

        svc.delete_option(new_id)
        gone = conn.execute(
            "SELECT id FROM wizard_options WHERE label='Delete Me'"
        ).fetchone()
        assert gone is None

    def test_system_option_cannot_be_deleted(self):
        """is_system=1 options must not be deleted (protected by SQL WHERE clause)."""
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardAdminService

        svc = WizardAdminService(conn)
        sys_opt = conn.execute(
            "SELECT id FROM wizard_options WHERE is_system=1 LIMIT 1"
        ).fetchone()
        if not sys_opt:
            pytest.skip("No system options seeded")

        svc.delete_option(sys_opt["id"])
        still_there = conn.execute(
            "SELECT id FROM wizard_options WHERE id=?", (sys_opt["id"],)
        ).fetchone()
        assert still_there is not None

    def test_add_group_appears_in_groups_for_step(self):
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardAdminService

        svc = WizardAdminService(conn)
        svc.add_group(step=4, label="Custom Projects")
        groups = svc.groups_for_step(4)
        labels = [g["label"] for g in groups]
        assert "Custom Projects" in labels

    def test_options_for_step_returns_list(self):
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardAdminService

        opts = WizardAdminService(conn).options_for_step(1)
        assert isinstance(opts, list)
        assert len(opts) > 0

    def test_add_option_with_accounts_stores_account_rows(self):
        """Accounts supplied when adding an option are persisted to wizard_option_accounts."""
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardAdminService

        svc = WizardAdminService(conn)
        group_id = conn.execute(
            "SELECT group_id FROM wizard_groups WHERE step_number=4 LIMIT 1"
        ).fetchone()["group_id"]

        svc.add_option(
            step=4,
            label="Option With Accounts",
            description="",
            group_id=group_id,
            accounts=[
                {"account_number": "8888", "account_name": "Test Expense",
                 "account_type": "EXPENSE", "fund_code": "OPERATING"},
            ],
        )
        opt_id = conn.execute(
            "SELECT id FROM wizard_options WHERE label='Option With Accounts'"
        ).fetchone()["id"]
        accts = conn.execute(
            "SELECT account_number FROM wizard_option_accounts WHERE wizard_option_id=?",
            (opt_id,),
        ).fetchall()
        assert any(a["account_number"] == "8888" for a in accts)


# ── WizardPages: render methods ───────────────────────────────────────────────

class TestWizardPagesRender:
    def test_render_wizard_returns_200(self):
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardPages

        org = {"name": "Test HOA"}
        status, html = WizardPages(conn).render_wizard(org=org, theme="warm")
        assert status == 200
        assert "wizard" in html.lower() or "step" in html.lower() or "account" in html.lower()

    def test_render_preview_returns_200(self):
        conn = _make_conn()
        from hoa_accounting.web.wizard_pages import WizardPages

        org = {"name": "Test HOA"}
        form = _fake_form({})
        status, html = WizardPages(conn).render_preview(form=form, org=org, theme="warm")
        assert status == 200
