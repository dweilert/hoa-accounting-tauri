"""Route protection decorators and before_request guard."""

from __future__ import annotations

import functools

from flask import redirect, request, session

from hoa_accounting.auth.base import ROLE_ADMIN, AuthUser
from hoa_accounting.web.auth_pages import _get_current_user
from hoa_accounting.web.template_engine import render_template

# Paths that never require authentication
_PUBLIC_PREFIXES = ("/login", "/logout", "/auth/", "/static/", "/setup")

# Paths that reports-level users can access (GET only)
_REPORTS_ALLOWED_PREFIXES = (
    "/",
    "/reports",
    "/run-report",
    "/reserve-study",
    "/ledger",
    "/all-ledger",
    "/account-ledger",
)


def current_user() -> AuthUser | None:
    return _get_current_user()


def require_login(f):
    """Decorator: redirect to /login if not authenticated."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        user = _get_current_user()
        if user is None:
            return redirect(f"/login?next={request.path}")
        return f(*args, **kwargs)
    return wrapper


def require_admin(f):
    """Decorator: require admin role, else 403."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        user = _get_current_user()
        if user is None:
            return redirect(f"/login?next={request.path}")
        if not user.is_admin:
            return _forbidden()
        return f(*args, **kwargs)
    return wrapper


def setup_auth_guard(app, org_ctx: dict) -> None:
    """Register a before_request that enforces login + role on every route."""

    @app.before_request
    def _guard():
        path = request.path

        # Always allow public routes
        if any(path.startswith(p) for p in _PUBLIC_PREFIXES):
            return None

        user = _get_current_user()

        # Not logged in → login page
        if user is None:
            return redirect(f"/login?next={path}")

        # Admin can do anything
        if user.is_admin:
            return None

        # Reports-only users: GET allowed on whitelisted paths, block everything else
        if user.is_reports_only:
            allowed_path = any(
                path == p or path.startswith(p + "/")
                for p in _REPORTS_ALLOWED_PREFIXES
            )
            if allowed_path and request.method == "GET":
                return None
            return _forbidden()

        return None


def _forbidden():
    from flask import g
    org = getattr(g, "org", {})
    ctx = {
        "active_nav": "",
        "page_key":   "",
        "theme":      org.get("theme", "warm"),
        "org":        org,
        "breadcrumb": "Access Denied",
    }
    return render_template("403.html", ctx), 403
