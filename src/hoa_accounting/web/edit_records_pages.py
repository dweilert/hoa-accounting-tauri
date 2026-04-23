"""Edit Records hub + per-ledger spreadsheet pages.

Gives the treasurer one place under Manage to find the inline-editable
ledger views. First editor covered here is Homeowner Payments; Vendor
Bills has its own dedicated page at /vendor-bills and is linked from
the hub. Other ledgers (bill payments, non-dues income, assessments)
are stubbed as "coming soon".
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date as _date
from decimal import Decimal, InvalidOperation
from http import HTTPStatus

from hoa_accounting.exceptions import AccountingError, NotFoundError, ValidationError
from hoa_accounting.models.enums import PaymentMethod
from hoa_accounting.repositories.assessments_repo import AssessmentsRepository
from hoa_accounting.repositories.bank_accounts_repo import BankAccountsRepository
from hoa_accounting.repositories.categories_repo import CategoriesRepository
from hoa_accounting.repositories.income_batches_repo import IncomeBatchesRepository
from hoa_accounting.repositories.payments_repo import PaymentsRepository
from hoa_accounting.web.template_engine import render_template


_PAYMENT_METHODS = [m.value for m in PaymentMethod]


@dataclass(frozen=True)
class EditRecordsResponse:
    status_code: int
    body_html: str


def _req(raw: str | None, label: str) -> str:
    v = (raw or "").strip()
    if not v:
        raise ValidationError(f"{label} is required.")
    return v


def _parse_int(raw: str | None, label: str) -> int:
    try:
        return int((raw or "").strip())
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} is required.") from exc


def _parse_positive_decimal(raw: str | None, label: str) -> Decimal:
    try:
        value = Decimal((raw or "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"{label} must be a number.") from exc
    if value <= Decimal("0"):
        raise ValidationError(f"{label} must be greater than zero.")
    return value


class EditRecordsPages:
    """Hub + payments-ledger inline editor."""

    HUB_TEMPLATE = "edit_records_hub.html"
    PAYMENTS_TEMPLATE = "edit_records_payments.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ── Hub ──────────────────────────────────────────────────────

    def render_hub(
        self, *, org: dict | None, theme: str,
    ) -> EditRecordsResponse:
        ctx = {
            "heading": "Edit Records",
            "org": org or {},
            "theme": theme,
            "active_nav": "master-data",
            "page_key": "edit-records",
            "breadcrumb": "Manage",
        }
        return EditRecordsResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.HUB_TEMPLATE, ctx),
        )

    # ── Homeowner Payments ledger ───────────────────────────────

    def render_payments(
        self,
        *,
        org: dict | None,
        theme: str,
        flash_message: str = "",
        error_message: str = "",
    ) -> EditRecordsResponse:
        repo = PaymentsRepository(self.conn)
        rows = repo.list_payments()
        ids_with_apps = {
            int(r["payment_id"])
            for r in self.conn.execute(
                "SELECT DISTINCT payment_id FROM payment_applications"
            ).fetchall()
        }
        payments = [
            {
                "id": r["id"],
                "receipt_number": r["receipt_number"] or "",
                "owner_id": r["owner_id"],
                "owner_name": r["owner_name"] or "",
                "payment_date": r["payment_date"] or "",
                "amount": f"{Decimal(str(r['amount'])):.2f}",
                "payment_method": r["payment_method"] or "",
                "reference_number": r["reference_number"] or "",
                "bank_account_id": r["bank_account_id"],
                "bank_label": (
                    f"{r['bank_account_name']} (···{r['bank_account_last4'] or '????'})"
                ),
                "notes": r["notes"] or "",
                "deposit_batch_id": r["deposit_batch_id"],
                "category_id": r["category_id"],
                "has_applications": int(r["id"]) in ids_with_apps,
            }
            for r in rows
        ]
        bank_accounts = [
            {"id": r["id"],
             "label": f"{r['account_name']} (···{r['account_last4'] or '????'})"}
            for r in BankAccountsRepository(self.conn).list_bank_accounts()
            if r["active_flag"]
        ]
        income_categories = [
            {"id": c["id"], "label": c["name"]}
            for c in CategoriesRepository(self.conn).list_categories(
                category_type="INCOME"
            )
        ]
        ctx = {
            "heading": "Homeowner Payments · Edit",
            "org": org or {},
            "theme": theme,
            "active_nav": "master-data",
            "page_key": "edit-records-payments",
            "breadcrumb": "Manage · Edit Records",
            "parent_url": "/manage/edit-records",
            "payments": payments,
            "bank_accounts": bank_accounts,
            "income_categories": income_categories,
            "payment_methods": _PAYMENT_METHODS,
            "flash_message": flash_message,
            "error_message": error_message,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return EditRecordsResponse(
            status_code=status,
            body_html=render_template(self.PAYMENTS_TEMPLATE, ctx),
        )

    def handle_payment_edit(
        self,
        payment_id: int,
        *,
        form_data: dict,
        org: dict | None,
        theme: str,
    ) -> tuple[str | None, EditRecordsResponse | None]:
        repo = PaymentsRepository(self.conn)
        payment = repo.get_payment(payment_id)
        if payment is None:
            return ("/manage/edit-records/payments", None)
        has_apps = repo.payment_has_applications(payment_id)

        try:
            receipt_number = _req(form_data.get("receipt_number"), "Receipt number")
            payment_date = _req(form_data.get("payment_date"), "Payment date")
            method_raw = _req(form_data.get("payment_method"), "Payment method").upper()
            if method_raw not in _PAYMENT_METHODS:
                raise ValidationError(f"Invalid payment method: {method_raw}")
            bank_account_id = _parse_int(form_data.get("bank_account_id"), "Bank account")
            reference_number = (form_data.get("reference_number") or "").strip() or None
            notes = (form_data.get("notes") or "").strip()
            cat_raw = (form_data.get("category_id") or "").strip()
            category_id = int(cat_raw) if cat_raw else None

            if has_apps:
                amount_to_write: str | None = None
            else:
                amount_dec = _parse_positive_decimal(form_data.get("amount"), "Amount")
                amount_to_write = str(amount_dec)

            repo.update_payment(
                payment_id,
                receipt_number=receipt_number,
                payment_date=payment_date,
                amount=amount_to_write,
                payment_method=method_raw,
                reference_number=reference_number,
                bank_account_id=bank_account_id,
                notes=notes,
                category_id=category_id,
            )
        except (ValidationError, NotFoundError, AccountingError) as exc:
            resp = self.render_payments(
                org=org, theme=theme, error_message=str(exc),
            )
            return (None, resp)
        except sqlite3.IntegrityError as exc:
            msg = str(exc)
            if "receipt_number" in msg:
                msg = f"Receipt number '{receipt_number}' already used."
            resp = self.render_payments(
                org=org, theme=theme, error_message=msg,
            )
            return (None, resp)

        return (
            f"/manage/edit-records/payments?msg=Saved&opened={payment_id}",
            None,
        )

    # ── Non-Dues Income ledger ──────────────────────────────────

    INCOME_TEMPLATE = "edit_records_income.html"

    def render_income(
        self,
        *,
        org: dict | None,
        theme: str,
        flash_message: str = "",
        error_message: str = "",
    ) -> EditRecordsResponse:
        repo = IncomeBatchesRepository(self.conn)
        batches = []
        for r in repo.list_batches(limit=500):
            batches.append({
                "id": r["id"],
                "posting_date": r["posting_date"] or "",
                "bank_account_id": r["bank_account_id"],
                "bank_label": (
                    f"{r['bank_account_name']} (···{r['bank_account_last4'] or '????'})"
                ),
                "income_description": r["income_description"] or "",
                "total_amount": f"{Decimal(str(r['total_amount'])):.2f}",
                "notes": r["notes"] or "",
                "category_id": r["category_id"],
                "category_name": r["category_name"] or "",
            })
        bank_accounts = [
            {"id": r["id"],
             "label": f"{r['account_name']} (···{r['account_last4'] or '????'})"}
            for r in BankAccountsRepository(self.conn).list_bank_accounts()
            if r["active_flag"]
        ]
        income_categories = [
            {"id": c["id"], "label": c["name"]}
            for c in CategoriesRepository(self.conn).list_categories(
                category_type="INCOME"
            )
        ]
        ctx = {
            "heading": "Non-Dues Income · Edit",
            "org": org or {},
            "theme": theme,
            "active_nav": "master-data",
            "page_key": "edit-records-income",
            "breadcrumb": "Manage · Edit Records",
            "parent_url": "/manage/edit-records",
            "batches": batches,
            "bank_accounts": bank_accounts,
            "income_categories": income_categories,
            "flash_message": flash_message,
            "error_message": error_message,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return EditRecordsResponse(
            status_code=status,
            body_html=render_template(self.INCOME_TEMPLATE, ctx),
        )

    def handle_income_edit(
        self,
        income_batch_id: int,
        *,
        form_data: dict,
        org: dict | None,
        theme: str,
    ) -> tuple[str | None, EditRecordsResponse | None]:
        repo = IncomeBatchesRepository(self.conn)
        row = repo.get_income_batch(income_batch_id)
        if row is None:
            return ("/manage/edit-records/non-dues-income", None)
        try:
            posting_date = _req(form_data.get("posting_date"), "Posting date")
            bank_account_id = _parse_int(form_data.get("bank_account_id"), "Bank account")
            income_description = _req(form_data.get("income_description"), "Description")
            amount = _parse_positive_decimal(form_data.get("total_amount"), "Amount")
            notes = (form_data.get("notes") or "").strip() or None
            cat_raw = (form_data.get("category_id") or "").strip()
            category_id = int(cat_raw) if cat_raw else None

            repo.update_income_batch(
                income_batch_id,
                posting_date=posting_date,
                bank_account_id=bank_account_id,
                income_description=income_description,
                total_amount=str(amount),
                notes=notes,
                category_id=category_id,
            )
        except (ValidationError, NotFoundError, AccountingError) as exc:
            resp = self.render_income(
                org=org, theme=theme, error_message=str(exc),
            )
            return (None, resp)
        return (
            f"/manage/edit-records/non-dues-income?msg=Saved&opened={income_batch_id}",
            None,
        )

    # ── Assessments / Charges ledger ────────────────────────────

    ASSESS_TEMPLATE = "edit_records_assessments.html"

    def render_assessments(
        self,
        *,
        org: dict | None,
        theme: str,
        flash_message: str = "",
        error_message: str = "",
    ) -> EditRecordsResponse:
        repo = AssessmentsRepository(self.conn)
        ids_with_apps = {
            int(r["assessment_id"])
            for r in self.conn.execute(
                "SELECT DISTINCT assessment_id FROM payment_applications"
            ).fetchall()
        }
        rows = []
        for r in repo.list_for_edit(limit=500):
            rows.append({
                "id": r["id"],
                "lot_number": r["lot_number"] or "",
                "owner_name": r["owner_name"] or "",
                "assessment_date": r["assessment_date"] or "",
                "due_date": r["due_date"] or "",
                "amount": f"{Decimal(str(r['amount'])):.2f}",
                "description": r["description"] or "",
                "status": r["status"] or "",
                "charge_type": r["charge_type"] or "",
                "category_id": r["category_id"],
                "category_name": r["category_name"] or "",
                "has_applications": int(r["id"]) in ids_with_apps,
            })
        income_categories = [
            {"id": c["id"], "label": c["name"]}
            for c in CategoriesRepository(self.conn).list_categories(
                category_type="INCOME"
            )
        ]
        ctx = {
            "heading": "Assessments / Charges · Edit",
            "org": org or {},
            "theme": theme,
            "active_nav": "master-data",
            "page_key": "edit-records-assessments",
            "breadcrumb": "Manage · Edit Records",
            "parent_url": "/manage/edit-records",
            "assessments": rows,
            "income_categories": income_categories,
            "flash_message": flash_message,
            "error_message": error_message,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return EditRecordsResponse(
            status_code=status,
            body_html=render_template(self.ASSESS_TEMPLATE, ctx),
        )

    def handle_assessment_edit(
        self,
        assessment_id: int,
        *,
        form_data: dict,
        org: dict | None,
        theme: str,
    ) -> tuple[str | None, EditRecordsResponse | None]:
        repo = AssessmentsRepository(self.conn)
        row = repo.get_for_edit(assessment_id)
        if row is None:
            return ("/manage/edit-records/assessments", None)
        has_apps = repo.has_applications(assessment_id)
        try:
            assessment_date = _req(form_data.get("assessment_date"), "Assessment date")
            due_date = _req(form_data.get("due_date"), "Due date")
            description = _req(form_data.get("description"), "Description")
            cat_raw = (form_data.get("category_id") or "").strip()
            category_id = int(cat_raw) if cat_raw else None
            if has_apps:
                amount_to_write: str | None = None
            else:
                amount_dec = _parse_positive_decimal(
                    form_data.get("amount"), "Amount"
                )
                amount_to_write = str(amount_dec)
            repo.update_for_edit(
                assessment_id,
                assessment_date=assessment_date,
                due_date=due_date,
                amount=amount_to_write,
                description=description,
                category_id=category_id,
            )
        except (ValidationError, NotFoundError, AccountingError) as exc:
            resp = self.render_assessments(
                org=org, theme=theme, error_message=str(exc),
            )
            return (None, resp)
        return (
            f"/manage/edit-records/assessments?msg=Saved&opened={assessment_id}",
            None,
        )
