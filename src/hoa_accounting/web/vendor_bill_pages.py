"""Vendor-bill list page + new-bill form page."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import date as _date
from decimal import Decimal, InvalidOperation
from http import HTTPStatus

from hoa_accounting.exceptions import AccountingError, NotFoundError, ValidationError
from hoa_accounting.models.enums import FundCode
from hoa_accounting.repositories.bank_accounts_repo import BankAccountsRepository
from hoa_accounting.repositories.categories_repo import CategoriesRepository
from hoa_accounting.repositories.vendors_repo import VendorsRepository
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.web.template_engine import render_template


@dataclass(frozen=True)
class VendorBillFormResponse:
    """Render of the form page."""

    status_code: int
    body_html: str


_FUND_CODES = [fc.value for fc in FundCode]


def _today() -> str:
    return _date.today().isoformat()


def _parse_positive_decimal(raw: str, label: str) -> Decimal:
    try:
        value = Decimal((raw or "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"{label} must be a number.") from exc
    if value <= Decimal("0"):
        raise ValidationError(f"{label} must be greater than zero.")
    return value


def _parse_int(raw: str, label: str) -> int:
    try:
        return int((raw or "").strip())
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} is required.") from exc


def _require(raw: str, label: str) -> str:
    value = (raw or "").strip()
    if not value:
        raise ValidationError(f"{label} is required.")
    return value


class VendorBillPages:
    """Render and submit the vendor-bill UI pages."""

    LIST_TEMPLATE = "vendor_bills_list.html"
    FORM_TEMPLATE = "vendor_bill_form.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.factory = ServiceFactory(conn)

    # ── List page ────────────────────────────────────────────────

    def render_list(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        created_entry_number: str | None = None,
    ) -> VendorBillFormResponse:
        repo = VendorsRepository(self.conn)
        rows = repo.list_vendor_bills()
        paid_ids = {
            int(r["vendor_bill_id"])
            for r in self.conn.execute(
                "SELECT DISTINCT vendor_bill_id FROM bill_payments"
            ).fetchall()
        }
        bills = [
            {
                "id": r["id"],
                "invoice_number": r["invoice_number"],
                "invoice_date": r["invoice_date"],
                "due_date": r["due_date"] or "",
                "amount": f"{Decimal(str(r['amount'])):.2f}",
                "fund_code": r["fund_code"],
                "status": r["status"],
                "vendor_name": r["vendor_name"],
                # Need vendor_id + category_id for the inline edit form defaults.
                "vendor_id": r["vendor_id"] if "vendor_id" in r.keys() else None,
                "category_id": r["category_id"] if "category_id" in r.keys() else None,
                "description": r["description"] or "",
                "entry_number": r["entry_number"] or "",
                "has_payment": int(r["id"]) in paid_ids,
            }
            for r in rows
        ]
        expense_categories = [
            {"id": c["id"], "label": c["name"], "fund_code": c["fund_code"]}
            for c in CategoriesRepository(self.conn).list_categories(
                category_type="EXPENSE"
            )
        ]
        ctx = {
            "heading": "Vendor Bills",
            "description": (
                "Click a column header to sort, type in the filter box to "
                "narrow the list, click Edit to fix any field inline."
            ),
            "bills": bills,
            "org": org or {},
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "vendor-bills",
            "breadcrumb": "Transactions",
            "created_entry_number": created_entry_number,
            "expense_categories": expense_categories,
            "fund_codes": _FUND_CODES,
        }
        return VendorBillFormResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.LIST_TEMPLATE, ctx),
        )

    # ── Form page (GET) ─────────────────────────────────────────

    def render_form(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        form_values: dict[str, str] | None = None,
        error_message: str = "",
    ) -> VendorBillFormResponse:
        values = form_values or {}
        vendors = [
            {"id": r["id"], "name": r["vendor_name"]}
            for r in VendorsRepository(self.conn).list_vendors()
        ]
        expense_categories = [
            {
                "id": r["id"],
                "label": r["name"],
                "fund_code": r["fund_code"],
            }
            for r in CategoriesRepository(self.conn).list_categories(
                category_type="EXPENSE"
            )
        ]
        bank_accounts = [
            {"id": r["id"],
             "label": f"{r['account_name']} (···{r['account_last4'] or '????'})"}
            for r in BankAccountsRepository(self.conn).list_bank_accounts()
            if r["active_flag"]
        ]

        # Treasurers typically enter a bill at the moment they pay it, so
        # "mark as paid now" is on by default on a fresh form. If the user
        # submitted and we're re-rendering with an error, keep their choice.
        mark_paid_raw = values.get("mark_paid")
        if mark_paid_raw is None:
            mark_paid_checked = True
        else:
            mark_paid_checked = mark_paid_raw in ("1", "on", "true", True)

        ctx = {
            "heading": "New Vendor Bill",
            "org": org or {},
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "vendor-bills",
            "breadcrumb": "Transactions · Vendor Bills",
            "vendors": vendors,
            "expense_categories": expense_categories,
            "fund_codes": _FUND_CODES,
            "bank_accounts": bank_accounts,
            "values": {
                "vendor_id": values.get("vendor_id", ""),
                "invoice_number": values.get("invoice_number", ""),
                "invoice_date": values.get("invoice_date", _today()),
                "due_date": values.get("due_date", ""),
                "entry_date": values.get("entry_date", _today()),
                "amount": values.get("amount", ""),
                "category_id": values.get("category_id", ""),
                "fund_code": values.get("fund_code", "OPERATING"),
                "description": values.get("description", ""),
                "mark_paid": mark_paid_checked,
                "bank_account_id": values.get("bank_account_id", ""),
                "check_number": values.get("check_number", ""),
                "payment_date": values.get("payment_date", ""),
            },
            "error_message": error_message,
            "templates": self._load_bill_templates(),
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return VendorBillFormResponse(
            status_code=status,
            body_html=render_template(self.FORM_TEMPLATE, ctx),
        )

    def _load_bill_templates(self) -> list[dict]:
        try:
            rows = self.conn.execute(
                """
                SELECT id, template_name, vendor_id, expense_account_id,
                       payable_account_id, fund_code, expense_classification,
                       default_amount, description
                FROM bill_templates
                WHERE active_flag = 1
                ORDER BY template_name
                """
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    # ── Edit form (GET) ─────────────────────────────────────────

    EDIT_TEMPLATE = "vendor_bill_edit.html"

    def render_edit(
        self,
        vendor_bill_id: int,
        *,
        org: dict[str, object] | None,
        theme: str,
        form_values: dict[str, str] | None = None,
        error_message: str = "",
    ) -> VendorBillFormResponse:
        repo = VendorsRepository(self.conn)
        bill = repo.get_vendor_bill(vendor_bill_id)
        if bill is None:
            return VendorBillFormResponse(
                status_code=HTTPStatus.NOT_FOUND,
                body_html=render_template("error.html", {
                    "org": org or {}, "theme": theme,
                    "heading": "Not Found",
                    "message": f"Vendor bill #{vendor_bill_id} not found.",
                    "page_key": "vendor-bills",
                }),
            )
        has_payment = repo.vendor_bill_has_payments(vendor_bill_id)

        defaults = {
            "invoice_number": bill["invoice_number"],
            "invoice_date":   bill["invoice_date"],
            "due_date":       bill["due_date"] or "",
            "amount":         f"{Decimal(str(bill['amount'])):.2f}",
            "fund_code":      bill["fund_code"],
            "category_id":    str(bill["category_id"] or ""),
            "description":    bill["description"] or "",
        }
        values = dict(defaults)
        if form_values:
            values.update({k: v for k, v in form_values.items() if v is not None})

        expense_categories = [
            {"id": r["id"], "label": r["name"], "fund_code": r["fund_code"]}
            for r in CategoriesRepository(self.conn).list_categories(
                category_type="EXPENSE"
            )
        ]
        ctx = {
            "heading": f"Edit Bill · {bill['vendor_name']} · {bill['invoice_number']}",
            "org": org or {},
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "vendor-bills",
            "breadcrumb": "Transactions · Vendor Bills",
            "bill": dict(bill),
            "has_payment": has_payment,
            "expense_categories": expense_categories,
            "fund_codes": _FUND_CODES,
            "values": values,
            "error_message": error_message,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return VendorBillFormResponse(
            status_code=status,
            body_html=render_template(self.EDIT_TEMPLATE, ctx),
        )

    # ── Edit submit (POST) ──────────────────────────────────────

    def handle_edit(
        self,
        vendor_bill_id: int,
        *,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, VendorBillFormResponse | None]:
        repo = VendorsRepository(self.conn)
        bill = repo.get_vendor_bill(vendor_bill_id)
        if bill is None:
            return ("/vendor-bills", None)
        has_payment = repo.vendor_bill_has_payments(vendor_bill_id)
        try:
            invoice_number = _require(form_data.get("invoice_number", ""), "Invoice number")
            invoice_date = _require(form_data.get("invoice_date", ""), "Invoice date")
            fund_code = _require(form_data.get("fund_code", ""), "Fund")
            description = (form_data.get("description", "") or "").strip()
            due_date_raw = (form_data.get("due_date", "") or "").strip()
            due_date = due_date_raw or None
            category_id = _parse_int(form_data.get("category_id", ""), "Expense category")

            if has_payment:
                amount_to_write: str | None = None
            else:
                amount_dec = _parse_positive_decimal(form_data.get("amount", ""), "Amount")
                amount_to_write = str(amount_dec)

            repo.update_vendor_bill(
                vendor_bill_id,
                invoice_number=invoice_number,
                invoice_date=invoice_date,
                due_date=due_date,
                amount=amount_to_write,
                fund_code=fund_code,
                description=description,
                category_id=category_id,
            )
        except (ValidationError, NotFoundError, AccountingError) as exc:
            resp = self.render_edit(
                vendor_bill_id,
                org=org, theme=theme,
                form_values=form_data,
                error_message=str(exc),
            )
            return (None, resp)
        except sqlite3.IntegrityError as exc:
            message = "This invoice number already exists for this vendor."
            if "invoice" not in str(exc).lower():
                message = f"Database error: {exc}"
            resp = self.render_edit(
                vendor_bill_id,
                org=org, theme=theme,
                form_values=form_data,
                error_message=message,
            )
            return (None, resp)

        return ("/vendor-bills?saved=1", None)

    # ── Form submit (POST) ──────────────────────────────────────

    def handle_post(
        self,
        *,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, VendorBillFormResponse | None]:
        try:
            invoice_number = _require(form_data.get("invoice_number", ""), "Invoice number")
            invoice_date = _require(form_data.get("invoice_date", ""), "Invoice date")
            entry_date = _require(form_data.get("entry_date", ""), "Entry date")
            amount = _parse_positive_decimal(form_data.get("amount", ""), "Amount")
            vendor_id = _parse_int(form_data.get("vendor_id", ""), "Vendor")
            category_id = _parse_int(form_data.get("category_id", ""), "Expense category")
            fund_code = _require(form_data.get("fund_code", ""), "Fund")
            description = (form_data.get("description", "") or "").strip()
            due_date_raw = (form_data.get("due_date", "") or "").strip()
            due_date = due_date_raw or None

            mark_paid = (form_data.get("mark_paid") or "").strip() in ("1", "on", "true")
            if mark_paid:
                bank_account_id = _parse_int(
                    form_data.get("bank_account_id", ""), "Bank account"
                )
                payment_date_raw = (form_data.get("payment_date") or "").strip()
                payment_date = payment_date_raw or entry_date
                check_number = (form_data.get("check_number") or "").strip() or None

            result = self.factory.vendor_bill_service().post_vendor_bill(
                entry_date=entry_date,
                vendor_id=vendor_id,
                amount=amount,
                description=description,
                invoice_number=invoice_number,
                invoice_date=invoice_date,
                due_date=due_date,
                fund_code=fund_code,
                category_id=category_id,
            )

            if mark_paid:
                self.factory.vendor_payment_service().post_vendor_payment(
                    entry_date=payment_date,
                    vendor_bill_id=result.vendor_bill_id,
                    amount=amount,
                    description=description,
                    bank_account_id=bank_account_id,
                    check_number=check_number,
                )
        except (ValidationError, NotFoundError, AccountingError) as exc:
            resp = self.render_form(
                org=org,
                theme=theme,
                form_values=form_data,
                error_message=str(exc),
            )
            return (None, resp)
        except sqlite3.IntegrityError as exc:
            message = "This invoice number already exists for this vendor."
            if "invoice" not in str(exc).lower():
                message = f"Database error: {exc}"
            resp = self.render_form(
                org=org,
                theme=theme,
                form_values=form_data,
                error_message=message,
            )
            return (None, resp)

        return (f"/vendor-bills?created={result.vendor_bill_id}", None)
