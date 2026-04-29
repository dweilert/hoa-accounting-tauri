"""Standalone renter management pages.

Routes handled:
  GET  /renters                    — list all renters (current + ended)
  GET  /renters/add                — blank add form
  POST /renters/add                — submit new renter
  GET  /renters/<id>/edit          — edit form pre-filled
  POST /renters/<id>/edit          — submit edits
  POST /renters/<id>/end           — end tenancy (inline form on list page)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date as _date
from http import HTTPStatus

from hoa_accounting.exceptions import ValidationError
from hoa_accounting.repositories.lot_renters_repo import LotRentersRepository
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.web.template_engine import render_template
from hoa_accounting.validators.forms import opt as _opt, parse_int as _parse_int, require as _require


@dataclass(frozen=True)
class RenterPageResponse:
    status_code: int
    body_html: str


def _today() -> str:
    return _date.today().isoformat()


_BASE_CTX = {
    "active_nav": "master-data",
    "page_key": "renters",
    "breadcrumb": "Master Data",
}


class LotRentersPages:
    """Render and handle the standalone renter management pages."""

    LIST_TEMPLATE = "renters_list.html"
    FORM_TEMPLATE = "renter_form.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.repo = LotRentersRepository(conn)
        self.lots_repo = LotsRepository(conn)

    def _lot_options(self) -> list[dict]:
        rows = self.lots_repo.list_lots(active_only=False)
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
    ) -> RenterPageResponse:
        rows = self.repo.list_all_renters()
        renters = [dict(r) for r in rows]
        ctx = {
            **_BASE_CTX,
            "heading": "Renters",
            "org": org or {},
            "theme": theme,
            "renters": renters,
            "today": _today(),
            "flash_message": flash_message,
            "error_message": error_message,
        }
        return RenterPageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.LIST_TEMPLATE, ctx),
        )

    # ── Add / Edit form (GET) ──────────────────────────────────────

    def render_form(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        renter_id: int | None = None,
        form_values: dict[str, str] | None = None,
        error_message: str = "",
    ) -> RenterPageResponse:
        is_edit = renter_id is not None
        values: dict[str, str] = {}

        if is_edit and form_values is None:
            row = self.repo.get_renter(renter_id)
            if row is None:
                return RenterPageResponse(
                    status_code=HTTPStatus.NOT_FOUND,
                    body_html="<h1>Renter not found</h1>",
                )
            values = {
                "lot_id": str(row["lot_id"]),
                "display_name": row["display_name"] or "",
                "first_name": row["first_name"] or "",
                "last_name": row["last_name"] or "",
                "email": row["email"] or "",
                "phone": row["phone"] or "",
                "start_date": row["start_date"] or "",
                "notes": row["notes"] or "",
            }
        else:
            values = form_values or {}

        heading = "Edit Renter" if is_edit else "Add Renter"
        breadcrumb = "Master Data \u00b7 Renters"
        ctx = {
            **_BASE_CTX,
            "heading": heading,
            "breadcrumb": breadcrumb,
            "org": org or {},
            "theme": theme,
            "is_edit": is_edit,
            "renter_id": renter_id,
            "lot_options": self._lot_options(),
            "values": {
                "lot_id": values.get("lot_id", ""),
                "display_name": values.get("display_name", ""),
                "first_name": values.get("first_name", ""),
                "last_name": values.get("last_name", ""),
                "email": values.get("email", ""),
                "phone": values.get("phone", ""),
                "start_date": values.get("start_date", _today()),
                "notes": values.get("notes", ""),
            },
            "error_message": error_message,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return RenterPageResponse(
            status_code=status,
            body_html=render_template(self.FORM_TEMPLATE, ctx),
        )

    # ── Add renter (POST) ──────────────────────────────────────────

    def handle_add(
        self,
        *,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, RenterPageResponse | None]:
        try:
            lot_id = _parse_int(form_data.get("lot_id", ""), "Lot")
            display_name = _require(form_data.get("display_name", ""), "Display Name")
            start_date = _require(form_data.get("start_date", ""), "Start Date")
            self.repo.insert_renter(
                lot_id=lot_id,
                display_name=display_name,
                first_name=_opt(form_data.get("first_name", "")),
                last_name=_opt(form_data.get("last_name", "")),
                email=_opt(form_data.get("email", "")),
                phone=_opt(form_data.get("phone", "")),
                start_date=start_date,
                notes=_opt(form_data.get("notes", "")),
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
        return "/renters?msg=Renter+added.", None

    # ── Edit renter (POST) ─────────────────────────────────────────

    def handle_edit(
        self,
        *,
        renter_id: int,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, RenterPageResponse | None]:
        try:
            lot_id = _parse_int(form_data.get("lot_id", ""), "Lot")
            display_name = _require(form_data.get("display_name", ""), "Display Name")
            start_date = _require(form_data.get("start_date", ""), "Start Date")
            self.repo.update_renter(
                renter_id=renter_id,
                lot_id=lot_id,
                display_name=display_name,
                first_name=_opt(form_data.get("first_name", "")),
                last_name=_opt(form_data.get("last_name", "")),
                email=_opt(form_data.get("email", "")),
                phone=_opt(form_data.get("phone", "")),
                start_date=start_date,
                notes=_opt(form_data.get("notes", "")),
            )
            self.conn.commit()
        except ValidationError as exc:
            return None, self.render_form(
                org=org, theme=theme,
                renter_id=renter_id,
                form_values=form_data,
                error_message=str(exc),
            )
        except Exception:
            self.conn.rollback()
            raise
        return "/renters?msg=Renter+updated.", None

    # ── End tenancy (POST) ─────────────────────────────────────────

    def handle_end(
        self,
        *,
        renter_id: int,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, RenterPageResponse | None]:
        try:
            end_date = _require(form_data.get("end_date", ""), "End Date")
            self.repo.end_tenancy(renter_id=renter_id, end_date=end_date)
            self.conn.commit()
        except ValidationError as exc:
            return None, self.render_list(
                org=org, theme=theme, error_message=str(exc),
            )
        except Exception:
            self.conn.rollback()
            raise
        return "/renters?msg=Tenancy+ended.", None
