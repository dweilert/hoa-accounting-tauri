"""Login / logout / Cognito callback routes."""

from __future__ import annotations
from typing import Any

from flask import Blueprint, redirect, request, session, url_for

from hoa_accounting.auth.base import AuthUser
from hoa_accounting.web.template_engine import render_template

auth_bp = Blueprint("auth", __name__)

_auth_manager = None
_org_ctx: dict[str, Any] = {}


def init_auth(auth_manager: Any, org_context: dict[str, Any]) -> None:
    global _auth_manager, _org_ctx
    _auth_manager = auth_manager
    _org_ctx = org_context


# ── Helpers ───────────────────────────────────────────────────────────────

def _set_current_user(user: AuthUser) -> None:
    session["user"] = user.to_session()


def _get_current_user() -> AuthUser | None:
    data = session.get("user")
    if data is None:
        return None
    try:
        return AuthUser.from_session(data)
    except Exception:
        return None


# ── Routes ────────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET", "POST"])
def login() -> Any:
    if _auth_manager is None:
        return "Auth not initialised", 500

    theme = _org_ctx.get("theme", "light")
    org = _org_ctx  # template expects an org object with .name, .short_name, etc.

    error = None
    prefill_email = ""

    if request.method == "POST":
        action = request.form.get("action", "local")

        if action == "cognito" and _auth_manager.cognito_enabled:
            redirect_uri = url_for("auth.cognito_callback", _external=True)
            login_url = _auth_manager.get_cognito_login_url(redirect_uri)
            return redirect(login_url)

        if action == "local" and _auth_manager.local_enabled:
            email = request.form.get("email", "").strip()
            password = request.form.get("password", "")
            prefill_email = email
            user = _auth_manager.authenticate_local(email, password)
            if user:
                _set_current_user(user)
                next_path = request.args.get("next", "/")
                from urllib.parse import urlparse as _urlparse
                _p = _urlparse(next_path)
                if _p.scheme or _p.netloc or not next_path.startswith("/") or next_path.startswith("//"):
                    next_path = "/"
                return redirect(next_path)
            error = "Invalid email or password."

    ctx = {
        "active_nav": "",
        "page_key": "login",
        "theme": theme,
        "org": org,
        "error": error,
        "prefill_email": prefill_email,
        "cognito_enabled": _auth_manager.cognito_enabled,
        "local_enabled": _auth_manager.local_enabled,
    }
    return render_template("login.html", ctx)


@auth_bp.route("/auth/callback")
def cognito_callback() -> Any:
    if _auth_manager is None:
        return "Auth not initialised", 500

    code = request.args.get("code")
    if not code:
        return redirect("/login?error=no_code")

    redirect_uri = url_for("auth.cognito_callback", _external=True)
    user = _auth_manager.handle_cognito_callback(code, redirect_uri)
    if user is None:
        return redirect("/login?error=callback_failed")

    _set_current_user(user)
    return redirect("/")


@auth_bp.route("/logout")
def logout() -> Any:
    session.clear()
    return redirect("/login")
