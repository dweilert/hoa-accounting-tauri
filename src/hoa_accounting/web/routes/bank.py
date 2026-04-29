"""Bank routes (accounts, recon, OFX, transactions, rules, deposits, AR)."""

from __future__ import annotations

import sqlite3
from typing import Any

from flask import Blueprint, Response, g, redirect, request
from flask.typing import ResponseReturnValue
from flask import session as _session

from hoa_accounting.web.route_context import RouteContext
from hoa_accounting.web.ar_pages import ARPages
from hoa_accounting.web.bank_account_pages import BankAccountPages
from hoa_accounting.web.bank_statement_pages import BankStatementPages
from hoa_accounting.web.bank_transactions_pages import BankTransactionsPages
from hoa_accounting.web.deposit_batch_pages import DepositBatchPages
from hoa_accounting.web.non_dues_income_pages import NonDuesIncomePages
from hoa_accounting.web.ofx_inbox_pages import OFXInboxPages
from hoa_accounting.web.reconciliation_pages import ReconciliationPages
from hoa_accounting.web.record_deposit_pages import RecordDepositPages
from hoa_accounting.web.transaction_rule_pages import TransactionRulePages


def _summarise_fetcher_response(status: int, body: Any, *, mode: str) -> str:
    """Turn the fetcher's JSON reply into a short user-facing message."""
    if status == 202 and isinstance(body, dict):
        job = body.get("job_id") or "?"
        return f"Fetcher queued {mode} job {job}. This page will refresh when it completes."
    if status == 503:
        return "Fetcher daemon not reachable on 127.0.0.1:17866 — is it running?"
    if isinstance(body, dict):
        return f"Fetcher returned HTTP {status}: {body}"
    return f"Fetcher returned HTTP {status}: {body}"


