"""Owner management pages.

Routes handled:
  GET  /owners                — list all active owners with their current lots
  GET  /owners/add            — blank add form
  POST /owners/add            — submit new owner (contact info only)
  GET  /owners/<id>/edit      — edit form pre-filled
  POST /owners/<id>/edit      — submit edits (contact info only)
  POST /owners/<id>/delete    — hard-delete (blocked if has current lots)

Lot-owner linking is managed from the Lot screen (/lots/<id>/edit).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from http import HTTPStatus

from hoa_accounting.exceptions import ValidationError
from hoa_accounting.repositories.owners_repo import OwnersRepository
from hoa_accounting.web.template_engine import render_template
from hoa_accounting.validators.forms import opt as _opt, require as _require


@dataclass(frozen=True)
class OwnerPageResponse:
    status_code: int
    body_html: str


_BASE_CTX = {
    "active_nav": "master-data",
    "page_key": "owners",
    "breadcrumb": "Master Data",
}


class OwnerPages:
    """Render and handle the owner management pages."""

    LIST_TEMPLATE = "owners_list.html"
    FORM_TEMPLATE = "owner_form.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.repo = OwnersRepository(conn)

    # ── List page ─────────────────────────────────────────────────────

    def render_list(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        flash_message: str = "",
        error_message: str = "",
    ) -> OwnerPageResponse:
        rows = self.repo.list_owners_with_lots()
        owners = [dict(r) for r in rows]
        ctx = {
            **_BASE_CTX,
            "heading": "Owners",
            "org": org or {},
            "theme": theme,
            "owners": owners,
            "flash_message": flash_message,
            "error_message": error_message,
        }
        return OwnerPageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.LIST_TEMPLATE, ctx),
        )

    # ── Add / Edit form (GET) ──────────────────────────────────────────

    def render_form(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        owner_id: int | None = None,
        form_values: dict[str, str] | None = None,
        error_message: str = "",
    ) -> OwnerPageResponse:
        is_edit = owner_id is not None
        values: dict[str, str] = {}

        if owner_id is not None and form_values is None:
            row = self.repo.get_owner(owner_id)
            if row is None:
                return OwnerPageResponse(
                    status_code=HTTPStatus.NOT_FOUND,
                    body_html="<h1>Owner not found</h1>",
                )
            values = {
                "owner_type":   row["owner_type"]   or "PERSON",
                "display_name": row["display_name"] or "",
                "first_name":   row["first_name"]   or "",
                "last_name":    row["last_name"]     or "",
                "entity_name":  row["entity_name"]  or "",
                "email":        row["email"]         or "",
                "phone":        row["phone"]         or "",
                "home_phone":   row["home_phone"]    or "",
                "notes":        row["notes"]         or "",
            }
        else:
            values = form_values or {}

        heading    = "Edit Owner" if is_edit else "Add Owner"
        breadcrumb = "Master Data · Owners"
        ctx = {
            **_BASE_CTX,
            "heading":       heading,
            "breadcrumb":    breadcrumb,
            "org":           org or {},
            "theme":         theme,
            "is_edit":       is_edit,
            "owner_id":      owner_id,
            "values": {
                "owner_type":   values.get("owner_type",   "PERSON"),
                "display_name": values.get("display_name", ""),
                "first_name":   values.get("first_name",   ""),
                "last_name":    values.get("last_name",    ""),
                "entity_name":  values.get("entity_name",  ""),
                "email":        values.get("email",        ""),
                "phone":        values.get("phone",        ""),
                "home_phone":   values.get("home_phone",   ""),
                "notes":        values.get("notes",        ""),
            },
            "error_message": error_message,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return OwnerPageResponse(
            status_code=status,
            body_html=render_template(self.FORM_TEMPLATE, ctx),
        )

    # ── Add owner (POST) ───────────────────────────────────────────────

    def handle_add(
        self,
        *,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, OwnerPageResponse | None]:
        try:
            owner_type   = _require(form_data.get("owner_type",   ""), "Owner Type")
            display_name = _require(form_data.get("display_name", ""), "Display Name")
            self.repo.insert_owner(
                owner_type=owner_type,
                display_name=display_name,
                first_name=_opt(form_data.get("first_name",  "")),
                last_name=_opt(form_data.get("last_name",   "")),
                entity_name=_opt(form_data.get("entity_name", "")),
                email=_opt(form_data.get("email",       "")),
                phone=_opt(form_data.get("phone",       "")),
                home_phone=_opt(form_data.get("home_phone", "")),
                notes=_opt(form_data.get("notes",       "")),
            )
            self.conn.commit()
        except ValidationError as exc:
            return None, self.render_form(
                org=org, theme=theme,
                form_values=form_data, error_message=str(exc),
            )
        except Exception:
            self.conn.rollback()
            raise
        return "/owners?msg=Owner+added.+Use+the+Lot+screen+to+assign+a+lot.", None

    # ── Edit owner (POST) ──────────────────────────────────────────────

    def handle_edit(
        self,
        *,
        owner_id: int,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, OwnerPageResponse | None]:
        try:
            owner_type   = _require(form_data.get("owner_type",   ""), "Owner Type")
            display_name = _require(form_data.get("display_name", ""), "Display Name")
            self.repo.update_owner(
                owner_id=owner_id,
                owner_type=owner_type,
                display_name=display_name,
                first_name=_opt(form_data.get("first_name",  "")),
                last_name=_opt(form_data.get("last_name",   "")),
                entity_name=_opt(form_data.get("entity_name", "")),
                email=_opt(form_data.get("email",       "")),
                phone=_opt(form_data.get("phone",       "")),
                home_phone=_opt(form_data.get("home_phone", "")),
                notes=_opt(form_data.get("notes",       "")),
            )
            self.conn.commit()
        except ValidationError as exc:
            return None, self.render_form(
                org=org, theme=theme,
                owner_id=owner_id, form_values=form_data,
                error_message=str(exc),
            )
        except Exception:
            self.conn.rollback()
            raise
        return "/owners?msg=Owner+updated.", None

    # ── Delete owner (POST) ────────────────────────────────────────────

    def handle_delete(
        self,
        *,
        owner_id: int,
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, OwnerPageResponse | None]:
        try:
            self.repo.deactivate_owner(owner_id)
            self.conn.commit()
        except Exception as exc:
            return None, self.render_form(
                org=org, theme=theme,
                owner_id=owner_id, error_message=str(exc),
            )
        return "/owners?msg=Owner+deactivated.", None
