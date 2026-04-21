"""Budget entry and management pages.

Routes handled:
  GET  /budgets                  — list all budgets
  GET  /budgets/new              — form to create a new budget
  POST /budgets/new              — create budget + save lines
  GET  /budgets/<id>/edit        — spreadsheet grid form for an existing budget
  POST /budgets/<id>/edit        — save (upsert) budget lines
  POST /budgets/<id>/approve     — DRAFT → APPROVED
  POST /budgets/<id>/archive     — APPROVED → ARCHIVED
  POST /budgets/<id>/delete      — delete DRAFT budget
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
from urllib.parse import quote

from hoa_accounting.repositories.budgets_repo import BudgetsRepository
from hoa_accounting.web.template_engine import render_template

_MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

_NO_GROUP_LABEL = "Other"


@dataclass(frozen=True)
class PageResponse:
    status_code: int
    body_html: str


class BudgetPages:
    """Page handlers for budget entry."""

    LIST_TEMPLATE = "budgets_list.html"
    FORM_TEMPLATE = "budget_form.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._repo = BudgetsRepository(conn)

    # ── List ──────────────────────────────────────────────────────────

    def render_list(
        self,
        *,
        org: dict,
        theme: str,
        flash_message: str = "",
    ) -> PageResponse:
        rows = self._repo.list_budgets()
        budgets = [
            {
                "id":          r["id"],
                "fiscal_year": r["fiscal_year"],
                "fund_code":   r["fund_code"],
                "status":      r["status"],
                "notes":       r["notes"] or "",
                "created_at":  r["created_at"],
            }
            for r in rows
        ]
        ctx = {
            "active_nav":  "master-data",
            "page_key":    "budgets",
            "breadcrumb":  "Master Data",
            "org":         org,
            "theme":       theme,
            "budgets":     budgets,
            "flash_message": flash_message,
        }
        return PageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.LIST_TEMPLATE, ctx),
        )

    # ── New budget form ───────────────────────────────────────────────

    def render_new_form(
        self,
        *,
        org: dict,
        theme: str,
        error: str = "",
        form_data: dict | None = None,
    ) -> PageResponse:
        fd = form_data or {}
        ctx = {
            "active_nav":  "master-data",
            "page_key":    "budgets",
            "breadcrumb":  "Master Data / Budgets",
            "org":         org,
            "theme":       theme,
            "error":       error,
            "fiscal_year": fd.get("fiscal_year", ""),
            "fund_code":   fd.get("fund_code", "OPERATING"),
            "notes":       fd.get("notes", ""),
        }
        return PageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template("budget_new.html", ctx),
        )

    def handle_new(
        self,
        *,
        form_data: dict,
        org: dict,
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        fiscal_year_raw = form_data.get("fiscal_year", "").strip()
        fund_code = form_data.get("fund_code", "OPERATING").strip()
        notes = form_data.get("notes", "").strip()

        try:
            fiscal_year = int(fiscal_year_raw)
        except ValueError:
            return None, self.render_new_form(
                org=org, theme=theme,
                error="Fiscal year must be a number.",
                form_data=form_data,
            )

        if fund_code not in ("OPERATING", "RESERVE", "SPECIAL"):
            return None, self.render_new_form(
                org=org, theme=theme,
                error="Invalid fund code.",
                form_data=form_data,
            )

        existing = self._repo.find_budget(fiscal_year, fund_code)
        if existing is not None:
            return None, self.render_new_form(
                org=org, theme=theme,
                error=f"A budget for {fiscal_year} {fund_code} already exists.",
                form_data=form_data,
            )

        try:
            budget_id = self._repo.insert_budget(
                fiscal_year=fiscal_year,
                fund_code=fund_code,
                notes=notes,
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return f"/budgets/{budget_id}/edit?msg=Budget+created.", None

    # ── Edit (grid) form ──────────────────────────────────────────────

    def render_edit_form(
        self,
        budget_id: int,
        *,
        org: dict,
        theme: str,
        flash_message: str = "",
        error: str = "",
        overrides: dict | None = None,
    ) -> PageResponse:
        budget = self._repo.get_budget(budget_id)
        if budget is None:
            return PageResponse(
                status_code=HTTPStatus.NOT_FOUND,
                body_html="<h1>Budget not found</h1>",
            )

        expense_categories = self._repo.list_expense_categories()
        saved_lines = self._repo.get_budget_lines(budget_id)

        # Build a lookup: (category_id, fiscal_period) → amount
        saved: dict[tuple[int, int], Decimal] = {}
        for line in saved_lines:
            key = (int(line["category_id"]), int(line["fiscal_period"]))
            saved[key] = Decimal(str(line["budget_amount"]))

        # Apply any form overrides (on validation error re-render)
        if overrides:
            for k, v in overrides.items():
                # k = "amt_{category_id}_{period}"
                parts = k.split("_")
                if len(parts) == 3:
                    try:
                        cid = int(parts[1])
                        period = int(parts[2])
                        saved[(cid, period)] = Decimal(v or "0")
                    except (ValueError, InvalidOperation):
                        pass

        # Group categories by group_name (preserving sort_order ordering)
        seen_groups: list[str | None] = []
        groups: dict[str | None, list] = {}
        for cat in expense_categories:
            gn = cat["group_name"]
            if gn not in groups:
                groups[gn] = []
                seen_groups.append(gn)
            groups[gn].append(cat)

        # Build rows for template
        category_rows = []
        for gn in seen_groups:
            cats = groups[gn]
            for cat in cats:
                cid = int(cat["id"])
                monthly = []
                row_total = Decimal("0.00")
                for p in range(1, 13):
                    amt = saved.get((cid, p), Decimal("0.00"))
                    row_total += amt
                    monthly.append({
                        "period":  p,
                        "field":   f"amt_{cid}_{p}",
                        "value":   "" if amt == Decimal("0.00") else str(amt),
                    })
                category_rows.append({
                    "category_id":    cid,
                    "category_name":  cat["name"],
                    "group_name":     gn,
                    "group_label":    gn or _NO_GROUP_LABEL,
                    "monthly":        monthly,
                    "row_total":      str(row_total) if row_total else "",
                })

        ctx = {
            "active_nav":     "master-data",
            "page_key":       "budgets",
            "breadcrumb":     "Master Data / Budgets",
            "org":            org,
            "theme":          theme,
            "budget":         dict(budget),
            "category_rows":  category_rows,
            "month_names":    _MONTH_NAMES,
            "flash_message":  flash_message,
            "error":          error,
            "is_approved":    budget["status"] == "APPROVED",
            "is_draft":       budget["status"] == "DRAFT",
        }
        return PageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.FORM_TEMPLATE, ctx),
        )

    def handle_save(
        self,
        budget_id: int,
        *,
        form_data: dict,
        org: dict,
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        budget = self._repo.get_budget(budget_id)
        if budget is None:
            return "/budgets?msg=Budget+not+found.", None

        notes = form_data.get("notes", "").strip()
        self._repo.update_budget_notes(budget_id, notes=notes)

        expense_categories = self._repo.list_expense_categories()
        category_ids = {int(c["id"]) for c in expense_categories}

        for key, val in form_data.items():
            if not key.startswith("amt_"):
                continue
            parts = key.split("_")
            if len(parts) != 3:
                continue
            try:
                cid = int(parts[1])
                period = int(parts[2])
                amount = Decimal(val.strip() or "0")
            except (ValueError, InvalidOperation):
                continue
            if cid not in category_ids:
                continue
            if period < 1 or period > 12:
                continue
            self._repo.upsert_budget_line(budget_id, cid, period, amount)

        try:
            self._repo.delete_zero_lines(budget_id)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        msg = quote("Budget saved.")
        return f"/budgets/{budget_id}/edit?msg={msg}", None

    # ── Status transitions ────────────────────────────────────────────

    def handle_approve(
        self,
        budget_id: int,
        *,
        org: dict,
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        budget = self._repo.get_budget(budget_id)
        if budget is None:
            return "/budgets?msg=Budget+not+found.", None
        if budget["status"] != "DRAFT":
            return f"/budgets/{budget_id}/edit?msg=Already+approved.", None
        try:
            self._repo.set_status(budget_id, "APPROVED")
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return f"/budgets/{budget_id}/edit?msg=Budget+approved.", None

    def handle_archive(
        self,
        budget_id: int,
        *,
        org: dict,
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        budget = self._repo.get_budget(budget_id)
        if budget is None:
            return "/budgets?msg=Budget+not+found.", None
        try:
            self._repo.set_status(budget_id, "ARCHIVED")
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return f"/budgets/{budget_id}/edit?msg=Budget+archived.", None

    def handle_delete(
        self,
        budget_id: int,
        *,
        org: dict,
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        budget = self._repo.get_budget(budget_id)
        if budget is None:
            return "/budgets?msg=Budget+not+found.", None
        if budget["status"] != "DRAFT":
            return f"/budgets/{budget_id}/edit?msg=Only+DRAFT+budgets+can+be+deleted.", None
        try:
            self._repo.delete_budget(budget_id)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return "/budgets?msg=Budget+deleted.", None
