"""Dashboard, system-settings, workflow-guide admin."""

from __future__ import annotations

import sqlite3

from flask import Blueprint, Response, redirect, request
from flask import session as _session
from flask.typing import ResponseReturnValue

from hoa_accounting.web.dashboard_pages import DashboardPages
from hoa_accounting.web.route_context import RouteContext


def make_dashboard_blueprint(ctx: RouteContext) -> Blueprint:
    bp = Blueprint("dashboard", __name__)
    org_context = ctx.org_context

    def _open_db() -> sqlite3.Connection:
        return ctx.open_db()

    def _open_dashboard() -> DashboardPages:
        from datetime import date

        conn = _open_db()
        start_month = int(org_context.get("fiscal_year_start_month", 1))
        today = date.today()
        fy = today.year if today.month >= start_month else today.year - 1
        return DashboardPages(conn, fiscal_year=fy, fy_start_month=start_month)

    @bp.get("/")
    def home() -> ResponseReturnValue:

        theme = str(org_context.get("theme", "warm"))
        pages = _open_dashboard()
        setup_flash = _session.pop("setup_complete_flash", False)
        resp = pages.render_dashboard(
            org=org_context, theme=theme, setup_complete=setup_flash
        )
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html")

    @bp.get("/system-settings")
    def system_settings_page() -> ResponseReturnValue:
        theme = str(org_context.get("theme", "warm"))
        flash = (request.args.get("msg") or "").strip() or None
        pages = _open_dashboard()
        resp = pages.render_settings(org=org_context, theme=theme, flash=flash)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html")

    @bp.post("/system-settings/save")
    def system_settings_save() -> ResponseReturnValue:

        theme = str(org_context.get("theme", "warm"))
        pages = _open_dashboard()
        redirect_url, page_resp = pages.handle_save_settings(
            request.form, org_context, theme
        )
        if redirect_url:
            return redirect(redirect_url)
        assert page_resp is not None
        return Response(
            page_resp.body_html, status=page_resp.status_code, mimetype="text/html"
        )

    @bp.get("/claude-code-guide")
    def claude_code_guide_page() -> ResponseReturnValue:
        from hoa_accounting.web.template_engine import render_template as _render

        theme = str(org_context.get("theme", "warm"))
        html = _render(
            "claude_code_guide.html",
            {
                "org": org_context,
                "theme": theme,
                "page_key": "claude-code-guide",
            },
        )
        return Response(html, mimetype="text/html")

    @bp.get("/workflow-cheatsheet")
    def workflow_cheatsheet_page() -> ResponseReturnValue:
        from hoa_accounting.web.template_engine import render_template as _render

        theme = str(org_context.get("theme", "warm"))
        html = _render(
            "workflow_cheatsheet.html",
            {
                "org": org_context,
                "theme": theme,
                "active_nav": "system",
                "breadcrumb": "System",
                "page_key": "workflow-cheatsheet",
            },
        )
        return Response(html, mimetype="text/html")

    @bp.get("/workflow-guide")
    def workflow_guide_page() -> ResponseReturnValue:
        from hoa_accounting.web.workflow_pages import WorkflowPages

        theme = str(org_context.get("theme", "warm"))
        conn = _open_db()
        status, html = WorkflowPages(conn).render_guide(org=org_context, theme=theme)
        return Response(html, status=status, mimetype="text/html")

    @bp.get("/admin/workflow-guide")
    def workflow_admin_page() -> ResponseReturnValue:
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages

        theme = str(org_context.get("theme", "warm"))
        conn = _open_db()
        tab_id = int(request.args.get("tab", 1))
        edit_card_raw = request.args.get("edit")
        edit_card_id = int(edit_card_raw) if edit_card_raw else None
        flash = (request.args.get("flash") or "").replace("+", " ")
        status, html = WorkflowAdminPages(conn).render_admin(
            org=org_context,
            theme=theme,
            active_tab_id=tab_id,
            edit_card_id=edit_card_id,
            flash=flash,
        )
        return Response(html, status=status, mimetype="text/html")

    @bp.post("/admin/workflow-guide/add-card")
    def workflow_add_card() -> ResponseReturnValue:
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages

        url = WorkflowAdminPages(_open_db()).handle_add_card(request.form)
        return redirect(url)

    @bp.post("/admin/workflow-guide/update-card")
    def workflow_update_card() -> ResponseReturnValue:
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages

        url = WorkflowAdminPages(_open_db()).handle_update_card(request.form)
        return redirect(url)

    @bp.post("/admin/workflow-guide/move-card")
    def workflow_move_card() -> ResponseReturnValue:
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages

        url = WorkflowAdminPages(_open_db()).handle_move_card(request.form)
        return redirect(url)

    @bp.post("/admin/workflow-guide/toggle-card")
    def workflow_toggle_card() -> ResponseReturnValue:
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages

        card_id = int(request.form.get("card_id", 0))
        tab_id = int(request.form.get("tab_id", 1))
        WorkflowAdminPages(_open_db()).handle_toggle_card(card_id, tab_id)
        return Response("ok", mimetype="text/plain")

    @bp.post("/admin/workflow-guide/delete-card")
    def workflow_delete_card() -> ResponseReturnValue:
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages

        url = WorkflowAdminPages(_open_db()).handle_delete_card(request.form)
        return redirect(url)

    @bp.post("/admin/workflow-guide/reorder-card")
    def workflow_reorder_card() -> ResponseReturnValue:
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages

        url = WorkflowAdminPages(_open_db()).handle_reorder_card(request.form)
        return redirect(url)

    @bp.post("/admin/workflow-guide/add-section")
    def workflow_add_section() -> ResponseReturnValue:
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages

        url = WorkflowAdminPages(_open_db()).handle_add_section(request.form)
        return redirect(url)

    @bp.post("/admin/workflow-guide/toggle-section")
    def workflow_toggle_section() -> ResponseReturnValue:
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages

        section_id = int(request.form.get("section_id", 0))
        tab_id = int(request.form.get("tab_id", 1))
        WorkflowAdminPages(_open_db()).handle_toggle_section(section_id, tab_id)
        return redirect(f"/admin/workflow-guide?tab={tab_id}")

    @bp.post("/admin/workflow-guide/add-tab")
    def workflow_add_tab() -> ResponseReturnValue:
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages

        url = WorkflowAdminPages(_open_db()).handle_add_tab(request.form)
        return redirect(url)

    @bp.post("/admin/workflow-guide/toggle-tab")
    def workflow_toggle_tab() -> ResponseReturnValue:
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages

        tab_id = int(request.form.get("tab_id", 1))
        WorkflowAdminPages(_open_db()).handle_toggle_tab(tab_id)
        return redirect(f"/admin/workflow-guide?tab={tab_id}")

    @bp.get("/dashboard-config")
    def dashboard_config_page() -> ResponseReturnValue:
        theme = str(org_context.get("theme", "warm"))
        flash = (request.args.get("msg") or "").strip() or None
        pages = _open_dashboard()
        resp = pages.render_card_catalog(org=org_context, theme=theme, flash=flash)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html")

    @bp.post("/dashboard-config/save-card")
    def dashboard_save_card() -> ResponseReturnValue:

        theme = str(org_context.get("theme", "warm"))
        pages = _open_dashboard()
        redirect_url, page_resp = pages.handle_save_card(
            request.form, org_context, theme
        )
        if redirect_url:
            return redirect(redirect_url)
        assert page_resp is not None
        return Response(
            page_resp.body_html, status=page_resp.status_code, mimetype="text/html"
        )

    @bp.post("/dashboard-config/delete-card/<int:card_id>")
    def dashboard_delete_card(card_id: int) -> ResponseReturnValue:

        theme = str(org_context.get("theme", "warm"))
        pages = _open_dashboard()
        redirect_url, _ = pages.handle_delete_card(card_id, org_context, theme)
        return redirect(redirect_url or "/dashboard-config")

    @bp.post("/dashboard-config/save-layout")
    def dashboard_save_layout() -> ResponseReturnValue:

        pages = _open_dashboard()
        redirect_url = pages.handle_save_layout(request.form)
        return redirect(redirect_url)

    @bp.post("/dashboard-config/reset-layout")
    def dashboard_reset_layout() -> ResponseReturnValue:

        pages = _open_dashboard()
        redirect_url = pages.handle_reset_layout()
        return redirect(redirect_url)

    @bp.post("/dashboard/dismiss-alert")
    def dashboard_dismiss_alert() -> ResponseReturnValue:
        from flask import jsonify

        key = request.form.get("alert_key", "")
        if key:
            _open_dashboard()._repo.dismiss_alert(key)
        return jsonify({"ok": True})

    @bp.post("/dashboard-config/save-alert-settings")
    def dashboard_save_alert_settings() -> ResponseReturnValue:

        enabled = set(request.form.getlist("enabled_alerts"))
        _open_dashboard()._repo.save_alert_settings(enabled)
        return redirect("/dashboard-config?msg=Alert+settings+saved.")

    return bp
