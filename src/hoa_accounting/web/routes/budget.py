"""Budget, periods (period add/close in periods.py), opening balances, reserve."""

from __future__ import annotations

import sqlite3

from flask import Blueprint, Response, g, redirect, request
from flask.typing import ResponseReturnValue
from flask import session as _session

from hoa_accounting.web.route_context import RouteContext
from hoa_accounting.web.budget_pages import BudgetPages
from hoa_accounting.web.opening_balances_pages import OpeningBalancesPages
from hoa_accounting.web.reserve_study_pages import ReserveStudyPages
from hoa_accounting.web.reserve_transfer_pages import ReserveTransferPages


def make_budget_blueprint(ctx: RouteContext) -> Blueprint:
    bp = Blueprint("budget", __name__)
    org_context = ctx.org_context

    def _open_db() -> sqlite3.Connection:
        return ctx.open_db()

    # ── Reserve Study pages ───────────────────────────────────────────

    def _rs_redirect(url: str) -> ResponseReturnValue:
        from flask import redirect as _redir

        return _redir(url, code=303)

    def _rs_resp(pr: object) -> ResponseReturnValue:
        return Response(pr.body_html, status=pr.status_code, mimetype="text/html; charset=utf-8")  # type: ignore[attr-defined]

    @bp.get("/reserve-study")
    def rs_summary() -> ResponseReturnValue:
        pages = ctx.open_pages(ReserveStudyPages)
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        return _rs_resp(
            pages.render_summary(
                org=org_context, theme=theme, flash_message=flash_message
            )
        )

    @bp.get("/reserve-study/assumptions/edit")
    def rs_assumptions_form() -> ResponseReturnValue:
        pages = ctx.open_pages(ReserveStudyPages)
        theme = str(org_context.get("theme", "warm"))
        return _rs_resp(pages.render_assumptions_form(org=org_context, theme=theme))

    @bp.post("/reserve-study/assumptions/edit")
    def rs_assumptions_save() -> ResponseReturnValue:
        from flask import redirect

        pages = ctx.open_pages(ReserveStudyPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_save_assumptions(
            form_data={k: v for k, v in request.form.items()},
            org=org_context,
            theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return _rs_resp(form_resp)

    @bp.get("/reserve-study/assets")
    def rs_assets() -> ResponseReturnValue:
        pages = ctx.open_pages(ReserveStudyPages)
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        return _rs_resp(
            pages.render_assets(
                org=org_context, theme=theme, flash_message=flash_message
            )
        )

    @bp.get("/reserve-study/assets/new")
    def rs_asset_new_form() -> ResponseReturnValue:
        pages = ctx.open_pages(ReserveStudyPages)
        theme = str(org_context.get("theme", "warm"))
        return _rs_resp(pages.render_asset_form(org=org_context, theme=theme))

    @bp.post("/reserve-study/assets/new")
    def rs_asset_new_save() -> ResponseReturnValue:
        from flask import redirect

        pages = ctx.open_pages(ReserveStudyPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_save_asset(
            None,
            form_data={k: v for k, v in request.form.items()},
            org=org_context,
            theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return _rs_resp(form_resp)

    @bp.get("/reserve-study/assets/<int:asset_id>/edit")
    def rs_asset_edit_form(asset_id: int) -> ResponseReturnValue:
        pages = ctx.open_pages(ReserveStudyPages)
        theme = str(org_context.get("theme", "warm"))
        return _rs_resp(pages.render_asset_form(asset_id, org=org_context, theme=theme))

    @bp.post("/reserve-study/assets/<int:asset_id>/edit")
    def rs_asset_edit_save(asset_id: int) -> ResponseReturnValue:
        from flask import redirect

        pages = ctx.open_pages(ReserveStudyPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_save_asset(
            asset_id,
            form_data={k: v for k, v in request.form.items()},
            org=org_context,
            theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return _rs_resp(form_resp)

    @bp.post("/reserve-study/assets/<int:asset_id>/delete")
    def rs_asset_delete(asset_id: int) -> ResponseReturnValue:
        from flask import redirect

        pages = ctx.open_pages(ReserveStudyPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, _ = pages.handle_delete_asset(
            asset_id, org=org_context, theme=theme
        )
        return redirect(redirect_url or "/reserve-study/assets", code=303)

    @bp.get("/reserve-study/funding-plan")
    def rs_funding_plan() -> ResponseReturnValue:
        pages = ctx.open_pages(ReserveStudyPages)
        theme = str(org_context.get("theme", "warm"))
        return _rs_resp(pages.render_funding_plan(org=org_context, theme=theme))

    @bp.get("/reserve-study/scenarios")
    def rs_scenarios() -> ResponseReturnValue:
        pages = ctx.open_pages(ReserveStudyPages)
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        return _rs_resp(
            pages.render_scenarios(
                org=org_context, theme=theme, flash_message=flash_message
            )
        )

    @bp.get("/reserve-study/scenarios/new")
    def rs_scenario_new_form() -> ResponseReturnValue:
        pages = ctx.open_pages(ReserveStudyPages)
        theme = str(org_context.get("theme", "warm"))
        return _rs_resp(pages.render_scenario_form(org=org_context, theme=theme))

    @bp.post("/reserve-study/scenarios/new")
    def rs_scenario_new_save() -> ResponseReturnValue:
        from flask import redirect

        pages = ctx.open_pages(ReserveStudyPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_save_scenario(
            None,
            form_data={k: v for k, v in request.form.items()},
            org=org_context,
            theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return _rs_resp(form_resp)

    @bp.get("/reserve-study/scenarios/<int:scenario_id>/edit")
    def rs_scenario_edit_form(scenario_id: int) -> ResponseReturnValue:
        pages = ctx.open_pages(ReserveStudyPages)
        theme = str(org_context.get("theme", "warm"))
        return _rs_resp(
            pages.render_scenario_form(scenario_id, org=org_context, theme=theme)
        )

    @bp.post("/reserve-study/scenarios/<int:scenario_id>/edit")
    def rs_scenario_edit_save(scenario_id: int) -> ResponseReturnValue:
        from flask import redirect

        pages = ctx.open_pages(ReserveStudyPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_save_scenario(
            scenario_id,
            form_data={k: v for k, v in request.form.items()},
            org=org_context,
            theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return _rs_resp(form_resp)

    @bp.post("/reserve-study/scenarios/<int:scenario_id>/delete")
    def rs_scenario_delete(scenario_id: int) -> ResponseReturnValue:
        from flask import redirect

        pages = ctx.open_pages(ReserveStudyPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, _ = pages.handle_delete_scenario(
            scenario_id, org=org_context, theme=theme
        )
        return redirect(redirect_url or "/reserve-study/scenarios", code=303)

    @bp.get("/reserve-study/report")
    def rs_report_preview() -> ResponseReturnValue:
        pages = ctx.open_pages(ReserveStudyPages)
        theme = str(org_context.get("theme", "warm"))
        return _rs_resp(pages.render_report_preview(org=org_context, theme=theme))

    @bp.get("/reserve-study/report/download")
    def rs_word_report() -> ResponseReturnValue:
        import urllib.parse

        pages = ctx.open_pages(ReserveStudyPages)
        org_name = str(org_context.get("name", "HOA"))
        docx_bytes = pages.generate_word_report(org_name=org_name)
        safe_name = urllib.parse.quote(org_name.replace(" ", "_"))
        filename = f"Reserve_Fund_Study_{safe_name}.docx"
        return Response(
            docx_bytes,
            status=200,
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ── Opening Balances pages ───────────────────────────────────────

    @bp.get("/opening-balances")
    def opening_balances_page() -> ResponseReturnValue:
        pages = ctx.open_pages(OpeningBalancesPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_page(
            org=org_context,
            theme=theme,
            flash=(request.args.get("msg") or "").strip() or None,
            error=(request.args.get("error") or "").strip() or None,
        )
        return Response(
            resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8"
        )

    @bp.post("/opening-balances/save")
    def save_opening_balances() -> ResponseReturnValue:
        from flask import redirect

        pages = ctx.open_pages(OpeningBalancesPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_save(
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

    # ── Reserve transfer pages ───────────────────────────────────────

    @bp.get("/reserve-transfers")
    def list_reserve_transfers() -> ResponseReturnValue:
        pages = ctx.open_pages(ReserveTransferPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_list(
            org=org_context,
            theme=theme,
            type_filter=(request.args.get("type_filter") or "").strip() or None,
            start_date=(request.args.get("start_date") or "").strip() or None,
            end_date=(request.args.get("end_date") or "").strip() or None,
            flash_message=(request.args.get("msg") or "").strip() or None,
            error_message=(request.args.get("error") or "").strip() or None,
        )
        return Response(
            resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8"
        )

    @bp.get("/reserve-transfers/new")
    def new_reserve_transfer_form() -> ResponseReturnValue:
        pages = ctx.open_pages(ReserveTransferPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_new_form(org=org_context, theme=theme)
        return Response(
            resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8"
        )

    @bp.post("/reserve-transfers/new")
    def submit_new_reserve_transfer() -> ResponseReturnValue:
        from flask import redirect

        pages = ctx.open_pages(ReserveTransferPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_new(
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

    @bp.post("/reserve-transfers/<int:transfer_id>/delete")
    def delete_reserve_transfer(transfer_id: int) -> ResponseReturnValue:
        from flask import redirect

        pages = ctx.open_pages(ReserveTransferPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_delete(
            transfer_id=transfer_id,
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

    # ── Budget pages ─────────────────────────────────────────────────

    @bp.get("/budgets")
    def list_budgets() -> ResponseReturnValue:
        pages = ctx.open_pages(BudgetPages)
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        resp = pages.render_list(
            org=org_context, theme=theme, flash_message=flash_message
        )
        return Response(
            resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8"
        )

    @bp.get("/budgets/new")
    def new_budget_form() -> ResponseReturnValue:
        pages = ctx.open_pages(BudgetPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_new_form(org=org_context, theme=theme)
        return Response(
            resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8"
        )

    @bp.post("/budgets/new")
    def submit_new_budget() -> ResponseReturnValue:
        from flask import redirect

        pages = ctx.open_pages(BudgetPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_new(
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

    @bp.get("/budgets/<int:budget_id>/edit")
    def edit_budget_form(budget_id: int) -> ResponseReturnValue:
        pages = ctx.open_pages(BudgetPages)
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        resp = pages.render_edit_form(
            budget_id,
            org=org_context,
            theme=theme,
            flash_message=flash_message,
        )
        return Response(
            resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8"
        )

    @bp.post("/budgets/<int:budget_id>/edit")
    def submit_save_budget(budget_id: int) -> ResponseReturnValue:
        from flask import redirect

        pages = ctx.open_pages(BudgetPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_save(
            budget_id,
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

    @bp.post("/budgets/<int:budget_id>/approve")
    def approve_budget(budget_id: int) -> ResponseReturnValue:
        from flask import redirect

        pages = ctx.open_pages(BudgetPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_approve(
            budget_id,
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

    @bp.post("/budgets/<int:budget_id>/revert-to-draft")
    def revert_budget_to_draft(budget_id: int) -> ResponseReturnValue:
        from flask import redirect

        pages = ctx.open_pages(BudgetPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_revert_to_draft(
            budget_id,
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

    @bp.post("/budgets/<int:budget_id>/archive")
    def archive_budget(budget_id: int) -> ResponseReturnValue:
        from flask import redirect

        pages = ctx.open_pages(BudgetPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_archive(
            budget_id,
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

    @bp.post("/budgets/<int:budget_id>/un-archive")
    def un_archive_budget(budget_id: int) -> ResponseReturnValue:
        from flask import redirect

        pages = ctx.open_pages(BudgetPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_un_archive(
            budget_id,
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

    @bp.post("/budgets/<int:budget_id>/delete")
    def delete_budget(budget_id: int) -> ResponseReturnValue:
        from flask import redirect

        pages = ctx.open_pages(BudgetPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_delete(
            budget_id,
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
