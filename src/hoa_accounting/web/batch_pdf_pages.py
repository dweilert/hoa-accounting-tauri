"""Batch PDF generation admin page.

Exposes a simple admin panel that lets the board treasurer trigger
Owner Ledger PDF generation for all active lots for a given year and
upload them to S3.

Designed to work both locally and when the app is deployed to AWS
(Amplify / EC2) — credentials are resolved by boto3 from environment
variables or IAM role automatically.
"""

from __future__ import annotations

import datetime
import sqlite3
from dataclasses import dataclass

from hoa_accounting.reporting.batch_pdf import BatchPdfService, PdfResult
from hoa_accounting.storage.backend import StorageBackend, default_s3_backend
from hoa_accounting.web.template_engine import render_template


@dataclass
class BatchPdfPages:
    conn: sqlite3.Connection

    def _backend(self) -> StorageBackend:
        return default_s3_backend()

    def render_page(
        self,
        *,
        org: dict,
        theme: str,
        year: int | None = None,
        results: list[PdfResult] | None = None,
        error: str = "",
    ) -> str:
        current_year = datetime.date.today().year
        return render_template(
            "batch_pdf.html",
            {
                "active_nav": "batch-pdf",
                "page_key": "batch-pdf",
                "breadcrumb": "Generate Owner Ledger PDFs",
                "org": org,
                "theme": theme,
                "current_year": current_year,
                "selected_year": year or current_year,
                "results": results,
                "error": error,
            },
        )

    def handle_generate(
        self,
        *,
        org: dict,
        theme: str,
        year: int,
    ) -> str:
        try:
            backend = self._backend()
            svc = BatchPdfService(self.conn, backend)
            results = svc.run(year)
            return self.render_page(org=org, theme=theme, year=year, results=results)
        except Exception as exc:  # noqa: BLE001
            return self.render_page(org=org, theme=theme, year=year, error=str(exc))