def make_bank_blueprint(ctx: RouteContext) -> Blueprint:
    bp = Blueprint("bank", __name__)
    org_context = ctx.org_context

    def _open_db() -> sqlite3.Connection:
        return ctx.open_db()

    # ── AR / Receivables pages ───────────────────────────────────────


    @bp.get("/ar/lots")
    def ar_lots_list() -> ResponseReturnValue:
        pages = ctx.open_pages(ARPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_list(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.get("/ar/lots/<int:lot_id>")
    def ar_lot_detail(lot_id: int) -> ResponseReturnValue:
        from datetime import date as _date
        pages = ctx.open_pages(ARPages)
        theme = str(org_context.get("theme", "warm"))
        try:
            year = int(request.args.get("year") or _date.today().year)
        except (ValueError, TypeError):
            year = _date.today().year
        resp = pages.render_lot_detail(
            lot_id=lot_id, year=year, org=org_context, theme=theme
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")


    # ── Transaction pages: Non-Dues Income ───────────────────────────


    # /income was the old "Other Income" screen; its flow is now an
    # "other source" row on the unified /deposit grid.
    @bp.get("/income")
    def list_income() -> ResponseReturnValue:
        from flask import redirect
        return redirect("/deposit", code=303)

    @bp.get("/income/new")
    def new_income_form() -> ResponseReturnValue:
        pages = ctx.open_pages(NonDuesIncomePages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/income/new")
    def submit_income() -> ResponseReturnValue:
        from flask import redirect
        pages = ctx.open_pages(NonDuesIncomePages)
        theme = str(org_context.get("theme", "warm"))
        form_data = {k: v for k, v in request.form.items()}
        redirect_url, form_resp = pages.handle_post(
            form_data=form_data, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")


    # ── Transaction pages: Deposit Batches ──────────────────────────


    # /deposits was the old "Record Payments" screen; collapsed into the
    # unified /deposit grid. Kept as a 303 so bookmarks survive.
    @bp.get("/deposits")
    def list_deposits() -> ResponseReturnValue:
        from flask import redirect
        return redirect("/deposit", code=303)

    @bp.get("/deposits/new")
    def new_deposit_batch_form() -> ResponseReturnValue:
        pages = ctx.open_pages(DepositBatchPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/deposits/new")
    def submit_deposit_batch() -> ResponseReturnValue:
        from flask import redirect
        pages = ctx.open_pages(DepositBatchPages)
        theme = str(org_context.get("theme", "warm"))
        form_data = {k: v for k, v in request.form.items()}
        redirect_url, form_resp = pages.handle_post(
            form_data=form_data, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")


    # ── Transaction rules ─────────────────────────────────────────────


    @bp.get("/admin/transaction-rules")
    def transaction_rules_list() -> ResponseReturnValue:
        pages = ctx.open_pages(TransactionRulePages)
        theme = str(org_context.get("theme", "warm"))
        return_to = request.args.get("return_to", "")
        resp = pages.render_list(org=org_context, theme=theme, return_to=return_to)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/admin/transaction-rules/save")
    def transaction_rules_save() -> ResponseReturnValue:
        from flask import redirect, request
        pages = ctx.open_pages(TransactionRulePages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_save(
            form_data=request.form.to_dict(),
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/admin/transaction-rules/<int:rule_id>/delete")
    def transaction_rules_delete(rule_id: int) -> ResponseReturnValue:
        from flask import redirect
        pages = ctx.open_pages(TransactionRulePages)
        return redirect(pages.handle_delete(rule_id), code=303)

    @bp.post("/admin/transaction-rules/<int:rule_id>/toggle")
    def transaction_rules_toggle(rule_id: int) -> ResponseReturnValue:
        from flask import redirect
        pages = ctx.open_pages(TransactionRulePages)
        return redirect(pages.handle_toggle(rule_id), code=303)

    @bp.get("/admin/transaction-rules/test")
    def transaction_rules_test() -> ResponseReturnValue:
        from hoa_accounting.web.rule_tester_pages import RuleTesterPages
        theme = str(org_context.get("theme", "warm"))
        rule_id = request.args.get("rule_id", type=int)
        txn_id = request.args.get("txn_id", type=int)
        synthetic = {
            "description": request.args.get("syn_description", ""),
            "memo": request.args.get("syn_memo", ""),
            "amount": request.args.get("syn_amount", ""),
            "transaction_type": request.args.get("syn_type", ""),
            "bank_account_id": request.args.get("syn_bank_account_id", ""),
        }
        resp = RuleTesterPages(_open_db()).render(
            org=org_context, theme=theme,
            focus_rule_id=rule_id, txn_id=txn_id,
            synthetic=synthetic,
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")


    # ── Standalone bank statement import ─────────────────────────────────────

    @bp.get("/bank-accounts/<int:bank_account_id>/import-statement")
    def bank_import_list(bank_account_id: int) -> ResponseReturnValue:
        pages = ctx.open_pages(BankStatementPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_standalone_batch_list(bank_account_id, org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.get("/bank-accounts/<int:bank_account_id>/import-statement/upload")
    def bank_import_upload_form(bank_account_id: int) -> ResponseReturnValue:
        pages = ctx.open_pages(BankStatementPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_standalone_upload_form(bank_account_id, org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/bank-accounts/<int:bank_account_id>/import-statement/upload")
    def bank_import_upload(bank_account_id: int) -> ResponseReturnValue:
        from flask import redirect, request
        pages = ctx.open_pages(BankStatementPages)
        theme = str(org_context.get("theme", "warm"))
        file = request.files.get("statement_file")
        if not file or not file.filename:
            resp = pages.render_standalone_upload_form(
                bank_account_id, org=org_context, theme=theme,
                error="Please select a file to upload.",
            )
            return Response(resp.body_html, status=resp.status_code,
                            mimetype="text/html; charset=utf-8")
        file_bytes = file.read()
        redirect_url, form_resp = pages.handle_standalone_upload(
            bank_account_id,
            file_bytes=file_bytes,
            filename=file.filename,
            org=org_context,
            theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    # Per-batch Import Preview screen retired — Pending Validation now
    # serves both the OFX-inbox and Upload-File flows. Batch-level cleanup
    # (delete a whole upload, remap a CSV) still lives at
    # /bank-accounts/<id>/import-statement (the All Imports list).

    @bp.post("/bank-accounts/<int:bank_account_id>/import-statement/<int:batch_id>/remap")
    def bank_import_remap(bank_account_id: int, batch_id: int) -> ResponseReturnValue:
        from flask import redirect, request
        pages = ctx.open_pages(BankStatementPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_standalone_remap(
            bank_account_id, batch_id,
            form_data=request.form.to_dict(),
            org=org_context,
            theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    # Legacy /apply and /reapply-rules removed — superseded by the canonical
    # bank_transactions queue at /bank-transactions/pending. Batches now serve
    # only as an import audit log.

    @bp.post("/bank-accounts/<int:bank_account_id>/import-statement/<int:batch_id>/delete")
    def bank_import_delete(bank_account_id: int, batch_id: int) -> ResponseReturnValue:
        from flask import redirect
        pages = ctx.open_pages(BankStatementPages)
        redirect_url = pages.handle_standalone_delete(bank_account_id, batch_id)
        return redirect(redirect_url, code=303)

    @bp.get("/bank-accounts/<int:bank_account_id>/import-statement/<int:batch_id>/find")
    def bank_import_find(bank_account_id: int, batch_id: int) -> ResponseReturnValue:
        from flask import jsonify
        pages = ctx.open_pages(BankStatementPages)
        result = pages.handle_standalone_find(
            bank_account_id=bank_account_id,
            batch_id=batch_id,
            txn_type=request.args.get("txn_type", ""),
            amount_str=request.args.get("amount", "0"),
            date_str=request.args.get("date", ""),
            ofx_desc=request.args.get("desc", ""),
            ofx_memo=request.args.get("memo", ""),
        )
        return jsonify(result)


    @bp.post("/bank-accounts/<int:bank_account_id>/import-statement/<int:batch_id>/transactions/<int:txn_id>/apply-find")
    def bank_import_apply_find(bank_account_id: int, batch_id: int, txn_id: int) -> ResponseReturnValue:
        from flask import jsonify
        body = request.get_json(silent=True) or {}
        pages = ctx.open_pages(BankStatementPages)
        result = pages.handle_apply_find_match(
            bank_account_id=bank_account_id,
            batch_id=batch_id,
            txn_id=txn_id,
            payment_ids=body.get("payment_ids", []),
        )
        return jsonify(result)

    @bp.post("/bank-accounts/<int:bank_account_id>/import-statement/<int:batch_id>/transactions/<int:txn_id>/apply-bill")
    def bank_import_apply_bill(bank_account_id: int, batch_id: int, txn_id: int) -> ResponseReturnValue:
        from flask import jsonify
        body = request.get_json(silent=True) or {}
        pages = ctx.open_pages(BankStatementPages)
        result = pages.handle_apply_bill_match(
            bank_account_id=bank_account_id,
            batch_id=batch_id,
            txn_id=txn_id,
            bill_ids=body.get("bill_ids", []),
        )
        return jsonify(result)



    # ── OFX Inbox (fetcher daemon integration) ───────────────────────────────

    def _open_ofx_inbox_pages() -> Any:
        from hoa_accounting.web.ofx_inbox_pages import OFXInboxPages
        return OFXInboxPages(_open_db())

    @bp.get("/ofx-inbox")
    def ofx_inbox_page() -> ResponseReturnValue:
        pages = _open_ofx_inbox_pages()
        theme = str(org_context.get("theme", "warm"))
        flash = request.args.get("msg", "") or request.args.get("err", "")
        resp = pages.render_inbox(
            org=org_context, theme=theme,
            flash_message=flash if request.args.get("msg") else "",
            error_message=flash if request.args.get("err") else "",
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/ofx-inbox/import")
    def ofx_inbox_import_one() -> ResponseReturnValue:
        from flask import redirect
        from urllib.parse import quote
        pages = _open_ofx_inbox_pages()
        filename = (request.form.get("filename") or "").strip()
        redirect_url, flash = pages.handle_import_one(
            filename=filename, org=org_context,
        )
        # Prefer the handler's redirect, augmenting with the flash text
        # so the user sees what happened.
        if flash:
            sep = "&" if "?" in redirect_url else "?"
            tag = "msg" if "failed" not in flash.lower() else "err"
            redirect_url = f"{redirect_url}{sep}{tag}={quote(flash)}"
        return redirect(redirect_url, code=303)

    @bp.post("/ofx-inbox/delete")
    def ofx_inbox_delete() -> ResponseReturnValue:
        from flask import redirect
        from urllib.parse import quote
        pages = _open_ofx_inbox_pages()
        filename = (request.form.get("filename") or "").strip()
        redirect_url, flash = pages.handle_delete(
            filename=filename, org=org_context,
        )
        if flash:
            sep = "&" if "?" in redirect_url else "?"
            tag = "msg" if "could not" not in flash.lower() else "err"
            redirect_url = f"{redirect_url}{sep}{tag}={quote(flash)}"
        return redirect(redirect_url, code=303)

    @bp.post("/ofx-inbox/import-all")
    def ofx_inbox_import_all() -> ResponseReturnValue:
        from flask import redirect
        from urllib.parse import quote
        pages = _open_ofx_inbox_pages()
        redirect_url, flash = pages.handle_import_all(org=org_context)
        if flash:
            sep = "&" if "?" in redirect_url else "?"
            tag = "msg" if "failed" not in flash.lower() else "err"
            redirect_url = f"{redirect_url}{sep}{tag}={quote(flash)}"
        return redirect(redirect_url, code=303)

    @bp.post("/ofx-inbox/fetch")
    def ofx_inbox_fetch() -> ResponseReturnValue:
        from flask import redirect
        from urllib.parse import quote
        pages = _open_ofx_inbox_pages()
        status, body = pages.proxy_fetch(mode="headless")
        msg = _summarise_fetcher_response(status, body, mode="headless")
        tag = "msg" if status < 400 else "err"
        return redirect(f"/ofx-inbox?{tag}={quote(msg)}", code=303)

    @bp.post("/ofx-inbox/fetch-headed")
    def ofx_inbox_fetch_headed() -> ResponseReturnValue:
        from flask import redirect
        from urllib.parse import quote
        pages = _open_ofx_inbox_pages()
        status, body = pages.proxy_fetch(mode="headed")
        msg = _summarise_fetcher_response(status, body, mode="headed")
        tag = "msg" if status < 400 else "err"
        return redirect(f"/ofx-inbox?{tag}={quote(msg)}", code=303)

    @bp.get("/ofx-inbox/status")
    def ofx_inbox_status() -> ResponseReturnValue:
        pages = _open_ofx_inbox_pages()
        status, body = pages.proxy_status()
        import json as _json
        if isinstance(body, dict):
            text = _json.dumps(body)
        else:
            text = str(body)
        return Response(text, status=status, mimetype="application/json")

    @bp.post("/api/ofx-ready")
    def ofx_ready_webhook() -> ResponseReturnValue:
        # Hardening: accept only from localhost; fetcher runs on the same
        # machine. This is belt-and-suspenders on top of path validation.
        if request.remote_addr not in ("127.0.0.1", "::1", "localhost"):
            return Response("", status=403)
        try:
            payload = request.get_json(force=True, silent=True) or {}
        except Exception:  # noqa: BLE001
            payload = {}
        pages = _open_ofx_inbox_pages()
        http_status, body = pages.handle_ofx_ready(
            payload=payload, org=org_context,
        )
        return Response(body, status=http_status, mimetype="text/plain")


    # ── Pending Validation (canonical bank_transactions queue) ───────────────

    def _open_bank_txn_pages() -> Any:
        from hoa_accounting.web.bank_transactions_pages import BankTransactionsPages
        return BankTransactionsPages(_open_db())

    @bp.get("/bank-transactions/pending")
    def bank_txn_pending_page() -> ResponseReturnValue:
        pages = _open_bank_txn_pages()
        theme = str(org_context.get("theme", "warm"))
        raw = request.args.get("bank_account_id", "")
        bank_account_id = int(raw) if raw.isdigit() else None
        show_ignored = (request.args.get("show_ignored") or "").strip() in ("1", "true", "yes")
        import_msg = request.args.get("import_msg", "")
        import_warn = request.args.get("import_warn", "")
        warnings = [w.strip() for w in import_warn.split(" | ") if w.strip()] if import_warn else []
        resp = pages.render_pending(
            org=org_context, theme=theme,
            bank_account_id=bank_account_id,
            show_ignored=show_ignored,
            flash_message=request.args.get("msg", ""),
            error_message=request.args.get("err", ""),
            import_message=import_msg,
            import_warnings=warnings,
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.get("/bank-transactions/dry-run")
    def bank_txn_dry_run() -> ResponseReturnValue:
        pages = _open_bank_txn_pages()
        theme = str(org_context.get("theme", "warm"))
        ba_raw = (request.args.get("bank_account_id") or "").strip()
        ba_id = int(ba_raw) if ba_raw.isdigit() else None
        resp = pages.render_dry_run(org=org_context, theme=theme, bank_account_id=ba_id)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/bank-transactions/accept-all")
    def bank_txn_accept_all() -> ResponseReturnValue:
        from flask import redirect
        from urllib.parse import quote
        pages = _open_bank_txn_pages()
        ba_raw = (request.form.get("bank_account_id") or "").strip()
        ba_id = int(ba_raw) if ba_raw.isdigit() else None
        url, flash = pages.handle_accept_all(bank_account_id=ba_id)
        if flash:
            sep = "&" if "?" in url else "?"
            tag = "msg" if "Accepted" in flash else "msg"
            url = f"{url}{sep}{tag}={quote(flash)}"
        return redirect(url, code=303)

    @bp.post("/bank-transactions/revalidate")
    def bank_txn_revalidate() -> ResponseReturnValue:
        from flask import redirect
        from urllib.parse import quote
        pages = _open_bank_txn_pages()
        ba_raw = (request.form.get("bank_account_id") or "").strip()
        ba_id = int(ba_raw) if ba_raw.isdigit() else None
        url, flash = pages.handle_revalidate(bank_account_id=ba_id)
        if flash:
            sep = "&" if "?" in url else "?"
            tag = "msg" if "no" not in flash.lower()[:3] else "msg"
            url = f"{url}{sep}{tag}={quote(flash)}"
        return redirect(url, code=303)

    @bp.post("/bank-transactions/<int:bank_txn_id>/accept")
    def bank_txn_accept(bank_txn_id: int) -> ResponseReturnValue:
        from flask import redirect
        from urllib.parse import quote
        pages = _open_bank_txn_pages()
        url, flash = pages.handle_accept(bank_txn_id)
        if flash:
            sep = "&" if "?" in url else "?"
            tag = "msg" if "could not" not in flash.lower() and "not found" not in flash.lower() else "err"
            url = f"{url}{sep}{tag}={quote(flash)}"
        return redirect(url, code=303)

    @bp.get("/bank-transactions/manual")
    def bank_txn_manual_page() -> ResponseReturnValue:
        pages = _open_bank_txn_pages()
        theme = str(org_context.get("theme", "warm"))
        raw = request.args.get("bank_account_id", "")
        resp = pages.render_manual_entry(
            org=org_context, theme=theme,
            bank_account_id=int(raw) if raw.isdigit() else None,
            flash_message=request.args.get("msg", ""),
            error_message=request.args.get("err", ""),
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/bank-transactions/manual")
    def bank_txn_manual_submit() -> ResponseReturnValue:
        from flask import redirect
        from urllib.parse import quote
        pages = _open_bank_txn_pages()
        theme = str(org_context.get("theme", "warm"))
        ba_raw = (request.form.get("bank_account_id") or "").strip()
        if not ba_raw.isdigit():
            return redirect("/bank-transactions/manual?err=Select+a+bank+account", code=303)

        # Rebuild the list of row dicts from the bracketed form names
        # ("rows[3][date]" etc.). Flask's MultiDict flattens them so we
        # walk the keys and coalesce by index.
        import re
        pat = re.compile(r"^rows\[(\d+)\]\[([a-z_]+)\]$")
        rows_by_idx: dict[int, dict[str, Any]] = {}
        for key, val in request.form.items():
            m = pat.match(key)
            if not m:
                continue
            idx = int(m.group(1))
            rows_by_idx.setdefault(idx, {})[m.group(2)] = val
        ordered_rows = [rows_by_idx[i] for i in sorted(rows_by_idx.keys())]

        url, flash = pages.handle_manual_submit(
            bank_account_id=int(ba_raw),
            rows=ordered_rows,
            org=org_context, theme=theme,
        )
        if flash:
            sep = "&" if "?" in url else "?"
            tag = "msg" if "added" in flash.lower() else "err"
            url = f"{url}{sep}{tag}={quote(flash)}"
        return redirect(url, code=303)

    @bp.get("/bank-transactions/<int:bank_txn_id>/classify")
    def bank_txn_classify_page(bank_txn_id: int) -> ResponseReturnValue:
        pages = _open_bank_txn_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_classify(
            bank_txn_id=bank_txn_id, org=org_context, theme=theme,
            error_message=request.args.get("err", ""),
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/bank-transactions/<int:bank_txn_id>/classify/pick")
    def bank_txn_classify_pick(bank_txn_id: int) -> ResponseReturnValue:
        from flask import redirect
        from urllib.parse import quote
        from decimal import Decimal as _D, InvalidOperation as _IOp
        pages = _open_bank_txn_pages()
        cat_list = request.form.getlist("line_category_id")
        amt_list = request.form.getlist("line_amount")
        if not cat_list or len(cat_list) != len(amt_list):
            return redirect(f"/bank-transactions/{bank_txn_id}/classify?err=Pick+at+least+one+category", code=303)
        lines: list[tuple[int, _D]] = []
        for c_raw, a_raw in zip(cat_list, amt_list):
            c = (c_raw or "").strip()
            a = (a_raw or "").strip().replace(",", "").replace("$", "")
            if not c.isdigit() or not a:
                return redirect(f"/bank-transactions/{bank_txn_id}/classify?err=Each+line+needs+a+category+and+amount", code=303)
            try:
                lines.append((int(c), _D(a)))
            except _IOp:
                return redirect(f"/bank-transactions/{bank_txn_id}/classify?err=Invalid+amount", code=303)
        vendor_raw = (request.form.get("vendor_id") or "").strip()
        vendor_id = int(vendor_raw) if vendor_raw.isdigit() else None
        lot_raw = (request.form.get("lot_id") or "").strip()
        lot_id = int(lot_raw) if lot_raw.isdigit() else None
        memo = (request.form.get("memo") or "").strip()
        url, flash = pages.handle_pick_category(
            bank_txn_id,
            lines=lines,
            vendor_id=vendor_id,
            lot_id=lot_id,
            memo=memo,
        )
        if flash:
            sep = "&" if "?" in url else "?"
            tag = "msg" if "not" not in flash.lower() and "required" not in flash.lower() else "err"
            url = f"{url}{sep}{tag}={quote(flash)}"
        return redirect(url, code=303)

    @bp.post("/bank-transactions/<int:bank_txn_id>/classify/link")
    def bank_txn_classify_link(bank_txn_id: int) -> ResponseReturnValue:
        from flask import redirect
        from urllib.parse import quote
        pages = _open_bank_txn_pages()
        pick = (request.form.get("pick") or "").strip()
        if ":" not in pick:
            return redirect(f"/bank-transactions/{bank_txn_id}/classify?err=Select+a+record", code=303)
        source_type, _, source_id_raw = pick.partition(":")
        if not source_id_raw.isdigit():
            return redirect(f"/bank-transactions/{bank_txn_id}/classify?err=Invalid+selection", code=303)
        url, flash = pages.handle_link_existing(
            bank_txn_id,
            source_type=source_type,
            source_id=int(source_id_raw),
        )
        if flash:
            sep = "&" if "?" in url else "?"
            tag = "msg" if "linked" in flash.lower() else "err"
            url = f"{url}{sep}{tag}={quote(flash)}"
        return redirect(url, code=303)

    @bp.post("/bank-transactions/<int:bank_txn_id>/ignore")
    def bank_txn_ignore(bank_txn_id: int) -> ResponseReturnValue:
        from flask import redirect
        from urllib.parse import quote
        pages = _open_bank_txn_pages()
        url, flash = pages.handle_ignore(bank_txn_id)
        if flash:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}msg={quote(flash)}"
        return redirect(url, code=303)

    @bp.post("/bank-transactions/<int:bank_txn_id>/unignore")
    def bank_txn_unignore(bank_txn_id: int) -> ResponseReturnValue:
        from flask import redirect
        from urllib.parse import quote
        pages = _open_bank_txn_pages()
        url, flash = pages.handle_unignore(bank_txn_id)
        if flash:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}msg={quote(flash)}"
        return redirect(url, code=303)


    # ── Record Deposit (unified money-in entry point) ────────────────────────

    def _open_record_deposit_pages() -> Any:
        from hoa_accounting.web.record_deposit_pages import RecordDepositPages
        return RecordDepositPages(_open_db())

    @bp.get("/deposit")
    def record_deposit_page() -> ResponseReturnValue:
        pages = _open_record_deposit_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(
            org=org_context, theme=theme,
            flash_message=request.args.get("msg", ""),
            error_message=request.args.get("err", ""),
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/deposit")
    def record_deposit_submit() -> ResponseReturnValue:
        from flask import redirect
        from urllib.parse import quote
        import re
        pages = _open_record_deposit_pages()

        deposit_date = (request.form.get("deposit_date") or "").strip()
        bank_raw = (request.form.get("bank_account_id") or "").strip()
        memo = (request.form.get("memo") or "").strip()

        # Reconstruct the grid rows from the bracketed form names.
        pat = re.compile(r"^rows\[(\d+)\]\[([a-z_]+)\]$")
        rows_by_idx: dict[int, dict[str, Any]] = {}
        for key, val in request.form.items():
            m = pat.match(key)
            if not m:
                continue
            rows_by_idx.setdefault(int(m.group(1)), {})[m.group(2)] = val
        ordered_rows = [rows_by_idx[i] for i in sorted(rows_by_idx.keys())]

        theme = str(org_context.get("theme", "warm"))

        def _rerender(err: str) -> ResponseReturnValue:
            resp = pages.render_form(
                org=org_context, theme=theme, error_message=err,
                prior_deposit_date=deposit_date,
                prior_bank_account_id=bank_raw,
                prior_memo=memo,
                prior_rows=ordered_rows,
            )
            return Response(resp.body_html, status=resp.status_code,
                            mimetype="text/html; charset=utf-8")

        if not bank_raw.isdigit():
            return _rerender("Pick a bank account.")

        url, flash = pages.handle_submit(
            deposit_date=deposit_date,
            bank_account_id=int(bank_raw),
            memo=memo,
            rows=ordered_rows,
        )
        # Validation failure: handle_submit returns ("/deposit", error_text).
        # Re-render the form with the typed values + error so the user
        # doesn't lose what they entered.
        if flash and url == "/deposit":
            return _rerender(flash)
        if flash:
            sep = "&" if "?" in url else "?"
            tag = "msg" if "saved" in flash.lower() else "err"
            url = f"{url}{sep}{tag}={quote(flash)}"
        return redirect(url, code=303)


    # ── Menu aliases / retired-page redirects ────────────────────────────────
    # The sidebar reorg points "Bill Owners" at /owners/bill — a thin alias
    # that lands on the Dues tab of the existing billing stack. The four
    # billing pages share a tab bar so any of them can land you elsewhere.

    @bp.get("/owners/bill")
    def owners_bill_landing() -> ResponseReturnValue:
        from flask import redirect
        return redirect("/dues-billing", code=303)


    # ── Account-agnostic bank import ─────────────────────────────────────────

    @bp.get("/bank-import/upload")
    def bank_import_agnostic_form() -> ResponseReturnValue:
        pages = ctx.open_pages(BankStatementPages)
        theme = str(org_context.get("theme", "warm"))
        success = request.args.get("msg") if request.args.get("ok") else None
        resp = pages.render_agnostic_upload_form(org=org_context, theme=theme, success=success)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8")

    @bp.post("/bank-import/upload")
    def bank_import_agnostic_upload() -> ResponseReturnValue:
        from flask import redirect
        pages = ctx.open_pages(BankStatementPages)
        theme = str(org_context.get("theme", "warm"))
        file = request.files.get("statement_file")
        if not file or not file.filename:
            resp = pages.render_agnostic_upload_form(org=org_context, theme=theme,
                                                     error="Please select a file.")
            return Response(resp.body_html, status=200, mimetype="text/html; charset=utf-8")
        ba_id_raw = request.form.get("csv_bank_account_id", "").strip()
        csv_ba_id = int(ba_id_raw) if ba_id_raw else None
        redirect_url, page_resp, _warnings = pages.handle_agnostic_upload(
            file_bytes=file.read(), filename=file.filename,
            csv_bank_account_id=csv_ba_id, org=org_context, theme=theme,
        )
        if redirect_url:
            return redirect(redirect_url, code=303)
        assert page_resp is not None
        return Response(page_resp.body_html, status=page_resp.status_code, mimetype="text/html; charset=utf-8")


    # ── Bank statement import ─────────────────────────────────────────



    # ── Reconciliation pages ──────────────────────────────────────────


    @bp.get("/reconciliations")
    def list_reconciliations() -> ResponseReturnValue:
        from flask import request
        pages = ctx.open_pages(ReconciliationPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_list(
            org=org_context, theme=theme,
            flash_message=request.args.get("msg"),
            error_message=request.args.get("error"),
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.get("/reconciliations/new")
    def new_reconciliation_form() -> ResponseReturnValue:
        pages = ctx.open_pages(ReconciliationPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_new_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/reconciliations/new")
    def submit_new_reconciliation() -> ResponseReturnValue:
        from flask import redirect, request
        pages = ctx.open_pages(ReconciliationPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_new(
            form_data=request.form.to_dict(),
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.get("/reconciliations/<int:reconciliation_id>")
    def view_reconciliation(reconciliation_id: int) -> ResponseReturnValue:
        from flask import request
        pages = ctx.open_pages(ReconciliationPages)
        theme = str(org_context.get("theme", "warm"))
        show_prior = request.args.get("show_prior") == "1"
        flash = request.args.get("msg")
        resp = pages.render_working(
            reconciliation_id, org=org_context, theme=theme,
            show_prior=show_prior, flash_message=flash,
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/reconciliations/<int:reconciliation_id>/toggle")
    def toggle_reconciliation_line(reconciliation_id: int) -> ResponseReturnValue:
        from flask import request
        pages = ctx.open_pages(ReconciliationPages)
        status, body = pages.handle_toggle(
            reconciliation_id, form_data=request.form.to_dict()
        )
        return Response(body, status=status,
                        mimetype="application/json")

    @bp.post("/reconciliations/<int:reconciliation_id>/finalize")
    def finalize_reconciliation(reconciliation_id: int) -> ResponseReturnValue:
        from flask import redirect
        pages = ctx.open_pages(ReconciliationPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_finalize(
            reconciliation_id, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/reconciliations/<int:reconciliation_id>/reopen")
    def reopen_reconciliation(reconciliation_id: int) -> ResponseReturnValue:
        from flask import redirect
        pages = ctx.open_pages(ReconciliationPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_reopen(
            reconciliation_id, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/reconciliations/<int:reconciliation_id>/delete")
    def delete_reconciliation(reconciliation_id: int) -> ResponseReturnValue:
        from flask import redirect
        pages = ctx.open_pages(ReconciliationPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_delete(
            reconciliation_id, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")


    # ── Bank account pages ────────────────────────────────────────────


    @bp.get("/bank-accounts")
    def list_bank_accounts() -> ResponseReturnValue:
        pages = ctx.open_pages(BankAccountPages)
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        resp = pages.render_list(org=org_context, theme=theme,
                                 flash_message=flash_message)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.get("/bank-accounts/add")
    def new_bank_account_form() -> ResponseReturnValue:
        pages = ctx.open_pages(BankAccountPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/bank-accounts/add")
    def submit_new_bank_account() -> ResponseReturnValue:
        from flask import redirect
        pages = ctx.open_pages(BankAccountPages)
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

    @bp.get("/bank-accounts/<int:bank_account_id>/edit")
    def edit_bank_account_form(bank_account_id: int) -> ResponseReturnValue:
        pages = ctx.open_pages(BankAccountPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme,
                                 bank_account_id=bank_account_id)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/bank-accounts/<int:bank_account_id>/edit")
    def submit_edit_bank_account(bank_account_id: int) -> ResponseReturnValue:
        from flask import redirect
        pages = ctx.open_pages(BankAccountPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_edit(
            bank_account_id=bank_account_id,
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/bank-accounts/<int:bank_account_id>/delete")
    def submit_delete_bank_account(bank_account_id: int) -> ResponseReturnValue:
        from flask import redirect
        pages = ctx.open_pages(BankAccountPages)
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_delete(
            bank_account_id=bank_account_id,
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")


    return bp
