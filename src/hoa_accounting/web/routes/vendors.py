"""Vendors and vendor bills."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from flask import Blueprint, Response, redirect, request
from flask.typing import ResponseReturnValue

from hoa_accounting.web.batch_pdf_pages import BatchPdfPages
from hoa_accounting.web.publish_reports_pages import PublishReportsPages
from hoa_accounting.web.route_context import RouteContext
from hoa_accounting.web.vendor_bill_pages import VendorBillPages
from hoa_accounting.web.vendor_pages import VendorPages


def make_vendors_blueprint(ctx: RouteContext) -> Blueprint:
    bp = Blueprint("vendors", __name__)
    org_context = ctx.org_context

    def _open_db() -> sqlite3.Connection:
        return ctx.open_db()

    # ── Batch PDF ─────────────────────────────────────────────────────────────
    def _open_batch_pdf_pages() -> BatchPdfPages:
        conn = _open_db()
        return BatchPdfPages(conn=conn)

    @bp.get("/batch-pdf")
    def batch_pdf_page() -> ResponseReturnValue:
        pages = _open_batch_pdf_pages()
        theme = str(org_context.get("theme", "warm"))
        html = pages.render_page(org=org_context, theme=theme)
        return Response(html, status=200, mimetype="text/html; charset=utf-8")

    @bp.post("/batch-pdf/generate")
    def batch_pdf_generate() -> ResponseReturnValue:
        from flask import request as _req

        pages = _open_batch_pdf_pages()
        theme = str(org_context.get("theme", "warm"))
        try:
            year = int(_req.form.get("year", "0"))
        except ValueError:
            year = 0
        if not year:
            html = pages.render_page(
                org=org_context, theme=theme, error="Please enter a valid year."
            )
            return Response(html, status=400, mimetype="text/html; charset=utf-8")
        html = pages.handle_generate(org=org_context, theme=theme, year=year)
        return Response(html, status=200, mimetype="text/html; charset=utf-8")

    # ── Publish Reports ───────────────────────────────────────────────────────
    def _open_publish_pages() -> PublishReportsPages:
        conn = _open_db()
        return PublishReportsPages(conn=conn)

    @bp.get("/publish-reports")
    def publish_reports_page() -> ResponseReturnValue:
        pages = _open_publish_pages()
        theme = str(org_context.get("theme", "warm"))
        html = pages.render_page(org=org_context, theme=theme)
        return Response(html, status=200, mimetype="text/html; charset=utf-8")

    @bp.post("/publish-reports/run")
    def publish_reports_run() -> ResponseReturnValue:
        pages = _open_publish_pages()
        theme = str(org_context.get("theme", "warm"))
        try:
            fiscal_year = int(request.form.get("year", "0"))
        except ValueError:
            fiscal_year = 0
        if not fiscal_year:
            html = pages.render_page(
                org=org_context, theme=theme, error="Please enter a valid year."
            )
            return Response(html, status=400, mimetype="text/html; charset=utf-8")
        fund_code = (request.form.get("fund_code") or "OPERATING").strip().upper()
        report = (request.form.get("report") or "all").strip()
        html = pages.handle_publish(
            org=org_context,
            theme=theme,
            fiscal_year=fiscal_year,
            fund_code=fund_code,
            report=report,
        )
        return Response(html, status=200, mimetype="text/html; charset=utf-8")

    @bp.get("/publish-reports/stream")
    def publish_reports_stream() -> ResponseReturnValue:
        from flask import stream_with_context

        from hoa_accounting.db.connection import connect_sqlite

        try:
            fiscal_year = int(request.args.get("year", "0"))
        except ValueError:
            fiscal_year = 0
        if not fiscal_year:
            return Response(
                'data: {"type":"error","message":"Invalid year"}\n\n',
                status=400,
                mimetype="text/event-stream",
            )
        fund_code = (request.args.get("fund_code") or "OPERATING").strip().upper()
        report = (request.args.get("report") or "all").strip()

        # Open a dedicated connection that is NOT stored on flask.g.
        # flask.g connections are closed at request teardown, which fires
        # before the SSE generator finishes yielding — causing "Cannot
        # operate on a closed database." This connection is owned by the
        # generator and closed in its finally block.
        db_path = org_context.get("db_path", "")
        stream_conn = connect_sqlite(str(db_path))
        pages = PublishReportsPages(conn=stream_conn)

        def _generate() -> Iterator[str]:
            try:
                yield from pages.stream_publish(
                    fiscal_year=fiscal_year,
                    fund_code=fund_code,
                    report=report,
                )
            finally:
                stream_conn.close()

        return Response(
            stream_with_context(_generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── Transaction pages: Vendor Bills ──────────────────────────────
    # Same per-request connection pattern as the master-data pages, with
    # a form-handling POST added. Redirect-on-success uses a query param
    # (`?created=JE-...`) so the list page can display a success banner
    # without pulling in Flask-Session or a secret key.

    @bp.get("/vendor-bills")
    def list_vendor_bills() -> ResponseReturnValue:
        pages = ctx.open_pages(VendorBillPages)
        theme = str(org_context.get("theme", "warm"))
        created = (request.args.get("created") or "").strip() or None
        resp = pages.render_list(
            org=org_context, theme=theme, created_entry_number=created
        )
        return Response(
            resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8"
        )

    @bp.get("/vendor-bills/new")
    def new_vendor_bill_form() -> ResponseReturnValue:
        pages = ctx.open_pages(VendorBillPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme)
        return Response(
            resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8"
        )

    @bp.post("/vendor-bills/new")
    def submit_vendor_bill() -> ResponseReturnValue:

        pages = ctx.open_pages(VendorBillPages)
        theme = str(org_context.get("theme", "warm"))
        form_data = {k: v for k, v in request.form.items()}
        redirect_url, form_resp = pages.handle_post(
            form_data=form_data,
            org=org_context,
            theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)  # see-other: GET the list
        assert form_resp is not None
        return Response(
            form_resp.body_html,
            status=form_resp.status_code,
            mimetype="text/html; charset=utf-8",
        )

    @bp.get("/vendor-bills/<int:vendor_bill_id>/edit")
    def edit_vendor_bill_form(vendor_bill_id: int) -> ResponseReturnValue:
        pages = ctx.open_pages(VendorBillPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_edit(vendor_bill_id, org=org_context, theme=theme)
        return Response(
            resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8"
        )

    @bp.post("/vendor-bills/<int:vendor_bill_id>/edit")
    def submit_vendor_bill_edit(vendor_bill_id: int) -> ResponseReturnValue:

        pages = ctx.open_pages(VendorBillPages)
        theme = str(org_context.get("theme", "warm"))
        form_data = {k: v for k, v in request.form.items()}
        redirect_url, form_resp = pages.handle_edit(
            vendor_bill_id,
            form_data=form_data,
            org=org_context,
            theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(
            form_resp.body_html,
            status=form_resp.status_code,
            mimetype="text/html; charset=utf-8",
        )

    @bp.get("/vendor-bills/<int:vendor_bill_id>/split")
    def split_vendor_bill_form(vendor_bill_id: int) -> ResponseReturnValue:
        pages = ctx.open_pages(VendorBillPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_split(vendor_bill_id, org=org_context, theme=theme)
        return Response(
            resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8"
        )

    @bp.post("/vendor-bills/<int:vendor_bill_id>/split")
    def submit_vendor_bill_split(vendor_bill_id: int) -> ResponseReturnValue:

        pages = ctx.open_pages(VendorBillPages)
        theme = str(org_context.get("theme", "warm"))
        cats = request.form.getlist("line_category_id")
        amts = request.form.getlist("line_amount")
        redirect_url, form_resp = pages.handle_split(
            vendor_bill_id,
            line_category_ids=cats,
            line_amounts=amts,
            org=org_context,
            theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(
            form_resp.body_html,
            status=form_resp.status_code,
            mimetype="text/html; charset=utf-8",
        )

    # ── Vendor pages ─────────────────────────────────────────────────

    @bp.get("/vendors")
    def list_vendors() -> ResponseReturnValue:
        pages = ctx.open_pages(VendorPages)
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        resp = pages.render_list(
            org=org_context, theme=theme, flash_message=flash_message
        )
        return Response(
            resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8"
        )

    @bp.get("/vendors/add")
    def new_vendor_form() -> ResponseReturnValue:
        pages = ctx.open_pages(VendorPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme)
        return Response(
            resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8"
        )

    @bp.post("/vendors/add")
    def submit_new_vendor() -> ResponseReturnValue:

        pages = ctx.open_pages(VendorPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_add(
            form_data={k: v for k, v in request.form.items()},
            org=org_context,
            theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(
            form_resp.body_html,
            status=form_resp.status_code,
            mimetype="text/html; charset=utf-8",
        )

    @bp.get("/vendors/<int:vendor_id>/edit")
    def edit_vendor_form(vendor_id: int) -> ResponseReturnValue:
        pages = ctx.open_pages(VendorPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme, vendor_id=vendor_id)
        return Response(
            resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8"
        )

    @bp.post("/vendors/<int:vendor_id>/edit")
    def submit_edit_vendor(vendor_id: int) -> ResponseReturnValue:

        pages = ctx.open_pages(VendorPages)
        theme = str(org_context.get("theme", "warm"))
        form_data = {k: v for k, v in request.form.items()}
        if "_active_flag_present" in form_data and "active_flag" not in form_data:
            form_data["active_flag"] = "0"
        redirect_url, form_resp = pages.handle_edit(
            vendor_id=vendor_id,
            form_data=form_data,
            org=org_context,
            theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(
            form_resp.body_html,
            status=form_resp.status_code,
            mimetype="text/html; charset=utf-8",
        )

    @bp.post("/vendors/<int:vendor_id>/delete")
    def submit_delete_vendor(vendor_id: int) -> ResponseReturnValue:

        pages = ctx.open_pages(VendorPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_delete(
            vendor_id=vendor_id,
            org=org_context,
            theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(
            form_resp.body_html,
            status=form_resp.status_code,
            mimetype="text/html; charset=utf-8",
        )

    return bp
