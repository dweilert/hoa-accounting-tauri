"""Homeowner-side: lots, owners, renters, board, billing, fees."""

from __future__ import annotations

from flask import Blueprint, Response, g, redirect, request
from flask import session as _session

from hoa_accounting.web.route_context import RouteContext
from hoa_accounting.web.assessment_billing_pages import AssessmentBillingPages
from hoa_accounting.web.dues_billing_pages import DuesBillingPages
from hoa_accounting.web.edit_records_pages import EditRecordsPages
from hoa_accounting.web.late_fee_pages import LateFeePages
from hoa_accounting.web.lot_pages import LotPages
from hoa_accounting.web.lot_renters_pages import LotRentersPages
from hoa_accounting.web.owner_pages import OwnerPages
from hoa_accounting.web.resale_fee_pages import ResaleFeePages


def make_homeowners_blueprint(ctx: RouteContext) -> Blueprint:
    bp = Blueprint("homeowners", __name__)
    org_context = ctx.org_context

    def _open_db():
        return ctx.open_db()

    # ── Resale Certificate Fee ────────────────────────────────────────────────
    def _open_resale_fee_pages() -> ResaleFeePages:
        conn = _open_db()
        return ResaleFeePages(conn=conn)

    def _resale_fee_config() -> tuple[str, str]:
        """Return (default_amount, income_account_number).

        ``income_account_number`` is vestigial after the Chart-of-Accounts
        removal — ResaleFeePages now looks up the RESALE_FEE category by
        code internally and ignores this argument. Kept in the tuple to
        avoid churning all the resale-fee call sites.
        """
        amount = str(org_context.get("resale_fee_default_amount") or "175.00")
        return amount, "4070"

    @bp.get("/resale-fee")
    def resale_fee_page() -> Response:
        from flask import request as _req
        pages = _open_resale_fee_pages()
        theme = str(org_context.get("theme", "warm"))
        default_amount, income_account = _resale_fee_config()
        flash = _req.args.get("msg", "")
        resp = pages.render_page(
            org=org_context, theme=theme,
            default_amount=default_amount,
            income_account_number=income_account,
            flash_message=flash,
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/resale-fee/post-charge")
    def resale_fee_post_charge() -> Response:
        from flask import redirect, request as _req
        pages = _open_resale_fee_pages()
        theme = str(org_context.get("theme", "warm"))
        default_amount, income_account = _resale_fee_config()
        redirect_url, resp = pages.handle_post_charge(
            form_data=dict(_req.form),
            org=org_context,
            theme=theme,
            default_amount=default_amount,
            income_account_number=income_account,
        )
        if redirect_url:
            return redirect(redirect_url)
        assert resp is not None
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    # /resale-fee/payments was a specialized payment form; under the new
    # model it's a specific-charges row on /deposit.
    @bp.get("/resale-fee/payments")
    def resale_fee_payments_page() -> Response:
        from flask import redirect
        return redirect("/deposit", code=303)

    @bp.post("/resale-fee/post-payment")
    def resale_fee_post_payment() -> Response:
        from flask import redirect, request as _req
        pages = _open_resale_fee_pages()
        theme = str(org_context.get("theme", "warm"))
        default_amount, income_account = _resale_fee_config()
        redirect_url, resp = pages.handle_post_payment(
            form_data=dict(_req.form),
            org=org_context,
            theme=theme,
            default_amount=default_amount,
            income_account_number=income_account,
        )
        if redirect_url:
            return redirect(redirect_url)
        assert resp is not None
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")


    # ── Dues Billing pages ───────────────────────────────────────────


    @bp.get("/dues-billing")
    def dues_billing_page() -> Response:
        pages = ctx.open_pages(DuesBillingPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_page(
            org=org_context, theme=theme,
            flash_message=(request.args.get("msg") or "").strip(),
            error_message=(request.args.get("error") or "").strip(),
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/dues-billing/post")
    def submit_dues_billing() -> Response:
        from flask import redirect
        pages = ctx.open_pages(DuesBillingPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_bill(
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")


    # ── Late Fee pages ───────────────────────────────────────────────


    @bp.get("/late-fees")
    def late_fees_page() -> Response:
        pages = ctx.open_pages(LateFeePages)
        theme = str(org_context.get("theme", "warm"))
        lot_id_raw = (request.args.get("lot_id") or "").strip()
        lot_id = int(lot_id_raw) if lot_id_raw.isdigit() else None
        resp = pages.render_page(
            org=org_context, theme=theme,
            lot_id=lot_id,
            flash_message=(request.args.get("msg") or "").strip(),
            error_message=(request.args.get("error") or "").strip(),
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/late-fees/post")
    def submit_late_fees() -> Response:
        from flask import redirect
        pages = ctx.open_pages(LateFeePages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_post(
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")


    # ── Transaction pages: Bill Assessments ─────────────────────────


    @bp.get("/assessments/bill")
    def bill_assessments_page() -> Response:
        pages = ctx.open_pages(AssessmentBillingPages)
        theme = str(org_context.get("theme", "warm"))
        billed_msg = (request.args.get("billed") or "").strip() or ""
        resp = pages.render_page(
            org=org_context, theme=theme,
            success_message=billed_msg,
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/assessments/bill-all")
    def submit_bill_all() -> Response:
        from flask import redirect
        pages = ctx.open_pages(AssessmentBillingPages)
        theme = str(org_context.get("theme", "warm"))
        form_data = {k: v for k, v in request.form.items()}
        redirect_url, form_resp = pages.handle_bill_all(
            form_data=form_data, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/assessments/bill-individual")
    def submit_bill_individual() -> Response:
        from flask import redirect
        pages = ctx.open_pages(AssessmentBillingPages)
        theme = str(org_context.get("theme", "warm"))
        form_data = {k: v for k, v in request.form.items()}
        redirect_url, form_resp = pages.handle_bill_individuals(
            form_data=form_data, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")


    # ── Edit Records hub + payments ledger ──────────────────────────

    def _open_edit_records_pages():
        from hoa_accounting.web.edit_records_pages import EditRecordsPages
        return EditRecordsPages(_open_db())

    @bp.get("/manage/edit-records")
    def edit_records_hub() -> Response:
        pages = _open_edit_records_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_hub(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.get("/manage/edit-records/payments")
    def edit_records_payments() -> Response:
        pages = _open_edit_records_pages()
        theme = str(org_context.get("theme", "warm"))
        flash = request.args.get("msg", "")
        resp = pages.render_payments(
            org=org_context, theme=theme, flash_message=flash,
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/manage/edit-records/payments/<int:payment_id>/edit")
    def edit_records_payments_submit(payment_id: int) -> Response:
        from flask import redirect
        pages = _open_edit_records_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_payment_edit(
            payment_id,
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.get("/manage/edit-records/non-dues-income")
    def edit_records_income() -> Response:
        pages = _open_edit_records_pages()
        theme = str(org_context.get("theme", "warm"))
        flash = request.args.get("msg", "")
        resp = pages.render_income(org=org_context, theme=theme, flash_message=flash)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.get("/manage/edit-records/non-dues-income/<int:income_batch_id>/split")
    def edit_records_income_split_form(income_batch_id: int) -> Response:
        pages = _open_edit_records_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_income_split(income_batch_id, org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/manage/edit-records/non-dues-income/<int:income_batch_id>/split")
    def edit_records_income_split_submit(income_batch_id: int) -> Response:
        from flask import redirect
        pages = _open_edit_records_pages()
        theme = str(org_context.get("theme", "warm"))
        cats = request.form.getlist("line_category_id")
        amts = request.form.getlist("line_amount")
        redirect_url, form_resp = pages.handle_income_split(
            income_batch_id,
            line_category_ids=cats, line_amounts=amts,
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/manage/edit-records/non-dues-income/<int:income_batch_id>/edit")
    def edit_records_income_submit(income_batch_id: int) -> Response:
        from flask import redirect
        pages = _open_edit_records_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_income_edit(
            income_batch_id,
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.get("/manage/edit-records/assessments")
    def edit_records_assessments() -> Response:
        pages = _open_edit_records_pages()
        theme = str(org_context.get("theme", "warm"))
        flash = request.args.get("msg", "")
        resp = pages.render_assessments(org=org_context, theme=theme, flash_message=flash)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/manage/edit-records/assessments/<int:assessment_id>/edit")
    def edit_records_assessments_submit(assessment_id: int) -> Response:
        from flask import redirect
        pages = _open_edit_records_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_assessment_edit(
            assessment_id,
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")


    # ── Owner pages ───────────────────────────────────────────────────


    @bp.get("/owners")
    def list_owners() -> Response:
        pages = ctx.open_pages(OwnerPages)
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        resp = pages.render_list(org=org_context, theme=theme,
                                 flash_message=flash_message)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.get("/owners/add")
    def new_owner_form() -> Response:
        pages = ctx.open_pages(OwnerPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/owners/add")
    def submit_new_owner() -> Response:
        from flask import redirect
        pages = ctx.open_pages(OwnerPages)
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

    @bp.get("/owners/<int:owner_id>/edit")
    def edit_owner_form(owner_id: int) -> Response:
        pages = ctx.open_pages(OwnerPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme,
                                 owner_id=owner_id)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/owners/<int:owner_id>/edit")
    def submit_edit_owner(owner_id: int) -> Response:
        from flask import redirect
        pages = ctx.open_pages(OwnerPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_edit(
            owner_id=owner_id,
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/owners/<int:owner_id>/delete")
    def submit_delete_owner(owner_id: int) -> Response:
        from flask import redirect
        pages = ctx.open_pages(OwnerPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_delete(
            owner_id=owner_id,
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")


    # ── Board Member pages ───────────────────────────────────────────

    def _open_board_member_pages():
        from hoa_accounting.web.board_member_pages import BoardMemberPages
        return BoardMemberPages(_open_db())

    @bp.get("/board-members")
    def list_board_members() -> Response:
        pages = _open_board_member_pages()
        theme = str(org_context.get("theme", "warm"))
        flash = (request.args.get("msg") or "").strip()
        resp = pages.render_list(org=org_context, theme=theme, flash_message=flash)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.get("/board-members/add")
    def new_board_member_form() -> Response:
        pages = _open_board_member_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/board-members/add")
    def submit_new_board_member() -> Response:
        from flask import redirect
        pages = _open_board_member_pages()
        theme = str(org_context.get("theme", "warm"))
        url, form_resp = pages.handle_add(form=request.form, org=org_context, theme=theme)
        if url:
            return redirect(url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.get("/board-members/<int:member_id>/edit")
    def edit_board_member_form(member_id: int) -> Response:
        pages = _open_board_member_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_edit(member_id, org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/board-members/<int:member_id>/edit")
    def submit_edit_board_member(member_id: int) -> Response:
        from flask import redirect
        pages = _open_board_member_pages()
        theme = str(org_context.get("theme", "warm"))
        url, form_resp = pages.handle_edit(member_id, form=request.form,
                                            org=org_context, theme=theme)
        if url:
            return redirect(url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/board-members/<int:member_id>/delete")
    def delete_board_member(member_id: int) -> Response:
        from flask import redirect
        pages = _open_board_member_pages()
        url = pages.handle_delete(member_id)
        return redirect(url, code=303)


    # ── Renter pages ─────────────────────────────────────────────────


    @bp.get("/renters")
    def list_renters() -> Response:
        pages = ctx.open_pages(LotRentersPages)
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        resp = pages.render_list(org=org_context, theme=theme,
                                 flash_message=flash_message)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.get("/renters/add")
    def new_renter_form() -> Response:
        pages = ctx.open_pages(LotRentersPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/renters/add")
    def submit_new_renter() -> Response:
        from flask import redirect
        pages = ctx.open_pages(LotRentersPages)
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

    @bp.get("/renters/<int:renter_id>/edit")
    def edit_renter_form(renter_id: int) -> Response:
        pages = ctx.open_pages(LotRentersPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme,
                                 renter_id=renter_id)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/renters/<int:renter_id>/edit")
    def submit_edit_renter(renter_id: int) -> Response:
        from flask import redirect
        pages = ctx.open_pages(LotRentersPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_edit(
            renter_id=renter_id,
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/renters/<int:renter_id>/end")
    def submit_end_tenancy(renter_id: int) -> Response:
        from flask import redirect
        pages = ctx.open_pages(LotRentersPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_end(
            renter_id=renter_id,
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")


    # ── Lot pages ─────────────────────────────────────────────────────


    @bp.get("/lots")
    def list_lots() -> Response:
        pages = ctx.open_pages(LotPages)
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        resp = pages.render_list(org=org_context, theme=theme,
                                 flash_message=flash_message)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.get("/lots/add")
    def new_lot_form() -> Response:
        pages = ctx.open_pages(LotPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/lots/add")
    def submit_new_lot() -> Response:
        from flask import redirect
        pages = ctx.open_pages(LotPages)
        theme = str(org_context.get("theme", "warm"))
        # active_flag checkbox: present=1, absent=0
        form_data = {k: v for k, v in request.form.items()}
        if "_active_flag_present" in form_data and "active_flag" not in form_data:
            form_data["active_flag"] = "0"
        redirect_url, form_resp = pages.handle_add(
            form_data=form_data, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.get("/lots/<int:lot_id>/edit")
    def edit_lot_form(lot_id: int) -> Response:
        pages = ctx.open_pages(LotPages)
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        resp = pages.render_form(org=org_context, theme=theme, lot_id=lot_id,
                                 flash_message=flash_message)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/lots/<int:lot_id>/edit")
    def submit_edit_lot(lot_id: int) -> Response:
        from flask import redirect
        pages = ctx.open_pages(LotPages)
        theme = str(org_context.get("theme", "warm"))
        form_data = {k: v for k, v in request.form.items()}
        if "_active_flag_present" in form_data and "active_flag" not in form_data:
            form_data["active_flag"] = "0"
        redirect_url, form_resp = pages.handle_edit(
            lot_id=lot_id, form_data=form_data, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/lots/<int:lot_id>/delete")
    def submit_delete_lot(lot_id: int) -> Response:
        from flask import redirect
        pages = ctx.open_pages(LotPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_delete(
            lot_id=lot_id, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/lots/<int:lot_id>/owners/link")
    def submit_link_owner(lot_id: int) -> Response:
        from flask import redirect
        pages = ctx.open_pages(LotPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_link_owner(
            lot_id=lot_id,
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/lots/<int:lot_id>/owners/<int:ownership_id>/end")
    def submit_end_ownership(lot_id: int, ownership_id: int) -> Response:
        from flask import redirect
        pages = ctx.open_pages(LotPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_end_ownership(
            lot_id=lot_id,
            ownership_id=ownership_id,
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/lots/<int:lot_id>/owners/<int:ownership_id>/edit-dates")
    def submit_edit_ownership_dates(lot_id: int, ownership_id: int) -> Response:
        from flask import redirect
        pages = ctx.open_pages(LotPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_edit_ownership_dates(
            lot_id=lot_id,
            ownership_id=ownership_id,
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")


    return bp
