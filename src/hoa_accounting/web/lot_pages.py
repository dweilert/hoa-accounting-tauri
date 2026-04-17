"""Lot management pages.

Routes handled:
  GET  /lots                — list all lots (active + inactive)
  GET  /lots/add            — blank add form
  POST /lots/add            — submit new lot
  GET  /lots/<id>/edit      — edit form pre-filled
  POST /lots/<id>/edit      — submit edits
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from http import HTTPStatus

from hoa_accounting.exceptions import ValidationError
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.web.template_engine import render_template


@dataclass(frozen=True)
class LotPageResponse:
    status_code: int
    body_html: str


def _require(raw: str, label: str) -> str:
    value = (raw or "").strip()
    if not value:
        raise ValidationError(f"{label} is required.")
    return value


def _opt(raw: str) -> str | None:
    return (raw or "").strip() or None


_BASE_CTX = {
    "active_nav": "master-data",
    "page_key": "lots",
    "breadcrumb": "Master Data",
}


class LotPages:
    """Render and handle the lot management pages."""

    LIST_TEMPLATE = "lots_list.html"
    FORM_TEMPLATE = "lot_form.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.repo = LotsRepository(conn)

    # ── List page ─────────────────────────────────────────────────

    def render_list(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        flash_message: str = "",
        error_message: str = "",
    ) -> LotPageResponse:
        rows = self.repo.list_lots_with_occupancy(active_only=False)
        lots = [dict(r) for r in rows]
        ctx = {
            **_BASE_CTX,
            "heading": "Lots",
            "org": org or {},
            "theme": theme,
            "lots": lots,
            "flash_message": flash_message,
            "error_message": error_message,
        }
        return LotPageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.LIST_TEMPLATE, ctx),
        )

    # ── Add / Edit form (GET) ──────────────────────────────────────

    def render_form(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        lot_id: int | None = None,
        form_values: dict[str, str] | None = None,
        error_message: str = "",
    ) -> LotPageResponse:
        is_edit = lot_id is not None
        values: dict[str, str] = {}

        if is_edit and form_values is None:
            row = self.repo.get_lot(lot_id)
            if row is None:
                return LotPageResponse(
                    status_code=HTTPStatus.NOT_FOUND,
                    body_html="<h1>Lot not found</h1>",
                )
            values = {
                "lot_number": row["lot_number"] or "",
                "street_address_1": row["street_address_1"] or "",
                "street_address_2": row["street_address_2"] or "",
                "city": row["city"] or "",
                "state": row["state"] or "",
                "postal_code": row["postal_code"] or "",
                "legal_description": row["legal_description"] or "",
                "active_flag": str(row["active_flag"]),
            }
        else:
            values = form_values or {}

        heading = "Edit Lot" if is_edit else "Add Lot"
        breadcrumb = "Master Data · Lots"
        ctx = {
            **_BASE_CTX,
            "heading": heading,
            "breadcrumb": breadcrumb,
            "org": org or {},
            "theme": theme,
            "is_edit": is_edit,
            "lot_id": lot_id,
            "values": {
                "lot_number": values.get("lot_number", ""),
                "street_address_1": values.get("street_address_1", ""),
                "street_address_2": values.get("street_address_2", ""),
                "city": values.get("city", ""),
                "state": values.get("state", ""),
                "postal_code": values.get("postal_code", ""),
                "legal_description": values.get("legal_description", ""),
                "active_flag": values.get("active_flag", "1"),
            },
            "error_message": error_message,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return LotPageResponse(
            status_code=status,
            body_html=render_template(self.FORM_TEMPLATE, ctx),
        )

    # ── Add lot (POST) ─────────────────────────────────────────────

    def handle_add(
        self,
        *,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, LotPageResponse | None]:
        try:
            lot_number = _require(form_data.get("lot_number", ""), "Lot Number")

            if self.repo.lot_number_exists(lot_number):
                raise ValidationError(
                    f"Lot number \"{lot_number}\" is already in use."
                )

            self.repo.insert_lot(
                lot_number=lot_number,
                street_address_1=_opt(form_data.get("street_address_1", "")),
                street_address_2=_opt(form_data.get("street_address_2", "")),
                city=_opt(form_data.get("city", "")),
                state=_opt(form_data.get("state", "")),
                postal_code=_opt(form_data.get("postal_code", "")),
                legal_description=_opt(form_data.get("legal_description", "")),
            )
            self.conn.commit()

        except ValidationError as exc:
            return None, self.render_form(
                org=org, theme=theme,
                form_values=form_data,
                error_message=str(exc),
            )
        return "/lots?msg=Lot+added.", None

    # ── Edit lot (POST) ────────────────────────────────────────────

    def handle_edit(
        self,
        *,
        lot_id: int,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, LotPageResponse | None]:
        try:
            lot_number = _require(form_data.get("lot_number", ""), "Lot Number")

            if self.repo.lot_number_exists(lot_number, exclude_id=lot_id):
                raise ValidationError(
                    f"Lot number \"{lot_number}\" is already in use by another lot."
                )

            active_flag = form_data.get("active_flag", "1") == "1"
            self.repo.update_lot(
                lot_id=lot_id,
                lot_number=lot_number,
                street_address_1=_opt(form_data.get("street_address_1", "")),
                street_address_2=_opt(form_data.get("street_address_2", "")),
                city=_opt(form_data.get("city", "")),
                state=_opt(form_data.get("state", "")),
                postal_code=_opt(form_data.get("postal_code", "")),
                legal_description=_opt(form_data.get("legal_description", "")),
                active_flag=active_flag,
            )
            self.conn.commit()

        except ValidationError as exc:
            return None, self.render_form(
                org=org, theme=theme,
                lot_id=lot_id,
                form_values=form_data,
                error_message=str(exc),
            )
        return "/lots?msg=Lot+updated.", None

    # ── Delete lot (POST) ──────────────────────────────────────────

    def handle_delete(
        self,
        *,
        lot_id: int,
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, LotPageResponse | None]:
        try:
            if self.repo.has_current_owners(lot_id):
                raise ValidationError(
                    "Cannot delete a lot that has a current owner. "
                    "Mark the owner as Previous first."
                )
            if self.repo.has_current_renters(lot_id):
                raise ValidationError(
                    "Cannot delete a lot that has a current renter. "
                    "End the tenancy first."
                )
            self.repo.delete_lot(lot_id)
            self.conn.commit()
        except ValidationError as exc:
            return None, self.render_form(
                org=org, theme=theme,
                lot_id=lot_id,
                error_message=str(exc),
            )
        return "/lots?msg=Lot+deleted.", None
