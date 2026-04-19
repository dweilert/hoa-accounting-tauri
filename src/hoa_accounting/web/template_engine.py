"""Centralized Jinja2 template rendering for the web UI."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import json

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup


TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _tojson_filter(value: object, indent: int | None = None) -> Markup:
    return Markup(json.dumps(value, indent=indent))


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
    from flask import g
    ctx = dict(context or {})
    try:
        ctx.setdefault("current_user", getattr(g, "current_user", None))
    except RuntimeError:
        pass  # outside Flask request context (e.g. tests)
    template = get_template_env().get_template(template_name)
    return template.render(**ctx)