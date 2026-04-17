"""Bank account management pages.

Routes handled:
  GET  /bank-accounts                   — list all bank accounts
  GET  /bank-accounts/add               — blank add form
  POST /bank-accounts/add               — submit new bank account
  GET  /bank-accounts/<id>/edit         — edit form pre-filled
  POST /bank-accounts/<id>/edit         — submit edits
  POST /bank-accounts/<id>/delete       — hard-delete (blocked if has transactions)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from http import HTTPStatus

from hoa_accounting.exceptions import ValidationError
from hoa_accounting.repositories.bank_accounts_repo import BankAccountsRepository
from hoa_accounting.web.template_engine import render_template


@dataclass(frozen=True)
class BankAccountPageResponse:
    status_code: int
    body_html: str


def _require(raw: str, label: str) -> str:
    value = (raw or "").strip()
    if not value:
        raise ValidationError(f"{label} is required.")
    return value


def _opt(raw: str) -> str | None:
    return (raw or "").strip() or None


_ACCOUNT_TYPES = ["CHECKING", "SAVINGS", "MONEY_MARKET", "OTHER"]

_BASE_CTX = {
    "active_nav": "master-data",
    "page_key": "bank-accounts",
    "breadcrumb": "Master Data",
}


class BankAccountPages:
    """Render and handle the bank account management pages."""

    LIST_TEMPLATE = "bank_accounts_list.html"
    FORM_TEMPLATE = "bank_account_form.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.repo = BankAccountsRepository(conn)

    # ── List page ─────────────────────────────────────────────────────

    def render_list(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        flash_message: str = "",
        error_message: str = "",
    ) -> BankAccountPageResponse:
        rows = self.repo.list_bank_accounts(active_only=False)
        accounts = [dict(r) for r in rows]
        ctx = {
            **_BASE_CTX,
            "heading": "Bank Accounts",
            "org": org or {},
            "theme": theme,
            "bank_accounts": accounts,
            "flash_message": flash_message,
            "error_message": error_message,
        }
        return BankAccountPageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.LIST_TEMPLATE, ctx),
        )

    # ── Add / Edit form (GET) ──────────────────────────────────────────

    def render_form(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        bank_account_id: int | None = None,
        form_values: dict[str, str] | None = None,
        error_message: str = "",
    ) -> BankAccountPageResponse:
        is_edit = bank_account_id is not None
        values: dict[str, str] = {}

        if is_edit and form_values is None:
            row = self.repo.get_bank_account(bank_account_id)
            if row is None:
                return BankAccountPageResponse(
                    status_code=HTTPStatus.NOT_FOUND,
                    body_html="<h1>Bank account not found</h1>",
                )
            values = {
                "account_name": row["account_name"] or "",
                "institution_name": row["institution_name"] or "",
                "account_last4": row["account_last4"] or "",
                "account_type": row["account_type"] or "CHECKING",
                "gl_account_id": str(row["gl_account_id"]),
                "active_flag": str(row["active_flag"]),
                "opening_balance": str(row["opening_balance"] or "0"),
                "opening_balance_date": row["opening_balance_date"] or "",
            }
        else:
            values = form_values or {}

        gl_options = [
            dict(r)
            for r in self.repo.list_gl_account_options(
                exclude_bank_account_id=bank_account_id
            )
        ]
        has_txns = is_edit and self.repo.has_transactions(bank_account_id)  # type: ignore[arg-type]

        heading = "Edit Bank Account" if is_edit else "Add Bank Account"
        breadcrumb = "Master Data · Bank Accounts"
        ctx = {
            **_BASE_CTX,
            "heading": heading,
            "breadcrumb": breadcrumb,
            "org": org or {},
            "theme": theme,
            "is_edit": is_edit,
            "bank_account_id": bank_account_id,
            "has_transactions": has_txns,
            "account_types": _ACCOUNT_TYPES,
            "gl_options": gl_options,
            "values": {
                "account_name": values.get("account_name", ""),
                "institution_name": values.get("institution_name", ""),
                "account_last4": values.get("account_last4", ""),
                "account_type": values.get("account_type", "CHECKING"),
                "gl_account_id": values.get("gl_account_id", ""),
                "active_flag": values.get("active_flag", "1"),
                "opening_balance": values.get("opening_balance", "0"),
                "opening_balance_date": values.get("opening_balance_date", ""),
            },
            "error_message": error_message,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return BankAccountPageResponse(
            status_code=status,
            body_html=render_template(self.FORM_TEMPLATE, ctx),
        )

    # ── Add bank account (POST) ────────────────────────────────────────

    def handle_add(
        self,
        *,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, BankAccountPageResponse | None]:
        try:
            account_name = _require(form_data.get("account_name", ""), "Account Name")
            institution_name = _require(
                form_data.get("institution_name", ""), "Institution Name"
            )
            account_type_raw = (form_data.get("account_type") or "").strip()
            if account_type_raw not in _ACCOUNT_TYPES:
                raise ValidationError("Account Type is required.")
            gl_account_id_raw = (form_data.get("gl_account_id") or "").strip()
            if not gl_account_id_raw:
                raise ValidationError("GL Account is required.")
            gl_account_id = int(gl_account_id_raw)

            self.repo.insert_bank_account(
                account_name=account_name,
                institution_name=institution_name,
                account_last4=_opt(form_data.get("account_last4", "")),
                account_type=account_type_raw,
                gl_account_id=gl_account_id,
                opening_balance=_opt(form_data.get("opening_balance", "")) or "0",
                opening_balance_date=_opt(form_data.get("opening_balance_date", "")),
            )
            self.conn.commit()
        except ValidationError as exc:
            return None, self.render_form(
                org=org, theme=theme,
                form_values=form_data,
                error_message=str(exc),
            )
        except Exception:
            self.conn.rollback()
            raise
        return "/bank-accounts?msg=Bank+account+added.", None

    # ── Edit bank account (POST) ───────────────────────────────────────

    def handle_edit(
        self,
        *,
        bank_account_id: int,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, BankAccountPageResponse | None]:
        try:
            account_name = _require(form_data.get("account_name", ""), "Account Name")
            institution_name = _require(
                form_data.get("institution_name", ""), "Institution Name"
            )
            account_type_raw = (form_data.get("account_type") or "").strip()
            if account_type_raw not in _ACCOUNT_TYPES:
                raise ValidationError("Account Type is required.")
            gl_account_id_raw = (form_data.get("gl_account_id") or "").strip()
            if not gl_account_id_raw:
                raise ValidationError("GL Account is required.")
            gl_account_id = int(gl_account_id_raw)

            # active_flag: presence of hidden sentinel means checkbox was rendered
            if form_data.get("_active_flag_present"):
                active_flag = form_data.get("active_flag") == "1"
            else:
                active_flag = True

            self.repo.update_bank_account(
                bank_account_id,
                account_name=account_name,
                institution_name=institution_name,
                account_last4=_opt(form_data.get("account_last4", "")),
                account_type=account_type_raw,
                gl_account_id=gl_account_id,
                active_flag=active_flag,
                opening_balance=_opt(form_data.get("opening_balance", "")) or "0",
                opening_balance_date=_opt(form_data.get("opening_balance_date", "")),
            )
            self.conn.commit()
        except ValidationError as exc:
            return None, self.render_form(
                org=org, theme=theme,
                bank_account_id=bank_account_id,
                form_values=form_data,
                error_message=str(exc),
            )
        except Exception:
            self.conn.rollback()
            raise
        return "/bank-accounts?msg=Bank+account+updated.", None

    # ── Delete bank account (POST) ─────────────────────────────────────

    def handle_delete(
        self,
        *,
        bank_account_id: int,
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, BankAccountPageResponse | None]:
        try:
            if self.repo.has_transactions(bank_account_id):
                raise ValidationError(
                    "Cannot delete a bank account that has transactions on record. "
                    "Deactivate it instead."
                )
            self.repo.delete_bank_account(bank_account_id)
            self.conn.commit()
        except ValidationError as exc:
            return None, self.render_form(
                org=org, theme=theme,
                bank_account_id=bank_account_id,
                error_message=str(exc),
            )
        except Exception:
            self.conn.rollback()
            raise
        return "/bank-accounts?msg=Bank+account+deleted.", None
