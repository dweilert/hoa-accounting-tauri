"""CSRF protection — a ``before_request`` hook checking session-scoped
token against form/header on every state-mutating request.

Tokens are minted in :mod:`hoa_accounting.web.template_engine` and
exposed to templates as the ``csrf_token()`` helper plus a
``<meta name="csrf-token">`` tag for JS-driven POSTs.
"""

from __future__ import annotations

import secrets

from flask import Flask, Response, abort, request, session

# Routes exempted from CSRF. Each must justify why:
#   - ``/login``, ``/logout``, ``/auth/callback`` — pre-session; no token can exist yet.
#   - ``/setup/*`` — first-time setup wizard; runs before any session is established.
#   - ``/api/ofx-ready`` — fetcher daemon webhook; localhost-only + path-validated in handler.
_CSRF_EXEMPT = frozenset(
    {
        "/login",
        "/logout",
        "/auth/callback",
        "/setup/admin",
        "/setup/login",
        "/setup/identity",
        "/setup/assessment",
        "/api/ofx-ready",
    }
)


def install_csrf_guard(app: Flask) -> None:
    """Register a ``before_request`` hook that aborts 403 when a
    state-mutating request lacks a valid token."""

    @app.before_request
    def _enforce_csrf() -> Response | None:
        if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
            return None
        if request.path in _CSRF_EXEMPT:
            return None
        expected = session.get("_csrf_token")
        provided = request.form.get("_csrf_token") or request.headers.get(
            "X-CSRF-Token"
        )
        # Constant-time compare so token validity can't be probed by
        # measuring response latency.
        if (
            not expected
            or not provided
            or not secrets.compare_digest(str(expected), str(provided))
        ):
            abort(403)
        return None
