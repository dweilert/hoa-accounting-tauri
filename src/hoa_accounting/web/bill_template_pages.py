"""Bill template CRUD pages — list, new, edit."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from http import HTTPStatus

from hoa_accounting.exceptions import ValidationError
from hoa_accounting.models.enums import FundCode
from hoa_accounting.repositories.accounts_repo import AccountsRepository
from hoa_accounting.repositories.vendors_repo import VendorsRepository
from hoa_accounting.web.template_engine import render_template


@dataclass(frozen=True)
class BillTemplatePageResponse:
    status_code: int
    body_html: str


_FUND_CODES = [fc.value for fc in FundCode]
_CLASSIFICATIONS = ["OPERATING", "IMPROVEMENT"]


def _require(raw: str, label: str) -> str:
    v = (raw or "").strip()
    if not v:
        raise ValidationError(f"{label} is required.")
    return v


def _parse_int(raw: str, label: str) -> int:
    try:
        return int((raw or "").strip())
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} is required.") from exc


class BillTemplatePages:
    LIST_TEMPLATE = "bill_templates_list.html"
    FORM_TEMPLATE = "bill_template_form.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ── helpers ───────────────────────────────────────────────────────

    def _load_vendors(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, vendor_name AS name FROM vendors WHERE active_flag=1 ORDER BY vendor_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def _load_expense_accounts(self) -> list[dict]:
        rows = AccountsRepository(self.conn).list_accounts_by_type(account_type_code="EXPENSE")
        return [{"id": r["id"], "label": f"{r['account_number']} – {r['account_name']}"} for r in rows]

    def _load_payable_accounts(self) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT a.id, a.account_number, a.account_name
            FROM accounts a
            JOIN account_types at ON at.id = a.account_type_id
            WHERE a.is_active = 1 AND at.code = 'LIABILITY'
            ORDER BY a.account_number
            """
        ).fetchall()
        return [{"id": r["id"], "label": f"{r['account_number']} – {r['account_name']}"} for r in rows]

    def _base_ctx(self, org: dict, theme: str) -> dict:
        return {
            "org": org,
            "theme": theme,
            "active_nav": "master-data",
            "page_key": "bill-templates",
            "breadcrumb": "Master Data",
            "vendors": self._load_vendors(),
            "expense_accounts": self._load_expense_accounts(),
            "payable_accounts": self._load_payable_accounts(),
            "fund_codes": _FUND_CODES,
            "classifications": _CLASSIFICATIONS,
        }

    # ── list ──────────────────────────────────────────────────────────

    def render_list(self, *, org: dict, theme: str, flash: str | None = None) -> BillTemplatePageResponse:
        rows = self.conn.execute(
            """
            SELECT bt.id, bt.template_name, bt.vendor_id, bt.expense_account_id,
                   bt.payable_account_id, bt.fund_code, bt.expense_classification,
                   bt.default_amount, bt.description, bt.active_flag,
                   v.vendor_name,
                   a.account_number || ' – ' || a.account_name AS expense_account_label
            FROM bill_templates bt
            JOIN vendors v ON v.id = bt.vendor_id
            JOIN accounts a ON a.id = bt.expense_account_id
            ORDER BY bt.active_flag DESC, bt.template_name
            """
        ).fetchall()
        templates = [dict(r) for r in rows]
        html = render_template(self.LIST_TEMPLATE, {
            **self._base_ctx(org, theme),
            "templates": templates,
            "flash": flash,
        })
        return BillTemplatePageResponse(HTTPStatus.OK, html)

    # ── new ───────────────────────────────────────────────────────────

    def render_new_form(self, *, org: dict, theme: str, values: dict | None = None,
                        error_message: str | None = None) -> BillTemplatePageResponse:
        defaults = {"fund_code": "OPERATING", "expense_classification": "OPERATING", "active_flag": True}
        html = render_template(self.FORM_TEMPLATE, {
            **self._base_ctx(org, theme),
            "template": None,
            "values": values or defaults,
            "error_message": error_message,
        })
        return BillTemplatePageResponse(HTTPStatus.OK, html)

    def handle_new(self, form_data: dict, *, org: dict, theme: str) -> tuple[str | None, BillTemplatePageResponse | None]:
        try:
            name = _require(form_data.get("template_name", ""), "Template Name")
            vendor_id = _parse_int(form_data.get("vendor_id", ""), "Vendor")
            expense_account_id = _parse_int(form_data.get("expense_account_id", ""), "Expense Account")
            payable_account_id = _parse_int(form_data.get("payable_account_id", ""), "Payable Account")
            fund_code = _require(form_data.get("fund_code", ""), "Fund")
            classification = _require(form_data.get("expense_classification", ""), "Classification")
            raw_amount = (form_data.get("default_amount") or "").strip()
            default_amount: str | None = None
            if raw_amount and raw_amount != "0.00":
                try:
                    default_amount = str(Decimal(raw_amount))
                except InvalidOperation:
                    raise ValidationError("Default Amount must be a number.")
            description = (form_data.get("description") or "").strip() or None

            self.conn.execute(
                """
                INSERT INTO bill_templates
                    (template_name, vendor_id, expense_account_id, payable_account_id,
                     fund_code, expense_classification, default_amount, description, active_flag)
                VALUES (?,?,?,?,?,?,?,?,1)
                """,
                (name, vendor_id, expense_account_id, payable_account_id,
                 fund_code, classification, default_amount, description),
            )
            self.conn.commit()
            return "/bill-templates?msg=Template+saved", None
        except ValidationError as exc:
            resp = self.render_new_form(org=org, theme=theme,
                                        values=form_data, error_message=str(exc))
            return None, BillTemplatePageResponse(HTTPStatus.UNPROCESSABLE_ENTITY, resp.body_html)

    # ── edit ──────────────────────────────────────────────────────────

    def render_edit_form(self, template_id: int, *, org: dict, theme: str,
                         values: dict | None = None, error_message: str | None = None) -> BillTemplatePageResponse:
        row = self.conn.execute(
            "SELECT * FROM bill_templates WHERE id=?", (template_id,)
        ).fetchone()
        if row is None:
            return BillTemplatePageResponse(HTTPStatus.NOT_FOUND, "<h1>Template not found</h1>")
        tmpl = dict(row)
        use_values = values or {**tmpl, "active_flag": bool(tmpl["active_flag"])}
        html = render_template(self.FORM_TEMPLATE, {
            **self._base_ctx(org, theme),
            "template": tmpl,
            "values": use_values,
            "error_message": error_message,
        })
        return BillTemplatePageResponse(HTTPStatus.OK, html)

    def handle_edit(self, template_id: int, form_data: dict, *, org: dict, theme: str) -> tuple[str | None, BillTemplatePageResponse | None]:
        try:
            name = _require(form_data.get("template_name", ""), "Template Name")
            vendor_id = _parse_int(form_data.get("vendor_id", ""), "Vendor")
            expense_account_id = _parse_int(form_data.get("expense_account_id", ""), "Expense Account")
            payable_account_id = _parse_int(form_data.get("payable_account_id", ""), "Payable Account")
            fund_code = _require(form_data.get("fund_code", ""), "Fund")
            classification = _require(form_data.get("expense_classification", ""), "Classification")
            raw_amount = (form_data.get("default_amount") or "").strip()
            default_amount: str | None = None
            if raw_amount and raw_amount != "0.00":
                try:
                    default_amount = str(Decimal(raw_amount))
                except InvalidOperation:
                    raise ValidationError("Default Amount must be a number.")
            description = (form_data.get("description") or "").strip() or None
            active_flag = 1 if form_data.get("active_flag") else 0

            self.conn.execute(
                """
                UPDATE bill_templates SET
                    template_name=?, vendor_id=?, expense_account_id=?, payable_account_id=?,
                    fund_code=?, expense_classification=?, default_amount=?, description=?,
                    active_flag=?, updated_at=datetime('now')
                WHERE id=?
                """,
                (name, vendor_id, expense_account_id, payable_account_id,
                 fund_code, classification, default_amount, description, active_flag, template_id),
            )
            self.conn.commit()
            return f"/bill-templates?msg=Template+updated", None
        except ValidationError as exc:
            resp = self.render_edit_form(template_id, org=org, theme=theme,
                                         values=form_data, error_message=str(exc))
            return None, BillTemplatePageResponse(HTTPStatus.UNPROCESSABLE_ENTITY, resp.body_html)
