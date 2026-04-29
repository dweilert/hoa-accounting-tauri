"""Accounting period routes."""

from __future__ import annotations

from flask import Blueprint, Response, g, redirect, request
from flask import session as _session

from hoa_accounting.web.route_context import RouteContext
from hoa_accounting.web.accounting_period_pages import AccountingPeriodPages


def make_periods_blueprint(ctx: RouteContext) -> Blueprint:
    bp = Blueprint("periods", __name__)
    org_context = ctx.org_context

    def _open_db():
        return ctx.open_db()

    # ── Accounting period pages ───────────────────────────────────────


    @bp.get("/accounting-periods")
    def list_periods() -> Response:
        pages = ctx.open_pages(AccountingPeriodPages)
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        resp = pages.render_list(org=org_context, theme=theme,
                                 flash_message=flash_message)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.get("/accounting-periods/add")
    def new_period_form() -> Response:
        pages = ctx.open_pages(AccountingPeriodPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_add_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/accounting-periods/add")
    def submit_new_period() -> Response:
        from flask import redirect
        pages = ctx.open_pages(AccountingPeriodPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_add(
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.get("/accounting-periods/generate")
    def generate_year_form() -> Response:
        pages = ctx.open_pages(AccountingPeriodPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_generate_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/accounting-periods/generate")
    def submit_generate_year() -> Response:
        from flask import redirect
        pages = ctx.open_pages(AccountingPeriodPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_generate_year(
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/accounting-periods/<int:period_id>/close")
    def close_period(period_id: int) -> Response:
        from flask import redirect
        pages = ctx.open_pages(AccountingPeriodPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_close(
            period_id=period_id, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/accounting-periods/<int:period_id>/reopen")
    def reopen_period(period_id: int) -> Response:
        from flask import redirect
        pages = ctx.open_pages(AccountingPeriodPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_reopen(
            period_id=period_id, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/accounting-periods/<int:period_id>/delete")
    def delete_period(period_id: int) -> Response:
        from flask import redirect
        pages = ctx.open_pages(AccountingPeriodPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_delete(
            period_id=period_id, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")


    return bp
