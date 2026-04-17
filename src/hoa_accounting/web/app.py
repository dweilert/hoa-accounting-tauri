"""Flask application for the HOA accounting web UI.

This module is the framework seam. The existing read-only page services
(``HomePageService``, ``ReportConsolePageService``) are reused verbatim —
the Flask view functions only translate between ``request`` / ``response``
objects and those services. No report logic, no template rendering, and
no accounting logic lives here.

Forms and write-side routes will be added in later PRs; earlier changes
were the framework swap and this change is the visual overhaul, so the
page services still return pre-rendered HTML strings. Future write-side
routes will use Flask's ``render_template`` directly for form UX.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, Response, g, request

from hoa_accounting.api.report_api import ReportAPIService
from hoa_accounting.application.report_runner import ReportRunner
from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.config.loader import load_config
from hoa_accounting.db.connection import connect_sqlite
from hoa_accounting.web.assessment_billing_pages import AssessmentBillingPages
from hoa_accounting.web.deposit_batch_pages import DepositBatchPages
from hoa_accounting.web.lot_pages import LotPages
from hoa_accounting.web.lot_renters_pages import LotRentersPages
from hoa_accounting.web.master_data_pages import MasterDataListService
from hoa_accounting.web.owner_pages import OwnerPages
from hoa_accounting.web.bank_account_pages import BankAccountPages
from hoa_accounting.web.vendor_pages import VendorPages
from hoa_accounting.web.non_dues_income_pages import NonDuesIncomePages
from hoa_accounting.web.ui_server import (
    HomePageService,
    ReportConsolePageService,
    UIResponse,
)
from hoa_accounting.web.vendor_bill_pages import VendorBillPages


def _ui_response_to_flask(response: UIResponse) -> Response:
    """Convert the UI layer's typed response into a Flask response."""
    return Response(
        response.body_html,
        status=response.status_code,
        mimetype="text/html; charset=utf-8",
    )


def _flatten_query_params(multi_dict: Any) -> dict[str, str]:
    """Collapse a werkzeug MultiDict/ImmutableMultiDict into the single-value
    shape the existing UI services expect.

    Mirrors the behavior of the legacy ``http.server`` code: keep only the
    last value for each key, drop empty strings.
    """
    out: dict[str, str] = {}
    for key in multi_dict.keys():
        value = multi_dict.getlist(key)[-1]
        if value is not None and str(value).strip() != "":
            out[key] = value
    return out


def _load_org_context(config_path: Path) -> dict[str, Any]:
    """Pull the pieces of config templates want into a small dict.

    If the config can't be loaded (missing or malformed), fall back to
    safe placeholders so the UI still renders rather than 500-ing at the
    sidebar. This matches the ergonomics of a dev machine where config
    may not be fully written yet.
    """
    try:
        config = load_config(config_path)
    except Exception:
        return {
            "name": "HOA Accounting",
            "legal_name": "",
            "environment": "local",
            "fiscal_year_start_month": 1,
            "theme": "warm",
            "dues_receivable_account_number": "1100",
        }
    return {
        "name": config.hoa.name,
        "legal_name": config.hoa.legal_name,
        "environment": config.app.environment,
        "fiscal_year_start_month": config.accounting.fiscal_year_start_month,
        "theme": getattr(config.app, "theme", "warm"),
        "db_path": config.database.path,
        "dues_receivable_account_number": getattr(
            config.accounting, "dues_receivable_account_number", "1100"
        ),
    }


