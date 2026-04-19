"""End-to-end tests for the Flask web UI routes.

Exercises the three read-only endpoints (/, /reports, /run-report) via
Flask's test client, confirming we have behavioural parity with the
previous http.server-based implementation.

Connection handling is mocked through ReportRunner's connection_factory
argument so we don't need a config.yaml or real database on disk.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from hoa_accounting.api.report_api import ReportAPIService
from hoa_accounting.application.report_runner import ReportRunner
from hoa_accounting.web.app import _flatten_query_params
from hoa_accounting.web.ui_server import HomePageService, ReportConsolePageService

# Reuse the in-memory DB fixture from the broader UI test module.
from test_web_ui import build_conn


def _build_app_with_conn(conn: sqlite3.Connection):
    """Create a Flask app pointed at the supplied in-memory DB.

    Mirrors ``create_app`` but swaps in a connection_factory so tests
    don't need to resolve a config file.
    """
    from flask import Flask, Response, request

    app = Flask(__name__)
    runner = ReportRunner(
        config_path=Path("unused.yaml"),
        connection_factory=lambda: conn,
    )
    api_service = ReportAPIService(runner)
    home_service = HomePageService(api_service)
    report_page_service = ReportConsolePageService(api_service)

    @app.get("/")
    def home():  # noqa: ANN202
        r = home_service.render_page()
        return Response(r.body_html, status=r.status_code, mimetype="text/html")

    @app.get("/reports")
    def reports_console():  # noqa: ANN202
        selected = request.args.get("report_name", "trial-balance").strip() or "trial-balance"
        r = report_page_service.render_page(selected_report=selected)
        return Response(r.body_html, status=r.status_code, mimetype="text/html")

    @app.get("/run-report")
    def run_report():  # noqa: ANN202
        params = _flatten_query_params(request.args)
        report_name = params.pop("report_name", "").strip()
        r = report_page_service.render_report(report_name=report_name, query_params=params)
        return Response(r.body_html, status=r.status_code, mimetype="text/html")

    return app


@pytest.fixture
def client() -> FlaskClient:
    conn = build_conn()
    app = _build_app_with_conn(conn)
    return app.test_client()


def test_home_page_returns_200_and_html(client: FlaskClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.mimetype == "text/html"
    body = resp.get_data(as_text=True)
    # Page should at least mention the app and show API status.
    assert "HOA" in body or "Reports" in body


def test_reports_console_default_report(client: FlaskClient) -> None:
    resp = client.get("/reports")
    assert resp.status_code == 200
    # Default selection is trial-balance — its form should be on the page.
    assert "trial-balance" in resp.get_data(as_text=True)


def test_reports_console_honors_report_name_query(client: FlaskClient) -> None:
    resp = client.get("/reports?report_name=general-ledger")
    assert resp.status_code == 200
    assert "general-ledger" in resp.get_data(as_text=True)


def test_run_report_missing_params_shows_validation_error(client: FlaskClient) -> None:
    # trial-balance requires as_of_date; omitting it must surface an error.
    resp = client.get("/run-report?report_name=trial-balance")
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "as_of_date" in body or "Missing" in body


def test_run_report_returns_200_with_valid_params(client: FlaskClient) -> None:
    resp = client.get("/run-report?report_name=trial-balance&as_of_date=2026-01-31")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "trial-balance" in body


def test_flatten_query_params_drops_empty_and_keeps_last() -> None:
    """Collapses a MultiDict to last-value-wins, drops empty strings."""
    from werkzeug.datastructures import MultiDict

    md = MultiDict([
        ("a", "1"),
        ("a", "2"),
        ("b", ""),
        ("c", "  "),
        ("d", "ok"),
    ])
    assert _flatten_query_params(md) == {"a": "2", "d": "ok"}
