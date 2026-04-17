"""Owner management pages.

Routes handled:
  GET  /owners                      — list all active owners with current lot
  GET  /owners/add                  — blank add form
  POST /owners/add                  — submit new owner (+ optional lot assignment)
  GET  /owners/<id>/edit            — edit form pre-filled
  POST /owners/<id>/edit            — submit edits
  POST /owners/<id>/mark-previous   — mark ownership as previous (set end_date)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date as _date
from http import HTTPStatus

from hoa_accounting.exceptions import ValidationError
from hoa_accounting.repositories.lot_ownership_repo import LotOwnershipRepository
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.repositories.owners_repo import OwnersRepository
from hoa_accounting.web.template_engine import render_template


@dataclass(frozen=True)
class OwnerPageResponse:
    status_code: int
    body_html: str


def _today() -> str:
    return _date.today().isoformat()


def _require(raw: str, label: str) -> str:
    value = (raw or "").strip()
    if not value:
        raise ValidationError(f"{label} is required.")
    return value


def _parse_int(raw: str, label: str) -> int:
    try:
        return int((raw or "").strip())
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} is required.") from exc


def _opt(raw: str) -> str | None:
    return (raw or "").strip() or None


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
        self.ownership_repo = LotOwnershipRepository(conn)
        self.lots_repo = LotsRepository(conn)

    def _lot_options(self) -> list[dict]:
        rows = self.lots_repo.list_lots(active_only=True)
        return [
            {
                "id": r["id"],
                "label": f"{r['lot_number']} — {r['street_address_1'] or ''}".strip(" —"),
            }
            for r in rows
        ]

    # ── List page ─────────────────────────────────────────────────

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
            "today": _today(),
            "flash_message": flash_message,
            "error_message": error_message,
        }
        return OwnerPageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.LIST_TEMPLATE, ctx),
        )

    # ── Add / Edit form (GET) ──────────────────────────────────────

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

        if is_edit and form_values is None:
            row = self.repo.get_owner(owner_id)
            if row is None:
                return OwnerPageResponse(
                    status_code=HTTPStatus.NOT_FOUND,
                    body_html="<h1>Owner not found</h1>",
                )
            current_ownership = self.ownership_repo.get_current_ownership_by_owner(owner_id)
            values = {
                "owner_type": row["owner_type"] or "PERSON",
                "display_name": row["display_name"] or "",
                "first_name": row["first_name"] or "",
                "last_name": row["last_name"] or "",
                "entity_name": row["entity_name"] or "",
                "email": row["email"] or "",
                "phone": row["phone"] or "",
                "notes": row["notes"] or "",
                "current_lot_number": (
                    current_ownership["lot_number"] if current_ownership else ""
                ),
                "current_lot_address": (
                    current_ownership["street_address_1"] if current_ownership else ""
                ),
                "is_primary_contact": (
                    str(current_ownership["is_primary_contact"])
                    if current_ownership else "1"
                ),
            }
        else:
            values = form_values or {}

        # Lot options are needed on add, and on edit when owner has no current lot
        has_lot = bool(values.get("current_lot_number", ""))
        needs_lot_options = not is_edit or (is_edit and not has_lot)

        heading = "Edit Owner" if is_edit else "Add Owner"
        breadcrumb = "Master Data · Owners"
        ctx = {
            **_BASE_CTX,
            "heading": heading,
            "breadcrumb": breadcrumb,
            "org": org or {},
            "theme": theme,
            "is_edit": is_edit,
            "owner_id": owner_id,
            "lot_options": self._lot_options() if needs_lot_options else [],
            "values": {
                "owner_type": values.get("owner_type", "PERSON"),
                "display_name": values.get("display_name", ""),
                "first_name": values.get("first_name", ""),
                "last_name": values.get("last_name", ""),
                "entity_name": values.get("entity_name", ""),
                "email": values.get("email", ""),
                "phone": values.get("phone", ""),
                "notes": values.get("notes", ""),
                "lot_id": values.get("lot_id", ""),
                "start_date": values.get("start_date", _today()),
                "is_primary_contact": values.get("is_primary_contact", "1"),
                # edit-only display values
                "current_lot_number": values.get("current_lot_number", ""),
                "current_lot_address": values.get("current_lot_address", ""),
            },
            "error_message": error_message,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return OwnerPageResponse(
            status_code=status,
            body_html=render_template(self.FORM_TEMPLATE, ctx),
        )

    # ── Add owner (POST) ───────────────────────────────────────────

    def handle_add(
        self,
        *,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, OwnerPageResponse | None]:
        try:
            owner_type = _require(form_data.get("owner_type", ""), "Owner Type")
            display_name = _require(form_data.get("display_name", ""), "Display Name")

            owner_id = self.repo.insert_owner(
                owner_type=owner_type,
                display_name=display_name,
                first_name=_opt(form_data.get("first_name", "")),
                last_name=_opt(form_data.get("last_name", "")),
                entity_name=_opt(form_data.get("entity_name", "")),
                email=_opt(form_data.get("email", "")),
                phone=_opt(form_data.get("phone", "")),
                notes=_opt(form_data.get("notes", "")),
            )

            # Required lot assignment
            lot_id = _parse_int(form_data.get("lot_id", ""), "Lot")
            start_date = _require(form_data.get("start_date", ""), "Start Date")
            is_primary = form_data.get("is_primary_contact", "1") == "1"

            count = self.ownership_repo.count_current_owners(lot_id)
            if count >= 2:
                raise ValidationError(
                    "This lot already has two current owners. "
                    "Mark one as Previous before adding another."
                )
            if is_primary and self.ownership_repo.has_current_primary(lot_id):
                raise ValidationError(
                    "This lot already has an Owner 1. "
                    "Assign as Owner 2 or mark the existing Owner 1 as Previous first."
                )
            if not is_primary:
                existing = self.ownership_repo.get_current_ownerships(lot_id)
                secondaries = [r for r in existing if not r["is_primary_contact"]]
                if secondaries:
                    raise ValidationError(
                        "This lot already has an Owner 2. "
                        "Mark the existing Owner 2 as Previous before adding another."
                    )

            self.ownership_repo.assign_owner(
                lot_id=lot_id,
                owner_id=owner_id,
                start_date=start_date,
                is_primary_contact=is_primary,
            )

            self.conn.commit()

        except ValidationError as exc:
            return None, self.render_form(
                org=org, theme=theme,
                form_values=form_data,
                error_message=str(exc),
            )
        return "/owners?msg=Owner+added.", None

    # ── Edit owner (POST) ──────────────────────────────────────────

    def handle_edit(
        self,
        *,
        owner_id: int,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, OwnerPageResponse | None]:
        try:
            owner_type = _require(form_data.get("owner_type", ""), "Owner Type")
            display_name = _require(form_data.get("display_name", ""), "Display Name")

            self.repo.update_owner(
                owner_id=owner_id,
                owner_type=owner_type,
                display_name=display_name,
                first_name=_opt(form_data.get("first_name", "")),
                last_name=_opt(form_data.get("last_name", "")),
                entity_name=_opt(form_data.get("entity_name", "")),
                email=_opt(form_data.get("email", "")),
                phone=_opt(form_data.get("phone", "")),
                notes=_opt(form_data.get("notes", "")),
            )

            # If owner has no current lot and a lot was submitted, assign it now
            has_no_lot = self.ownership_repo.get_current_ownership_by_owner(owner_id) is None
            lot_id_raw = _opt(form_data.get("lot_id", ""))
            if has_no_lot and lot_id_raw:
                lot_id = _parse_int(lot_id_raw, "Lot")
                start_date = _require(form_data.get("start_date", ""), "Start Date")
                is_primary = form_data.get("is_primary_contact", "1") == "1"

                count = self.ownership_repo.count_current_owners(lot_id)
                if count >= 2:
                    raise ValidationError(
                        "This lot already has two current owners. "
                        "Mark one as Previous before adding another."
                    )
                if is_primary and self.ownership_repo.has_current_primary(lot_id):
                    raise ValidationError(
                        "This lot already has an Owner 1. "
                        "Assign as Owner 2 or mark the existing Owner 1 as Previous first."
                    )
                if not is_primary:
                    existing = self.ownership_repo.get_current_ownerships(lot_id)
                    secondaries = [r for r in existing if not r["is_primary_contact"]]
                    if secondaries:
                        raise ValidationError(
                            "This lot already has an Owner 2. "
                            "Mark the existing Owner 2 as Previous before adding another."
                        )
                self.ownership_repo.assign_owner(
                    lot_id=lot_id,
                    owner_id=owner_id,
                    start_date=start_date,
                    is_primary_contact=is_primary,
                )

            self.conn.commit()

        except ValidationError as exc:
            return None, self.render_form(
                org=org, theme=theme,
                owner_id=owner_id,
                form_values=form_data,
                error_message=str(exc),
            )
        return "/owners?msg=Owner+updated.", None

    # ── Mark as Previous (POST) ────────────────────────────────────

    def handle_mark_previous(
        self,
        *,
        owner_id: int,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, OwnerPageResponse | None]:
        try:
            end_date = _require(form_data.get("end_date", ""), "End Date")
            ownership = self.ownership_repo.get_current_ownership_by_owner(owner_id)
            if ownership is None:
                raise ValidationError("This owner has no current lot assignment to end.")
            self.ownership_repo.end_ownership(
                ownership_id=ownership["id"],
                end_date=end_date,
            )
            self.conn.commit()
        except ValidationError as exc:
            return None, self.render_list(
                org=org, theme=theme, error_message=str(exc),
            )
        return "/owners?msg=Owner+marked+as+previous.", None