def create_app(config_path: str | Path = "config.yaml") -> Flask:
    """Build a Flask app wired to the read-only report UI services."""
    app = Flask(__name__)
    resolved_config_path = Path(config_path)

    runner = ReportRunner(config_path=resolved_config_path)
    api_service = ReportAPIService(runner)
    home_service = HomePageService(api_service)
    report_page_service = ReportConsolePageService(api_service)

    # The existing UI services render via their own Jinja environment and
    # don't see Flask's context processors. Pass `org` through as part of
    # the view-model context instead — handled in view_models.py.
    org_context = _load_org_context(resolved_config_path)

    # Apply any pending schema migrations to the configured database on
    # startup. The migrator is idempotent (already-applied migrations are
    # skipped), so booting an older DB silently catches up to the current
    # schema. Failure here is intentionally left to surface at boot rather
    # than per-request — better to fail loudly at startup than to 500 on
    # every page that touches a missing column.
    db_path = org_context.get("db_path")
    if db_path:
        boot_conn = connect_sqlite(str(db_path))
        try:
            Migrator().apply_all(boot_conn)
        finally:
            boot_conn.close()

    @app.before_request
    def _attach_org() -> None:
        g.org = org_context

    @app.get("/static/app.css")
    def _static_css_passthrough() -> Response:
        # Flask serves /static/* by default when static_folder is set.
        # This route is only here as a fallback if the Flask app is ever
        # initialised without a discoverable static folder.
        from flask import send_from_directory
        static_dir = Path(__file__).resolve().parent / "static"
        return send_from_directory(static_dir, "app.css")

    @app.get("/")
    def home() -> Response:
        return _ui_response_to_flask(home_service.render_page(org=org_context))

    @app.get("/reports")
    def reports_console() -> Response:
        selected = request.args.get("report_name", "trial-balance").strip()
        if not selected:
            selected = "trial-balance"
        return _ui_response_to_flask(
            report_page_service.render_page(
                selected_report=selected,
                org=org_context,
            )
        )

    @app.get("/run-report")
    def run_report() -> Response:
        params = _flatten_query_params(request.args)
        report_name = params.pop("report_name", "").strip()
        return _ui_response_to_flask(
            report_page_service.render_report(
                report_name=report_name,
                query_params=params,
                org=org_context,
            )
        )

    # ── Master-data list pages ───────────────────────────────────────
    # Each route opens its own SQLite connection per request and closes
    # it via Flask's teardown hook. Short-lived, independent, and safe
    # to run concurrently with WAL mode (enabled in connect_sqlite).

    def _open_master_data_service() -> MasterDataListService:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; master-data pages need it."
            )
        conn = connect_sqlite(str(db_path))
        g._md_conn = conn
        return MasterDataListService(conn)

    @app.teardown_request
    def _close_master_data_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_md_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._md_conn = None

    def _render_list(page: str) -> Response:
        svc = _open_master_data_service()
        renderer = {
            "accounts": svc.render_accounts,
        }[page]
        theme = str(org_context.get("theme", "warm"))
        resp = renderer(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/accounts")
    def list_accounts() -> Response: return _render_list("accounts")

    # ── Bank account pages ────────────────────────────────────────────

    def _open_bank_account_pages() -> BankAccountPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; bank account pages need it."
            )
        conn = connect_sqlite(str(db_path))
        g._ba_conn = conn
        return BankAccountPages(conn)

    @app.teardown_request
    def _close_ba_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_ba_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._ba_conn = None

    @app.get("/bank-accounts")
    def list_bank_accounts() -> Response:
        pages = _open_bank_account_pages()
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        resp = pages.render_list(org=org_context, theme=theme,
                                 flash_message=flash_message)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/bank-accounts/add")
    def new_bank_account_form() -> Response:
        pages = _open_bank_account_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/bank-accounts/add")
    def submit_new_bank_account() -> Response:
        from flask import redirect
        pages = _open_bank_account_pages()
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

    @app.get("/bank-accounts/<int:bank_account_id>/edit")
    def edit_bank_account_form(bank_account_id: int) -> Response:
        pages = _open_bank_account_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme,
                                 bank_account_id=bank_account_id)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/bank-accounts/<int:bank_account_id>/edit")
    def submit_edit_bank_account(bank_account_id: int) -> Response:
        from flask import redirect
        pages = _open_bank_account_pages()
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

    @app.post("/bank-accounts/<int:bank_account_id>/delete")
    def submit_delete_bank_account(bank_account_id: int) -> Response:
        from flask import redirect
        pages = _open_bank_account_pages()
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

    # ── Lot pages ─────────────────────────────────────────────────────

    def _open_lot_pages() -> LotPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; lot pages need it."
            )
        conn = connect_sqlite(str(db_path))
        g._lot_conn = conn
        return LotPages(conn)

    @app.teardown_request
    def _close_lot_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_lot_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._lot_conn = None

    @app.get("/lots")
    def list_lots() -> Response:
        pages = _open_lot_pages()
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        resp = pages.render_list(org=org_context, theme=theme,
                                 flash_message=flash_message)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/lots/add")
    def new_lot_form() -> Response:
        pages = _open_lot_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/lots/add")
    def submit_new_lot() -> Response:
        from flask import redirect
        pages = _open_lot_pages()
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

    @app.get("/lots/<int:lot_id>/edit")
    def edit_lot_form(lot_id: int) -> Response:
        pages = _open_lot_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme, lot_id=lot_id)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/lots/<int:lot_id>/edit")
    def submit_edit_lot(lot_id: int) -> Response:
        from flask import redirect
        pages = _open_lot_pages()
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

    @app.post("/lots/<int:lot_id>/delete")
    def submit_delete_lot(lot_id: int) -> Response:
        from flask import redirect
        pages = _open_lot_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_delete(
            lot_id=lot_id, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    # ── Renter pages ─────────────────────────────────────────────────

    def _open_renter_pages() -> LotRentersPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; renter pages need it."
            )
        conn = connect_sqlite(str(db_path))
        g._renter_conn = conn
        return LotRentersPages(conn)

    @app.teardown_request
    def _close_renter_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_renter_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._renter_conn = None

    @app.get("/renters")
    def list_renters() -> Response:
        pages = _open_renter_pages()
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        resp = pages.render_list(org=org_context, theme=theme,
                                 flash_message=flash_message)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/renters/add")
    def new_renter_form() -> Response:
        pages = _open_renter_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/renters/add")
    def submit_new_renter() -> Response:
        from flask import redirect
        pages = _open_renter_pages()
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

    @app.get("/renters/<int:renter_id>/edit")
    def edit_renter_form(renter_id: int) -> Response:
        pages = _open_renter_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme,
                                 renter_id=renter_id)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/renters/<int:renter_id>/edit")
    def submit_edit_renter(renter_id: int) -> Response:
        from flask import redirect
        pages = _open_renter_pages()
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

    @app.post("/renters/<int:renter_id>/end")
    def submit_end_tenancy(renter_id: int) -> Response:
        from flask import redirect
        pages = _open_renter_pages()
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

    # ── Vendor pages ─────────────────────────────────────────────────

    def _open_vendor_pages() -> VendorPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; vendor pages need it."
            )
        conn = connect_sqlite(str(db_path))
        g._vendor_conn = conn
        return VendorPages(conn)

    @app.teardown_request
    def _close_vendor_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_vendor_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._vendor_conn = None

    @app.get("/vendors")
    def list_vendors() -> Response:
        pages = _open_vendor_pages()
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        resp = pages.render_list(org=org_context, theme=theme,
                                 flash_message=flash_message)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/vendors/add")
    def new_vendor_form() -> Response:
        pages = _open_vendor_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/vendors/add")
    def submit_new_vendor() -> Response:
        from flask import redirect
        pages = _open_vendor_pages()
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

    @app.get("/vendors/<int:vendor_id>/edit")
    def edit_vendor_form(vendor_id: int) -> Response:
        pages = _open_vendor_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme,
                                 vendor_id=vendor_id)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/vendors/<int:vendor_id>/edit")
    def submit_edit_vendor(vendor_id: int) -> Response:
        from flask import redirect
        pages = _open_vendor_pages()
        theme = str(org_context.get("theme", "warm"))
        form_data = {k: v for k, v in request.form.items()}
        if "_active_flag_present" in form_data and "active_flag" not in form_data:
            form_data["active_flag"] = "0"
        redirect_url, form_resp = pages.handle_edit(
            vendor_id=vendor_id, form_data=form_data,
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/vendors/<int:vendor_id>/delete")
    def submit_delete_vendor(vendor_id: int) -> Response:
        from flask import redirect
        pages = _open_vendor_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_delete(
            vendor_id=vendor_id, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    # ── Owner pages ───────────────────────────────────────────────────

    def _open_owner_pages() -> OwnerPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; owner pages need it."
            )
        conn = connect_sqlite(str(db_path))
        g._owner_conn = conn
        return OwnerPages(conn)

    @app.teardown_request
    def _close_owner_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_owner_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._owner_conn = None

    @app.get("/owners")
    def list_owners() -> Response:
        pages = _open_owner_pages()
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        resp = pages.render_list(org=org_context, theme=theme,
                                 flash_message=flash_message)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/owners/add")
    def new_owner_form() -> Response:
        pages = _open_owner_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/owners/add")
    def submit_new_owner() -> Response:
        from flask import redirect
        pages = _open_owner_pages()
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

    @app.get("/owners/<int:owner_id>/edit")
    def edit_owner_form(owner_id: int) -> Response:
        pages = _open_owner_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme,
                                 owner_id=owner_id)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/owners/<int:owner_id>/edit")
    def submit_edit_owner(owner_id: int) -> Response:
        from flask import redirect
        pages = _open_owner_pages()
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

    @app.post("/owners/<int:owner_id>/mark-previous")
    def submit_mark_previous(owner_id: int) -> Response:
        from flask import redirect
        pages = _open_owner_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_mark_previous(
            owner_id=owner_id,
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/owners/<int:owner_id>/delete")
    def submit_delete_owner(owner_id: int) -> Response:
        from flask import redirect
        pages = _open_owner_pages()
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

    # ── Transaction pages: Vendor Bills ──────────────────────────────
    # Same per-request connection pattern as the master-data pages, with
    # a form-handling POST added. Redirect-on-success uses a query param
    # (`?created=JE-...`) so the list page can display a success banner
    # without pulling in Flask-Session or a secret key.

    def _open_vendor_bill_pages() -> VendorBillPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; transaction pages need it."
            )
        conn = connect_sqlite(str(db_path))
        g._tx_conn = conn
        return VendorBillPages(conn)

    @app.teardown_request
    def _close_tx_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_tx_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._tx_conn = None

    @app.get("/vendor-bills")
    def list_vendor_bills() -> Response:
        pages = _open_vendor_bill_pages()
        theme = str(org_context.get("theme", "warm"))
        created = (request.args.get("created") or "").strip() or None
        resp = pages.render_list(org=org_context, theme=theme, created_entry_number=created)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/vendor-bills/new")
    def new_vendor_bill_form() -> Response:
        pages = _open_vendor_bill_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/vendor-bills/new")
    def submit_vendor_bill() -> Response:
        from flask import redirect
        pages = _open_vendor_bill_pages()
        theme = str(org_context.get("theme", "warm"))
        form_data = {k: v for k, v in request.form.items()}
        redirect_url, form_resp = pages.handle_post(
            form_data=form_data, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)  # see-other: GET the list
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    # ── Transaction pages: Deposit Batches ──────────────────────────

    def _open_deposit_batch_pages() -> DepositBatchPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; transaction pages need it."
            )
        conn = connect_sqlite(str(db_path))
        g._tx_conn = conn
        return DepositBatchPages(conn)

    @app.get("/deposits")
    def list_deposits() -> Response:
        pages = _open_deposit_batch_pages()
        theme = str(org_context.get("theme", "warm"))
        created = (request.args.get("created") or "").strip() or None
        resp = pages.render_list(org=org_context, theme=theme, created_entry_number=created)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/deposits/new")
    def new_deposit_batch_form() -> Response:
        pages = _open_deposit_batch_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/deposits/new")
    def submit_deposit_batch() -> Response:
        from flask import redirect
        pages = _open_deposit_batch_pages()
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

    # ── Transaction pages: Non-Dues Income ───────────────────────────

    def _open_income_pages() -> NonDuesIncomePages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; income pages need it."
            )
        conn = connect_sqlite(str(db_path))
        g._tx_conn = conn
        return NonDuesIncomePages(conn)

    @app.get("/income")
    def list_income() -> Response:
        pages = _open_income_pages()
        theme = str(org_context.get("theme", "warm"))
        created = (request.args.get("created") or "").strip() or None
        resp = pages.render_list(org=org_context, theme=theme, created_entry_number=created)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/income/new")
    def new_income_form() -> Response:
        pages = _open_income_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/income/new")
    def submit_income() -> Response:
        from flask import redirect
        pages = _open_income_pages()
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

    # ── Transaction pages: Bill Assessments ─────────────────────────

    def _open_assessment_billing_pages() -> AssessmentBillingPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; billing pages need it."
            )
        conn = connect_sqlite(str(db_path))
        g._tx_conn = conn
        return AssessmentBillingPages(conn)

    @app.get("/assessments/bill")
    def bill_assessments_page() -> Response:
        pages = _open_assessment_billing_pages()
        theme = str(org_context.get("theme", "warm"))
        billed_msg = (request.args.get("billed") or "").strip() or ""
        resp = pages.render_page(
            org=org_context, theme=theme,
            success_message=billed_msg,
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/assessments/bill-all")
    def submit_bill_all() -> Response:
        from flask import redirect
        pages = _open_assessment_billing_pages()
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

    @app.post("/assessments/bill-individual")
    def submit_bill_individual() -> Response:
        from flask import redirect
        pages = _open_assessment_billing_pages()
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

    return app
