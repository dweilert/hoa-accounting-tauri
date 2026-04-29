"""Lot management pages.

Routes handled:
  GET  /lots                                        — list all lots
  GET  /lots/add                                    — blank add form
  POST /lots/add                                    — submit new lot
  GET  /lots/<id>/edit                              — edit form pre-filled
  POST /lots/<id>/edit                              — submit edits
  POST /lots/<id>/delete                            — hard-delete
  POST /lots/<id>/owners/link                       — link an owner to this lot
  POST /lots/<id>/owners/<ownership_id>/end         — end an ownership
  POST /lots/<id>/owners/<ownership_id>/edit-dates  — change start/end dates
"""

from __future__ import annotations
from typing import Any

import sqlite3
from dataclasses import dataclass
from datetime import date
from http import HTTPStatus

from hoa_accounting.exceptions import ValidationError
from hoa_accounting.repositories.lot_ownership_repo import LotOwnershipRepository
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.repositories.owners_repo import OwnersRepository
from hoa_accounting.web.template_engine import render_template
from hoa_accounting.validators.forms import opt as _opt, require as _require


@dataclass(frozen=True)
class LotPageResponse:
    status_code: int
    body_html: str


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
        self.ownership_repo = LotOwnershipRepository(conn)
        self.owners_repo = OwnersRepository(conn)

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
        flash_message: str = "",
        error_message: str = "",
        ownership_error: str = "",
    ) -> LotPageResponse:
        is_edit = lot_id is not None
        values: dict[str, str] = {}

        if lot_id is not None and form_values is None:
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

        # Build owner data for the edit view
        current_ownerships: list[dict[str, Any]] = []
        owner_options: list[dict[str, Any]] = []
        if lot_id is not None:
            current_ownerships = [
                dict(r) for r in self.ownership_repo.get_current_ownerships(lot_id)
            ]
            all_owners = self.owners_repo.list_owners(active_only=True)
            # Exclude owners already linked to this lot
            linked_ids = {o["owner_id"] for o in current_ownerships}

            def _owner_label(r: sqlite3.Row) -> str:
                first = (r["first_name"] or "").strip()
                last = (r["last_name"] or "").strip()
                name = (
                    f"{first} {last}".strip() if (first or last) else r["display_name"]
                )
                return name

            owner_options = [
                {"id": r["id"], "label": _owner_label(r)}
                for r in all_owners
                if r["id"] not in linked_ids
            ]

        heading = "Edit Lot" if is_edit else "Add Lot"
        breadcrumb = "Master Data · Lots"
        ctx = {
            **_BASE_CTX,
            "heading": heading,
            "breadcrumb": breadcrumb,
            "parent_url": "/lots",
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
            "current_ownerships": current_ownerships,
            "owner_options": owner_options,
            "today": date.today().isoformat(),
            "flash_message": flash_message,
            "error_message": error_message,
            "ownership_error": ownership_error,
        }
        status = (
            HTTPStatus.BAD_REQUEST
            if (error_message or ownership_error)
            else HTTPStatus.OK
        )
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
                raise ValidationError(f'Lot number "{lot_number}" is already in use.')

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
                org=org,
                theme=theme,
                form_values=form_data,
                error_message=str(exc),
            )
        except Exception:
            self.conn.rollback()
            raise
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
                    f'Lot number "{lot_number}" is already in use by another lot.'
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
                org=org,
                theme=theme,
                lot_id=lot_id,
                form_values=form_data,
                error_message=str(exc),
            )
        except Exception:
            self.conn.rollback()
            raise
        return f"/lots/{lot_id}/edit?msg=Lot+updated.", None

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
                    "End the ownership first."
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
                org=org,
                theme=theme,
                lot_id=lot_id,
                error_message=str(exc),
            )
        except Exception:
            self.conn.rollback()
            raise
        return "/lots?msg=Lot+deleted.", None

    # ── Link owner (POST) ──────────────────────────────────────────

    def handle_link_owner(
        self,
        *,
        lot_id: int,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, LotPageResponse | None]:
        try:
            owner_id_str = (form_data.get("owner_id") or "").strip()
            if not owner_id_str:
                raise ValidationError("Owner is required.")
            try:
                owner_id = int(owner_id_str)
            except ValueError:
                raise ValidationError("Invalid owner selection.")

            start_date = _require(form_data.get("start_date", ""), "Start Date")

            if self.ownership_repo.owner_already_linked(lot_id, owner_id):
                raise ValidationError(
                    "That owner is already a current owner of this lot."
                )

            self.ownership_repo.assign_owner(
                lot_id=lot_id,
                owner_id=owner_id,
                start_date=start_date,
            )
            self.conn.commit()
        except ValidationError as exc:
            return None, self.render_form(
                org=org,
                theme=theme,
                lot_id=lot_id,
                ownership_error=str(exc),
            )
        except Exception:
            self.conn.rollback()
            raise
        return f"/lots/{lot_id}/edit?msg=Owner+linked.", None

    # ── End ownership (POST) ───────────────────────────────────────

    def handle_end_ownership(
        self,
        *,
        lot_id: int,
        ownership_id: int,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, LotPageResponse | None]:
        try:
            end_date = _require(form_data.get("end_date", ""), "End Date")
            self.ownership_repo.end_ownership(
                ownership_id=ownership_id,
                end_date=end_date,
            )
            self.conn.commit()
        except ValidationError as exc:
            return None, self.render_form(
                org=org,
                theme=theme,
                lot_id=lot_id,
                ownership_error=str(exc),
            )
        except Exception:
            self.conn.rollback()
            raise
        return f"/lots/{lot_id}/edit?msg=Ownership+ended.", None

    # ── Edit ownership dates (POST) ────────────────────────────────

    def handle_edit_ownership_dates(
        self,
        *,
        lot_id: int,
        ownership_id: int,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, LotPageResponse | None]:
        try:
            start_date = _require(form_data.get("start_date", ""), "Start Date")
            end_date = _opt(form_data.get("end_date", ""))
            self.ownership_repo.update_ownership_dates(
                ownership_id=ownership_id,
                start_date=start_date,
                end_date=end_date,
            )
            self.conn.commit()
        except ValidationError as exc:
            return None, self.render_form(
                org=org,
                theme=theme,
                lot_id=lot_id,
                ownership_error=str(exc),
            )
        except Exception:
            self.conn.rollback()
            raise
        return f"/lots/{lot_id}/edit?msg=Ownership+dates+updated.", None
