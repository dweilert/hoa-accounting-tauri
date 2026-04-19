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

import yaml
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
from hoa_accounting.web.owner_pages import OwnerPages
from hoa_accounting.web.account_pages import AccountPages
from hoa_accounting.web.account_ledger_pages import AccountLedgerPages
from hoa_accounting.web.all_ledger_pages import AllLedgerPages
from hoa_accounting.web.accounting_period_pages import AccountingPeriodPages
from hoa_accounting.web.bank_account_pages import BankAccountPages
from hoa_accounting.web.database_admin_pages import DatabaseAdminPages
from hoa_accounting.web.export_pages import ExportPages
from hoa_accounting.web.import_pages import ImportPages
from hoa_accounting.web.gl_import_pages import GlImportPages
from hoa_accounting.web.dashboard_pages import DashboardPages
from hoa_accounting.web.year_end_close_pages import YearEndClosePages
from hoa_accounting.web.dues_billing_pages import DuesBillingPages
from hoa_accounting.web.late_fee_pages import LateFeePages
from hoa_accounting.web.opening_balances_pages import OpeningBalancesPages
from hoa_accounting.web.reconciliation_pages import ReconciliationPages
from hoa_accounting.web.reserve_transfer_pages import ReserveTransferPages
from hoa_accounting.web.vendor_pages import VendorPages
from hoa_accounting.web.non_dues_income_pages import NonDuesIncomePages
from hoa_accounting.web.ui_server import (
    HomePageService,
    ReportConsolePageService,
    UIResponse,
)
from hoa_accounting.web.vendor_bill_pages import VendorBillPages
from hoa_accounting.web.manual_journal_pages import ManualJournalPages
from hoa_accounting.web.budget_pages import BudgetPages
from hoa_accounting.web.batch_pdf_pages import BatchPdfPages
from hoa_accounting.web.resale_fee_pages import ResaleFeePages
from hoa_accounting.web.reserve_study_pages import ReserveStudyPages
from hoa_accounting.web.ar_pages import ARPages
from hoa_accounting.web.audit_log_pages import AuditLogPages
from hoa_accounting.web.search_pages import SearchPages


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
            "dues_income_account_number": "4000",
        }
    # Try to read HOA names from the DB (editable via System Settings);
    # fall back to config.yaml values if the table is empty or missing.
    hoa_name = config.hoa.name
    hoa_legal = config.hoa.legal_name
    try:
        import sqlite3 as _sq3
        _c = _sq3.connect(config.database.path)
        _c.row_factory = _sq3.Row
        _row = _c.execute("SELECT display_name, legal_name FROM hoa_profile LIMIT 1").fetchone()
        if _row and _row["display_name"]:
            hoa_name = _row["display_name"]
        if _row and _row["legal_name"]:
            hoa_legal = _row["legal_name"]
        _c.close()
    except Exception:
        pass
    return {
        "name": hoa_name,
        "legal_name": hoa_legal,
        "environment": config.app.environment,
        "fiscal_year_start_month": config.accounting.fiscal_year_start_month,
        "theme": getattr(config.app, "theme", "warm"),
        "db_path": config.database.path,
        "dues_receivable_account_number": getattr(
            config.accounting, "dues_receivable_account_number", "1100"
        ),
        "dues_income_account_number": getattr(
            config.accounting, "dues_income_account_number", "4000"
        ),
        "resale_fee_default_amount": getattr(
            config.accounting, "resale_fee_default_amount", "175.00"
        ),
        "resale_fee_income_account_number": getattr(
            config.accounting, "resale_fee_income_account_number", "4070"
        ),
        "backup_config": (yaml.safe_load(Path(config_path).read_text()) or {}).get("backup") or {},
    }


