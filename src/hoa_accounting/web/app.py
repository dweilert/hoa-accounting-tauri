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

from flask import Flask, Response, g, redirect, request
from flask.typing import ResponseReturnValue

from hoa_accounting.api.report_api import ReportAPIService
from hoa_accounting.application.report_runner import ReportRunner
from hoa_accounting.bootstrap.migrator import Migrator
from hoa_accounting.db.connection import connect_sqlite
from hoa_accounting.web.csrf import install_csrf_guard
from hoa_accounting.web.error_handlers import install_error_handler
from hoa_accounting.web.org_context_loader import load_org_context
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
    org_context = load_org_context(resolved_config_path)

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

    raw_config: dict[str, Any] = {}
    try:
        import yaml  # type: ignore[import-untyped]
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
    def _setup_guard() -> ResponseReturnValue | None:
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

    install_csrf_guard(app)
    setup_auth_guard(app, org_context)

    # ── User management routes ────────────────────────────────────────────
    from hoa_accounting.web.user_management_pages import UserManagementPages
    UserManagementPages(auth_manager).register(app)

    install_error_handler(app, org_context)

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
            return g.db  # type: ignore[no-any-return]
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
