"""Route protection decorators and before_request guard."""

from __future__ import annotations
from typing import Any

import functools

from flask import redirect, request, session

from hoa_accounting.auth.base import ROLE_ADMIN, AuthUser
from hoa_accounting.web.auth_pages import _get_current_user
from hoa_accounting.web.template_engine import render_template

# Paths that never require authentication.
# /api/ofx-ready is the fetcher webhook — localhost-only, no session
# available to authenticate with. The route's handler still validates
# the payload's claimed file path against the inbox directory.
_PUBLIC_PREFIXES = (
    "/login",
    "/logout",
    "/auth/",
    "/static/",
    "/setup",
    "/api/ofx-ready",
)

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


def require_admin(f: Any) -> Any:
    """Decorator: require admin role, else 403."""

    @functools.wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        user = _get_current_user()
        if user is None:
            return redirect(f"/login?next={request.path}")
        if not user.is_admin:
            return _forbidden()
        return f(*args, **kwargs)

    return wrapper


def setup_auth_guard(app: Any, org_ctx: dict[str, Any]) -> None:
    """Register a before_request that enforces login + role on every route."""

    @app.before_request  # type: ignore[untyped-decorator]
    def _guard() -> Any:
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
                path == p or path.startswith(p + "/") for p in _REPORTS_ALLOWED_PREFIXES
            )
            if allowed_path and request.method == "GET":
                return None
            return _forbidden()

        # Default-deny: any authenticated user with an unknown role
        # (future role added without explicit handling above) is blocked.
        return _forbidden()


def _forbidden() -> Any:
    from flask import g

    org = getattr(g, "org", {})
    ctx = {
        "active_nav": "",
        "page_key": "",
        "theme": org.get("theme", "warm"),
        "org": org,
        "breadcrumb": "Access Denied",
    }
    return render_template("403.html", ctx), 403
