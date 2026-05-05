"""Publish financial report PDFs to S3.

Each method generates a report from the database, renders it to PDF,
and uploads it to the configured storage backend.  S3 keys are
deterministic so re-running a report always overwrites the previous
version — no stale files accumulate.

S3 key layout (all in the existing ``mmpoa-owner-reports`` bucket):
  budget/expense-vs-budget-{year}.pdf
  budget/expense-detail-{year}.pdf
  budget/expense-summary-{year}.pdf
  budget/budget-summary-{year}.pdf
  community/homeowner-contact-list.pdf

``budget/`` files appear automatically on the mmpoaii Budget & Financials
page (accessible to all authenticated users).  ``community/`` files
appear on the Homeowner Contact List page (all authenticated users).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from hoa_accounting.reporting.budget_summary import BudgetSummaryReportService
from hoa_accounting.reporting.expenses_by_date import ExpensesByDateReportService
from hoa_accounting.reporting.expenses_vs_budget import ExpenseVsBudgetReportService
from hoa_accounting.reporting.homeowner_contact_list import (
    HomeownerContactListReportService,
)
from hoa_accounting.reporting.report_pdfs import (
    render_budget_summary_pdf,
    render_expense_detail_pdf,
    render_expense_summary_pdf,
    render_expense_vs_budget_pdf,
    render_homeowner_contact_list_pdf,
)
from hoa_accounting.reporting.ytd_expense_summary import YtdExpenseSummaryReportService
from hoa_accounting.storage.backend import StorageBackend


@dataclass
class PublishResult:
    report_name: str
    s3_key: str
    url: str
    ok: bool
    error: str = field(default="")


class ReportPublisher:
    """Generate PDFs and push them to S3."""

    def __init__(self, conn: sqlite3.Connection, backend: StorageBackend) -> None:
        self._conn = conn
        self._backend = backend

    # ── Financial reports (→ budget/ prefix) ─────────────────────────────────

    def publish_expense_vs_budget(
        self, *, fiscal_year: int, fund_code: str
    ) -> PublishResult:
        s3_key = f"budget/expense-vs-budget-{fiscal_year}.pdf"
        try:
            svc = ExpenseVsBudgetReportService(self._conn)
            report = svc.generate(fiscal_year=fiscal_year, fund_code=fund_code)
            pdf = render_expense_vs_budget_pdf(report)
            url = self._backend.upload(s3_key, pdf)
            return PublishResult(
                report_name="Expense vs Budget", s3_key=s3_key, url=url, ok=True
            )
        except Exception as exc:  # noqa: BLE001
            return PublishResult(
                report_name="Expense vs Budget",
                s3_key=s3_key,
                url="",
                ok=False,
                error=str(exc),
            )

    def publish_expense_detail(
        self, *, fiscal_year: int, fund_code: str
    ) -> PublishResult:
        from_date = f"{fiscal_year}-01-01"
        to_date = f"{fiscal_year}-12-31"
        s3_key = f"budget/expense-detail-{fiscal_year}.pdf"
        try:
            svc = ExpensesByDateReportService(self._conn)
            report = svc.generate(from_date=from_date, to_date=to_date)
            pdf = render_expense_detail_pdf(report)
            url = self._backend.upload(s3_key, pdf)
            return PublishResult(
                report_name="Expense Detail", s3_key=s3_key, url=url, ok=True
            )
        except Exception as exc:  # noqa: BLE001
            return PublishResult(
                report_name="Expense Detail",
                s3_key=s3_key,
                url="",
                ok=False,
                error=str(exc),
            )

    def publish_expense_summary(
        self, *, fiscal_year: int, fund_code: str
    ) -> PublishResult:
        from_date = f"{fiscal_year}-01-01"
        to_date = f"{fiscal_year}-12-31"
        s3_key = f"budget/expense-summary-{fiscal_year}.pdf"
        try:
            svc = YtdExpenseSummaryReportService(self._conn)
            report = svc.generate(from_date=from_date, to_date=to_date)
            pdf = render_expense_summary_pdf(report)
            url = self._backend.upload(s3_key, pdf)
            return PublishResult(
                report_name="Expense Summary", s3_key=s3_key, url=url, ok=True
            )
        except Exception as exc:  # noqa: BLE001
            return PublishResult(
                report_name="Expense Summary",
                s3_key=s3_key,
                url="",
                ok=False,
                error=str(exc),
            )

    def publish_budget_summary(self, *, fiscal_year: int) -> PublishResult:
        s3_key = f"budget/budget-summary-{fiscal_year}.pdf"
        try:
            svc = BudgetSummaryReportService(self._conn)
            report = svc.generate(years_mode="current", current_year=fiscal_year)
            pdf = render_budget_summary_pdf(report)
            url = self._backend.upload(s3_key, pdf)
            return PublishResult(
                report_name="Budget Summary", s3_key=s3_key, url=url, ok=True
            )
        except Exception as exc:  # noqa: BLE001
            return PublishResult(
                report_name="Budget Summary",
                s3_key=s3_key,
                url="",
                ok=False,
                error=str(exc),
            )

    # ── Community reports (→ community/ prefix) ───────────────────────────────

    def publish_homeowner_contact_list(self) -> PublishResult:
        s3_key = "community/homeowner-contact-list.pdf"
        try:
            svc = HomeownerContactListReportService(self._conn)
            report = svc.generate()
            pdf = render_homeowner_contact_list_pdf(report)
            url = self._backend.upload(s3_key, pdf)
            return PublishResult(
                report_name="Homeowner Contact List",
                s3_key=s3_key,
                url=url,
                ok=True,
            )
        except Exception as exc:  # noqa: BLE001
            return PublishResult(
                report_name="Homeowner Contact List",
                s3_key=s3_key,
                url="",
                ok=False,
                error=str(exc),
            )

    # ── Publish all at once ───────────────────────────────────────────────────

    def publish_all(self, *, fiscal_year: int, fund_code: str) -> list[PublishResult]:
        """Push all five reports in one call."""
        return [
            self.publish_expense_vs_budget(
                fiscal_year=fiscal_year, fund_code=fund_code
            ),
            self.publish_expense_detail(fiscal_year=fiscal_year, fund_code=fund_code),
            self.publish_expense_summary(fiscal_year=fiscal_year, fund_code=fund_code),
            self.publish_budget_summary(fiscal_year=fiscal_year),
            self.publish_homeowner_contact_list(),
        ]
