"""Publish financial reports to S3 — admin page handler.

One page with a year + fund selector and five individual Publish
buttons (plus a Publish All).  Each button POSTs to the same endpoint
with a hidden ``report`` field indicating which report to run.

Mirrors the pattern used by BatchPdfPages.
"""

from __future__ import annotations

import datetime
import sqlite3
from dataclasses import dataclass
from typing import Any

from hoa_accounting.reporting.report_publisher import PublishResult, ReportPublisher
from hoa_accounting.storage.backend import StorageBackend, default_s3_backend
from hoa_accounting.web.template_engine import render_template

_FUND_CODES = ["OPERATING", "RESERVE"]


@dataclass
class PublishReportsPages:
    conn: sqlite3.Connection

    def _backend(self) -> StorageBackend:
        return default_s3_backend()

    def render_page(
        self,
        *,
        org: dict[str, Any],
        theme: str,
        fiscal_year: int | None = None,
        fund_code: str = "OPERATING",
        results: list[PublishResult] | None = None,
        error: str = "",
    ) -> str:
        current_year = datetime.date.today().year
        return render_template(
            "publish_reports.html",
            {
                "active_nav": "reports",
                "page_key": "publish-reports",
                "breadcrumb": "Publish Reports to S3",
                "org": org,
                "theme": theme,
                "current_year": current_year,
                "selected_year": fiscal_year or current_year,
                "selected_fund": fund_code,
                "fund_codes": _FUND_CODES,
                "results": results,
                "error": error,
            },
        )

    def handle_publish(
        self,
        *,
        org: dict[str, Any],
        theme: str,
        fiscal_year: int,
        fund_code: str,
        report: str,
    ) -> str:
        """Run one or all reports and return the rendered results page."""
        try:
            backend = self._backend()
            publisher = ReportPublisher(self.conn, backend)

            if report == "all":
                results = publisher.publish_all(
                    fiscal_year=fiscal_year, fund_code=fund_code
                )
            elif report == "expense_vs_budget":
                results = [
                    publisher.publish_expense_vs_budget(
                        fiscal_year=fiscal_year, fund_code=fund_code
                    )
                ]
            elif report == "expense_detail":
                results = [
                    publisher.publish_expense_detail(
                        fiscal_year=fiscal_year, fund_code=fund_code
                    )
                ]
            elif report == "expense_summary":
                results = [
                    publisher.publish_expense_summary(
                        fiscal_year=fiscal_year, fund_code=fund_code
                    )
                ]
            elif report == "budget_summary":
                results = [publisher.publish_budget_summary(fiscal_year=fiscal_year)]
            elif report == "contact_list":
                results = [publisher.publish_homeowner_contact_list()]
            else:
                results = None
                return self.render_page(
                    org=org,
                    theme=theme,
                    fiscal_year=fiscal_year,
                    fund_code=fund_code,
                    error=f"Unknown report: {report!r}",
                )

            return self.render_page(
                org=org,
                theme=theme,
                fiscal_year=fiscal_year,
                fund_code=fund_code,
                results=results,
            )

        except Exception as exc:  # noqa: BLE001
            return self.render_page(
                org=org,
                theme=theme,
                fiscal_year=fiscal_year,
                fund_code=fund_code,
                error=str(exc),
            )
