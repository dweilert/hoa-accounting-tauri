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
from flask import Flask, Response, g, redirect, request

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
from hoa_accounting.web.bank_statement_pages import BankStatementPages
from hoa_accounting.web.reserve_transfer_pages import ReserveTransferPages
from hoa_accounting.web.vendor_pages import VendorPages
from hoa_accounting.web.non_dues_income_pages import NonDuesIncomePages
from hoa_accounting.web.ui_server import (
    ReportConsolePageService,
    UIResponse,
)
from hoa_accounting.web.vendor_bill_pages import VendorBillPages
from hoa_accounting.web.budget_pages import BudgetPages
from hoa_accounting.web.batch_pdf_pages import BatchPdfPages
from hoa_accounting.web.resale_fee_pages import ResaleFeePages
from hoa_accounting.web.reserve_study_pages import ReserveStudyPages
from hoa_accounting.web.ar_pages import ARPages
from hoa_accounting.web.audit_log_pages import AuditLogPages
from hoa_accounting.web.search_pages import SearchPages
from hoa_accounting.web.setup_pages import SetupPages, needs_setup
from hoa_accounting.web.transaction_rule_pages import TransactionRulePages
from hoa_accounting.web.report_catalog import REPORT_DEFINITIONS


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
    db_theme = getattr(config.app, "theme", "warm")
    db_dues = "0.00"
    db_freq = "annual"
    try:
        import sqlite3 as _sq3
        _c = _sq3.connect(config.database.path)
        _c.row_factory = _sq3.Row
        _row = _c.execute(
            "SELECT display_name, legal_name, theme, default_assessment_amount, default_billing_frequency FROM hoa_profile LIMIT 1"
        ).fetchone()
        if _row and _row["display_name"]:
            hoa_name = _row["display_name"]
        if _row and _row["legal_name"]:
            hoa_legal = _row["legal_name"]
        if _row and _row["theme"]:
            db_theme = _row["theme"]
        if _row and _row["default_assessment_amount"]:
            db_dues = _row["default_assessment_amount"]
        db_freq = (_row["default_billing_frequency"] if _row else None) or "annual"
        _c.close()
    except Exception:
        pass
    return {
        "name": hoa_name,
        "legal_name": hoa_legal,
        "environment": config.app.environment,
        "fiscal_year_start_month": config.accounting.fiscal_year_start_month,
        "theme": db_theme,
        "default_assessment_amount": db_dues,
        "default_billing_frequency": db_freq,
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
            # Recreate audit triggers before migrations so any stale trigger
            # definitions (referencing removed columns) can't block executescript.
            install_audit_triggers(boot_conn)
            Migrator().apply_all(boot_conn)
            install_audit_triggers(boot_conn)
            backup_cfg = org_context.get("backup_config") or {}
            if backup_cfg.get("dir"):
                BackupService(str(db_path), backup_cfg).run(boot_conn)
            # Clear per-session alert dismissals so alerts reappear on each app start
            from hoa_accounting.repositories.dashboard_repo import DashboardRepository
            DashboardRepository(boot_conn).clear_alert_dismissals()
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

    _DEFAULT_SECRET = "change-me-to-a-random-secret"
    session_secret = raw_config.get("auth", {}).get("session_secret", _DEFAULT_SECRET)
    if session_secret == _DEFAULT_SECRET and org_context.get("environment") != "local":
        raise RuntimeError(
            "auth.session_secret must be changed from the default value before running outside local mode."
        )
    app.secret_key = session_secret
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 64 MB cap on uploads
    if org_context.get("environment") != "local":
        app.config["SESSION_COOKIE_SECURE"] = True

    init_auth(auth_manager, org_context)
    app.register_blueprint(auth_bp)

    # _attach_org must be registered BEFORE setup_auth_guard so g.org is
    # available when _forbidden() renders the 403 template.
    @app.before_request
    def _attach_org() -> None:
        from hoa_accounting.web.auth_pages import _get_current_user
        g.org = org_context
        g.current_user = _get_current_user()

    # ── Setup wizard ──────────────────────────────────────────────────────
    _setup = SetupPages(str(db_path), org_context)

    _SETUP_PATHS = {"/setup", "/setup/admin", "/setup/login", "/setup/identity", "/setup/assessment"}

    @app.before_request
    def _setup_guard() -> Response | None:
        from flask import redirect as _redir
        if request.path in _SETUP_PATHS or request.path.startswith("/static"):
            return None
        if needs_setup(str(db_path)):
            return _redir("/setup")
        return None

    @app.get("/setup")
    def setup_get() -> Response:
        return _setup.get_setup()

    @app.post("/setup/admin")
    def setup_post_admin() -> Response:
        return _setup.post_admin()

    @app.post("/setup/login")
    def setup_post_login() -> Response:
        return _setup.post_login()

    @app.post("/setup/identity")
    def setup_post_identity() -> Response:
        return _setup.post_identity()

    @app.post("/setup/assessment")
    def setup_post_assessment() -> Response:
        return _setup.post_assessment()

    # ── CSRF enforcement ──────────────────────────────────────────────────
    _CSRF_EXEMPT = {"/login", "/logout", "/auth/callback",
                    "/setup/admin", "/setup/login", "/setup/identity", "/setup/assessment"}

    @app.before_request
    def _enforce_csrf() -> Response | None:
        if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
            return None
        if request.path in _CSRF_EXEMPT:
            return None
        from flask import session as _session, abort as _abort
        expected = _session.get("_csrf_token")
        provided = (
            request.form.get("_csrf_token")
            or request.headers.get("X-CSRF-Token")
        )
        if not expected or expected != provided:
            _abort(403)
        return None

    setup_auth_guard(app, org_context)

    # ── User management routes ────────────────────────────────────────────
    from hoa_accounting.web.user_management_pages import UserManagementPages
    UserManagementPages(auth_manager).register(app)

    @app.errorhandler(Exception)
    def _handle_unhandled_exception(exc: Exception) -> Response:
        import traceback as tb
        from hoa_accounting.web.template_engine import render_template as _render

        _is_local_env = org_context.get("environment") == "local"
        _is_local_request = request.remote_addr in ("127.0.0.1", "::1", "localhost")
        show_traceback = _is_local_env and _is_local_request
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
        """Return the per-request shared DB connection, creating it on first call."""
        if hasattr(g, "db"):
            return g.db
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
        g.db = conn
        return conn

    @app.teardown_request
    def _close_db(exc: BaseException | None) -> None:
        conn = getattr(g, "db", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                g.db = None

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
        from datetime import date
        conn = _open_db()
        start_month = int(org_context.get("fiscal_year_start_month", 1))
        today = date.today()
        fy = today.year if today.month >= start_month else today.year - 1
        return DashboardPages(conn, fiscal_year=fy, fy_start_month=start_month)

    @app.get("/")
    def home() -> Response:
        from flask import session as _session
        theme = str(org_context.get("theme", "warm"))
        pages = _open_dashboard()
        setup_flash = _session.pop("setup_complete_flash", False)
        resp = pages.render_dashboard(org=org_context, theme=theme, setup_complete=setup_flash)
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

    @app.get("/claude-code-guide")
    def claude_code_guide_page() -> Response:
        from hoa_accounting.web.template_engine import render_template as _render
        theme = str(org_context.get("theme", "warm"))
        html = _render("claude_code_guide.html", {
            "org": org_context,
            "theme": theme,
            "page_key": "claude-code-guide",
        })
        return Response(html, mimetype="text/html")

    @app.get("/workflow-cheatsheet")
    def workflow_cheatsheet_page() -> Response:
        from hoa_accounting.web.template_engine import render_template as _render
        theme = str(org_context.get("theme", "warm"))
        html = _render("workflow_cheatsheet.html", {
            "org": org_context,
            "theme": theme,
            "active_nav": "system",
            "breadcrumb": "System",
            "page_key": "workflow-cheatsheet",
        })
        return Response(html, mimetype="text/html")

    @app.get("/workflow-guide")
    def workflow_guide_page() -> Response:
        from hoa_accounting.web.workflow_pages import WorkflowPages
        theme = str(org_context.get("theme", "warm"))
        conn = _open_db()
        status, html = WorkflowPages(conn).render_guide(org=org_context, theme=theme)
        return Response(html, status=status, mimetype="text/html")

    @app.get("/admin/workflow-guide")
    def workflow_admin_page() -> Response:
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages
        theme = str(org_context.get("theme", "warm"))
        conn = _open_db()
        tab_id = int(request.args.get("tab", 1))
        edit_card_id = request.args.get("edit")
        edit_card_id = int(edit_card_id) if edit_card_id else None
        flash = (request.args.get("flash") or "").replace("+", " ")
        status, html = WorkflowAdminPages(conn).render_admin(
            org=org_context, theme=theme,
            active_tab_id=tab_id, edit_card_id=edit_card_id, flash=flash
        )
        return Response(html, status=status, mimetype="text/html")

    @app.post("/admin/workflow-guide/add-card")
    def workflow_add_card() -> Response:
        from flask import redirect
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages
        url = WorkflowAdminPages(_open_db()).handle_add_card(request.form)
        return redirect(url)

    @app.post("/admin/workflow-guide/update-card")
    def workflow_update_card() -> Response:
        from flask import redirect
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages
        url = WorkflowAdminPages(_open_db()).handle_update_card(request.form)
        return redirect(url)

    @app.post("/admin/workflow-guide/move-card")
    def workflow_move_card() -> Response:
        from flask import redirect
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages
        url = WorkflowAdminPages(_open_db()).handle_move_card(request.form)
        return redirect(url)

    @app.post("/admin/workflow-guide/toggle-card")
    def workflow_toggle_card() -> Response:
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages
        card_id = int(request.form.get("card_id", 0))
        tab_id = int(request.form.get("tab_id", 1))
        WorkflowAdminPages(_open_db()).handle_toggle_card(card_id, tab_id)
        return Response("ok", mimetype="text/plain")

    @app.post("/admin/workflow-guide/delete-card")
    def workflow_delete_card() -> Response:
        from flask import redirect
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages
        url = WorkflowAdminPages(_open_db()).handle_delete_card(request.form)
        return redirect(url)

    @app.post("/admin/workflow-guide/reorder-card")
    def workflow_reorder_card() -> Response:
        from flask import redirect
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages
        url = WorkflowAdminPages(_open_db()).handle_reorder_card(request.form)
        return redirect(url)

    @app.post("/admin/workflow-guide/add-section")
    def workflow_add_section() -> Response:
        from flask import redirect
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages
        url = WorkflowAdminPages(_open_db()).handle_add_section(request.form)
        return redirect(url)

    @app.post("/admin/workflow-guide/toggle-section")
    def workflow_toggle_section() -> Response:
        from flask import redirect
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages
        section_id = int(request.form.get("section_id", 0))
        tab_id = int(request.form.get("tab_id", 1))
        WorkflowAdminPages(_open_db()).handle_toggle_section(section_id, tab_id)
        return redirect(f"/admin/workflow-guide?tab={tab_id}")

    @app.post("/admin/workflow-guide/add-tab")
    def workflow_add_tab() -> Response:
        from flask import redirect
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages
        url = WorkflowAdminPages(_open_db()).handle_add_tab(request.form)
        return redirect(url)

    @app.post("/admin/workflow-guide/toggle-tab")
    def workflow_toggle_tab() -> Response:
        from flask import redirect
        from hoa_accounting.web.workflow_pages import WorkflowAdminPages
        tab_id = int(request.form.get("tab_id", 1))
        WorkflowAdminPages(_open_db()).handle_toggle_tab(tab_id)
        return redirect(f"/admin/workflow-guide?tab={tab_id}")

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

    @app.post("/dashboard-config/reset-layout")
    def dashboard_reset_layout() -> Response:
        from flask import redirect
        pages = _open_dashboard()
        redirect_url = pages.handle_reset_layout()
        return redirect(redirect_url)

    @app.post("/dashboard/dismiss-alert")
    def dashboard_dismiss_alert() -> Response:
        from flask import jsonify
        key = request.form.get("alert_key", "")
        if key:
            _open_dashboard()._repo.dismiss_alert(key)
        return jsonify({"ok": True})

    @app.post("/dashboard-config/save-alert-settings")
    def dashboard_save_alert_settings() -> Response:
        from flask import redirect
        enabled = set(request.form.getlist("enabled_alerts"))
        _open_dashboard()._repo.save_alert_settings(enabled)
        return redirect("/dashboard-config?msg=Alert+settings+saved.")

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
                    "years_mode": [
                        {"value": "current",           "label": "Current year only"},
                        {"value": "prev_current",      "label": "Prior year + Current year"},
                        {"value": "prev_current_next", "label": "Prior + Current + Next year"},
                    ],
                }
            finally:
                conn.close()
        except Exception:
            return {}

    @app.get("/reports")
    def reports_console() -> Response:
        _default_report = REPORT_DEFINITIONS[0].name
        selected = request.args.get("report_name", _default_report).strip()
        if not selected:
            selected = _default_report
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
        return AccountPages(conn)

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

    @app.get("/accounts/wizard")
    def coa_wizard() -> Response:
        from hoa_accounting.web.wizard_pages import WizardPages
        conn = _open_db()
        theme = str(org_context.get("theme", "warm"))
        status, html = WizardPages(conn).render_wizard(org=org_context, theme=theme)
        return Response(html, status=status, mimetype="text/html; charset=utf-8")

    @app.post("/accounts/wizard/preview")
    def coa_wizard_preview() -> Response:
        from hoa_accounting.web.wizard_pages import WizardPages
        conn = _open_db()
        theme = str(org_context.get("theme", "warm"))
        status, html = WizardPages(conn).render_preview(form=request.form, org=org_context, theme=theme)
        return Response(html, status=status, mimetype="text/html; charset=utf-8")

    @app.post("/accounts/wizard/create")
    def coa_wizard_create() -> Response:
        from flask import redirect
        from hoa_accounting.web.wizard_pages import WizardPages
        conn = _open_db()
        url = WizardPages(conn).handle_create(form=request.form, org=org_context, theme=str(org_context.get("theme", "warm")))
        return redirect(url, code=303)

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

    # ── Categories pages ──────────────────────────────────────────────

    from hoa_accounting.web.categories_pages import CategoriesPages

    def _open_categories_pages() -> CategoriesPages:
        return CategoriesPages(_open_db())

    @app.get("/categories", strict_slashes=False)
    def list_categories() -> Response:
        from flask import redirect
        theme = str(org_context.get("theme", "warm"))
        flash = (request.args.get("flash") or "").replace("+", " ")
        resp = _open_categories_pages().render_list(org=org_context, theme=theme, flash_message=flash)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8")

    @app.get("/categories/add")
    def new_category_form() -> Response:
        theme = str(org_context.get("theme", "warm"))
        resp = _open_categories_pages().render_add_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8")

    @app.post("/categories/add")
    def submit_new_category() -> Response:
        from flask import redirect
        theme = str(org_context.get("theme", "warm"))
        resp = _open_categories_pages().handle_add(
            dict(request.form), org=org_context, theme=theme
        )
        if resp.status_code in (301, 302, 303):
            return redirect("/categories?flash=Category+added.", code=303)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8")

    @app.get("/categories/<int:category_id>/edit")
    def edit_category_form(category_id: int) -> Response:
        theme = str(org_context.get("theme", "warm"))
        resp = _open_categories_pages().render_edit_form(category_id, org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8")

    @app.post("/categories/<int:category_id>/edit")
    def submit_edit_category(category_id: int) -> Response:
        from flask import redirect
        theme = str(org_context.get("theme", "warm"))
        resp = _open_categories_pages().handle_edit(
            category_id, dict(request.form), org=org_context, theme=theme
        )
        if resp.status_code in (301, 302, 303):
            return redirect("/categories?flash=Category+saved.", code=303)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8")

    @app.post("/categories/<int:category_id>/delete")
    def delete_category(category_id: int) -> Response:
        from flask import redirect
        target = _open_categories_pages().handle_delete(category_id)
        return redirect(target, code=303)

    @app.get("/categories/<int:category_id>/ledger")
    def view_category_ledger(category_id: int) -> Response:
        theme = str(org_context.get("theme", "warm"))
        resp = _open_categories_pages().render_ledger(category_id, org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8")

    # ── Accounting period pages ───────────────────────────────────────

    def _open_period_pages() -> AccountingPeriodPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; period pages need it."
            )
        conn = _open_db()
        return AccountingPeriodPages(conn)

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
        return BankAccountPages(conn)

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
        return ReconciliationPages(conn)

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

    # ── Bank statement import ─────────────────────────────────────────

    def _open_bank_stmt_pages() -> BankStatementPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError("database.path missing from config.")
        conn = _open_db()
        return BankStatementPages(conn)

    # ── Account-agnostic bank import ─────────────────────────────────────────

    @app.get("/bank-import/upload")
    def bank_import_agnostic_form() -> Response:
        pages = _open_bank_stmt_pages()
        theme = str(org_context.get("theme", "warm"))
        success = request.args.get("msg") if request.args.get("ok") else None
        resp = pages.render_agnostic_upload_form(org=org_context, theme=theme, success=success)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8")

    @app.post("/bank-import/upload")
    def bank_import_agnostic_upload() -> Response:
        from flask import redirect
        pages = _open_bank_stmt_pages()
        theme = str(org_context.get("theme", "warm"))
        file = request.files.get("statement_file")
        if not file or not file.filename:
            resp = pages.render_agnostic_upload_form(org=org_context, theme=theme,
                                                     error="Please select a file.")
            return Response(resp.body_html, status=200, mimetype="text/html; charset=utf-8")
        ba_id_raw = request.form.get("csv_bank_account_id", "").strip()
        csv_ba_id = int(ba_id_raw) if ba_id_raw else None
        redirect_url, page_resp = pages.handle_agnostic_upload(
            file_bytes=file.read(), filename=file.filename,
            csv_bank_account_id=csv_ba_id, org=org_context, theme=theme,
        )
        if redirect_url:
            return redirect(redirect_url, code=303)
        return Response(page_resp.body_html, status=page_resp.status_code, mimetype="text/html; charset=utf-8")

    # ── Standalone bank statement import ─────────────────────────────────────

    @app.get("/bank-accounts/<int:bank_account_id>/import-statement")
    def bank_import_list(bank_account_id: int) -> Response:
        pages = _open_bank_stmt_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_standalone_batch_list(bank_account_id, org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.get("/bank-accounts/<int:bank_account_id>/import-statement/upload")
    def bank_import_upload_form(bank_account_id: int) -> Response:
        pages = _open_bank_stmt_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_standalone_upload_form(bank_account_id, org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/bank-accounts/<int:bank_account_id>/import-statement/upload")
    def bank_import_upload(bank_account_id: int) -> Response:
        from flask import redirect, request
        pages = _open_bank_stmt_pages()
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

    @app.get("/bank-accounts/<int:bank_account_id>/import-statement/<int:batch_id>")
    def bank_import_preview(bank_account_id: int, batch_id: int) -> Response:
        pages = _open_bank_stmt_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_standalone_batch_preview(
            bank_account_id, batch_id, org=org_context, theme=theme
        )
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/bank-accounts/<int:bank_account_id>/import-statement/<int:batch_id>/remap")
    def bank_import_remap(bank_account_id: int, batch_id: int) -> Response:
        from flask import redirect, request
        pages = _open_bank_stmt_pages()
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

    @app.post("/bank-accounts/<int:bank_account_id>/import-statement/<int:batch_id>/reapply-rules")
    def bank_import_reapply(bank_account_id: int, batch_id: int) -> Response:
        from flask import redirect
        pages = _open_bank_stmt_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, page_resp = pages.handle_standalone_reapply(
            bank_account_id, batch_id, org=org_context, theme=theme
        )
        if redirect_url:
            return redirect(redirect_url, code=303)
        assert page_resp is not None
        return Response(page_resp.body_html, status=page_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/bank-accounts/<int:bank_account_id>/import-statement/<int:batch_id>/apply")
    def bank_import_apply(bank_account_id: int, batch_id: int) -> Response:
        from flask import redirect
        pages = _open_bank_stmt_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, page_resp = pages.handle_standalone_apply(
            bank_account_id, batch_id, org=org_context, theme=theme
        )
        if redirect_url:
            return redirect(redirect_url, code=303)
        assert page_resp is not None
        return Response(page_resp.body_html, status=page_resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/bank-accounts/<int:bank_account_id>/import-statement/<int:batch_id>/delete")
    def bank_import_delete(bank_account_id: int, batch_id: int) -> Response:
        from flask import redirect
        pages = _open_bank_stmt_pages()
        redirect_url = pages.handle_standalone_delete(bank_account_id, batch_id)
        return redirect(redirect_url, code=303)

    @app.get("/bank-accounts/<int:bank_account_id>/import-statement/<int:batch_id>/find")
    def bank_import_find(bank_account_id: int, batch_id: int) -> Response:
        from flask import jsonify
        pages = _open_bank_stmt_pages()
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


    @app.post("/bank-accounts/<int:bank_account_id>/import-statement/<int:batch_id>/transactions/<int:txn_id>/apply-find")
    def bank_import_apply_find(bank_account_id: int, batch_id: int, txn_id: int) -> Response:
        from flask import jsonify
        body = request.get_json(silent=True) or {}
        pages = _open_bank_stmt_pages()
        result = pages.handle_apply_find_match(
            bank_account_id=bank_account_id,
            batch_id=batch_id,
            txn_id=txn_id,
            payment_ids=body.get("payment_ids", []),
        )
        return jsonify(result)

    @app.post("/bank-accounts/<int:bank_account_id>/import-statement/<int:batch_id>/transactions/<int:txn_id>/apply-bill")
    def bank_import_apply_bill(bank_account_id: int, batch_id: int, txn_id: int) -> Response:
        from flask import jsonify
        body = request.get_json(silent=True) or {}
        pages = _open_bank_stmt_pages()
        result = pages.handle_apply_bill_match(
            bank_account_id=bank_account_id,
            batch_id=batch_id,
            txn_id=txn_id,
            bill_ids=body.get("bill_ids", []),
        )
        return jsonify(result)


    # ── Transaction rules ─────────────────────────────────────────────

    def _open_txn_rule_pages() -> TransactionRulePages:
        conn = _open_db()
        return TransactionRulePages(conn)

    @app.get("/admin/transaction-rules")
    def transaction_rules_list() -> Response:
        pages = _open_txn_rule_pages()
        theme = str(org_context.get("theme", "warm"))
        return_to = request.args.get("return_to", "")
        resp = pages.render_list(org=org_context, theme=theme, return_to=return_to)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/admin/transaction-rules/save")
    def transaction_rules_save() -> Response:
        from flask import redirect, request
        pages = _open_txn_rule_pages()
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

    @app.post("/admin/transaction-rules/<int:rule_id>/delete")
    def transaction_rules_delete(rule_id: int) -> Response:
        from flask import redirect
        pages = _open_txn_rule_pages()
        return redirect(pages.handle_delete(rule_id), code=303)

    @app.post("/admin/transaction-rules/<int:rule_id>/toggle")
    def transaction_rules_toggle(rule_id: int) -> Response:
        from flask import redirect
        pages = _open_txn_rule_pages()
        return redirect(pages.handle_toggle(rule_id), code=303)

    # ── Lot pages ─────────────────────────────────────────────────────

    def _open_lot_pages() -> LotPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; lot pages need it."
            )
        conn = _open_db()
        return LotPages(conn)

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
        return LotRentersPages(conn)

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
        return VendorPages(conn)

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
        return OwnerPages(conn)

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
        return VendorBillPages(conn)

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

    @app.get("/vendor-bills/<int:vendor_bill_id>/edit")
    def edit_vendor_bill_form(vendor_bill_id: int) -> Response:
        pages = _open_vendor_bill_pages()
        theme = str(org_context.get("theme", "warm"))
        resp = pages.render_edit(vendor_bill_id, org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code,
                        mimetype="text/html; charset=utf-8")

    @app.post("/vendor-bills/<int:vendor_bill_id>/edit")
    def submit_vendor_bill_edit(vendor_bill_id: int) -> Response:
        from flask import redirect
        pages = _open_vendor_bill_pages()
        theme = str(org_context.get("theme", "warm"))
        form_data = {k: v for k, v in request.form.items()}
        redirect_url, form_resp = pages.handle_edit(
            vendor_bill_id, form_data=form_data, org=org_context, theme=theme,
        )
        if redirect_url is not None:
            return redirect(redirect_url, code=303)
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
        return AllLedgerPages(conn)

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
        # Old route — redirect to the unified transactions view
        qs = request.query_string.decode()
        target = "/ledger/transactions" + (f"?{qs}" if qs else "")
        return redirect(target, 301)

    # ── Budget pages ─────────────────────────────────────────────────

    def _open_budget_pages() -> BudgetPages:
        db_path = org_context.get("db_path")
        if not db_path:
            raise RuntimeError(
                "database.path missing from config; budget pages need it."
            )
        conn = _open_db()
        return BudgetPages(conn)

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

    @app.post("/budgets/<int:budget_id>/revert-to-draft")
    def revert_budget_to_draft(budget_id: int) -> Response:
        from flask import redirect
        pages = _open_budget_pages()
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = pages.handle_revert_to_draft(
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
        return ReserveTransferPages(conn)

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
        return LateFeePages(conn)

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
        return DuesBillingPages(conn)

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
        ar_num = str(org_context.get("dues_receivable_account_number", "1100"))
        return OpeningBalancesPages(conn, ar_account_number=ar_num)

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
        return DatabaseAdminPages(conn, db_path=str(db_path))

    @app.get("/admin/wizard-catalog")
    def wizard_catalog() -> Response:
        from hoa_accounting.web.wizard_pages import WizardAdminPages
        conn = _open_db()
        theme = str(org_context.get("theme", "warm"))
        active_step = int(request.args.get("step", 1))
        flash = (request.args.get("flash") or "").replace("+", " ").strip()
        status, html = WizardAdminPages(conn).render_catalog(
            org=org_context, theme=theme, active_step=active_step, flash=flash
        )
        return Response(html, status=status, mimetype="text/html; charset=utf-8")

    @app.post("/admin/wizard-catalog/toggle")
    def wizard_catalog_toggle() -> Response:
        from flask import redirect
        from hoa_accounting.web.wizard_pages import WizardAdminPages
        conn = _open_db()
        option_id = int(request.form.get("option_id", 0))
        active_step = int(request.form.get("active_step", 1))
        url = WizardAdminPages(conn).handle_toggle(option_id, org_context, str(org_context.get("theme", "warm")), active_step)
        return redirect(url, code=303)

    @app.post("/admin/wizard-catalog/add-option")
    def wizard_catalog_add_option() -> Response:
        from flask import redirect
        from hoa_accounting.web.wizard_pages import WizardAdminPages
        conn = _open_db()
        url = WizardAdminPages(conn).handle_add_option(request.form, org_context, str(org_context.get("theme", "warm")))
        return redirect(url, code=303)

    @app.post("/admin/wizard-catalog/delete")
    def wizard_catalog_delete() -> Response:
        from flask import redirect
        from hoa_accounting.web.wizard_pages import WizardAdminPages
        conn = _open_db()
        option_id = int(request.form.get("option_id", 0))
        active_step = int(request.form.get("active_step", 1))
        url = WizardAdminPages(conn).handle_delete_option(option_id, active_step)
        return redirect(url, code=303)

    @app.post("/admin/wizard-catalog/add-group")
    def wizard_catalog_add_group() -> Response:
        from flask import redirect
        from hoa_accounting.web.wizard_pages import WizardAdminPages
        conn = _open_db()
        url = WizardAdminPages(conn).handle_add_group(request.form)
        return redirect(url, code=303)

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
        return ExportPages(conn)

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
        return ImportPages(conn)

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
        return GlImportPages(conn)

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
        return YearEndClosePages(conn)

    # ── Batch PDF ─────────────────────────────────────────────────────────────
    def _open_batch_pdf_pages() -> BatchPdfPages:
        conn = _open_db()
        return BatchPdfPages(conn=conn)

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
        return ResaleFeePages(conn=conn)

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

    @app.get("/resale-fee/payments")
    def resale_fee_payments_page() -> Response:
        from flask import request as _req
        pages = _open_resale_fee_pages()
        theme = str(org_context.get("theme", "warm"))
        flash = _req.args.get("msg", "")
        resp = pages.render_payments_page(
            org=org_context, theme=theme,
            flash_message=flash,
        )
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
        return ReserveStudyPages(conn)

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
        return ARPages(conn)

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
        return AuditLogPages(conn)

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

    # ── Delinquency report ────────────────────────────────────────────────

    @app.get("/delinquency-report")
    def delinquency_report() -> Response:
        conn = _open_db()
        theme = str(org_context.get("theme", "warm"))
        resp = ARPages(conn).render_delinquency_report(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8")

    # ── Bill templates ───────────────────────────────────────────────────

    from hoa_accounting.web.bill_template_pages import BillTemplatePages as _BillTemplatePages

    def _open_bill_template_pages() -> _BillTemplatePages:
        return _BillTemplatePages(_open_db())

    @app.get("/bill-templates")
    def list_bill_templates() -> Response:
        theme = str(org_context.get("theme", "warm"))
        flash = (request.args.get("msg") or "").strip() or None
        resp = _open_bill_template_pages().render_list(org=org_context, theme=theme, flash=flash)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8")

    @app.get("/bill-templates/new")
    def new_bill_template_form() -> Response:
        theme = str(org_context.get("theme", "warm"))
        resp = _open_bill_template_pages().render_new_form(org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8")

    @app.post("/bill-templates/new")
    def submit_new_bill_template() -> Response:
        from flask import redirect
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = _open_bill_template_pages().handle_new(
            {k: v for k, v in request.form.items()}, org=org_context, theme=theme,
        )
        if redirect_url:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code, mimetype="text/html; charset=utf-8")

    @app.get("/bill-templates/<int:template_id>/edit")
    def edit_bill_template_form(template_id: int) -> Response:
        theme = str(org_context.get("theme", "warm"))
        resp = _open_bill_template_pages().render_edit_form(template_id, org=org_context, theme=theme)
        return Response(resp.body_html, status=resp.status_code, mimetype="text/html; charset=utf-8")

    @app.post("/bill-templates/<int:template_id>/edit")
    def submit_edit_bill_template(template_id: int) -> Response:
        from flask import redirect
        theme = str(org_context.get("theme", "warm"))
        redirect_url, form_resp = _open_bill_template_pages().handle_edit(
            template_id, {k: v for k, v in request.form.items()}, org=org_context, theme=theme,
        )
        if redirect_url:
            return redirect(redirect_url, code=303)
        assert form_resp is not None
        return Response(form_resp.body_html, status=form_resp.status_code, mimetype="text/html; charset=utf-8")

    # ── Global search ─────────────────────────────────────────────────────

    def _open_search_pages() -> SearchPages:
        conn = _open_db()
        return SearchPages(conn)

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
