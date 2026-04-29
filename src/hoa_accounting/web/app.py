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

import sqlite3
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
from hoa_accounting.web.all_ledger_pages import AllLedgerPages
from hoa_accounting.web.accounting_period_pages import AccountingPeriodPages
from hoa_accounting.web.bank_account_pages import BankAccountPages
from hoa_accounting.web.database_admin_pages import DatabaseAdminPages
from hoa_accounting.web.export_pages import ExportPages
from hoa_accounting.web.import_pages import ImportPages
from hoa_accounting.web.dashboard_pages import DashboardPages
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
from hoa_accounting.web.setup_pages import needs_setup
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
        "resale_fee_default_amount": getattr(
            config.accounting, "resale_fee_default_amount", "175.00"
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
        from flask import session as _session
        g.org = org_context
        # In TESTING mode, auto-seat an admin session so test_client tests
        # don't need to call _login_as_admin manually. Production runs
        # with TESTING=False so this is a no-op.
        if app.config.get("TESTING") and "user" not in _session:
            _session["user"] = {
                "email": "test-admin@local",
                "display_name": "Test Admin",
                "role": "admin",
                "backend": "local",
                "groups": [],
            }
        g.current_user = _get_current_user()

    # ── Setup wizard ──────────────────────────────────────────────────────
    _SETUP_PATHS = {"/setup", "/setup/admin", "/setup/login", "/setup/identity", "/setup/assessment"}

    @app.before_request
    def _setup_guard() -> Response | None:
        from flask import redirect as _redir
        if request.path in _SETUP_PATHS or request.path.startswith("/static"):
            return None
        if needs_setup(str(db_path)):
            return _redir("/setup")
        return None

    from hoa_accounting.web.route_context import RouteContext
    from hoa_accounting.web.routes.setup import make_setup_blueprint
    from hoa_accounting.web.routes.categories import make_categories_blueprint
    from hoa_accounting.web.routes.periods import make_periods_blueprint
    from hoa_accounting.web.routes.bank import make_bank_blueprint
    from hoa_accounting.web.routes.vendors import make_vendors_blueprint
    from hoa_accounting.web.routes.homeowners import make_homeowners_blueprint
    from hoa_accounting.web.routes.budget import make_budget_blueprint
    from hoa_accounting.web.routes.reports import make_reports_blueprint
    from hoa_accounting.web.routes.admin import make_admin_blueprint
    ctx = RouteContext(org_context=org_context)
    app.register_blueprint(make_setup_blueprint(ctx))
    app.register_blueprint(make_categories_blueprint(ctx))
    app.register_blueprint(make_periods_blueprint(ctx))
    app.register_blueprint(make_bank_blueprint(ctx))
    app.register_blueprint(make_vendors_blueprint(ctx))
    app.register_blueprint(make_homeowners_blueprint(ctx))
    app.register_blueprint(make_budget_blueprint(ctx))
    app.register_blueprint(make_reports_blueprint(ctx))
    app.register_blueprint(make_admin_blueprint(ctx))

    # ── CSRF enforcement ──────────────────────────────────────────────────
    # /api/ofx-ready is the fetcher webhook — the fetcher has no session,
    # so a CSRF token is impossible. Localhost-only + path validation in
    # the handler provide the safety margin.
    _CSRF_EXEMPT = {"/login", "/logout", "/auth/callback",
                    "/setup/admin", "/setup/login", "/setup/identity", "/setup/assessment",
                    "/api/ofx-ready"}

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

    # ── OFX-inbox proxy response summariser ──────────────────────────────
    def _summarise_fetcher_response(status: int, body, *, mode: str) -> str:
        """Turn the fetcher's JSON reply into a short user-facing message."""
        if status == 202 and isinstance(body, dict):
            job = body.get("job_id") or "?"
            return f"Fetcher queued {mode} job {job}. This page will refresh when it completes."
        if status == 503:
            return "Fetcher daemon not reachable on 127.0.0.1:17866 — is it running?"
        if isinstance(body, dict):
            return f"Fetcher returned HTTP {status}: {body}"
        return f"Fetcher returned HTTP {status}: {body}"

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
                    "id": int(r["id"]),
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
        edit_card_raw = request.args.get("edit")
        edit_card_id = int(edit_card_raw) if edit_card_raw else None
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

                # Chart of Accounts retired — these dropdowns are gone.
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


    # ── Chart of Accounts pages — REMOVED. ──────────────────────────
    # Categories drive classification; bank_accounts hold the cash.

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

    # ── GL Transaction Import + Year-End Close — REMOVED ──────────────

    return app
