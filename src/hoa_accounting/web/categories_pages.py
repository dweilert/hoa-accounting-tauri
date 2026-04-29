"""Categories management pages.

Routes handled:
  GET  /categories                — list grouped by type
  GET  /categories/add            — blank add form
  POST /categories/add            — submit new category
  GET  /categories/<id>/edit      — edit form pre-filled
  POST /categories/<id>/edit      — submit edits
  POST /categories/<id>/delete    — hard-delete; only allowed when unused
  GET  /categories/<id>/ledger    — all transactions for a category
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from dataclasses import dataclass
from http import HTTPStatus

from hoa_accounting.repositories.categories_repo import CategoriesRepository
from hoa_accounting.validators.format import format_currency
from hoa_accounting.web.template_engine import render_template
from hoa_accounting.validators.forms import opt as _opt, require as _req

_FUND_CODES = ["OPERATING", "RESERVE", "SPECIAL"]
_CATEGORY_TYPES = ["INCOME", "EXPENSE", "TRANSFER"]

_BASE_CTX = {
    "active_nav": "master-data",
    "page_key": "categories",
    "breadcrumb": "Manage",
}


@dataclass(frozen=True)
class CategoriesPageResponse:
    status_code: int
    body_html: str


class CategoriesPages:

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.repo = CategoriesRepository(conn)

    # ── List ──────────────────────────────────────────────────────────────

    def render_list(
        self,
        *,
        org: dict,
        theme: str,
        flash_message: str = "",
    ) -> CategoriesPageResponse:
        rows = self.repo.list_categories(active_only=False)
        categories = []
        for r in rows:
            d = dict(r)
            breakdown = self.repo.usage_breakdown(int(d["id"]))
            d["transactions_count"] = breakdown["transactions"]
            d["other_count"]        = breakdown["other"]
            d["usage_count"]        = breakdown["total"]
            categories.append(d)
        ctx = {
            **_BASE_CTX,
            "heading": "Maintain Categories",
            "org": org,
            "theme": theme,
            "categories": categories,
            "flash_message": flash_message,
        }
        return CategoriesPageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template("categories_list.html", ctx),
        )

    # ── Add form (GET) ────────────────────────────────────────────────────

    def render_add_form(
        self,
        *,
        org: dict,
        theme: str,
        form_values: dict | None = None,
        error_message: str = "",
    ) -> CategoriesPageResponse:
        ctx = {
            **_BASE_CTX,
            "heading": "Add Category",
            "breadcrumb": "Manage · Categories",
            "org": org,
            "theme": theme,
            "is_edit": False,
            "category_id": None,
            "fund_codes": _FUND_CODES,
            "category_types": _CATEGORY_TYPES,
            "values": form_values or {
                "code": "",
                "name": "",
                "category_type": "EXPENSE",
                "fund_code": "OPERATING",
                "sort_order": "100",
                "group_name": "",
                "description": "",
                "active_flag": "1",
            },
            "error_message": error_message,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return CategoriesPageResponse(
            status_code=status,
            body_html=render_template("category_edit.html", ctx),
        )

    # ── Add (POST) ────────────────────────────────────────────────────────

    def handle_add(self, form: dict, *, org: dict, theme: str) -> CategoriesPageResponse:
        from flask import redirect
        try:
            code = _req(form.get("code"), "Code").upper()
            name = _req(form.get("name"), "Name")
            category_type = _req(form.get("category_type"), "Category Type")
            if category_type not in _CATEGORY_TYPES:
                raise ValueError("Invalid category type.")
            fund_code = form.get("fund_code", "OPERATING")
            if fund_code not in _FUND_CODES:
                raise ValueError("Invalid fund code.")
            sort_order = int(form.get("sort_order") or 100)
            group_name = _opt(form.get("group_name"))
            description = _opt(form.get("description"))
            self.repo.insert_category(
                code=code,
                name=name,
                category_type=category_type,
                fund_code=fund_code,
                sort_order=sort_order,
                group_name=group_name,
                description=description,
            )
        except Exception as exc:
            return self.render_add_form(
                org=org,
                theme=theme,
                form_values=form,
                error_message=str(exc),
            )
        from flask import redirect as _redir
        resp = _redir("/categories?flash=Category+added.")
        return CategoriesPageResponse(
            status_code=resp.status_code,
            body_html=resp.get_data(as_text=True),
        )

    # ── Edit form (GET) ───────────────────────────────────────────────────

    def render_edit_form(
        self,
        category_id: int,
        *,
        org: dict,
        theme: str,
        form_values: dict | None = None,
        error_message: str = "",
    ) -> CategoriesPageResponse:
        row = self.repo.get_category(category_id)
        if row is None:
            return CategoriesPageResponse(
                status_code=HTTPStatus.NOT_FOUND,
                body_html="<h1>Category not found</h1>",
            )
        values = form_values or {
            "code": row["code"],
            "name": row["name"],
            "category_type": row["category_type"],
            "fund_code": row["fund_code"],
            "sort_order": str(row["sort_order"]),
            "group_name": row["group_name"] or "",
            "description": row["description"] or "",
            "active_flag": str(row["active_flag"]),
        }
        ctx = {
            **_BASE_CTX,
            "heading": f"Edit: {row['name']}",
            "breadcrumb": "Manage · Categories",
            "org": org,
            "theme": theme,
            "is_edit": True,
            "category_id": category_id,
            "fund_codes": _FUND_CODES,
            "category_types": _CATEGORY_TYPES,
            "values": values,
            "error_message": error_message,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return CategoriesPageResponse(
            status_code=status,
            body_html=render_template("category_edit.html", ctx),
        )

    # ── Edit (POST) ───────────────────────────────────────────────────────

    def handle_edit(
        self, category_id: int, form: dict, *, org: dict, theme: str
    ) -> CategoriesPageResponse:
        try:
            name = _req(form.get("name"), "Name")
            fund_code = form.get("fund_code", "OPERATING")
            if fund_code not in _FUND_CODES:
                raise ValueError("Invalid fund code.")
            sort_order = int(form.get("sort_order") or 100)
            group_name = _opt(form.get("group_name"))
            description = _opt(form.get("description"))
            active_flag = 1 if form.get("active_flag", "1") == "1" else 0
            self.repo.update_category(
                category_id,
                name=name,
                group_name=group_name,
                description=description,
                fund_code=fund_code,
                sort_order=sort_order,
                active_flag=active_flag,
            )
        except Exception as exc:
            return self.render_edit_form(
                category_id,
                org=org,
                theme=theme,
                form_values=form,
                error_message=str(exc),
            )
        from flask import redirect as _redir
        resp = _redir("/categories?flash=Category+saved.")
        return CategoriesPageResponse(
            status_code=resp.status_code,
            body_html=resp.get_data(as_text=True),
        )

    # ── Delete (POST) ─────────────────────────────────────────────────────

    def handle_delete(self, category_id: int) -> str:
        """Attempt to delete a category. Returns a redirect URL with a flash
        message — category not found, in-use rejection, or success.
        """
        row = self.repo.get_category(category_id)
        if row is None:
            return "/categories?flash=Category+not+found."
        count = self.repo.usage_count(category_id)
        if count > 0:
            return (
                f"/categories?flash=Cannot+delete+{row['name']}"
                f"+%E2%80%94+{count}+records+reference+it."
            )
        self.repo.delete_category(category_id)
        return f"/categories?flash=Category+{row['name']}+deleted."

    # ── Ledger (GET) ──────────────────────────────────────────────────────

    def render_ledger(
        self, category_id: int, *, org: dict, theme: str
    ) -> CategoriesPageResponse:
        row = self.repo.get_category(category_id)
        if row is None:
            return CategoriesPageResponse(
                status_code=HTTPStatus.NOT_FOUND,
                body_html="<h1>Category not found</h1>",
            )
        txns = [dict(r) for r in self.repo.ledger_for_category(category_id)]
        # Sum as Decimal — float accumulation across dozens of transactions
        # compounds rounding error and the displayed total ends up off by
        # a cent from the visible per-row sum.
        total = sum(
            (Decimal(str(t["amount"] or "0")) for t in txns),
            Decimal("0.00"),
        )
        ctx = {
            **_BASE_CTX,
            "heading": f"Ledger: {row['name']}",
            "breadcrumb": "Manage · Categories",
            "org": org,
            "theme": theme,
            "category": dict(row),
            "category_id": category_id,
            "transactions": txns,
            "total": format_currency(total),
        }
        return CategoriesPageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template("category_ledger.html", ctx),
        )
