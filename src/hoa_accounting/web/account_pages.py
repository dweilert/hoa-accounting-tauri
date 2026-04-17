"""Chart of Accounts management pages.

Routes handled:
  GET  /accounts                — list all accounts (active + inactive)
  GET  /accounts/add            — blank add form
  POST /accounts/add            — submit new account
  GET  /accounts/<id>/edit      — edit form pre-filled
  POST /accounts/<id>/edit      — submit edits
  POST /accounts/<id>/delete    — hard-delete (blocked if account has activity)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from http import HTTPStatus

from hoa_accounting.exceptions import ValidationError
from hoa_accounting.repositories.accounts_repo import AccountsRepository
from hoa_accounting.web.template_engine import render_template

_FUND_CODES = ["OPERATING", "RESERVE", "SPECIAL"]
_GROUP_CODES = [
    "LANDSCAPE", "SEWER", "ROAD", "WALL", "ENTRANCE",
    "UTILITIES", "INSURANCE", "MISC", "FIREWISE",
]

_BASE_CTX = {
    "active_nav": "master-data",
    "page_key": "accounts",
    "breadcrumb": "Master Data",
}


@dataclass(frozen=True)
class AccountPageResponse:
    status_code: int
    body_html: str


def _require(raw: str, label: str) -> str:
    value = (raw or "").strip()
    if not value:
        raise ValidationError(f"{label} is required.")
    return value


def _opt(raw: str) -> str | None:
    return (raw or "").strip() or None


class AccountPages:
    """Render and handle the Chart of Accounts management pages."""

    LIST_TEMPLATE = "accounts_list.html"
    FORM_TEMPLATE = "account_form.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.repo = AccountsRepository(conn)

    # ── List page ─────────────────────────────────────────────────────

    def render_list(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        flash_message: str = "",
        error_message: str = "",
    ) -> AccountPageResponse:
        rows = self.repo.list_chart(active_only=False)
        accounts = [dict(r) for r in rows]
        ctx = {
            **_BASE_CTX,
            "heading": "Chart of Accounts",
            "org": org or {},
            "theme": theme,
            "accounts": accounts,
            "flash_message": flash_message,
            "error_message": error_message,
        }
        return AccountPageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.LIST_TEMPLATE, ctx),
        )

    # ── Add / Edit form (GET) ──────────────────────────────────────────

    def render_form(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        account_id: int | None = None,
        form_values: dict[str, str] | None = None,
        error_message: str = "",
    ) -> AccountPageResponse:
        is_edit = account_id is not None
        values: dict[str, str] = {}

        if is_edit and form_values is None:
            row = self.repo.get_account(account_id)
            if row is None:
                return AccountPageResponse(
                    status_code=HTTPStatus.NOT_FOUND,
                    body_html="<h1>Account not found</h1>",
                )
            values = {
                "account_number": row["account_number"] or "",
                "account_name": row["account_name"] or "",
                "account_type_id": str(row["account_type_id"]),
                "fund_code": row["fund_code"] or "OPERATING",
                "group_code": row["group_code"] or "",
                "is_bank_account": "1" if row["is_bank_account"] else "0",
                "is_active": str(row["is_active"]),
                "description": row["description"] or "",
            }
        else:
            values = form_values or {}

        account_types = [dict(r) for r in self.repo.list_account_types()]
        has_act = is_edit and self.repo.has_activity(account_id)  # type: ignore[arg-type]

        heading = "Edit Account" if is_edit else "Add Account"
        breadcrumb = "Master Data · Chart of Accounts"
        ctx = {
            **_BASE_CTX,
            "heading": heading,
            "breadcrumb": breadcrumb,
            "org": org or {},
            "theme": theme,
            "is_edit": is_edit,
            "account_id": account_id,
            "has_activity": has_act,
            "account_types": account_types,
            "fund_codes": _FUND_CODES,
            "group_codes": _GROUP_CODES,
            "values": {
                "account_number": values.get("account_number", ""),
                "account_name": values.get("account_name", ""),
                "account_type_id": values.get("account_type_id", ""),
                "fund_code": values.get("fund_code", "OPERATING"),
                "group_code": values.get("group_code", ""),
                "is_bank_account": values.get("is_bank_account", "0"),
                "is_active": values.get("is_active", "1"),
                "description": values.get("description", ""),
            },
            "error_message": error_message,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return AccountPageResponse(
            status_code=status,
            body_html=render_template(self.FORM_TEMPLATE, ctx),
        )

    # ── Add account (POST) ─────────────────────────────────────────────

    def handle_add(
        self,
        *,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, AccountPageResponse | None]:
        try:
            account_number = _require(form_data.get("account_number", ""), "Account Number")
            account_name = _require(form_data.get("account_name", ""), "Account Name")
            account_type_id_raw = (form_data.get("account_type_id") or "").strip()
            if not account_type_id_raw:
                raise ValidationError("Account Type is required.")
            account_type_id = int(account_type_id_raw)
            fund_code = (form_data.get("fund_code") or "").strip()
            if fund_code not in _FUND_CODES:
                raise ValidationError("Fund Code is required.")
            if self.repo.account_number_exists(account_number):
                raise ValidationError(
                    f"Account number {account_number!r} is already in use."
                )
            group_code = _opt(form_data.get("group_code", ""))
            is_bank_account = form_data.get("is_bank_account") == "1"
            description = _opt(form_data.get("description", ""))

            self.repo.insert_account(
                account_number=account_number,
                account_name=account_name,
                account_type_id=account_type_id,
                fund_code=fund_code,
                group_code=group_code,
                is_bank_account=is_bank_account,
                description=description,
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
        return "/accounts?msg=Account+added.", None

    # ── Edit account (POST) ────────────────────────────────────────────

    def handle_edit(
        self,
        *,
        account_id: int,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, AccountPageResponse | None]:
        try:
            account_number = _require(form_data.get("account_number", ""), "Account Number")
            account_name = _require(form_data.get("account_name", ""), "Account Name")
            account_type_id_raw = (form_data.get("account_type_id") or "").strip()
            if not account_type_id_raw:
                raise ValidationError("Account Type is required.")
            account_type_id = int(account_type_id_raw)
            fund_code = (form_data.get("fund_code") or "").strip()
            if fund_code not in _FUND_CODES:
                raise ValidationError("Fund Code is required.")
            if self.repo.account_number_exists(account_number, exclude_id=account_id):
                raise ValidationError(
                    f"Account number {account_number!r} is already in use by another account."
                )
            group_code = _opt(form_data.get("group_code", ""))
            is_bank_account = form_data.get("is_bank_account") == "1"
            description = _opt(form_data.get("description", ""))

            if form_data.get("_is_active_present"):
                is_active = form_data.get("is_active") == "1"
            else:
                is_active = True

            self.repo.update_account(
                account_id,
                account_number=account_number,
                account_name=account_name,
                account_type_id=account_type_id,
                fund_code=fund_code,
                group_code=group_code,
                is_bank_account=is_bank_account,
                is_active=is_active,
                description=description,
            )
            self.conn.commit()
        except ValidationError as exc:
            return None, self.render_form(
                org=org, theme=theme,
                account_id=account_id,
                form_values=form_data,
                error_message=str(exc),
            )
        except Exception:
            self.conn.rollback()
            raise
        return "/accounts?msg=Account+updated.", None

    # ── Delete account (POST) ──────────────────────────────────────────

    def handle_delete(
        self,
        *,
        account_id: int,
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, AccountPageResponse | None]:
        try:
            if self.repo.has_activity(account_id):
                raise ValidationError(
                    "Cannot delete an account that has posted activity. "
                    "Deactivate it instead."
                )
            self.repo.delete_account(account_id)
            self.conn.commit()
        except ValidationError as exc:
            return None, self.render_form(
                org=org, theme=theme,
                account_id=account_id,
                error_message=str(exc),
            )
        except Exception:
            self.conn.rollback()
            raise
        return "/accounts?msg=Account+deleted.", None
