"""Category management routes (/categories/*)."""

from __future__ import annotations

from flask import Blueprint, Response, g, redirect, request
from flask import session as _session

from hoa_accounting.web.route_context import RouteContext


def make_categories_blueprint(ctx: RouteContext) -> Blueprint:
    bp = Blueprint("categories", __name__)
    org_context = ctx.org_context

    def _open_db():
        return ctx.open_db()

    # ── Categories pages ──────────────────────────────────────────────

    from hoa_accounting.web.categories_pages import CategoriesPages


    @bp.get("/categories", strict_slashes=False)
    def list_categories() -> Response:
        from flask import redirect
        theme = str(org_context.get("theme", "warm"))
        flash = (request.args.get("flash") or "").replace("+", " ")
        resp = ctx.open_pages(CategoriesPages).render_list(org=org_context, theme=theme, flash_message=flash)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8")

    @bp.get("/categories/add")
    def new_category_form() -> Response:
        theme = str(org_context.get("theme", "warm"))
        resp = ctx.open_pages(CategoriesPages).render_add_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8")

    @bp.post("/categories/add")
    def submit_new_category() -> Response:
        from flask import redirect
        theme = str(org_context.get("theme", "warm"))
        resp = ctx.open_pages(CategoriesPages).handle_add(
            dict(request.form), org=org_context, theme=theme
        )
        if resp.status_code in (301, 302, 303):
            return redirect("/categories?flash=Category+added.", code=303)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8")

    @bp.get("/categories/<int:category_id>/edit")
    def edit_category_form(category_id: int) -> Response:
        theme = str(org_context.get("theme", "warm"))
        resp = ctx.open_pages(CategoriesPages).render_edit_form(category_id, org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8")

    @bp.post("/categories/<int:category_id>/edit")
    def submit_edit_category(category_id: int) -> Response:
        from flask import redirect
        theme = str(org_context.get("theme", "warm"))
        resp = ctx.open_pages(CategoriesPages).handle_edit(
            category_id, dict(request.form), org=org_context, theme=theme
        )
        if resp.status_code in (301, 302, 303):
            return redirect("/categories?flash=Category+saved.", code=303)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8")

    @bp.post("/categories/<int:category_id>/delete")
    def delete_category(category_id: int) -> Response:
        from flask import redirect
        target = ctx.open_pages(CategoriesPages).handle_delete(category_id)
        return redirect(target, code=303)

    @bp.get("/categories/<int:category_id>/ledger")
    def view_category_ledger(category_id: int) -> Response:
        theme = str(org_context.get("theme", "warm"))
        resp = ctx.open_pages(CategoriesPages).render_ledger(category_id, org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8")

    return bp
