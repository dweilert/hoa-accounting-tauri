"""Lot Transfer pages — GET form + POST handler.

Routes handled:
  GET  /lots/<lot_id>/transfer  — show the transfer form
  POST /lots/<lot_id>/transfer  — process the transfer
"""

from __future__ import annotations

import sqlite3
from datetime import date
from http import HTTPStatus
from typing import Any

from hoa_accounting.exceptions import ValidationError
from hoa_accounting.repositories.assessments_repo import AssessmentsRepository
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.lot_ownership_repo import LotOwnershipRepository
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.repositories.owners_repo import OwnersRepository
from hoa_accounting.services.lot_transfer_service import LotTransferService
from hoa_accounting.validators.common import q2
from hoa_accounting.web.lot_pages import LotPageResponse
from hoa_accounting.web.template_engine import render_template

_BASE_CTX = {
    "active_nav": "master-data",
    "page_key": "lots",
    "breadcrumb": "Master Data · Lots · Transfer",
}

TRANSFER_TEMPLATE = "lot_transfer.html"


class LotTransferPages:
    """Render and handle the Lot Transfer workflow page."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.lots_repo = LotsRepository(conn)
        self.ownership_repo = LotOwnershipRepository(conn)
        self.owners_repo = OwnersRepository(conn)
        self.assessments_repo = AssessmentsRepository(conn)
        self.audit_repo = AuditRepository(conn)

    # ── GET /lots/<lot_id>/transfer ────────────────────────────────────────────

    def render_transfer_form(
        self,
        *,
        lot_id: int,
        org: dict[str, object] | None,
        theme: str,
        form_values: dict[str, Any] | None = None,
        error_message: str = "",
        flash_message: str = "",
    ) -> LotPageResponse:
        lot_row = self.lots_repo.get_lot(lot_id)
        if lot_row is None:
            return LotPageResponse(
                status_code=HTTPStatus.NOT_FOUND,
                body_html="<h1>Lot not found</h1>",
            )

        lot_number = lot_row["lot_number"] or ""
        address_parts = [
            lot_row["street_address_1"] or "",
            lot_row["street_address_2"] or "",
            lot_row["city"] or "",
        ]
        address = ", ".join(p for p in address_parts if p).strip(", ")

        # Current (departing) owners
        current_ownerships: list[dict[str, Any]] = [
            dict(r) for r in self.ownership_repo.get_current_ownerships(lot_id)
        ]
        current_owner_ids = {int(o["owner_id"]) for o in current_ownerships}

        # All active owners EXCEPT those already owning this lot
        all_owners = self.owners_repo.list_owners(active_only=True)

        def _label(r: sqlite3.Row) -> str:
            first = (r["first_name"] or "").strip()
            last = (r["last_name"] or "").strip()
            name = f"{first} {last}".strip() if (first or last) else r["display_name"]
            return name

        available_owners: list[dict[str, Any]] = [
            {"id": r["id"], "label": _label(r)}
            for r in all_owners
            if r["id"] not in current_owner_ids
        ]

        # Outstanding balance as of today
        today = date.today().isoformat()
        balance_row = self.conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM assessments
            WHERE lot_id = ?
              AND status NOT IN ('VOID', 'PAID')
              AND due_date <= ?
            """,
            (lot_id, today),
        ).fetchone()
        balance = q2(balance_row["total"] if balance_row else 0)

        ctx = {
            **_BASE_CTX,
            "heading": "Transfer Lot Ownership",
            "org": org or {},
            "theme": theme,
            "lot_id": lot_id,
            "lot_number": lot_number,
            "address": address,
            "current_ownerships": current_ownerships,
            "available_owners": available_owners,
            "balance": balance,
            "today": today,
            "form_values": form_values or {},
            "error_message": error_message,
            "flash_message": flash_message,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return LotPageResponse(
            status_code=status,
            body_html=render_template(TRANSFER_TEMPLATE, ctx),
        )

    # ── POST /lots/<lot_id>/transfer ───────────────────────────────────────────

    def handle_transfer(
        self,
        *,
        lot_id: int,
        form_data: dict[str, Any],
        org: dict[str, object] | None,
        theme: str,
        user_id: int | None = None,
    ) -> tuple[str | None, LotPageResponse | None]:
        # Parse sale_date
        sale_date = (form_data.get("sale_date") or "").strip()

        # Parse new_owner_ids — the form POSTs multiple values under the same key;
        # Flask's ImmutableMultiDict exposes them via request.form.getlist, but
        # callers pass us a plain dict so we check for both str and list values.
        raw_ids = form_data.get("new_owner_id")
        if raw_ids is None:
            new_owner_ids: list[int] = []
        elif isinstance(raw_ids, list):
            new_owner_ids = [int(v) for v in raw_ids if str(v).strip()]
        else:
            new_owner_ids = [int(str(raw_ids).strip())] if str(raw_ids).strip() else []

        # Force checkbox — present when checked
        force = bool(form_data.get("force"))

        service = LotTransferService(
            self.conn,
            lots_repo=self.lots_repo,
            ownership_repo=self.ownership_repo,
            assessments_repo=self.assessments_repo,
            audit_repo=self.audit_repo,
        )

        try:
            service.transfer(
                lot_id=lot_id,
                new_owner_ids=new_owner_ids,
                sale_date=sale_date,
                created_by_user_id=user_id,
                force=force,
            )
        except ValidationError as exc:
            return None, self.render_transfer_form(
                lot_id=lot_id,
                org=org,
                theme=theme,
                form_values=form_data,
                error_message=str(exc),
            )

        return f"/lots/{lot_id}/edit?msg=Ownership+transferred.", None
