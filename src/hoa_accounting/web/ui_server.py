"""Minimal read-only web UI for report execution."""

from __future__ import annotations
from typing import Any

from dataclasses import asdict, dataclass
from http import HTTPStatus

from hoa_accounting.api.report_api import ReportAPIService
from hoa_accounting.web.summary_view_models import build_summary_view_model
from hoa_accounting.web.template_engine import render_template
from hoa_accounting.web.view_models import (
    build_home_page_context,
    build_report_console_context,
)


@dataclass(frozen=True)
class UIResponse:
    """Simple UI-layer response."""

    status_code: int
    body_html: str


class HomePageService:
    """Render the dashboard landing page."""

    def __init__(
        self, api_service: ReportAPIService, template_path: str | None = None
    ) -> None:
        self.api_service = api_service
        self.template_name = "home.html"

    def render_page(self, *, org: dict[str, object] | None = None) -> UIResponse:
        """Render the home dashboard."""
        health = self.api_service.get_health()
        api_status = "READY" if health.body.get("ok") is True else "ERROR"

        context = build_home_page_context(api_status=api_status, org=org)

        return UIResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.template_name, asdict(context)),
        )


class ReportConsolePageService:
    """Render a minimal report console page."""

    def __init__(
        self, api_service: ReportAPIService, template_path: str | None = None
    ) -> None:
        self.api_service = api_service
        self.template_name = "report_console.html"

    def render_page(
        self,
        *,
        selected_report: str = "trial-balance",
        org: dict[str, object] | None = None,
        lookup_options: dict[str, Any] | None = None,
    ) -> UIResponse:
        """Render the default console page without report output."""
        return UIResponse(
            status_code=HTTPStatus.OK,
            body_html=self._render_template(
                selected_report=selected_report,
                form_values={},
                api_payload=None,
                error_message="",
                org=org,
                lookup_options=lookup_options,
            ),
        )

    def render_report(
        self,
        *,
        report_name: str,
        query_params: dict[str, str],
        org: dict[str, object] | None = None,
        lookup_options: dict[str, Any] | None = None,
    ) -> UIResponse:
        """Render the page with report results."""
        api_response = self.api_service.get_report(
            report_name=report_name,
            query_params=query_params,
        )

        error_message = ""
        if api_response.body.get("ok") is not True:
            error_message = str(
                api_response.body.get("error", {}).get("message", "Unknown error.")
            )

        return UIResponse(
            status_code=api_response.status_code,
            body_html=self._render_template(
                selected_report=report_name,
                form_values=query_params,
                api_payload=api_response.body,
                error_message=error_message,
                org=org,
                lookup_options=lookup_options,
            ),
        )

    def _render_template(
        self,
        *,
        selected_report: str,
        form_values: dict[str, str],
        api_payload: dict[str, object] | None,
        error_message: str,
        org: dict[str, object] | None = None,
        lookup_options: dict[str, Any] | None = None,
    ) -> str:
        summary_vm = build_summary_view_model(
            selected_report=selected_report,
            api_payload=api_payload,
        )

        page_context = build_report_console_context(
            selected_report=selected_report,
            form_values=form_values,
            summary_template=summary_vm["summary_template"],
            summary=summary_vm["summary"],
            error_message=error_message,
            api_payload=api_payload,
            org=org,
            lookup_options=lookup_options,
        )

        return render_template(self.template_name, asdict(page_context))
