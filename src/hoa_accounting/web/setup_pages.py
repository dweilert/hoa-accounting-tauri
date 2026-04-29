"""First-launch setup wizard — 4 steps, runs only when no local users exist."""

from __future__ import annotations
from typing import Any

import sqlite3
from decimal import Decimal, InvalidOperation


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


from flask import Response, redirect, request, session
from flask.typing import ResponseReturnValue

from hoa_accounting.auth.local import LocalBackend, hash_password
from hoa_accounting.web.auth_pages import _set_current_user
from hoa_accounting.web.template_engine import render_template as _render

# Steps in order — each maps to a session key tracking completion
STEPS = ["admin", "login", "identity", "assessment"]
STEP_LABELS = {
    "admin": "Create Admin Account",
    "login": "Confirm Your Login",
    "identity": "HOA Identity",
    "assessment": "Assessment & Accounts",
}

BILLING_FREQUENCIES = ["monthly", "quarterly", "semi-annual", "annual"]


def needs_setup(db_path: str) -> bool:
    """Return True when no local users exist (first launch)."""
    try:
        conn = _connect(db_path)
        row = conn.execute("SELECT COUNT(*) FROM local_users").fetchone()
        conn.close()
        return (row[0] if row else 0) == 0
    except Exception:
        return False


def _render_setup(step: str, ctx: dict[str, Any] | None = None) -> str:
    current_index = STEPS.index(step)
    return _render(
        "setup.html",
        {
            "step": step,
            "step_index": current_index + 1,
            "step_total": len(STEPS),
            "step_label": STEP_LABELS[step],
            "steps": STEPS,
            "step_labels": STEP_LABELS,
            **(ctx or {}),
        },
    )


class SetupPages:
    def __init__(self, db_path: str, org_context: dict[str, Any]) -> None:
        self._db_path = db_path
        self._org = org_context
        self._auth = LocalBackend(db_path)

    # ── Entry point ───────────────────────────────────────────────────────

    def get_setup(self) -> ResponseReturnValue:
        current_step = session.get("setup_step", "admin")
        if current_step not in STEPS:
            current_step = "admin"
        return Response(_render_setup(current_step), mimetype="text/html")

    # ── Step 1: Create admin account ──────────────────────────────────────

    def post_admin(self) -> ResponseReturnValue:
        form = request.form
        display_name = form.get("display_name", "").strip()
        email = form.get("email", "").strip().lower()
        password = form.get("password", "")
        confirm = form.get("confirm_password", "")

        errors = []
        if not display_name:
            errors.append("Please enter your name.")
        if not email or "@" not in email:
            errors.append("Please enter a valid email address.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")

        if errors:
            return Response(
                _render_setup("admin", {"errors": errors, "form": form}),
                mimetype="text/html",
            )

        self._auth.create_user(email, display_name, "admin", password)
        session["setup_step"] = "login"
        session["setup_admin_email"] = email
        return redirect("/setup")

    # ── Step 2: Force login ───────────────────────────────────────────────

    def post_login(self) -> ResponseReturnValue:
        form = request.form
        email = form.get("email", "").strip().lower()
        password = form.get("password", "")

        user = self._auth.authenticate(email, password)
        if not user:
            return Response(
                _render_setup(
                    "login",
                    {
                        "errors": [
                            "Login failed. Please check your email and password."
                        ],
                        "form": form,
                    },
                ),
                mimetype="text/html",
            )

        _set_current_user(user)
        session["setup_step"] = "identity"
        return redirect("/setup")

    # ── Step 3: HOA identity ──────────────────────────────────────────────

    def post_identity(self) -> ResponseReturnValue:
        form = request.form
        legal_name = form.get("legal_name", "").strip()
        display_name = form.get("display_name", "").strip()
        fiscal_month = form.get("fiscal_year_start_month", "1").strip()

        errors = []
        if not legal_name:
            errors.append("Full legal name is required.")
        if not display_name:
            errors.append("Abbreviated name is required.")

        if errors:
            return Response(
                _render_setup("identity", {"errors": errors, "form": form}),
                mimetype="text/html",
            )

        try:
            conn = _connect(self._db_path)
            existing = conn.execute("SELECT id FROM hoa_profile LIMIT 1").fetchone()
            if existing:
                conn.execute(
                    "UPDATE hoa_profile SET legal_name=?, display_name=? WHERE id=?",
                    (legal_name, display_name, existing[0]),
                )
            else:
                conn.execute(
                    "INSERT INTO hoa_profile (legal_name, display_name, theme, default_assessment_amount, default_billing_frequency) "
                    "VALUES (?, ?, 'warm', '0.00', 'annual')",
                    (legal_name, display_name),
                )
            conn.commit()
            conn.close()
        except Exception as exc:
            return Response(
                _render_setup(
                    "identity",
                    {
                        "errors": [f"Could not save — please try again. ({exc})"],
                        "form": form,
                    },
                ),
                mimetype="text/html",
            )

        self._org["name"] = display_name
        self._org["legal_name"] = legal_name

        session["setup_step"] = "assessment"
        return redirect("/setup")

    # ── Step 4: Assessment amount + chart of accounts ─────────────────────

    def post_assessment(self) -> ResponseReturnValue:
        form = request.form
        action = form.get("action", "starter")  # "starter", "skip", "wizard"

        raw_amount = form.get("default_assessment_amount", "0.00").strip() or "0.00"
        try:
            amount = str(Decimal(raw_amount).quantize(Decimal("0.01")))
        except (ValueError, InvalidOperation):
            amount = "0.00"
        frequency = form.get("default_billing_frequency", "annual")
        if frequency not in BILLING_FREQUENCIES:
            frequency = "annual"

        try:
            conn = _connect(self._db_path)
            conn.execute(
                "UPDATE hoa_profile SET default_assessment_amount=?, default_billing_frequency=?",
                (amount, frequency),
            )
            if action == "starter":
                self._seed_accounts(conn)
            conn.commit()
            conn.close()
        except Exception as exc:
            return Response(
                _render_setup(
                    "assessment",
                    {
                        "errors": [f"Could not save — please try again. ({exc})"],
                        "form": form,
                    },
                ),
                mimetype="text/html",
            )

        self._org["default_assessment_amount"] = amount
        self._org["default_billing_frequency"] = frequency

        # Setup complete — clear wizard session state, set completion flash
        session.pop("setup_step", None)
        session.pop("setup_admin_email", None)
        session["setup_complete_flash"] = True
        return redirect("/")

    # ── Helpers ───────────────────────────────────────────────────────────

    def _seed_accounts(self, conn: sqlite3.Connection) -> None:
        # Chart of Accounts retired in migration 0061. Starter accounts /
        # account_types tables are gone. The Categories Interview at
        # /setup/categories-interview now seeds Income & Expense categories
        # for new HOAs; this method is kept as a no-op so the existing
        # "starter" action on the setup wizard doesn't 404.
        return
