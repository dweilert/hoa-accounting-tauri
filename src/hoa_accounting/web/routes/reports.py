"""Reports + global search routes."""

from __future__ import annotations

from flask import Blueprint, Response, g, redirect, request
from flask import session as _session

from hoa_accounting.web.route_context import RouteContext
from hoa_accounting.web.ar_pages import ARPages
from hoa_accounting.web.all_ledger_pages import AllLedgerPages
from hoa_accounting.web.search_pages import SearchPages


def make_reports_blueprint(ctx: RouteContext) -> Blueprint:
    bp = Blueprint("reports", __name__)
    org_context = ctx.org_context

    def _open_db():
        return ctx.open_db()

    # ── Global search ─────────────────────────────────────────────────────

    def _open_search_pages() -> SearchPages:
        conn = _open_db()
        return SearchPages(conn)

    @bp.get("/search")
    def search_page() -> Response:
        pages = _open_search_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render(
            q=(request.args.get("q") or "").strip(),
            org=org_context,
            theme=theme,
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")


    # ── Delinquency report ────────────────────────────────────────────────

    @bp.get("/delinquency-report")
    def delinquency_report() -> Response:
        conn = _open_db()
        theme = str(org_context.get("theme", "warm"))
        resp = ARPages(conn).render_delinquency_report(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8")

    # Bill Templates retired — recurring bills are now created automatically
    # by OFX transaction rules (action_type=recurring_bill / vendor_bill_match)
    # whenever a matching bank line lands in Pending Validation.


    # ── Ledger reports: all-accounts views ───────────────────────────

    def _open_all_ledger_pages() -> AllLedgerPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError("database.path missing from config.")
        conn = _open_db()
        return AllLedgerPages(conn)

    @bp.get("/ledger/transactions")
    def all_transactions() -> Response:
        pages = _open_all_ledger_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_all_transactions(
            org=org_context, theme=theme,
            start_date=(request.args.get("start") or "").strip(),
            end_date=(request.args.get("end") or "").strip(),
            sort=(request.args.get("sort") or "asc").strip(),
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.get("/ledger/by-account")
    def ledger_by_account() -> Response:
        # Old route — redirect to the unified transactions view
        qs = request.query_string.decode()
        target = "/ledger/transactions" + (f"?{qs}" if qs else "")
        return redirect(target, 301)


    return bp
