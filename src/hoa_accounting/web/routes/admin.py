"""Admin (database, import/export, audit log)."""

from __future__ import annotations

from flask import Blueprint, Response, g, redirect, request
from flask.typing import ResponseReturnValue
from flask import session as _session

from hoa_accounting.web.route_context import RouteContext
from hoa_accounting.web.audit_log_pages import AuditLogPages
from hoa_accounting.web.bank_statement_pages import BankStatementPages
from hoa_accounting.web.database_admin_pages import DatabaseAdminPages
from hoa_accounting.web.export_pages import ExportPages
from hoa_accounting.web.import_pages import ImportPages


def make_admin_blueprint(ctx: RouteContext) -> Blueprint:
    bp = Blueprint("admin", __name__)
    org_context = ctx.org_context

    def _open_db():
        return ctx.open_db()

    # ── Audit log pages ──────────────────────────────────────────────


    @bp.get("/admin/audit-log")
    def audit_log_page() -> ResponseReturnValue:
        pages = ctx.open_pages(AuditLogPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render(
            org=org_context,
            theme=theme,
            table_filter=(request.args.get("table") or "").strip(),
            action_filter=(request.args.get("action") or "").strip(),
            user_filter=(request.args.get("user") or "").strip(),
            date_from=(request.args.get("date_from") or "").strip(),
            date_to=(request.args.get("date_to") or "").strip(),
            page=max(1, int(request.args.get("page") or 1)),
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")


    # ── Import pages ──────────────────────────────────────────────────


    @bp.get("/admin/import")
    def import_page() -> ResponseReturnValue:
        pages = ctx.open_pages(ImportPages)
        theme = str(org_context.get("theme", "warm"))
        ba_raw = request.args.get("bank_account_id", "")
        resp  = pages.render_page(
            org=org_context, theme=theme,
            prefill_type=request.args.get("prefill_type", ""),
            stash_token=request.args.get("stash", ""),
            bank_account_id=int(ba_raw) if ba_raw.isdigit() else None,
            note=request.args.get("note", ""),
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/bank-import/save-mapping")
    def bank_import_save_mapping() -> ResponseReturnValue:
        """Persist a CSV → canonical-fields map, then replay the stashed
        upload through the normal ingest path so it produces canonical
        ``bank_transactions`` rows with the new mapping applied."""
        from flask import redirect
        from urllib.parse import quote
        from hoa_accounting.web.bank_ingest import (
            consume_stash, fingerprint_csv_headers, read_csv_headers,
            save_csv_mapping,
        )
        import json as _json
        conn = _open_db()
        theme = str(org_context.get("theme", "warm"))

        try:
            mapping = _json.loads(request.form.get("mapping", "{}"))
        except ValueError:
            return redirect("/bank-transactions/pending?err=Invalid+mapping", code=303)
        stash_token = (request.form.get("stash_token") or "").strip()
        if not stash_token:
            return redirect("/bank-transactions/pending?err=Missing+stash+token", code=303)

        stash = consume_stash(conn, stash_token)
        if stash is None:
            return redirect(
                "/bank-transactions/pending?err=Upload+expired.+Please+retry.",
                code=303,
            )
        bank_account_id, filename, content = stash

        # Persist the mapping so future uploads with this same CSV shape
        # skip the wizard entirely.
        fp = fingerprint_csv_headers(content)
        save_csv_mapping(conn, bank_account_id, fp, mapping, read_csv_headers(content))

        # Replay ingest with the mapping now in place. The saved-mapping
        # lookup inside handle_agnostic_upload will find the new row and
        # parse silently.
        from hoa_accounting.web.bank_statement_pages import BankStatementPages
        pages = BankStatementPages(conn)
        url, page_resp, _warnings = pages.handle_agnostic_upload(
            file_bytes=content, filename=filename or "upload.csv",
            csv_bank_account_id=bank_account_id,
            org=org_context, theme=theme,
        )
        if url:
            # Success: drop them on the Pending Validation queue scoped to
            # this account so they see the rows they just imported.
            return redirect(
                f"/bank-transactions/pending?bank_account_id={bank_account_id}"
                f"&msg={quote('Mapping saved; import complete.')}",
                code=303,
            )
        assert page_resp is not None
        return Response(page_resp.body_html, status=page_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.get("/admin/import/run")
    def import_run_redirect() -> ResponseReturnValue:
        from flask import redirect
        return redirect("/admin/import", code=303)

    @bp.post("/admin/import/run")
    def import_run() -> ResponseReturnValue:
        pages = ctx.open_pages(ImportPages)
        theme = str(org_context.get("theme", "warm"))
        resp  = pages.handle_run(
            data_type   = request.form.get("data_type",   ""),
            mapping_json= request.form.get("mapping",     "{}"),
            csv_content = request.form.get("csv_content", ""),
            file_name   = request.form.get("file_name",   "unknown.csv"),
            org         = org_context,
            theme       = theme,
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/admin/import/validate")
    def import_validate() -> ResponseReturnValue:
        import json as _json
        pages  = ctx.open_pages(ImportPages)
        result = pages.handle_validate(
            data_type    = request.form.get("data_type",    ""),
            mapping_json = request.form.get("mapping",      "{}"),
            csv_content  = request.form.get("csv_content",  ""),
            filter_field = request.form.get("filter_field", ""),
        )
        return Response(_json.dumps(result), status=200,
                        mimetype="application/json")


    # ── Export pages ─────────────────────────────────────────────────


    @bp.get("/admin/export")
    def export_page() -> ResponseReturnValue:
        pages = ctx.open_pages(ExportPages)
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_page(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/admin/export/download")
    def export_download() -> ResponseReturnValue:
        pages = ctx.open_pages(ExportPages)
        selected = request.form.getlist("export_key")
        if not selected:
            theme = str(org_context.get("theme", "warm"))
            resp = pages.render_page(
                org=org_context, theme=theme,
                error_message="Please select at least one data set to export.",
            )
            return Response(resp.body_html, status=resp.status_code,
                            mimetype="text/html; charset=utf-8")
        zip_bytes = pages.build_zip(selected)
        return Response(
            zip_bytes,
            status=200,
            mimetype="application/zip",
            headers={"Content-Disposition": 'attachment; filename="hoa-download.zip"'},
        )


    # ── Database admin pages ─────────────────────────────────────────

    def _open_db_admin_pages() -> DatabaseAdminPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError("database.path missing from config.")
        conn = _open_db()
        return DatabaseAdminPages(conn, db_path=str(db_path))

    # Wizard Catalog routes removed — the COA-era admin tool is gone.
    # The interview now drives the Categories table instead.

    @bp.get("/setup/categories-interview")
    def categories_interview() -> ResponseReturnValue:
        from hoa_accounting.web.category_wizard_pages import CategoryWizardPages
        conn = _open_db()
        theme = str(org_context.get("theme", "warm"))
        flash = (request.args.get("msg") or "").replace("+", " ").strip()
        resp = CategoryWizardPages(conn).render(
            org=org_context, theme=theme, flash_message=flash,
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/setup/categories-interview")
    def categories_interview_submit() -> ResponseReturnValue:
        from flask import redirect
        from hoa_accounting.web.category_wizard_pages import CategoryWizardPages
        conn = _open_db()
        codes = request.form.getlist("codes")
        url, _ = CategoryWizardPages(conn).handle_submit(selected_codes=codes)
        return redirect(url, code=303)

    @bp.get("/admin/database")
    def database_admin_page() -> ResponseReturnValue:
        pages = _open_db_admin_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_page(
            org=org_context, theme=theme,
            flash_message=(request.args.get("msg") or "").strip(),
            error_message=(request.args.get("error") or "").strip(),
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/admin/database/check")
    def database_health_check() -> ResponseReturnValue:
        pages = _open_db_admin_pages()
        theme = str(org_context.get("theme", "warm"))
        _, form_resp = pages.handle_check(org=org_context, theme=theme)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/admin/database/reindex")
    def database_reindex() -> ResponseReturnValue:
        from flask import redirect
        pages = _open_db_admin_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_reindex(org=org_context, theme=theme)
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/admin/database/vacuum")
    def database_vacuum() -> ResponseReturnValue:
        from flask import redirect
        pages = _open_db_admin_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_vacuum(org=org_context, theme=theme)
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.post("/admin/database/wal-checkpoint")
    def database_wal_checkpoint() -> ResponseReturnValue:
        from flask import redirect
        pages = _open_db_admin_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_wal_checkpoint(org=org_context, theme=theme)
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @bp.get("/admin/database/backup")
    def database_backup() -> ResponseReturnValue:
        import json as _json
        pages = _open_db_admin_pages()
        data, filename, stats = pages.handle_backup()
        return Response(
            data,
            status=200,
            mimetype="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(data)),
                "X-Backup-Stats": _json.dumps(stats),
                "Access-Control-Expose-Headers": "X-Backup-Stats",
            },
        )

    @bp.post("/admin/database/restore-preview")
    def database_restore_preview() -> ResponseReturnValue:
        import json as _json
        pages = _open_db_admin_pages()
        backup_file = request.files.get("backup_file")
        if not backup_file:
            return Response(
                _json.dumps({"ok": False, "error": "No file received."}),
                status=400, mimetype="application/json",
            )
        result = pages.handle_restore_preview(backup_file.read())
        status = 200 if result.get("ok") else 400
        return Response(_json.dumps(result), status=status,
                        mimetype="application/json")

    @bp.post("/admin/database/restore")
    def database_restore() -> ResponseReturnValue:
        import json as _json
        from flask import redirect
        pages = _open_db_admin_pages()
        theme = str(org_context.get("theme", "warm"))
        # JS callers send X-Restore-Fetch: 1 and expect JSON back.
        wants_json = request.headers.get("X-Restore-Fetch") == "1"
        backup_file = request.files.get("backup_file")
        if not backup_file:
            if wants_json:
                return Response(
                    _json.dumps({"ok": False, "error": "No backup file received — please try again."}),
                    status=400, mimetype="application/json",
                )
            resp = pages.render_page(
                org=org_context, theme=theme,
                error_message="No backup file received — please try again.",
            )
            return Response(resp.body_html, status=resp.status_code,
                            mimetype="text/html; charset=utf-8")
        file_bytes = backup_file.read()
        redirect_url, form_resp, error_msg = pages.handle_restore(
            file_bytes, org=org_context, theme=theme
        )
        if wants_json:
            if redirect_url is not None:
                return Response(
                    _json.dumps({"ok": True, "message": "Database restored successfully. All previous data has been replaced with the backup."}),
                    status=200, mimetype="application/json",
                )
            return Response(
                _json.dumps({"ok": False, "error": error_msg or "Restore failed."}),
                status=400, mimetype="application/json",
            )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")


    return bp
