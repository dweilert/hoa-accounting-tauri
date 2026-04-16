"""Centralized Jinja2 template rendering for the web UI."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape


TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


@lru_cache(maxsize=1)
def get_template_env() -> Environment:
    """Build and cache the Jinja environment."""
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "xml"]),
        enable_async=False,
    )


def render_template(template_name: str, context: dict[str, Any] | None = None) -> str:
    """Render a named template with the provided context."""
    template = get_template_env().get_template(template_name)
    return template.render(**(context or {}))