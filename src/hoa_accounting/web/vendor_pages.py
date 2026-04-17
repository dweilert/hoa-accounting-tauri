"""Vendor management pages.

Routes handled:
  GET  /vendors                — list all vendors (active + inactive)
  GET  /vendors/add            — blank add form
  POST /vendors/add            — submit new vendor
  GET  /vendors/<id>/edit      — edit form pre-filled
  POST /vendors/<id>/edit      — submit edits
  POST /vendors/<id>/delete    — hard-delete (blocked if vendor has bills)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from http import HTTPStatus

from hoa_accounting.exceptions import ValidationError
from hoa_accounting.repositories.vendors_repo import VendorsRepository
from hoa_accounting.web.template_engine import render_template


@dataclass(frozen=True)
class VendorPageResponse:
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
    "page_key": "vendors",
    "breadcrumb": "Master Data",
}


class VendorPages:
    """Render and handle the vendor management pages."""

    LIST_TEMPLATE = "vendors_list.html"
    FORM_TEMPLATE = "vendor_form.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.repo = VendorsRepository(conn)

    # ── List page ─────────────────────────────────────────────────

    def render_list(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        flash_message: str = "",
        error_message: str = "",
    ) -> VendorPageResponse:
        rows = self.repo.list_vendors(active_only=False)
        vendors = [dict(r) for r in rows]
        ctx = {
            **_BASE_CTX,
            "heading": "Vendors",
            "org": org or {},
            "theme": theme,
            "vendors": vendors,
            "flash_message": flash_message,
            "error_message": error_message,
        }
        return VendorPageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.LIST_TEMPLATE, ctx),
        )

    # ── Add / Edit form (GET) ──────────────────────────────────────

    def render_form(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        vendor_id: int | None = None,
        form_values: dict[str, str] | None = None,
        error_message: str = "",
    ) -> VendorPageResponse:
        is_edit = vendor_id is not None
        values: dict[str, str] = {}

        if is_edit and form_values is None:
            row = self.repo.get_vendor(vendor_id)
            if row is None:
                return VendorPageResponse(
                    status_code=HTTPStatus.NOT_FOUND,
                    body_html="<h1>Vendor not found</h1>",
                )
            values = {
                "vendor_name": row["vendor_name"] or "",
                "contact_name": row["contact_name"] or "",
                "email": row["email"] or "",
                "phone": row["phone"] or "",
                "address_1": row["address_1"] or "",
                "address_2": row["address_2"] or "",
                "city": row["city"] or "",
                "state": row["state"] or "",
                "postal_code": row["postal_code"] or "",
                "notes": row["notes"] or "",
                "active_flag": str(row["active_flag"]),
                "has_bills": "1" if self.repo.has_bills(vendor_id) else "0",
            }
        else:
            values = form_values or {}

        heading = "Edit Vendor" if is_edit else "Add Vendor"
        breadcrumb = "Master Data · Vendors"
        ctx = {
            **_BASE_CTX,
            "heading": heading,
            "breadcrumb": breadcrumb,
            "org": org or {},
            "theme": theme,
            "is_edit": is_edit,
            "vendor_id": vendor_id,
            "values": {
                "vendor_name": values.get("vendor_name", ""),
                "contact_name": values.get("contact_name", ""),
                "email": values.get("email", ""),
                "phone": values.get("phone", ""),
                "address_1": values.get("address_1", ""),
                "address_2": values.get("address_2", ""),
                "city": values.get("city", ""),
                "state": values.get("state", ""),
                "postal_code": values.get("postal_code", ""),
                "notes": values.get("notes", ""),
                "active_flag": values.get("active_flag", "1"),
                "has_bills": values.get("has_bills", "0"),
            },
            "error_message": error_message,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return VendorPageResponse(
            status_code=status,
            body_html=render_template(self.FORM_TEMPLATE, ctx),
        )

    # ── Add vendor (POST) ──────────────────────────────────────────

    def handle_add(
        self,
        *,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, VendorPageResponse | None]:
        try:
            vendor_name = _require(form_data.get("vendor_name", ""), "Vendor Name")
            self.repo.insert_vendor(
                vendor_name=vendor_name,
                contact_name=_opt(form_data.get("contact_name", "")),
                email=_opt(form_data.get("email", "")),
                phone=_opt(form_data.get("phone", "")),
                address_1=_opt(form_data.get("address_1", "")),
                address_2=_opt(form_data.get("address_2", "")),
                city=_opt(form_data.get("city", "")),
                state=_opt(form_data.get("state", "")),
                postal_code=_opt(form_data.get("postal_code", "")),
                notes=_opt(form_data.get("notes", "")),
            )
            self.conn.commit()
        except ValidationError as exc:
            return None, self.render_form(
                org=org, theme=theme,
                form_values=form_data,
                error_message=str(exc),
            )
        return "/vendors?msg=Vendor+added.", None

    # ── Edit vendor (POST) ─────────────────────────────────────────

    def handle_edit(
        self,
        *,
        vendor_id: int,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, VendorPageResponse | None]:
        try:
            vendor_name = _require(form_data.get("vendor_name", ""), "Vendor Name")
            active_flag = form_data.get("active_flag", "1") == "1"
            self.repo.update_vendor(
                vendor_id=vendor_id,
                vendor_name=vendor_name,
                contact_name=_opt(form_data.get("contact_name", "")),
                email=_opt(form_data.get("email", "")),
                phone=_opt(form_data.get("phone", "")),
                address_1=_opt(form_data.get("address_1", "")),
                address_2=_opt(form_data.get("address_2", "")),
                city=_opt(form_data.get("city", "")),
                state=_opt(form_data.get("state", "")),
                postal_code=_opt(form_data.get("postal_code", "")),
                notes=_opt(form_data.get("notes", "")),
                active_flag=active_flag,
            )
            self.conn.commit()
        except ValidationError as exc:
            return None, self.render_form(
                org=org, theme=theme,
                vendor_id=vendor_id,
                form_values=form_data,
                error_message=str(exc),
            )
        return "/vendors?msg=Vendor+updated.", None

    # ── Delete vendor (POST) ───────────────────────────────────────

    def handle_delete(
        self,
        *,
        vendor_id: int,
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, VendorPageResponse | None]:
        try:
            if self.repo.has_bills(vendor_id):
                raise ValidationError(
                    "Cannot delete a vendor that has bills on record. "
                    "Deactivate the vendor instead."
                )
            self.repo.delete_vendor(vendor_id)
            self.conn.commit()
        except ValidationError as exc:
            return None, self.render_form(
                org=org, theme=theme,
                vendor_id=vendor_id,
                error_message=str(exc),
            )
        return "/vendors?msg=Vendor+deleted.", None
