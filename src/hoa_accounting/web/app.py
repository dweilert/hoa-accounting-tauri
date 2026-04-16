"""Flask application for the HOA accounting web UI.

This module is the framework seam. The existing read-only page services
(``HomePageService``, ``ReportConsolePageService``) are reused verbatim —
the Flask view functions only translate between ``request`` / ``response``
objects and those services. No report logic, no template rendering, and
no accounting logic lives here.

Forms and write-side routes will be added in later PRs; this change is
strictly framework-swap parity.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, Response, request

from hoa_accounting.api.report_api import ReportAPIService
from hoa_accounting.application.report_runner import ReportRunner
from hoa_accounting.web.ui_server import (
    HomePageService,
    ReportConsolePageService,
    UIResponse,
)


def _ui_response_to_flask(response: UIResponse) -> Response:
    """Convert the UI layer's typed response into a Flask response."""
    return Response(
        response.body_html,
        status=response.status_code,
        mimetype="text/html; charset=utf-8",
    )


def _flatten_query_params(multi_dict: Any) -> dict[str, str]:
    """Collapse a werkzeug MultiDict/ImmutableMultiDict into the single-value
    shape the existing UI services expect.

    Mirrors the behavior of the legacy ``http.server`` code: keep only the
    last value for each key, drop empty strings.
    """
    out: dict[str, str] = {}
    for key in multi_dict.keys():
        value = multi_dict.getlist(key)[-1]
        if value is not None and str(value).strip() != "":
            out[key] = value
    return out


def create_app(config_path: str | Path = "config.yaml") -> Flask:
    """Build a Flask app wired to the read-only report UI services.

    Accepts either a string or Path for ``config_path`` so callers can pass
    configuration from wherever they've already resolved it.
    """
    app = Flask(__name__)

    runner = ReportRunner(config_path=Path(config_path))
    api_service = ReportAPIService(runner)
    home_service = HomePageService(api_service)
    report_page_service = ReportConsolePageService(api_service)

    @app.get("/")
    def home() -> Response:
        return _ui_response_to_flask(home_service.render_page())

    @app.get("/reports")
    def reports_console() -> Response:
        selected = request.args.get("report_name", "trial-balance").strip()
        if not selected:
            selected = "trial-balance"
        return _ui_response_to_flask(
            report_page_service.render_page(selected_report=selected)
        )

    @app.get("/run-report")
    def run_report() -> Response:
        params = _flatten_query_params(request.args)
        report_name = params.pop("report_name", "").strip()
        return _ui_response_to_flask(
            report_page_service.render_report(
                report_name=report_name,
                query_params=params,
            )
        )

    return app
