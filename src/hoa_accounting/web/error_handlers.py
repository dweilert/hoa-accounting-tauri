"""Global error handler for unhandled exceptions.

Renders ``error_500.html``. Only shows tracebacks when
``org_context["environment"] == "local"`` — see commit dca662b for
why we don't gate on ``remote_addr`` (unreliable behind a reverse
proxy). HTTPException is passed through so ``abort(403)`` etc.
surface with their original status code instead of being flattened
to 500.
"""

from __future__ import annotations

import traceback
from typing import Any

from flask import Flask, Response
from werkzeug.exceptions import HTTPException

from hoa_accounting.web.template_engine import render_template


def install_error_handler(app: Flask, org_context: dict[str, Any]) -> None:
    @app.errorhandler(Exception)
    def _handle_unhandled_exception(exc: Exception) -> Response:
        if isinstance(exc, HTTPException):
            return exc  # type: ignore[return-value]

        show_traceback = org_context.get("environment") == "local"
        trace_str = traceback.format_exc() if show_traceback else None
        theme = str(org_context.get("theme", "warm"))
        html = render_template(
            "error_500.html",
            {
                "active_nav": "",
                "page_key": "",
                "breadcrumb": "",
                "org": org_context,
                "theme": theme,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "traceback": trace_str,
            },
        )
        return Response(html, status=500, mimetype="text/html; charset=utf-8")