def create_app(config_path: str | Path = "config.yaml") -> Flask:
    """Build a Flask app wired to the read-only report UI services."""
    app = Flask(__name__)
    # Always use our error handler instead of Werkzeug's interactive debugger,
    # so users see a styled page rather than a raw traceback.
    app.config["PROPAGATE_EXCEPTIONS"] = False
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
        from hoa_accounting.bootstrap.audit_triggers import install_audit_triggers
        from hoa_accounting.bootstrap.backup_service import BackupService
        boot_conn = connect_sqlite(str(db_path))
        try:
            Migrator().apply_all(boot_conn)
            install_audit_triggers(boot_conn)
            backup_cfg = org_context.get("backup_config") or {}
            if backup_cfg.get("dir"):
                BackupService(str(db_path), backup_cfg).run(boot_conn)
        finally:
            boot_conn.close()

    # ── Auth setup ────────────────────────────────────────────────────────
    from hoa_accounting.auth.factory import build_auth_manager
    from hoa_accounting.web.auth_pages import auth_bp, init_auth
    from hoa_accounting.web.decorators import setup_auth_guard

    raw_config: dict = {}
    try:
        import yaml
        with open(resolved_config_path) as _f:
            raw_config = yaml.safe_load(_f) or {}
    except Exception:
        pass

    if db_path:
        auth_manager = build_auth_manager(raw_config, str(db_path))
    else:
        from hoa_accounting.auth.factory import AuthManager, AuthConfig
        from hoa_accounting.auth.local import LocalBackend
        auth_manager = AuthManager(AuthConfig(), LocalBackend(":memory:"))

    app.secret_key = raw_config.get("auth", {}).get("session_secret", "dev-secret-change-me")
    init_auth(auth_manager, org_context)
    app.register_blueprint(auth_bp)

    # _attach_org must be registered BEFORE setup_auth_guard so g.org is
    # available when _forbidden() renders the 403 template.
    @app.before_request
    def _attach_org() -> None:
        from hoa_accounting.web.auth_pages import _get_current_user
        g.org = org_context
        g.current_user = _get_current_user()

    setup_auth_guard(app, org_context)

    # ── User management routes ────────────────────────────────────────────
    from hoa_accounting.web.user_management_pages import UserManagementPages
    UserManagementPages(auth_manager).register(app)

    @app.errorhandler(Exception)
    def _handle_unhandled_exception(exc: Exception) -> Response:
        import traceback as tb
        from hoa_accounting.web.template_engine import render_template as _render

        show_traceback = org_context.get("environment") == "local"
        trace_str = tb.format_exc() if show_traceback else None
        theme = str(org_context.get("theme", "warm"))
        html = _render("error_500.html", {
            "active_nav": "",
            "page_key": "",
            "breadcrumb": "",
            "org": org_context,
            "theme": theme,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": trace_str,
        })
        return Response(html, status=500, mimetype="text/html; charset=utf-8")

    @app.get("/static/app.css")
    def _static_css_passthrough() -> Response:
        # Flask serves /static/* by default when static_folder is set.
        # This route is only here as a fallback if the Flask app is ever
        # initialised without a discoverable static folder.
        from flask import send_from_directory
        static_dir = Path(__file__).resolve().parent / "static"
        return send_from_directory(static_dir, "app.css")

    # ── Audited DB connection helper ─────────────────────────────────────
    def _open_db() -> sqlite3.Connection:
        """Open a connection tagged with the current request user for audit triggers."""
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError("database.path missing from config.")
        conn = connect_sqlite(str(db_path))
        try:
            user = getattr(g, "current_user", None)
            email = user.email if user else "system"
            conn.create_function("audit_user", 0, lambda: email)
        except Exception:
            pass
        return conn

    # ── API helpers ───────────────────────────────────────────────────────

    @app.get("/api/lots/<int:lot_id>/open-charges")
    def api_lot_open_charges(lot_id: int) -> Response:
        """Return open assessments for a lot's current owner in payment-order.

        Used by the deposit batch form to show the treasurer what charges
        will be covered by a payment before it is posted.
        """
        import json
        from decimal import Decimal
        from hoa_accounting.repositories.assessments_repo import AssessmentsRepository
        from hoa_accounting.repositories.lots_repo import LotsRepository

        db_path = org_context.get("db_path")
        if not db_path:
            return Response(json.dumps({"error": "no db"}), status=500,
                            mimetype="application/json")

        conn = _open_db()
        try:
            owner_id = LotsRepository(conn).get_current_owner_id(lot_id)
            if owner_id is None:
                return Response(json.dumps({"charges": [], "total_outstanding": "0.00"}),
                                mimetype="application/json")

            rows = AssessmentsRepository(conn).list_open_for_owner(owner_id)
            charges = []
            total = Decimal("0.00")
            for r in rows:
                outstanding = Decimal(str(r["amount"])) - Decimal(str(r["already_applied"]))
                if outstanding <= 0:
                    continue
                charges.append({
                    "charge_type": r["charge_type"],
                    "description": r["description"] or "",
                    "due_date": r["due_date"] or "",
                    "outstanding": str(outstanding),
                })
                total += outstanding
            return Response(
                json.dumps({"charges": charges, "total_outstanding": str(total)}),
                mimetype="application/json",
            )
        finally:
            conn.close()

    # ── Page routes ───────────────────────────────────────────────────────

    def _open_dashboard() -> DashboardPages:
        conn = _open_db()
        fiscal_year = int(org_context.get("fiscal_year_start_month", 1))
        from datetime import date
        fy = date.today().year
        return DashboardPages(conn, fy)

    @app.get("/")
    def home() -> Response:
        theme = str(org_context.get("theme", "warm"))
        pages = _open_dashboard()
        resp = pages.render_dashboard(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html")

    @app.get("/system-settings")
    def system_settings_page() -> Response:
        theme = str(org_context.get("theme", "warm"))
        flash = (request.args.get("msg") or "").strip() or None
        pages = _open_dashboard()
        resp = pages.render_settings(org=org_context, theme=theme, flash=flash)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html")

    @app.post("/system-settings/save")
    def system_settings_save() -> Response:
        from flask import redirect
        theme = str(org_context.get("theme", "warm"))
        pages = _open_dashboard()
        redirect_url, page_resp = pages.handle_save_settings(request.form, org_context, theme)
        if redirect_url:
            return redirect(redirect_url)
        return Response(page_resp.body_html, status=page_resp.status_code, mimetype="text/html")

    @app.get("/dashboard-config")
    def dashboard_config_page() -> Response:
        theme = str(org_context.get("theme", "warm"))
        flash = (request.args.get("msg") or "").strip() or None
        pages = _open_dashboard()
        resp = pages.render_card_catalog(org=org_context, theme=theme, flash=flash)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html")

    @app.post("/dashboard-config/save-card")
    def dashboard_save_card() -> Response:
        from flask import redirect
        theme = str(org_context.get("theme", "warm"))
        pages = _open_dashboard()
        redirect_url, page_resp = pages.handle_save_card(request.form, org_context, theme)
        if redirect_url:
            return redirect(redirect_url)
        return Response(page_resp.body_html, status=page_resp.status_code, mimetype="text/html")

    @app.post("/dashboard-config/delete-card/<int:card_id>")
    def dashboard_delete_card(card_id: int) -> Response:
        from flask import redirect
        theme = str(org_context.get("theme", "warm"))
        pages = _open_dashboard()
        redirect_url, _ = pages.handle_delete_card(card_id, org_context, theme)
        return redirect(redirect_url)

    @app.post("/dashboard-config/save-layout")
    def dashboard_save_layout() -> Response:
        from flask import redirect
        pages = _open_dashboard()
        redirect_url = pages.handle_save_layout(request.form)
        return redirect(redirect_url)

    def _load_report_lookup_options() -> dict:
        """Load dropdown options for report parameter fields from the DB."""
        db_path = org_context.get("db_path")
        if not db_path:
            return {}
        try:
            conn = _open_db()
            try:
                owners = conn.execute(
                    """
                    SELECT o.id, o.display_name,
                           COALESCE(l.lot_number, '') AS lot_number
                    FROM owners o
                    LEFT JOIN lot_ownership lo
                      ON lo.owner_id = o.id AND lo.end_date IS NULL
                    LEFT JOIN lots l ON l.id = lo.lot_id
                    WHERE o.active_flag = 1
                    ORDER BY CAST(l.lot_number AS REAL), l.lot_number, o.display_name
                    """
                ).fetchall()

                lots = conn.execute(
                    """
                    SELECT l.id, l.lot_number,
                           COALESCE(l.street_address_1, '') AS address,
                           COALESCE(o.display_name, '') AS owner_name
                    FROM lots l
                    LEFT JOIN lot_ownership lo
                      ON lo.lot_id = l.id AND lo.end_date IS NULL
                    LEFT JOIN owners o
                      ON o.id = lo.owner_id AND o.active_flag = 1
                    WHERE l.active_flag = 1
                    GROUP BY l.id
                    ORDER BY CAST(l.lot_number AS REAL), l.lot_number
                    """
                ).fetchall()

                accounts = conn.execute(
                    """
                    SELECT a.id, a.account_number, a.account_name
                    FROM accounts a
                    WHERE a.is_active = 1
                    ORDER BY a.account_number
                    """
                ).fetchall()

                receivable_accounts = conn.execute(
                    """
                    SELECT a.id, a.account_number, a.account_name
                    FROM accounts a
                    JOIN account_types at ON at.id = a.account_type_id
                    WHERE a.is_active = 1 AND at.code = 'ASSET'
                    ORDER BY a.account_number
                    """
                ).fetchall()

                vendors = conn.execute(
                    """
                    SELECT id, vendor_name FROM vendors
                    WHERE active_flag = 1
                    ORDER BY vendor_name
                    """
                ).fetchall()

                def _owner_label(row: object) -> str:
                    lot = str(row["lot_number"]).strip()  # type: ignore[index]
                    name = str(row["display_name"])  # type: ignore[index]
                    return f"Lot {lot} — {name}" if lot else name

                def _lot_label(r: object) -> str:
                    num = str(r["lot_number"])  # type: ignore[index]
                    addr = str(r["address"]).strip()  # type: ignore[index]
                    owner = str(r["owner_name"]).strip()  # type: ignore[index]
                    parts = [f"Lot {num}"]
                    if addr:
                        parts.append(addr)
                    if owner:
                        parts.append(f"({owner})")
                    return " – ".join(parts[:2]) + (" " + parts[2] if len(parts) > 2 else "")

                return {
                    "lot_id": [
                        {"value": str(r["id"]), "label": _lot_label(r)}
                        for r in lots
                    ],
                    "owner_id": [
                        {"value": str(r["id"]), "label": _owner_label(r)}
                        for r in owners
                    ],
                    "account_id": [
                        {"value": str(r["id"]),
                         "label": f"{r['account_number']} – {r['account_name']}"}
                        for r in accounts
                    ],
                    "receivable_account_id": [
                        {"value": str(r["id"]),
                         "label": f"{r['account_number']} – {r['account_name']}"}
                        for r in receivable_accounts
                    ],
                    "vendor_id": [
                        {"value": str(r["id"]), "label": str(r["vendor_name"])}
                        for r in vendors
                    ],
                    "fund_code": [
                        {"value": "OPERATING", "label": "Operating"},
                        {"value": "RESERVE",   "label": "Reserve"},
                        {"value": "SPECIAL",   "label": "Special"},
                    ],
                    "sort_by": [
                        {"value": "name",    "label": "Name (last, first)"},
                        {"value": "address", "label": "Address"},
                    ],
                }
            finally:
                conn.close()
        except Exception:
            return {}

    @app.get("/reports")
    def reports_console() -> Response:
        selected = request.args.get("report_name", "trial-balance").strip()
        if not selected:
            selected = "trial-balance"
        return _ui_response_to_flask(
            report_page_service.render_page(
                selected_report=selected,
                org=org_context,
                lookup_options=_load_report_lookup_options(),
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
                lookup_options=_load_report_lookup_options(),
            )
        )


    # ── Account (Chart of Accounts) pages ────────────────────────────

    def _open_account_pages() -> AccountPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; account pages need it."
            )
        conn = _open_db()
        g._acct_conn = conn
        return AccountPages(conn)

    @app.teardown_request
    def _close_acct_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_acct_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._acct_conn = None

    @app.get("/accounts")
    def list_accounts() -> Response:
        pages = _open_account_pages()
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        resp = pages.render_list(org=org_context, theme=theme,
                                 flash_message=flash_message)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/accounts/add")
    def new_account_form() -> Response:
        pages = _open_account_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/accounts/add")
    def submit_new_account() -> Response:
        from flask import redirect
        pages = _open_account_pages()
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

    @app.get("/accounts/<int:account_id>/edit")
    def edit_account_form(account_id: int) -> Response:
        pages = _open_account_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_form(org=org_context, theme=theme,
                                 account_id=account_id)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/accounts/<int:account_id>/edit")
    def submit_edit_account(account_id: int) -> Response:
        from flask import redirect
        pages = _open_account_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_edit(
            account_id=account_id,
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/accounts/<int:account_id>/ledger")
    def view_account_ledger(account_id: int) -> Response:
        conn = _open_db()
        try:
            pages = AccountLedgerPages(conn)
            theme = str(org_context.get("theme", "warm"))
            start_date = (request.args.get("start") or "").strip()
            end_date = (request.args.get("end") or "").strip()
            resp = pages.render_ledger(
                account_id=account_id,
                org=org_context, theme=theme,
                start_date=start_date,
                end_date=end_date,
            )
        finally:
            conn.close()
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/accounts/<int:account_id>/delete")
    def submit_delete_account(account_id: int) -> Response:
        from flask import redirect
        pages = _open_account_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_delete(
            account_id=account_id,
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    # ── Accounting period pages ───────────────────────────────────────

    def _open_period_pages() -> AccountingPeriodPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; period pages need it."
            )
        conn = _open_db()
        g._period_conn = conn
        return AccountingPeriodPages(conn)

    @app.teardown_request
    def _close_period_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_period_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._period_conn = None

    @app.get("/accounting-periods")
    def list_periods() -> Response:
        pages = _open_period_pages()
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        resp = pages.render_list(org=org_context, theme=theme,
                                 flash_message=flash_message)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/accounting-periods/add")
    def new_period_form() -> Response:
        pages = _open_period_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_add_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/accounting-periods/add")
    def submit_new_period() -> Response:
        from flask import redirect
        pages = _open_period_pages()
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

    @app.get("/accounting-periods/generate")
    def generate_year_form() -> Response:
        pages = _open_period_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_generate_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/accounting-periods/generate")
    def submit_generate_year() -> Response:
        from flask import redirect
        pages = _open_period_pages()
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

    @app.post("/accounting-periods/<int:period_id>/close")
    def close_period(period_id: int) -> Response:
        from flask import redirect
        pages = _open_period_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_close(
            period_id=period_id, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/accounting-periods/<int:period_id>/reopen")
    def reopen_period(period_id: int) -> Response:
        from flask import redirect
        pages = _open_period_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_reopen(
            period_id=period_id, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/accounting-periods/<int:period_id>/delete")
    def delete_period(period_id: int) -> Response:
        from flask import redirect
        pages = _open_period_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_delete(
            period_id=period_id, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    # ── Bank account pages ────────────────────────────────────────────

    def _open_bank_account_pages() -> BankAccountPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; bank account pages need it."
            )
        conn = _open_db()
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

    # ── Reconciliation pages ──────────────────────────────────────────

    def _open_recon_pages() -> ReconciliationPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError("database.path missing from config.")
        conn = _open_db()
        g._recon_conn = conn
        return ReconciliationPages(conn)

    @app.teardown_request
    def _close_recon_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_recon_conn", None)
        if conn is not None:
            conn.close()
            g._recon_conn = None

    @app.get("/reconciliations")
    def list_reconciliations() -> Response:
        from flask import request
        pages = _open_recon_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_list(
            org=org_context, theme=theme,
            flash_message=request.args.get("msg"),
            error_message=request.args.get("error"),
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/reconciliations/new")
    def new_reconciliation_form() -> Response:
        pages = _open_recon_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_new_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/reconciliations/new")
    def submit_new_reconciliation() -> Response:
        from flask import redirect, request
        pages = _open_recon_pages()
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

    @app.get("/reconciliations/<int:reconciliation_id>")
    def view_reconciliation(reconciliation_id: int) -> Response:
        from flask import request
        pages = _open_recon_pages()
        theme = str(org_context.get("theme", "warm"))
        show_prior = request.args.get("show_prior") == "1"
        flash = request.args.get("msg")
        resp = pages.render_working(
            reconciliation_id, org=org_context, theme=theme,
            show_prior=show_prior, flash_message=flash,
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/reconciliations/<int:reconciliation_id>/toggle")
    def toggle_reconciliation_line(reconciliation_id: int) -> Response:
        from flask import request
        pages = _open_recon_pages()
        status, body = pages.handle_toggle(
            reconciliation_id, form_data=request.form.to_dict()
        )
        return Response(body, status=status,
                        mimetype="application/json")

    @app.post("/reconciliations/<int:reconciliation_id>/finalize")
    def finalize_reconciliation(reconciliation_id: int) -> Response:
        from flask import redirect
        pages = _open_recon_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_finalize(
            reconciliation_id, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/reconciliations/<int:reconciliation_id>/reopen")
    def reopen_reconciliation(reconciliation_id: int) -> Response:
        from flask import redirect
        pages = _open_recon_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_reopen(
            reconciliation_id, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/reconciliations/<int:reconciliation_id>/delete")
    def delete_reconciliation(reconciliation_id: int) -> Response:
        from flask import redirect
        pages = _open_recon_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_delete(
            reconciliation_id, org=org_context, theme=theme,
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
        conn = _open_db()
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
        flash_message = (request.args.get("msg") or "").strip()
        resp = pages.render_form(org=org_context, theme=theme, lot_id=lot_id,
                                 flash_message=flash_message)
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

    @app.post("/lots/<int:lot_id>/owners/link")
    def submit_link_owner(lot_id: int) -> Response:
        from flask import redirect
        pages = _open_lot_pages()
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

    @app.post("/lots/<int:lot_id>/owners/<int:ownership_id>/end")
    def submit_end_ownership(lot_id: int, ownership_id: int) -> Response:
        from flask import redirect
        pages = _open_lot_pages()
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

    @app.post("/lots/<int:lot_id>/owners/<int:ownership_id>/edit-dates")
    def submit_edit_ownership_dates(lot_id: int, ownership_id: int) -> Response:
        from flask import redirect
        pages = _open_lot_pages()
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

    # ── Renter pages ─────────────────────────────────────────────────

    def _open_renter_pages() -> LotRentersPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; renter pages need it."
            )
        conn = _open_db()
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
        conn = _open_db()
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
        conn = _open_db()
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
        conn = _open_db()
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
        conn = _open_db()
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
        conn = _open_db()
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

    # ── Ledger reports: all-accounts views ───────────────────────────

    def _open_all_ledger_pages() -> AllLedgerPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError("database.path missing from config.")
        conn = _open_db()
        g._all_ledger_conn = conn
        return AllLedgerPages(conn)

    @app.teardown_request
    def _close_all_ledger_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_all_ledger_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._all_ledger_conn = None

    @app.get("/ledger/transactions")
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

    @app.get("/ledger/by-account")
    def ledger_by_account() -> Response:
        pages = _open_all_ledger_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_by_account(
            org=org_context, theme=theme,
            start_date=(request.args.get("start") or "").strip(),
            end_date=(request.args.get("end") or "").strip(),
            sort=(request.args.get("sort") or "asc").strip(),
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    # ── Transaction pages: Manual Journal Entries ───────────────────

    def _open_manual_journal_pages() -> ManualJournalPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; journal entry pages need it."
            )
        conn = _open_db()
        g._je_conn = conn
        return ManualJournalPages(conn)

    @app.teardown_request
    def _close_je_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_je_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._je_conn = None

    @app.get("/journal-entries")
    def list_journal_entries() -> Response:
        pages = _open_manual_journal_pages()
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        resp = pages.render_list(org=org_context, theme=theme,
                                 flash_message=flash_message)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/journal-entries/new")
    def new_journal_entry_form() -> Response:
        pages = _open_manual_journal_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_new_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/journal-entries/new")
    def submit_journal_entry() -> Response:
        from flask import redirect
        pages = _open_manual_journal_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_new(
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/journal-entries/<int:journal_entry_id>")
    def view_journal_entry(journal_entry_id: int) -> Response:
        pages = _open_manual_journal_pages()
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        resp = pages.render_view(
            journal_entry_id=journal_entry_id,
            org=org_context, theme=theme,
            flash_message=flash_message,
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    # ── Budget pages ─────────────────────────────────────────────────

    def _open_budget_pages() -> BudgetPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; budget pages need it."
            )
        conn = _open_db()
        g._budget_conn = conn
        return BudgetPages(conn)

    @app.teardown_request
    def _close_budget_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_budget_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._budget_conn = None

    @app.get("/budgets")
    def list_budgets() -> Response:
        pages = _open_budget_pages()
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        resp = pages.render_list(org=org_context, theme=theme,
                                 flash_message=flash_message)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/budgets/new")
    def new_budget_form() -> Response:
        pages = _open_budget_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_new_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/budgets/new")
    def submit_new_budget() -> Response:
        from flask import redirect
        pages = _open_budget_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_new(
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/budgets/<int:budget_id>/edit")
    def edit_budget_form(budget_id: int) -> Response:
        pages = _open_budget_pages()
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        resp = pages.render_edit_form(
            budget_id, org=org_context, theme=theme,
            flash_message=flash_message,
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/budgets/<int:budget_id>/edit")
    def submit_save_budget(budget_id: int) -> Response:
        from flask import redirect
        pages = _open_budget_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_save(
            budget_id,
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/budgets/<int:budget_id>/approve")
    def approve_budget(budget_id: int) -> Response:
        from flask import redirect
        pages = _open_budget_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_approve(
            budget_id, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/budgets/<int:budget_id>/archive")
    def archive_budget(budget_id: int) -> Response:
        from flask import redirect
        pages = _open_budget_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_archive(
            budget_id, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/budgets/<int:budget_id>/delete")
    def delete_budget(budget_id: int) -> Response:
        from flask import redirect
        pages = _open_budget_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_delete(
            budget_id, org=org_context, theme=theme,
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
        conn = _open_db()
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

    # ── Reserve transfer pages ───────────────────────────────────────

    def _open_reserve_transfer_pages() -> ReserveTransferPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; reserve transfer pages need it."
            )
        conn = _open_db()
        g._rt_conn = conn
        return ReserveTransferPages(conn)

    @app.teardown_request
    def _close_rt_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_rt_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._rt_conn = None

    @app.get("/reserve-transfers")
    def list_reserve_transfers() -> Response:
        pages = _open_reserve_transfer_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_list(
            org=org_context, theme=theme,
            type_filter=(request.args.get("type_filter") or "").strip() or None,
            start_date=(request.args.get("start_date") or "").strip() or None,
            end_date=(request.args.get("end_date") or "").strip() or None,
            flash_message=(request.args.get("msg") or "").strip() or None,
            error_message=(request.args.get("error") or "").strip() or None,
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/reserve-transfers/new")
    def new_reserve_transfer_form() -> Response:
        pages = _open_reserve_transfer_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_new_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/reserve-transfers/new")
    def submit_new_reserve_transfer() -> Response:
        from flask import redirect
        pages = _open_reserve_transfer_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_new(
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/reserve-transfers/<int:transfer_id>/delete")
    def delete_reserve_transfer(transfer_id: int) -> Response:
        from flask import redirect
        pages = _open_reserve_transfer_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_delete(
            transfer_id=transfer_id, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    # ── Late Fee pages ───────────────────────────────────────────────

    def _open_late_fee_pages() -> LateFeePages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError("database.path missing from config; late fee pages need it.")
        conn = _open_db()
        g._lf_conn = conn
        return LateFeePages(conn)

    @app.teardown_request
    def _close_lf_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_lf_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._lf_conn = None

    @app.get("/late-fees")
    def late_fees_page() -> Response:
        pages = _open_late_fee_pages()
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

    @app.post("/late-fees/post")
    def submit_late_fees() -> Response:
        from flask import redirect
        pages = _open_late_fee_pages()
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

    # ── Dues Billing pages ───────────────────────────────────────────

    def _open_dues_billing_pages() -> DuesBillingPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; dues billing pages need it."
            )
        conn = _open_db()
        g._dues_conn = conn
        return DuesBillingPages(conn)

    @app.teardown_request
    def _close_dues_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_dues_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._dues_conn = None

    @app.get("/dues-billing")
    def dues_billing_page() -> Response:
        pages = _open_dues_billing_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_page(
            org=org_context, theme=theme,
            flash_message=(request.args.get("msg") or "").strip(),
            error_message=(request.args.get("error") or "").strip(),
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/dues-billing/post")
    def submit_dues_billing() -> Response:
        from flask import redirect
        pages = _open_dues_billing_pages()
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

    # ── Opening Balances pages ───────────────────────────────────────

    def _open_ob_pages() -> OpeningBalancesPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; opening balance pages need it."
            )
        conn = _open_db()
        g._ob_conn = conn
        ar_num = str(org_context.get("dues_receivable_account_number", "1100"))
        return OpeningBalancesPages(conn, ar_account_number=ar_num)

    @app.teardown_request
    def _close_ob_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_ob_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._ob_conn = None

    @app.get("/opening-balances")
    def opening_balances_page() -> Response:
        pages = _open_ob_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_page(
            org=org_context, theme=theme,
            flash=(request.args.get("msg") or "").strip() or None,
            error=(request.args.get("error") or "").strip() or None,
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/opening-balances/save")
    def save_opening_balances() -> Response:
        from flask import redirect
        pages = _open_ob_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_save(
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    # ── Database admin pages ─────────────────────────────────────────

    def _open_db_admin_pages() -> DatabaseAdminPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError("database.path missing from config.")
        conn = _open_db()
        g._dba_conn = conn
        return DatabaseAdminPages(conn, db_path=str(db_path))

    @app.teardown_request
    def _close_dba_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_dba_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._dba_conn = None

    @app.get("/admin/database")
    def database_admin_page() -> Response:
        pages = _open_db_admin_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_page(
            org=org_context, theme=theme,
            flash_message=(request.args.get("msg") or "").strip(),
            error_message=(request.args.get("error") or "").strip(),
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/admin/database/check")
    def database_health_check() -> Response:
        pages = _open_db_admin_pages()
        theme = str(org_context.get("theme", "warm"))
        _, form_resp = pages.handle_check(org=org_context, theme=theme)
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/admin/database/reindex")
    def database_reindex() -> Response:
        from flask import redirect
        pages = _open_db_admin_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_reindex(org=org_context, theme=theme)
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/admin/database/vacuum")
    def database_vacuum() -> Response:
        from flask import redirect
        pages = _open_db_admin_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_vacuum(org=org_context, theme=theme)
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/admin/database/wal-checkpoint")
    def database_wal_checkpoint() -> Response:
        from flask import redirect
        pages = _open_db_admin_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_wal_checkpoint(org=org_context, theme=theme)
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/admin/database/backup")
    def database_backup() -> Response:
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

    @app.post("/admin/database/restore-preview")
    def database_restore_preview() -> Response:
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

    @app.post("/admin/database/restore")
    def database_restore() -> Response:
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
        return Response(form_resp.body_html, status=form_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    # ── Export pages ─────────────────────────────────────────────────

    def _open_export_pages() -> ExportPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError("database.path missing from config.")
        conn = _open_db()
        g._export_conn = conn
        return ExportPages(conn)

    @app.teardown_request
    def _close_export_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_export_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._export_conn = None

    @app.get("/admin/export")
    def export_page() -> Response:
        pages = _open_export_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_page(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/admin/export/download")
    def export_download() -> Response:
        pages = _open_export_pages()
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

    # ── Import pages ──────────────────────────────────────────────────

    def _open_import_pages() -> ImportPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError("database.path missing from config.")
        conn = _open_db()
        g._import_conn = conn
        return ImportPages(conn)

    @app.teardown_request
    def _close_import_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_import_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._import_conn = None

    @app.get("/admin/import")
    def import_page() -> Response:
        pages = _open_import_pages()
        theme = str(org_context.get("theme", "warm"))
        resp  = pages.render_page(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/admin/import/run")
    def import_run() -> Response:
        pages = _open_import_pages()
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

    @app.post("/admin/import/validate")
    def import_validate() -> Response:
        import json as _json
        pages  = _open_import_pages()
        result = pages.handle_validate(
            data_type    = request.form.get("data_type",    ""),
            mapping_json = request.form.get("mapping",      "{}"),
            csv_content  = request.form.get("csv_content",  ""),
            filter_field = request.form.get("filter_field", ""),
        )
        return Response(_json.dumps(result), status=200,
                        mimetype="application/json")

    # ── GL Transaction Import ──────────────────────────────────────────

    def _open_gl_import_pages() -> GlImportPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError("database.path missing from config.")
        conn = _open_db()
        g._gl_import_conn = conn
        return GlImportPages(conn)

    @app.teardown_request
    def _close_gl_import_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_gl_import_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._gl_import_conn = None

    @app.get("/admin/gl-import")
    def gl_import_page() -> Response:
        theme = str(org_context.get("theme", "warm"))
        pages = _open_gl_import_pages()
        resp  = pages.render_page(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html")

    @app.post("/admin/gl-import/preview")
    def gl_import_preview() -> Response:
        theme = str(org_context.get("theme", "warm"))
        pages = _open_gl_import_pages()
        csv_content = request.form.get("csv_content", "")
        resp = pages.handle_preview(csv_content=csv_content, org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html")

    @app.post("/admin/gl-import/run")
    def gl_import_run() -> Response:
        theme = str(org_context.get("theme", "warm"))
        pages = _open_gl_import_pages()
        csv_content = request.form.get("csv_content", "")
        resp = pages.handle_run(csv_content=csv_content, org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html")

    # ── Year-End Close pages ───────────────────────────────────────────

    def _open_yec_pages() -> YearEndClosePages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError("database.path missing from config.")
        conn = _open_db()
        g._yec_conn = conn
        return YearEndClosePages(conn)

    @app.teardown_request
    def _close_yec_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_yec_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._yec_conn = None

    # ── Batch PDF ─────────────────────────────────────────────────────────────
    def _open_batch_pdf_pages() -> BatchPdfPages:
        conn = _open_db()
        g._batch_pdf_conn = conn
        return BatchPdfPages(conn=conn)

    @app.teardown_request
    def _close_batch_pdf_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_batch_pdf_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._batch_pdf_conn = None

    @app.get("/batch-pdf")
    def batch_pdf_page() -> Response:
        pages = _open_batch_pdf_pages()
        theme = str(org_context.get("theme", "warm"))
        html = pages.render_page(org=org_context, theme=theme)
        return Response(html, status=200, mimetype="text/html; charset=utf-8")

    @app.post("/batch-pdf/generate")
    def batch_pdf_generate() -> Response:
        from flask import request as _req
        pages = _open_batch_pdf_pages()
        theme = str(org_context.get("theme", "warm"))
        try:
            year = int(_req.form.get("year", "0"))
        except ValueError:
            year = 0
        if not year:
            html = pages.render_page(org=org_context, theme=theme,
                                     error="Please enter a valid year.")
            return Response(html, status=400, mimetype="text/html; charset=utf-8")
        html = pages.handle_generate(org=org_context, theme=theme, year=year)
        return Response(html, status=200, mimetype="text/html; charset=utf-8")

    # ── Resale Certificate Fee ────────────────────────────────────────────────
    def _open_resale_fee_pages() -> ResaleFeePages:
        conn = _open_db()
        g._resale_fee_conn = conn
        return ResaleFeePages(conn=conn)

    @app.teardown_request
    def _close_resale_fee_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_resale_fee_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._resale_fee_conn = None

    def _resale_fee_config() -> tuple[str, str]:
        """Return (default_amount, income_account_number) from config."""
        amount = str(org_context.get("resale_fee_default_amount") or "175.00")
        account = str(org_context.get("resale_fee_income_account_number") or "4070")
        return amount, account

    @app.get("/resale-fee")
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

    @app.post("/resale-fee/post-charge")
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

    @app.post("/resale-fee/post-payment")
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

    @app.get("/year-end-close")
    def yec_list() -> Response:
        pages = _open_yec_pages()
        theme = str(org_context.get("theme", "warm"))
        resp  = pages.render_list(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/year-end-close/<int:fiscal_year>")
    def yec_detail(fiscal_year: int) -> Response:
        pages = _open_yec_pages()
        theme = str(org_context.get("theme", "warm"))
        resp  = pages.render_detail(fiscal_year, org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/year-end-close/<int:fiscal_year>/close")
    def yec_close(fiscal_year: int) -> Response:
        pages = _open_yec_pages()
        theme = str(org_context.get("theme", "warm"))
        resp  = pages.handle_close(fiscal_year, org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/year-end-close/<int:fiscal_year>/reopen")
    def yec_reopen(fiscal_year: int) -> Response:
        pages = _open_yec_pages()
        theme = str(org_context.get("theme", "warm"))
        resp  = pages.handle_reopen(fiscal_year, org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    # ── Reserve Study pages ───────────────────────────────────────────

    def _open_reserve_study_pages() -> ReserveStudyPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError("database.path missing from config; reserve study pages need it.")
        conn = _open_db()
        g._rs_conn = conn
        return ReserveStudyPages(conn)

    @app.teardown_request
    def _close_rs_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_rs_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._rs_conn = None

    def _rs_redirect(url: str) -> Response:
        from flask import redirect as _redir
        return _redir(url, code=303)

    def _rs_resp(pr: object) -> Response:
        return Response(pr.body_html, status=pr.status_code, mimetype="text/html; charset=utf-8")

    @app.get("/reserve-study")
    def rs_summary() -> Response:
        pages = _open_reserve_study_pages()
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        return _rs_resp(pages.render_summary(org=org_context, theme=theme,
                                             flash_message=flash_message))

    @app.get("/reserve-study/assumptions/edit")
    def rs_assumptions_form() -> Response:
        pages = _open_reserve_study_pages()
        theme = str(org_context.get("theme", "warm"))
        return _rs_resp(pages.render_assumptions_form(org=org_context, theme=theme))

    @app.post("/reserve-study/assumptions/edit")
    def rs_assumptions_save() -> Response:
        from flask import redirect
        pages = _open_reserve_study_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_save_assumptions(
            form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return _rs_resp(form_resp)

    @app.get("/reserve-study/assets")
    def rs_assets() -> Response:
        pages = _open_reserve_study_pages()
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        return _rs_resp(pages.render_assets(org=org_context, theme=theme,
                                            flash_message=flash_message))

    @app.get("/reserve-study/assets/new")
    def rs_asset_new_form() -> Response:
        pages = _open_reserve_study_pages()
        theme = str(org_context.get("theme", "warm"))
        return _rs_resp(pages.render_asset_form(org=org_context, theme=theme))

    @app.post("/reserve-study/assets/new")
    def rs_asset_new_save() -> Response:
        from flask import redirect
        pages = _open_reserve_study_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_save_asset(
            None, form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return _rs_resp(form_resp)

    @app.get("/reserve-study/assets/<int:asset_id>/edit")
    def rs_asset_edit_form(asset_id: int) -> Response:
        pages = _open_reserve_study_pages()
        theme = str(org_context.get("theme", "warm"))
        return _rs_resp(pages.render_asset_form(asset_id, org=org_context, theme=theme))

    @app.post("/reserve-study/assets/<int:asset_id>/edit")
    def rs_asset_edit_save(asset_id: int) -> Response:
        from flask import redirect
        pages = _open_reserve_study_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_save_asset(
            asset_id, form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return _rs_resp(form_resp)

    @app.post("/reserve-study/assets/<int:asset_id>/delete")
    def rs_asset_delete(asset_id: int) -> Response:
        from flask import redirect
        pages = _open_reserve_study_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, _ = pages.handle_delete_asset(asset_id, org=org_context, theme=theme)
        return redirect(redirect_url or "/reserve-study/assets", code=303)

    @app.get("/reserve-study/funding-plan")
    def rs_funding_plan() -> Response:
        pages = _open_reserve_study_pages()
        theme = str(org_context.get("theme", "warm"))
        return _rs_resp(pages.render_funding_plan(org=org_context, theme=theme))

    @app.get("/reserve-study/scenarios")
    def rs_scenarios() -> Response:
        pages = _open_reserve_study_pages()
        theme = str(org_context.get("theme", "warm"))
        flash_message = (request.args.get("msg") or "").strip()
        return _rs_resp(pages.render_scenarios(org=org_context, theme=theme,
                                               flash_message=flash_message))

    @app.get("/reserve-study/scenarios/new")
    def rs_scenario_new_form() -> Response:
        pages = _open_reserve_study_pages()
        theme = str(org_context.get("theme", "warm"))
        return _rs_resp(pages.render_scenario_form(org=org_context, theme=theme))

    @app.post("/reserve-study/scenarios/new")
    def rs_scenario_new_save() -> Response:
        from flask import redirect
        pages = _open_reserve_study_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_save_scenario(
            None, form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return _rs_resp(form_resp)

    @app.get("/reserve-study/scenarios/<int:scenario_id>/edit")
    def rs_scenario_edit_form(scenario_id: int) -> Response:
        pages = _open_reserve_study_pages()
        theme = str(org_context.get("theme", "warm"))
        return _rs_resp(pages.render_scenario_form(scenario_id, org=org_context, theme=theme))

    @app.post("/reserve-study/scenarios/<int:scenario_id>/edit")
    def rs_scenario_edit_save(scenario_id: int) -> Response:
        from flask import redirect
        pages = _open_reserve_study_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_save_scenario(
            scenario_id, form_data={k: v for k, v in request.form.items()},
            org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return _rs_resp(form_resp)

    @app.post("/reserve-study/scenarios/<int:scenario_id>/delete")
    def rs_scenario_delete(scenario_id: int) -> Response:
        from flask import redirect
        pages = _open_reserve_study_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, _ = pages.handle_delete_scenario(scenario_id, org=org_context, theme=theme)
        return redirect(redirect_url or "/reserve-study/scenarios", code=303)

    @app.get("/reserve-study/report")
    def rs_report_preview() -> Response:
        pages = _open_reserve_study_pages()
        theme = str(org_context.get("theme", "warm"))
        return _rs_resp(pages.render_report_preview(org=org_context, theme=theme))

    @app.get("/reserve-study/report/download")
    def rs_word_report() -> Response:
        import urllib.parse
        pages = _open_reserve_study_pages()
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

    # ── AR / Receivables pages ───────────────────────────────────────

    def _open_ar_pages() -> ARPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError("database.path missing from config; AR pages need it.")
        conn = _open_db()
        g._ar_conn = conn
        return ARPages(conn)

    @app.teardown_request
    def _close_ar_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_ar_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._ar_conn = None

    @app.get("/ar/lots")
    def ar_lots_list() -> Response:
        pages = _open_ar_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_list(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/ar/lots/<int:lot_id>")
    def ar_lot_detail(lot_id: int) -> Response:
        from datetime import date as _date
        pages = _open_ar_pages()
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

    # ── Audit log pages ──────────────────────────────────────────────

    def _open_audit_pages() -> AuditLogPages:
        conn = _open_db()
        g._audit_conn = conn
        return AuditLogPages(conn)

    @app.teardown_request
    def _close_audit_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_audit_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._audit_conn = None

    @app.get("/admin/audit-log")
    def audit_log_page() -> Response:
        pages = _open_audit_pages()
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

    # ── Global search ─────────────────────────────────────────────────────

    def _open_search_pages() -> SearchPages:
        conn = _open_db()
        g._search_conn = conn
        return SearchPages(conn)

    @app.teardown_request
    def _close_search_conn(exc: BaseException | None) -> None:
        conn = getattr(g, "_search_conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g._search_conn = None

    @app.get("/search")
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

    return app
