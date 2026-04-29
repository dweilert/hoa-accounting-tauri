"""Reports + global search routes."""

from __future__ import annotations

import sqlite3
from typing import Any

from flask import Blueprint, Response, redirect, request
from flask.typing import ResponseReturnValue

from hoa_accounting.web.all_ledger_pages import AllLedgerPages
from hoa_accounting.web.ar_pages import ARPages
from hoa_accounting.web.report_catalog import REPORT_DEFINITIONS
from hoa_accounting.web.route_context import RouteContext
from hoa_accounting.web.search_pages import SearchPages
from hoa_accounting.web.ui_server import UIResponse


def _ui_response_to_flask(response: UIResponse) -> ResponseReturnValue:
    return Response(
        response.body_html,
        status=response.status_code,
        mimetype="text/html; charset=utf-8",
    )


def _flatten_query_params(multi_dict: Any) -> dict[str, str]:
    """Collapse a werkzeug MultiDict into single-value form."""
    out: dict[str, str] = {}
    for key in multi_dict.keys():
        value = multi_dict.getlist(key)[-1]
        if value is not None and str(value).strip() != "":
            out[key] = value
    return out


def make_reports_blueprint(ctx: RouteContext) -> Blueprint:
    bp = Blueprint("reports", __name__)
    org_context = ctx.org_context
    # Reports blueprint requires the page service. ``RouteContext`` types it
    # ``Any | None`` because not every entry point needs it; here we assert
    # presence so handler bodies don't need per-call None guards.
    assert (
        ctx.report_page_service is not None
    ), "Reports blueprint requires ctx.report_page_service"
    report_page_service = ctx.report_page_service

    def _open_db() -> sqlite3.Connection:
        return ctx.open_db()

    # ── Global search ─────────────────────────────────────────────────────

    @bp.get("/search")
    def search_page() -> ResponseReturnValue:
        pages = ctx.open_pages(SearchPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render(
            q=(request.args.get("q") or "").strip(),
            org=org_context,
            theme=theme,
        )
        return Response(
            resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8"
        )

    # ── Delinquency report ────────────────────────────────────────────────

    @bp.get("/delinquency-report")
    def delinquency_report() -> ResponseReturnValue:
        conn = _open_db()
        theme = str(org_context.get("theme", "warm"))
        resp = ARPages(conn).render_delinquency_report(org=org_context, theme=theme)
        return Response(
            resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8"
        )

    # Bill Templates retired — recurring bills are now created automatically
    # by OFX transaction rules (action_type=recurring_bill / vendor_bill_match)
    # whenever a matching bank line lands in Pending Validation.

    # ── Ledger reports: all-accounts views ───────────────────────────

    @bp.get("/ledger/transactions")
    def all_transactions() -> ResponseReturnValue:
        pages = ctx.open_pages(AllLedgerPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_all_transactions(
            org=org_context,
            theme=theme,
            start_date=(request.args.get("start") or "").strip(),
            end_date=(request.args.get("end") or "").strip(),
            sort=(request.args.get("sort") or "asc").strip(),
        )
        return Response(
            resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8"
        )

    @bp.get("/ledger/by-account")
    def ledger_by_account() -> ResponseReturnValue:
        # Old route — redirect to the unified transactions view
        qs = request.query_string.decode()
        target = "/ledger/transactions" + (f"?{qs}" if qs else "")
        return redirect(target, 301)

    def _load_report_lookup_options() -> dict[str, Any]:
        """Load dropdown options for report parameter fields from the DB."""
        db_path = org_context.get("db_path")
        if not db_path:
            return {}
        try:
            conn = _open_db()
            try:
                owners = conn.execute("""
                    SELECT o.id, o.display_name,
                           COALESCE(l.lot_number, '') AS lot_number
                    FROM owners o
                    LEFT JOIN lot_ownership lo
                      ON lo.owner_id = o.id AND lo.end_date IS NULL
                    LEFT JOIN lots l ON l.id = lo.lot_id
                    WHERE o.active_flag = 1
                    ORDER BY CAST(l.lot_number AS REAL), l.lot_number, o.display_name
                    """).fetchall()

                lots = conn.execute("""
                    SELECT l.id, l.lot_number,
                           COALESCE(l.street_address_1, '') AS address,
                           COALESCE(o.display_name, '') AS owner_name
                    FROM lots l
                    LEFT JOIN lot_ownership lo
                      ON lo.lot_id = l.id AND lo.end_date IS NULL
                    LEFT JOIN owners o
                      ON o.id = lo.owner_id AND o.active_flag = 1
                    WHERE l.active_flag = 1
                    GROUP BY l.id
                    ORDER BY CAST(l.lot_number AS REAL), l.lot_number
                    """).fetchall()

                # Chart of Accounts retired — these dropdowns are gone.
                vendors = conn.execute("""
                    SELECT id, vendor_name FROM vendors
                    WHERE active_flag = 1
                    ORDER BY vendor_name
                    """).fetchall()

                def _owner_label(row: object) -> str:
                    lot = str(row["lot_number"]).strip()  # type: ignore[index]
                    name = str(row["display_name"])  # type: ignore[index]
                    return f"Lot {lot} — {name}" if lot else name

                def _lot_label(r: object) -> str:
                    num = str(r["lot_number"])  # type: ignore[index]
                    addr = str(r["address"]).strip()  # type: ignore[index]
                    owner = str(r["owner_name"]).strip()  # type: ignore[index]
                    parts = [f"Lot {num}"]
                    if addr:
                        parts.append(addr)
                    if owner:
                        parts.append(f"({owner})")
                    return " – ".join(parts[:2]) + (
                        " " + parts[2] if len(parts) > 2 else ""
                    )

                return {
                    "lot_id": [
                        {"value": str(r["id"]), "label": _lot_label(r)} for r in lots
                    ],
                    "owner_id": [
                        {"value": str(r["id"]), "label": _owner_label(r)}
                        for r in owners
                    ],
                    "vendor_id": [
                        {"value": str(r["id"]), "label": str(r["vendor_name"])}
                        for r in vendors
                    ],
                    "fund_code": [
                        {"value": "OPERATING", "label": "Operating"},
                        {"value": "RESERVE", "label": "Reserve"},
                        {"value": "SPECIAL", "label": "Special"},
                    ],
                    "sort_by": [
                        {"value": "name", "label": "Name (last, first)"},
                        {"value": "address", "label": "Address"},
                    ],
                    "years_mode": [
                        {"value": "current", "label": "Current year only"},
                        {"value": "prev_current", "label": "Prior year + Current year"},
                        {
                            "value": "prev_current_next",
                            "label": "Prior + Current + Next year",
                        },
                    ],
                }
            finally:
                conn.close()
        except Exception:
            return {}

    @bp.get("/reports")
    def reports_console() -> ResponseReturnValue:
        _default_report = REPORT_DEFINITIONS[0].name
        selected = request.args.get("report_name", _default_report).strip()
        if not selected:
            selected = _default_report
        return _ui_response_to_flask(
            report_page_service.render_page(
                selected_report=selected,
                org=org_context,
                lookup_options=_load_report_lookup_options(),
            )
        )

    @bp.get("/run-report")
    def run_report() -> ResponseReturnValue:
        params = _flatten_query_params(request.args)
        report_name = params.pop("report_name", "").strip()
        return _ui_response_to_flask(
            report_page_service.render_report(
                report_name=report_name,
                query_params=params,
                org=org_context,
                lookup_options=_load_report_lookup_options(),
            )
        )

    return bp
