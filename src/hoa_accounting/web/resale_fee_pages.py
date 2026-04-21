"""Resale Certificate Fee workflow.

Flow
----
GET  /resale-fee
     Show open resale fee assessments + the "Create Fee" form.

POST /resale-fee/post-charge
     Create a RESALE_FEE assessment on the selected lot.
     Debits AR (1100), credits Resale Certificate Fee Income (4070).

POST /resale-fee/post-payment
     Record the title company's check and apply it to the assessment.
     Debits bank GL account, credits AR (1100).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date as _date
from decimal import Decimal, InvalidOperation
from http import HTTPStatus

from hoa_accounting.exceptions import AccountingError, NotFoundError, ValidationError
from hoa_accounting.repositories.accounts_repo import AccountsRepository
from hoa_accounting.repositories.bank_accounts_repo import BankAccountsRepository
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.web.template_engine import render_template

_AR_DEFAULT = "1100"
_RESALE_FEE_ACCOUNT = "4070"
_CHARGE_TYPE = "RESALE_FEE"


def _today() -> str:
    return _date.today().isoformat()


@dataclass(frozen=True)
class ResaleFeePageResponse:
    status_code: int
    body_html: str


class ResaleFeePages:
    TEMPLATE = "resale_fee.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.factory = ServiceFactory(conn)

    # ── helpers ─────────────────────────────────────────────────────────

    def _resolve_income_account(self, account_number: str) -> tuple[int | None, str]:
        row = AccountsRepository(self.conn).get_by_number(account_number)
        if row is None:
            return None, f"Resale Fee Income account '{account_number}' not found — run migrations."
        if not int(row["is_active"]):
            return None, f"Resale Fee Income account '{account_number}' is inactive."
        return int(row["id"]), f"{row['account_number']} · {row['account_name']}"

    def _resolve_ar_account(self, account_number: str) -> tuple[int | None, str]:
        row = AccountsRepository(self.conn).get_by_number(account_number)
        if row is None:
            return None, f"AR account '{account_number}' not found."
        return int(row["id"]), f"{row['account_number']} · {row['account_name']}"

    def _lot_options(self) -> list[dict]:
        lots = LotsRepository(self.conn).list_lots(active_only=True)
        options = []
        for r in lots:
            owner = r["owner_names"] or "(no owner)"
            label = f"Lot {r['lot_number']} · {owner}"
            options.append({"id": r["id"], "label": label})
        return options

    def _bank_account_options(self) -> list[dict]:
        rows = BankAccountsRepository(self.conn).list_bank_accounts()
        return [
            {
                "id": r["id"],
                "gl_account_id": r["gl_account_id"],
                "label": f"{r['account_name']} (…{r['account_last4'] or '????'})",
            }
            for r in rows
            if r["active_flag"]
        ]

    def _open_resale_fees(self) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT
                a.id,
                a.assessment_date,
                a.due_date,
                a.amount,
                a.description,
                a.status,
                l.lot_number,
                GROUP_CONCAT(
                    TRIM(COALESCE(o.first_name || ' ' || o.last_name, o.display_name, '')),
                    ', '
                ) AS owner_name,
                COALESCE(
                    (SELECT SUM(pa.applied_amount)
                     FROM payment_applications pa WHERE pa.assessment_id = a.id), 0
                ) AS applied_amount
            FROM assessments a
            JOIN lots l ON l.id = a.lot_id
            LEFT JOIN lot_ownership lo ON lo.lot_id = a.lot_id AND lo.end_date IS NULL
            LEFT JOIN owners o ON o.id = lo.owner_id
            WHERE a.charge_type = ?
              AND a.status NOT IN ('PAID', 'VOID', 'WRITTEN_OFF')
            GROUP BY a.id
            ORDER BY a.assessment_date DESC
            """,
            (_CHARGE_TYPE,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── render ───────────────────────────────────────────────────────────

    def render_page(
        self,
        *,
        org: dict,
        theme: str,
        default_amount: str = "175.00",
        income_account_number: str = _RESALE_FEE_ACCOUNT,
        error_message: str = "",
        flash_message: str = "",
        form_values: dict | None = None,
    ) -> ResaleFeePageResponse:
        fv = form_values or {}
        income_account_id, income_label = self._resolve_income_account(income_account_number)
        if income_account_id is None:
            error_message = error_message or income_label

        ctx = {
            "heading": "Resale Certificate Fee",
            "org": org,
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "resale-fee",
            "breadcrumb": "Transactions",
            "lot_options": self._lot_options(),
            "bank_account_options": self._bank_account_options(),
            "open_fees": self._open_resale_fees(),
            "default_amount": fv.get("amount") or default_amount,
            "today": _today(),
            "income_account_label": income_label if income_account_id else "",
            "error_message": error_message,
            "flash_message": flash_message,
            "form_values": fv,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return ResaleFeePageResponse(
            status_code=status,
            body_html=render_template(self.TEMPLATE, ctx),
        )

    # ── POST: create charge ───────────────────────────────────────────────

    def handle_post_charge(
        self,
        *,
        form_data: dict,
        org: dict,
        theme: str,
        default_amount: str,
        income_account_number: str,
    ) -> tuple[str | None, ResaleFeePageResponse | None]:
        ar_num = str(org.get("dues_receivable_account_number") or _AR_DEFAULT)

        def _err(msg: str) -> tuple[None, ResaleFeePageResponse]:
            return None, self.render_page(
                org=org, theme=theme,
                default_amount=default_amount,
                income_account_number=income_account_number,
                error_message=msg,
                form_values=form_data,
            )

        try:
            lot_id = int((form_data.get("lot_id") or "").strip())
        except (TypeError, ValueError):
            return _err("Lot is required.")

        amount_raw = (form_data.get("amount") or "").strip()
        try:
            amount = Decimal(amount_raw)
            if amount <= 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            return _err("Amount must be a positive number.")

        assessment_date = (form_data.get("assessment_date") or "").strip() or _today()
        due_date = (form_data.get("due_date") or "").strip() or assessment_date
        description = (form_data.get("description") or "Resale Certificate Fee").strip()

        income_account_id, income_err = self._resolve_income_account(income_account_number)
        if income_account_id is None:
            return _err(income_err)

        ar_row = AccountsRepository(self.conn).get_by_number(ar_num)
        if ar_row is None:
            return _err(f"AR account '{ar_num}' not found.")

        lot = LotsRepository(self.conn).get_lot_with_owner(lot_id)
        if lot is None:
            return _err("Lot not found.")
        owner_id = lot["owner_id"]
        if owner_id is None:
            return _err("This lot has no current owner on record.")

        try:
            svc = self.factory.assessment_service()
            svc.post_assessment(
                entry_date=assessment_date,
                lot_id=lot_id,
                owner_id=owner_id,
                amount=amount,
                description=description,
                receivable_account_id=int(ar_row["id"]),
                income_account_id=income_account_id,
                charge_type=_CHARGE_TYPE,
                due_date=due_date,
            )
        except (ValidationError, NotFoundError, AccountingError) as exc:
            return _err(str(exc))

        from urllib.parse import quote
        msg = f"Resale certificate fee of ${amount:,.2f} posted for Lot {lot['lot_number']}."
        return f"/resale-fee?msg={quote(msg)}", None

    # ── POST: record payment ──────────────────────────────────────────────

    def handle_post_payment(
        self,
        *,
        form_data: dict,
        org: dict,
        theme: str,
        default_amount: str,
        income_account_number: str,
    ) -> tuple[str | None, ResaleFeePageResponse | None]:
        ar_num = str(org.get("dues_receivable_account_number") or _AR_DEFAULT)

        def _err(msg: str) -> tuple[None, ResaleFeePageResponse]:
            return None, self.render_page(
                org=org, theme=theme,
                default_amount=default_amount,
                income_account_number=income_account_number,
                error_message=msg,
                form_values=form_data,
            )

        try:
            assessment_id = int((form_data.get("assessment_id") or "").strip())
        except (TypeError, ValueError):
            return _err("Assessment is required.")

        try:
            bank_account_id = int((form_data.get("bank_account_id") or "").strip())
        except (TypeError, ValueError):
            return _err("Bank account is required.")

        amount_raw = (form_data.get("amount") or "").strip()
        try:
            amount = Decimal(amount_raw)
            if amount <= 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            return _err("Payment amount must be a positive number.")

        payment_date = (form_data.get("payment_date") or "").strip() or _today()
        receipt_number = (form_data.get("receipt_number") or "").strip()
        check_number = (form_data.get("check_number") or "").strip() or None

        if not receipt_number:
            return _err("Receipt number is required.")

        # Look up the assessment to get owner + lot info.
        assessment = self.conn.execute(
            """
            SELECT a.lot_id, a.amount,
                   lo.owner_id, l.lot_number
            FROM assessments a
            JOIN lots l ON l.id = a.lot_id
            LEFT JOIN lot_ownership lo ON lo.lot_id = a.lot_id AND lo.end_date IS NULL
            WHERE a.id = ? AND a.charge_type = ?
            """,
            (assessment_id, _CHARGE_TYPE),
        ).fetchone()
        if assessment is None:
            return _err("Resale fee assessment not found.")
        owner_id = assessment["owner_id"]
        if owner_id is None:
            return _err("No current owner found for this lot.")

        # Resolve bank account → GL cash account.
        bank_row = BankAccountsRepository(self.conn).get_bank_account(bank_account_id)
        if bank_row is None:
            return _err("Bank account not found.")
        cash_account_id = int(bank_row["gl_account_id"])

        ar_row = AccountsRepository(self.conn).get_by_number(ar_num)
        if ar_row is None:
            return _err(f"AR account '{ar_num}' not found.")

        try:
            svc = self.factory.payment_service()
            svc.post_payment(
                entry_date=payment_date,
                owner_id=owner_id,
                amount=amount,
                description=f"Resale certificate fee payment — check {check_number or receipt_number}",
                cash_account_id=cash_account_id,
                receivable_account_id=int(ar_row["id"]),
                bank_account_id=bank_account_id,
                payment_method="CHECK",
                receipt_number=receipt_number,
                reference_number=check_number,
                apply_to_assessment_ids=[assessment_id],
            )
        except (ValidationError, NotFoundError, AccountingError) as exc:
            return _err(str(exc))

        from urllib.parse import quote
        msg = (
            f"Payment of ${amount:,.2f} recorded for Lot {assessment['lot_number']} "
            f"(receipt {receipt_number})."
        )
        return f"/resale-fee?msg={quote(msg)}", None
