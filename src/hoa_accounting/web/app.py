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
from hoa_accounting.web.ui_server import (
    ReportConsolePageService,
    UIResponse,
)
from hoa_accounting.web.setup_pages import needs_setup


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
    from hoa_accounting.web.routes.dashboard import make_dashboard_blueprint
    from hoa_accounting.web.routes.api import make_api_blueprint
    ctx = RouteContext(org_context=org_context, report_page_service=report_page_service)
    app.register_blueprint(make_setup_blueprint(ctx))
    app.register_blueprint(make_categories_blueprint(ctx))
    app.register_blueprint(make_periods_blueprint(ctx))
    app.register_blueprint(make_bank_blueprint(ctx))
    app.register_blueprint(make_vendors_blueprint(ctx))
    app.register_blueprint(make_homeowners_blueprint(ctx))
    app.register_blueprint(make_budget_blueprint(ctx))
    app.register_blueprint(make_reports_blueprint(ctx))
    app.register_blueprint(make_admin_blueprint(ctx))
    app.register_blueprint(make_dashboard_blueprint(ctx))
    app.register_blueprint(make_api_blueprint(ctx))

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
        from werkzeug.exceptions import HTTPException
        from hoa_accounting.web.template_engine import render_template as _render

        # Don't swallow HTTPException — abort(403)/abort(404) etc. should
        # surface with their original status code, not be flattened to 500.
        if isinstance(exc, HTTPException):
            return exc  # type: ignore[return-value]

        # Tracebacks only ever shown in `environment == "local"`. The
        # earlier ``remote_addr`` check was unreliable behind a reverse
        # proxy (the proxy IP is what we'd see, not the user's), so
        # we don't gate on it: deployments configure environment != local
        # and tracebacks stay hidden regardless of source IP.
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


    # ── Page routes ───────────────────────────────────────────────────────

    return app
