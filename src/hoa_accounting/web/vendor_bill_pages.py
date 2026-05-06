"""Vendor-bill list page + new-bill form page."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date as _date
from decimal import Decimal
from http import HTTPStatus

from hoa_accounting.db.transaction import transaction
from hoa_accounting.exceptions import AccountingError, NotFoundError, ValidationError
from hoa_accounting.models.enums import FundCode
from hoa_accounting.repositories.bank_accounts_repo import BankAccountsRepository
from hoa_accounting.repositories.categories_repo import CategoriesRepository
from hoa_accounting.repositories.vendors_repo import VendorsRepository
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.validators.format import format_currency, format_money
from hoa_accounting.validators.forms import (
    parse_int as _parse_int,
)
from hoa_accounting.validators.forms import (
    parse_nonzero_decimal as _parse_nonzero_decimal,
)
from hoa_accounting.validators.forms import (
    parse_positive_decimal as _parse_positive_decimal,
)
from hoa_accounting.validators.forms import (
    require as _require,
)
from hoa_accounting.web.template_engine import render_template


@dataclass(frozen=True)
class VendorBillFormResponse:
    """Render of the form page."""

    status_code: int
    body_html: str


_FUND_CODES = [fc.value for fc in FundCode]


def _today() -> str:
    return _date.today().isoformat()


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
                "amount": format_money(r["amount"]),
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
            {
                "id": r["id"],
                "name": r["account_name"],
                "label": f"{r['account_name']} (···{r['account_last4'] or '????'})",
            }
            for r in BankAccountsRepository(self.conn).list_bank_accounts()
            if r["active_flag"]
        ]

        # Prefer the Operating Checking account as the default since that's
        # where day-to-day bills are paid from. Fall back to the first active
        # bank if the user hasn't named one "Operating".
        default_bank_id = ""
        for ba in bank_accounts:
            if "operating" in (ba["name"] or "").lower():
                default_bank_id = str(ba["id"])
                break
        if not default_bank_id and bank_accounts:
            default_bank_id = str(bank_accounts[0]["id"])

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
                "due_date": values.get("due_date", _today()),
                "entry_date": values.get("entry_date", _today()),
                "amount": values.get("amount", ""),
                "category_id": values.get("category_id", ""),
                "fund_code": values.get("fund_code", "OPERATING"),
                "description": values.get("description", ""),
                "bank_account_id": values.get("bank_account_id") or default_bank_id,
                "check_number": values.get("check_number", ""),
                "payment_date": values.get("payment_date", ""),
            },
            "error_message": error_message,
            # Bill Templates retired — empty list keeps the form template
            # happy without rendering the (deleted) "apply template" panel.
            "templates": [],
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return VendorBillFormResponse(
            status_code=status,
            body_html=render_template(self.FORM_TEMPLATE, ctx),
        )

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
                body_html=render_template(
                    "error.html",
                    {
                        "org": org or {},
                        "theme": theme,
                        "heading": "Not Found",
                        "message": f"Vendor bill #{vendor_bill_id} not found.",
                        "page_key": "vendor-bills",
                    },
                ),
            )
        has_payment = repo.vendor_bill_has_payments(vendor_bill_id)

        defaults = {
            "invoice_number": bill["invoice_number"],
            "invoice_date": bill["invoice_date"],
            "due_date": bill["due_date"] or "",
            "amount": format_money(bill["amount"]),
            "fund_code": bill["fund_code"],
            "category_id": str(bill["category_id"] or ""),
            "description": bill["description"] or "",
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
            invoice_number = _require(
                form_data.get("invoice_number", ""), "Invoice number"
            )
            invoice_date = _require(form_data.get("invoice_date", ""), "Invoice date")
            fund_code = _require(form_data.get("fund_code", ""), "Fund")
            description = (form_data.get("description", "") or "").strip()
            due_date_raw = (form_data.get("due_date", "") or "").strip()
            due_date = due_date_raw or None
            category_id = _parse_int(
                form_data.get("category_id", ""), "Expense category"
            )

            if has_payment:
                amount_to_write: str | None = None
            else:
                amount_dec = _parse_positive_decimal(
                    form_data.get("amount", ""), "Amount"
                )
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
            resp = self.render_edit(
                vendor_bill_id,
                org=org,
                theme=theme,
                form_values=form_data,
                error_message=message,
            )
            return (None, resp)

        return ("/vendor-bills?saved=1", None)

    # ── Split (GET + POST) ──────────────────────────────────────

    SPLIT_TEMPLATE = "vendor_bill_split.html"

    def render_split(
        self,
        vendor_bill_id: int,
        *,
        org: dict[str, object] | None,
        theme: str,
        form_values: dict[str, list[str]] | None = None,
        error_message: str = "",
    ) -> VendorBillFormResponse:
        repo = VendorsRepository(self.conn)
        bill = repo.get_vendor_bill(vendor_bill_id)
        if bill is None:
            return VendorBillFormResponse(
                status_code=HTTPStatus.NOT_FOUND,
                body_html=render_template(
                    "error.html",
                    {
                        "org": org or {},
                        "theme": theme,
                        "heading": "Not Found",
                        "message": f"Vendor bill #{vendor_bill_id} not found.",
                        "page_key": "vendor-bills",
                    },
                ),
            )
        bill_amount = format_money(bill["amount"])

        if form_values and form_values.get("line_category_id"):
            cats = form_values["line_category_id"]
            amts = form_values.get("line_amount", [])
            initial_lines = [
                {
                    "category_id": cats[i] if i < len(cats) else "",
                    "amount": amts[i] if i < len(amts) else "",
                }
                for i in range(max(len(cats), 1))
            ]
        else:
            initial_lines = [
                {"category_id": str(bill["category_id"] or ""), "amount": bill_amount},
                {"category_id": "", "amount": ""},
            ]

        expense_categories = [
            {"id": r["id"], "label": r["name"], "fund_code": r["fund_code"]}
            for r in CategoriesRepository(self.conn).list_categories(
                category_type="EXPENSE"
            )
        ]
        ctx = {
            "heading": f"Split Bill · {bill['vendor_name']} · {bill['invoice_number']}",
            "org": org or {},
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "vendor-bills",
            "breadcrumb": "Transactions · Vendor Bills · Split",
            "bill": dict(bill),
            "bill_amount": bill_amount,
            "expense_categories": expense_categories,
            "initial_lines": initial_lines,
            "error_message": error_message,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return VendorBillFormResponse(
            status_code=status,
            body_html=render_template(self.SPLIT_TEMPLATE, ctx),
        )

    def handle_split(
        self,
        vendor_bill_id: int,
        *,
        line_category_ids: list[str],
        line_amounts: list[str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, VendorBillFormResponse | None]:
        repo = VendorsRepository(self.conn)
        bill = repo.get_vendor_bill(vendor_bill_id)
        if bill is None:
            return ("/vendor-bills", None)
        form_values = {
            "line_category_id": line_category_ids,
            "line_amount": line_amounts,
        }
        try:
            if len(line_category_ids) != len(line_amounts) or not line_category_ids:
                raise ValidationError("Provide at least one line.")
            lines: list[tuple[int, Decimal]] = []
            for cid_raw, amt_raw in zip(line_category_ids, line_amounts, strict=True):
                cid = _parse_int(cid_raw, "Category")
                amt = _parse_positive_decimal(amt_raw, "Line amount")
                lines.append((cid, amt))
            total = sum((a for _, a in lines), Decimal("0"))
            target = Decimal(str(bill["amount"]))
            if abs(total - target) > Decimal("0.005"):
                raise ValidationError(
                    f"Lines sum to {format_currency(total)} but bill total is {format_currency(target)}."
                )
            if len(lines) < 2:
                raise ValidationError("A split needs at least two lines.")

            # Capture original payment details (assume one payment per bill —
            # invariant for bills posted via this app).
            pay_row = self.conn.execute(
                """SELECT id, payment_date, bank_account_id, check_number, notes
                     FROM bill_payments WHERE vendor_bill_id = ?
                     ORDER BY id LIMIT 1""",
                (vendor_bill_id,),
            ).fetchone()
            if pay_row is None:
                raise ValidationError("Cannot split a bill with no payment recorded.")
            old_payment_id = int(pay_row["id"])
            payment_date = pay_row["payment_date"]
            bank_account_id = int(pay_row["bank_account_id"])
            check_number = pay_row["check_number"]
            payment_notes = pay_row["notes"] or ""

            base_inv = bill["invoice_number"]
            # Splitting a bill is one logical operation: create N new
            # bill+payment pairs, re-point bank-recon links, and delete
            # the original bill+payment. A mid-flight failure must roll
            # back the new rows AND keep the original intact.
            with transaction(self.conn):
                new_payment_ids: list[int] = []
                for idx, (cat_id, line_amt) in enumerate(lines, start=1):
                    new_inv = f"{base_inv}-S{idx}"
                    new_bill = self.factory.vendor_bill_service().post_vendor_bill(
                        entry_date=bill["invoice_date"],
                        vendor_id=int(bill["vendor_id"]),
                        amount=str(line_amt),
                        description=bill["description"] or "",
                        invoice_number=new_inv,
                        invoice_date=bill["invoice_date"],
                        due_date=bill["due_date"] or None,
                        fund_code=bill["fund_code"],
                        category_id=int(cat_id),
                    )
                    new_payment = (
                        self.factory.vendor_payment_service().post_vendor_payment(
                            entry_date=payment_date,
                            vendor_bill_id=new_bill.vendor_bill_id,
                            amount=str(line_amt),
                            description=payment_notes,
                            bank_account_id=bank_account_id,
                            check_number=check_number,
                        )
                    )
                    new_payment_ids.append(int(new_payment.bill_payment_id))

                # Re-point bank reconciliation links from the old payment to the
                # new ones. matched_source_* points at the first new payment.
                self.conn.execute(
                    """UPDATE bank_transactions
                          SET matched_source_id = ?
                        WHERE matched_source_type = 'BILL_PAYMENT'
                          AND matched_source_id = ?""",
                    (new_payment_ids[0], old_payment_id),
                )
                bank_txn_rows = self.conn.execute(
                    """SELECT bank_transaction_id FROM bank_transaction_links
                        WHERE ledger_source_type = 'BILL_PAYMENT'
                          AND ledger_source_id = ?""",
                    (old_payment_id,),
                ).fetchall()
                self.conn.execute(
                    """DELETE FROM bank_transaction_links
                        WHERE ledger_source_type = 'BILL_PAYMENT'
                          AND ledger_source_id = ?""",
                    (old_payment_id,),
                )
                for btx in bank_txn_rows:
                    for pid in new_payment_ids:
                        self.conn.execute(
                            """INSERT OR IGNORE INTO bank_transaction_links
                                  (bank_transaction_id, ledger_source_type,
                                   ledger_source_id, link_source)
                               VALUES (?, 'BILL_PAYMENT', ?, 'MANUAL')""",
                            (int(btx["bank_transaction_id"]), pid),
                        )

                # Remove the original payment + bill.
                self.conn.execute(
                    "DELETE FROM bill_payments WHERE id = ?", (old_payment_id,)
                )
                self.conn.execute(
                    "DELETE FROM vendor_bills WHERE id = ?", (vendor_bill_id,)
                )
        except (ValidationError, NotFoundError, AccountingError) as exc:
            resp = self.render_split(
                vendor_bill_id,
                org=org,
                theme=theme,
                form_values=form_values,
                error_message=str(exc),
            )
            return (None, resp)
        except sqlite3.IntegrityError as exc:
            resp = self.render_split(
                vendor_bill_id,
                org=org,
                theme=theme,
                form_values=form_values,
                error_message=f"Database error: {exc}",
            )
            return (None, resp)

        return (f"/vendor-bills?split={vendor_bill_id}", None)

    # ── Form submit (POST) ──────────────────────────────────────

    def handle_post(
        self,
        *,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, VendorBillFormResponse | None]:
        try:
            invoice_number = _require(
                form_data.get("invoice_number", ""), "Invoice number"
            )
            invoice_date = _require(form_data.get("invoice_date", ""), "Invoice date")
            entry_date = _require(form_data.get("entry_date", ""), "Entry date")
            amount = _parse_nonzero_decimal(form_data.get("amount", ""), "Amount")
            vendor_id = _parse_int(form_data.get("vendor_id", ""), "Vendor")
            category_id = _parse_int(
                form_data.get("category_id", ""), "Expense category"
            )
            fund_code = _require(form_data.get("fund_code", ""), "Fund")
            description = (form_data.get("description", "") or "").strip()
            due_date_raw = (form_data.get("due_date", "") or "").strip()
            due_date = due_date_raw or None

            # Every new bill is posted AS PAID: the HOA records bills at the
            # moment payment goes out. The form collects Bank Account and
            # optional Check # so a bill_payment is written alongside the bill.
            bank_account_id = _parse_int(
                form_data.get("bank_account_id", ""), "Bank account"
            )
            payment_date_raw = (form_data.get("payment_date") or "").strip()
            payment_date = payment_date_raw or entry_date
            check_number = (form_data.get("check_number") or "").strip() or None

            # Wrap the bill + payment in a single outer transaction so a
            # payment-side failure rolls back the bill too. The two
            # services use ``with transaction(self.conn)`` internally,
            # which becomes savepoints when nested inside this outer
            # block — see test_fail_injection.py.
            with transaction(self.conn):
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
