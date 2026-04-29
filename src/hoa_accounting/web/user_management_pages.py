"""User and role-override management routes — admin only."""

from __future__ import annotations

from typing import Any

from flask import Flask, redirect, request

from hoa_accounting.web.decorators import require_admin
from hoa_accounting.web.template_engine import render_template


class UserManagementPages:
    def __init__(self, auth_manager: Any) -> None:
        self._am = auth_manager

    def register(self, app: Flask) -> None:
        app.add_url_rule(
            "/system/users", "users_list", require_admin(self._list), methods=["GET"]
        )
        app.add_url_rule(
            "/system/users/new",
            "users_new",
            require_admin(self._new),
            methods=["GET", "POST"],
        )
        app.add_url_rule(
            "/system/users/<int:uid>/edit",
            "users_edit",
            require_admin(self._edit),
            methods=["GET", "POST"],
        )
        app.add_url_rule(
            "/system/users/<int:uid>/password",
            "users_password",
            require_admin(self._set_password),
            methods=["POST"],
        )
        app.add_url_rule(
            "/system/users/<int:uid>/delete",
            "users_delete",
            require_admin(self._delete),
            methods=["POST"],
        )
        app.add_url_rule(
            "/system/overrides",
            "overrides_list",
            require_admin(self._overrides),
            methods=["GET", "POST"],
        )
        app.add_url_rule(
            "/system/overrides/<int:oid>/delete",
            "overrides_delete",
            require_admin(self._delete_override),
            methods=["POST"],
        )

    # ── Context helper ────────────────────────────────────────────────────

    def _ctx(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        from flask import g

        ctx = {
            "active_nav": "system",
            "page_key": "users",
            "theme": (
                getattr(g, "org", {}).get("theme", "warm")
                if hasattr(g, "org")
                else "warm"
            ),
            "org": getattr(g, "org", {}),
            "breadcrumb": "System",
        }
        if extra:
            ctx.update(extra)
        return ctx

    # ── Users list ────────────────────────────────────────────────────────

    def _list(self) -> Any:
        users = self._am.local.list_users()
        return render_template(
            "users_list.html",
            self._ctx(
                {
                    "users": users,
                    "flash": request.args.get("flash"),
                }
            ),
        )

    # ── New user ──────────────────────────────────────────────────────────

    def _new(self) -> Any:
        error = None
        if request.method == "POST":
            email = request.form.get("email", "").strip()
            display_name = request.form.get("display_name", "").strip()
            role = request.form.get("role", "reports")
            password = request.form.get("password", "")
            confirm = request.form.get("confirm_password", "")

            if not email or not password:
                error = "Email and password are required."
            elif password != confirm:
                error = "Passwords do not match."
            elif len(password) < 8:
                error = "Password must be at least 8 characters."
            elif self._am.local.get_user_by_email(email):
                error = f"A user with email {email} already exists."
            else:
                self._am.local.create_user(email, display_name, role, password)
                return redirect("/system/users?flash=created")

        return render_template(
            "user_form.html",
            self._ctx(
                {
                    "form_action": "/system/users/new",
                    "form_title": "Add User",
                    "user": None,
                    "error": error,
                }
            ),
        )

    # ── Edit user ─────────────────────────────────────────────────────────

    def _edit(self, uid: int) -> Any:
        user = self._am.local.get_user(uid)
        if not user:
            return redirect("/system/users")

        error = None
        if request.method == "POST":
            display_name = request.form.get("display_name", "").strip()
            role = request.form.get("role", "reports")
            is_active = request.form.get("is_active") == "1"
            self._am.local.update_user(uid, display_name, role, is_active)
            return redirect("/system/users?flash=saved")

        return render_template(
            "user_form.html",
            self._ctx(
                {
                    "form_action": f"/system/users/{uid}/edit",
                    "form_title": "Edit User",
                    "user": user,
                    "error": error,
                }
            ),
        )

    # ── Set password ──────────────────────────────────────────────────────

    def _set_password(self, uid: int) -> Any:
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if password and password == confirm and len(password) >= 8:
            self._am.local.set_password(uid, password)
            return redirect(f"/system/users/{uid}/edit?flash=password_changed")
        return redirect(f"/system/users/{uid}/edit?flash=password_error")

    # ── Delete user ───────────────────────────────────────────────────────

    def _delete(self, uid: int) -> Any:
        self._am.local.delete_user(uid)
        return redirect("/system/users?flash=deleted")

    # ── Role overrides ────────────────────────────────────────────────────

    def _overrides(self) -> Any:
        error = None
        if request.method == "POST":
            action = request.form.get("action", "add")
            if action == "add":
                email = request.form.get("email", "").strip()
                role = request.form.get("role", "reports")
                note = request.form.get("note", "").strip()
                if not email:
                    error = "Email is required."
                else:
                    self._am.local.upsert_override(email, role, note)
                    return redirect("/system/overrides?flash=saved")

        overrides = self._am.local.list_overrides()
        return render_template(
            "role_overrides.html",
            self._ctx(
                {
                    "page_key": "overrides",
                    "overrides": overrides,
                    "flash": request.args.get("flash"),
                    "error": error,
                }
            ),
        )

    def _delete_override(self, oid: int) -> Any:
        self._am.local.delete_override(oid)
        return redirect("/system/overrides?flash=deleted")
