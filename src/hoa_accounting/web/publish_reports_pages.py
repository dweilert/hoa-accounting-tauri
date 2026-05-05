"""Publish financial reports to S3 — admin page handler.

The page uses Server-Sent Events (SSE) for real-time progress feedback.
When a publish button is clicked the browser opens an EventSource to
``/publish-reports/stream``, which yields one JSON event per report step:

  {"type": "start",    "report": "Expense vs Budget"}
  {"type": "done",     "report": "Expense vs Budget", "s3_key": "...",
                       "ok": true, "error": ""}
  {"type": "complete", "ok": 4, "failed": 1}

The legacy synchronous POST (``handle_publish``) is kept for fallback.
"""

from __future__ import annotations

import datetime
import json
import sqlite3
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

from hoa_accounting.reporting.report_publisher import PublishResult, ReportPublisher
from hoa_accounting.storage.backend import StorageBackend, default_s3_backend
from hoa_accounting.web.template_engine import render_template

_FUND_CODES = ["OPERATING", "RESERVE"]

# Ordered list of (key, display_name) for all publishable reports.
_ALL_JOBS: list[tuple[str, str]] = [
    ("expense_vs_budget", "Expense vs Budget"),
    ("expense_detail", "Expense Detail"),
    ("expense_summary", "Expense Summary"),
    ("budget_summary", "Budget Summary"),
    ("contact_list", "Homeowner Contact List"),
]
_JOB_MAP = dict(_ALL_JOBS)


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
                "all_jobs": _ALL_JOBS,
                "results": results,
                "error": error,
            },
        )

    # ── SSE streaming ─────────────────────────────────────────────────────────

    def stream_publish(
        self,
        *,
        fiscal_year: int,
        fund_code: str,
        report: str,
    ) -> Generator[str, None, None]:
        """Yield SSE-formatted strings, one event per publish step."""

        def evt(data: dict[str, Any]) -> str:
            return f"data: {json.dumps(data)}\n\n"

        jobs = (
            _ALL_JOBS if report == "all" else [(report, _JOB_MAP.get(report, report))]
        )

        try:
            backend = self._backend()
            publisher = ReportPublisher(self.conn, backend)
        except Exception as exc:  # noqa: BLE001
            yield evt({"type": "error", "message": str(exc)})
            return

        ok_count = 0
        fail_count = 0

        for job_key, job_name in jobs:
            yield evt({"type": "start", "report": job_name})

            result = self._run_job(publisher, job_key, fiscal_year, fund_code)

            if result.ok:
                ok_count += 1
            else:
                fail_count += 1

            yield evt(
                {
                    "type": "done",
                    "report": result.report_name,
                    "s3_key": result.s3_key,
                    "ok": result.ok,
                    "error": result.error,
                }
            )

        yield evt({"type": "complete", "ok": ok_count, "failed": fail_count})

    def _run_job(
        self,
        publisher: ReportPublisher,
        job_key: str,
        fiscal_year: int,
        fund_code: str,
    ) -> PublishResult:
        if job_key == "expense_vs_budget":
            return publisher.publish_expense_vs_budget(
                fiscal_year=fiscal_year, fund_code=fund_code
            )
        if job_key == "expense_detail":
            return publisher.publish_expense_detail(
                fiscal_year=fiscal_year, fund_code=fund_code
            )
        if job_key == "expense_summary":
            return publisher.publish_expense_summary(
                fiscal_year=fiscal_year, fund_code=fund_code
            )
        if job_key == "budget_summary":
            return publisher.publish_budget_summary(fiscal_year=fiscal_year)
        if job_key == "contact_list":
            return publisher.publish_homeowner_contact_list()
        return PublishResult(
            report_name=job_key,
            s3_key="",
            url="",
            ok=False,
            error=f"Unknown report key: {job_key!r}",
        )

    # ── Synchronous fallback (kept for non-JS environments) ───────────────────

    def handle_publish(
        self,
        *,
        org: dict[str, Any],
        theme: str,
        fiscal_year: int,
        fund_code: str,
        report: str,
    ) -> str:
        try:
            backend = self._backend()
            publisher = ReportPublisher(self.conn, backend)
            jobs = (
                _ALL_JOBS
                if report == "all"
                else [(report, _JOB_MAP.get(report, report))]
            )
            results = [
                self._run_job(publisher, k, fiscal_year, fund_code) for k, _ in jobs
            ]
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
