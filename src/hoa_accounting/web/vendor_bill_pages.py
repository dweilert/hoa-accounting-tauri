"""Vendor-bill list page + new-bill form page.

Two routes' worth of logic:

- ``render_list`` shows every posted vendor bill in reverse chronological
  order.
- ``render_form`` shows a blank or partially-filled posting form (when
  re-rendering after a validation error).
- ``handle_post`` parses the submitted form, calls
  ``VendorBillService.post_vendor_bill`` inside its own connection, and
  returns either a redirect URL on success or a re-rendered form
  response with the user's input preserved and an error surfaced.

Kept in its own module so the Flask app stays thin (routes only) and so
adding more transaction-type forms later follows the same pattern.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import date as _date
from decimal import Decimal, InvalidOperation
from http import HTTPStatus

from hoa_accounting.exceptions import AccountingError, NotFoundError, ValidationError
from hoa_accounting.models.enums import FundCode
from hoa_accounting.repositories.accounts_repo import AccountsRepository
from hoa_accounting.repositories.vendors_repo import VendorsRepository
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.web.template_engine import render_template


@dataclass(frozen=True)
class VendorBillFormResponse:
    """Render of the form page."""

    status_code: int
    body_html: str


_FUND_CODES = [fc.value for fc in FundCode]
_CLASSIFICATIONS = ["OPERATING", "IMPROVEMENT"]


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
        rows = VendorsRepository(self.conn).list_vendor_bills()
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
                "description": r["description"] or "",
                "entry_number": r["entry_number"] or "",
            }
            for r in rows
        ]
        ctx = {
            "heading": "Vendor Bills",
            "description": (
                "Bills posted from vendors. Each bill creates a journal "
                "entry debiting the chosen expense account and crediting "
                "Accounts Payable."
            ),
            "bills": bills,
            "org": org or {},
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "vendor-bills",
            "breadcrumb": "Transactions",
            "created_entry_number": created_entry_number,
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
        expense_accounts = [
            {
                "id": r["id"],
                "label": (
                    f"{r['account_number']} · {r['account_name']}"
                    + (f"  [{r['group_code']}]" if r["group_code"] else "")
                ),
                "fund_code": r["fund_code"],
                "group_code": r["group_code"] or "",
            }
            for r in AccountsRepository(self.conn).list_accounts_by_type(
                account_type_code="EXPENSE"
            )
        ]
        payable_accounts = [
            {
                "id": r["id"],
                "label": f"{r['account_number']} · {r['account_name']}",
            }
            for r in AccountsRepository(self.conn).list_accounts_by_type(
                account_type_code="LIABILITY"
            )
        ]

        ctx = {
            "heading": "New Vendor Bill",
            "org": org or {},
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "vendor-bills",
            "breadcrumb": "Transactions · Vendor Bills",
            "vendors": vendors,
            "expense_accounts": expense_accounts,
            "payable_accounts": payable_accounts,
            "fund_codes": _FUND_CODES,
            "classifications": _CLASSIFICATIONS,
            "values": {
                "vendor_id": values.get("vendor_id", ""),
                "invoice_number": values.get("invoice_number", ""),
                "invoice_date": values.get("invoice_date", _today()),
                "due_date": values.get("due_date", ""),
                "entry_date": values.get("entry_date", _today()),
                "amount": values.get("amount", ""),
                "expense_account_id": values.get("expense_account_id", ""),
                "expense_classification": values.get("expense_classification", "OPERATING"),
                "payable_account_id": values.get("payable_account_id", ""),
                "fund_code": values.get("fund_code", "OPERATING"),
                "description": values.get("description", ""),
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

    # ── Form submit (POST) ──────────────────────────────────────

    def handle_post(
        self,
        *,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, VendorBillFormResponse | None]:
        """Process a submitted form.

        Returns ``(redirect_url, None)`` on success — the Flask layer
        redirects the browser to the list page with a success-banner
        query param. Returns ``(None, form_response)`` on failure — the
        form re-renders with the user's input preserved and an error
        line at the top.
        """
        try:
            invoice_number = _require(form_data.get("invoice_number", ""), "Invoice number")
            invoice_date = _require(form_data.get("invoice_date", ""), "Invoice date")
            entry_date = _require(form_data.get("entry_date", ""), "Entry date")
            amount = _parse_positive_decimal(form_data.get("amount", ""), "Amount")
            vendor_id = _parse_int(form_data.get("vendor_id", ""), "Vendor")
            expense_account_id = _parse_int(
                form_data.get("expense_account_id", ""), "Expense account"
            )
            payable_account_id = _parse_int(
                form_data.get("payable_account_id", ""), "Payable account"
            )
            fund_code = _require(form_data.get("fund_code", ""), "Fund")
            classification = _require(
                form_data.get("expense_classification", ""), "Expense classification"
            )
            description = (form_data.get("description", "") or "").strip()
            due_date_raw = (form_data.get("due_date", "") or "").strip()
            due_date = due_date_raw or None

            result = self.factory.vendor_bill_service().post_vendor_bill(
                entry_date=entry_date,
                vendor_id=vendor_id,
                amount=amount,
                description=description,
                expense_account_id=expense_account_id,
                payable_account_id=payable_account_id,
                invoice_number=invoice_number,
                invoice_date=invoice_date,
                due_date=due_date,
                fund_code=fund_code,
                expense_classification=classification,
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
            # Most common case: (vendor_id, invoice_number) UNIQUE clash.
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

        return (f"/vendor-bills?created={result.entry_number}", None)
