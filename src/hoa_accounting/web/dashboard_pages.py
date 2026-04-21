"""Dashboard and System Settings page services."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from hoa_accounting.repositories.dashboard_repo import DashboardRepository
from hoa_accounting.web.template_engine import render_template

CARD_COLORS = [
    ("#2f6046", "Green"),
    ("#1f4d7a", "Blue"),
    ("#c26000", "Orange"),
    ("#0f7173", "Teal"),
    ("#5a3a7a", "Purple"),
    ("#4a5462", "Slate"),
    ("#9a3a38", "Red"),
    ("#7a5312", "Gold"),
    ("#9a3060", "Rose"),
    ("#2a6099", "Steel Blue"),
    ("#3d7a5a", "Sage"),
    ("#7a2a2a", "Maroon"),
]

REPORT_CHOICES = [
    ("ytd-expense-summary",   "Expense Summary"),
    ("income-by-date",        "Income Summary"),
    ("expenses-by-date",      "Expenses by Date"),
    ("vendor-expenses",       "Vendor Payment History"),
    ("expenses-vs-budget",    "Budget vs Actual"),
    ("ar-aging",              "AR Aging"),
    ("owner-ledger",          "Owner Ledger"),
    ("homeowner-contact-list","Homeowner Contact List"),
]


@dataclass(frozen=True)
class PageResponse:
    status_code: int
    body_html: str


class DashboardPages:
    def __init__(self, conn: sqlite3.Connection, fiscal_year: int, fy_start_month: int = 1) -> None:
        self._conn = conn
        self._repo = DashboardRepository(conn)
        self._fiscal_year = fiscal_year
        self._fy_start_month = fy_start_month

    def _render(self, template: str, **ctx) -> PageResponse:
        return PageResponse(200, render_template(template, ctx))

    # ── Dashboard home ─────────────────────────────────────────────────

    def render_dashboard(self, org: dict, theme: str, setup_complete: bool = False) -> PageResponse:
        profile = self._repo.get_hoa_profile()
        bank_tiles = self._repo.get_bank_tiles()
        last_recon = self._repo.get_last_reconciliation()
        budget_tile = self._repo.get_budget_tile(self._fiscal_year, self._fy_start_month)
        budget_cat_tile = self._repo.get_budget_category_tile(self._fiscal_year, self._fy_start_month)
        last_auto_backup = self._repo.get_last_auto_backup()
        cards = self._repo.get_dashboard_cards()
        nudges = self._repo.get_next_action_nudges()

        hoa_name = (profile["legal_name"] if profile else org.get("legal_name", org.get("name", "")))

        return self._render(
            "home.html",
            org=org, theme=theme,
            active_nav="home",
            heading="Dashboard",
            hoa_name=hoa_name,
            bank_tiles=bank_tiles,
            last_recon=last_recon,
            budget_tile=budget_tile,
            budget_cat_tile=budget_cat_tile,
            last_auto_backup=last_auto_backup,
            cards=cards,
            nudges=nudges,
            fiscal_year=self._fiscal_year,
            setup_complete=setup_complete,
        )

    # ── System Settings ────────────────────────────────────────────────

    def render_settings(self, org: dict, theme: str,
                        flash: str | None = None,
                        error: str | None = None) -> PageResponse:
        profile = self._repo.get_hoa_profile()
        return self._render(
            "system_settings.html",
            org=org, theme=theme,
            page_key="system-settings",
            heading="System Settings",
            profile=profile,
            flash=flash,
            error=error,
        )

    _VALID_THEMES = {"warm", "slate", "sage", "ocean", "sand", "dusk"}

    def handle_save_settings(self, form: dict, org: dict, theme: str) -> tuple[str | None, PageResponse | None]:
        legal_name = form.get("legal_name", "").strip()
        display_name = form.get("display_name", "").strip()
        new_theme = form.get("theme", theme).strip()
        if new_theme not in self._VALID_THEMES:
            new_theme = theme
        if not legal_name:
            return None, self.render_settings(org, new_theme, error="Full HOA name is required.")
        if not display_name:
            return None, self.render_settings(org, new_theme, error="Abbreviated name is required.")
        raw_dues = form.get("default_assessment_amount", "0.00").strip() or "0.00"
        try:
            from decimal import Decimal, InvalidOperation
            new_dues = str(Decimal(raw_dues).quantize(Decimal("0.01")))
        except (ValueError, InvalidOperation):
            new_dues = "0.00"
        new_freq = form.get("default_billing_frequency", "annual")
        self._repo.save_hoa_profile(legal_name, display_name, theme=new_theme, default_assessment_amount=new_dues, default_billing_frequency=new_freq)
        org["theme"] = new_theme
        org["default_assessment_amount"] = new_dues
        org["default_billing_frequency"] = new_freq
        return "/system-settings?msg=Settings+saved.", None

    # ── Card Catalog ───────────────────────────────────────────────────

    def render_card_catalog(self, org: dict, theme: str,
                             flash: str | None = None,
                             error: str | None = None) -> PageResponse:
        cards = self._repo.get_all_catalog_cards()
        layout_cards = self._repo.get_dashboard_cards()
        alert_settings = self._repo.get_alert_settings_list()
        card_types = [
            ("NAV",       "Navigation link"),
            ("REPORT",    "Report"),
            ("COMMENT",   "Comment / note"),
            ("SECTION",   "Section header / divider"),
            ("FINANCIAL", "Financial summary tile"),
        ]
        return self._render(
            "dashboard_config.html",
            org=org, theme=theme,
            page_key="dashboard-config",
            heading="Dashboard Configuration",
            cards=cards,
            layout_cards=layout_cards,
            alert_settings=alert_settings,
            colors=CARD_COLORS,
            card_types=card_types,
            report_choices=REPORT_CHOICES,
            flash=flash,
            error=error,
        )

    def handle_save_card(self, form: dict, org: dict, theme: str) -> tuple[str | None, PageResponse | None]:
        title = form.get("title", "").strip()
        if not title:
            return None, self.render_card_catalog(org, theme, error="Title is required.")
        card_id_raw = form.get("card_id", "").strip()
        card_id = int(card_id_raw) if card_id_raw else None
        new_id = self._repo.upsert_card(
            card_id=card_id,
            title=title,
            description=form.get("description", "").strip(),
            card_type=form.get("card_type", "NAV"),
            target_url=form.get("target_url", "").strip(),
            report_name=form.get("report_name", "").strip(),
            color=form.get("color", "#4a5462"),
        )
        self._conn.commit()
        # When auto_add_to_layout=1, also append the new card to the submitted layout order.
        # This lets the section-bar quick-add create+place the card without losing unsaved reordering.
        if form.get("auto_add_to_layout") == "1" and not card_id:
            raw = form.get("current_layout", "")
            ids = [int(x) for x in raw.split(",") if x.strip().isdigit()]
            if new_id not in ids:
                ids.append(new_id)
            self._repo.save_layout(ids)
            return "/dashboard-config?msg=Section+bar+added.", None
        return "/dashboard-config?msg=Card+saved.", None

    def handle_delete_card(self, card_id: int, org: dict, theme: str) -> tuple[str | None, PageResponse | None]:
        self._repo.delete_card(card_id)
        self._conn.commit()
        return "/dashboard-config?msg=Card+deleted.", None

    def handle_save_layout(self, form: dict) -> str:
        raw = form.get("layout_order", "")
        card_ids = [int(x) for x in raw.split(",") if x.strip().isdigit()]
        self._repo.save_layout(card_ids)
        return "/dashboard-config?msg=Layout+saved."

    def handle_reset_layout(self) -> str:
        self._repo.reset_layout()
        return "/dashboard-config?msg=Layout+reset+to+default."
