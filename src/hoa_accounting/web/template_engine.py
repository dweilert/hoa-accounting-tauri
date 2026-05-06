"""Centralized Jinja2 template rendering for the web UI."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup


def _resolve_templates_dir() -> Path:
    """Return the templates directory, handling PyInstaller bundles."""
    import sys

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "src" / "hoa_accounting" / "web" / "templates"
    return Path(__file__).resolve().parent / "templates"


TEMPLATES_DIR = _resolve_templates_dir()


def _tojson_filter(value: object, indent: int | None = None) -> Markup:
    """Render *value* as JSON safe to embed inside a ``<script>`` block.

    ``json.dumps`` does not escape ``<``, ``>``, ``&``, or ``'`` — all of
    which break out of an HTML script context if they appear in a
    user-supplied string (a CSV cell, a memo, a category name, …).
    Escape them as Unicode escapes so the JSON stays semantically
    identical but cannot terminate the surrounding tag or comment.
    """
    encoded = (
        json.dumps(value, indent=indent)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("'", "\\u0027")
    )
    return Markup(encoded)


@lru_cache(maxsize=1)
def get_template_env() -> Environment:
    """Build and cache the Jinja environment."""
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "xml"]),
        enable_async=False,
    )
    env.filters["tojson"] = _tojson_filter
    return env


def render_template(template_name: str, context: dict[str, Any] | None = None) -> str:
    """Render a named template with the provided context."""
    import secrets as _secrets

    from flask import g, session

    ctx = dict(context or {})
    try:
        ctx.setdefault("current_user", getattr(g, "current_user", None))
        if "_csrf_token" not in session:
            session["_csrf_token"] = _secrets.token_hex(32)
        ctx.setdefault("csrf_token", session["_csrf_token"])
    except RuntimeError:
        ctx.setdefault("csrf_token", "")  # outside Flask request context (e.g. tests)
    template = get_template_env().get_template(template_name)
    return template.render(**ctx)
