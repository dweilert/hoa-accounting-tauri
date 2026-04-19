"""Batch PDF generation — Owner Ledger for all active lots.

Generates one PDF per active lot for the given year, uploads each to the
configured storage backend, and returns a result summary.

One file per lot — new runs overwrite the previous version.

Filename format:
    {report_year}_{lot_number}_{owner_name}.pdf

S3 key (fixed per lot, so uploads always overlay the previous file):
    owner-reports/{lot_number}/{report_year}_{lot_number}_{owner_name}.pdf

Creation date/time is embedded inside the PDF itself, not the filename.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from hoa_accounting.reporting.lot_statement import LotStatementReportService
from hoa_accounting.reporting.dto import LotStatementReport
from hoa_accounting.storage.backend import StorageBackend
from hoa_accounting.web.template_engine import render_template


@dataclass
class PdfResult:
    lot_id: int
    lot_number: str
    owner_name: str
    filename: str
    s3_key: str
    url: str
    ok: bool
    error: str = ""


def _owner_name(report: LotStatementReport) -> str:
    owner = report.owners[0] if report.owners else None
    if owner and (owner.first_name or owner.last_name):
        return f"{owner.first_name} {owner.last_name}".strip()
    if owner:
        return owner.display_name
    return "Unknown"


def _build_filename(report: LotStatementReport) -> str:
    return f"{report.year}_{report.lot_number}_{_owner_name(report)}.pdf"


def _build_s3_key(report: LotStatementReport) -> str:
    """Fixed key per lot — uploading always overwrites the previous file."""
    filename = _build_filename(report)
    return f"owner-reports/{report.lot_number}/{filename}"


def _report_to_template_context(report: LotStatementReport) -> dict:
    owners = [
        {
            "display_name": o.display_name,
            "first_name": o.first_name,
            "last_name": o.last_name,
            "email": o.email,
            "phone": o.phone,
        }
        for o in report.owners
    ]
    ob_lines = [
        {
            "charge_type": line.charge_type,
            "label": line.label,
            "amount": str(line.amount),
        }
        for line in report.opening_balance_lines
    ]
    rows = [
        {
            "entry_date": row.entry_date,
            "entry_type": row.entry_type,
            "charge_type": row.charge_type,
            "description": row.description,
            "due_date": row.due_date,
            "debit_amount": str(row.debit_amount),
            "credit_amount": str(row.credit_amount),
            "running_balance": str(row.running_balance),
            "status": row.status,
            "receipt_number": row.receipt_number,
        }
        for row in report.rows
    ]
    return {
        "lot_number": report.lot_number,
        "lot_address": report.lot_address,
        "owners": owners,
        "year": str(report.year),
        "opening_balance": str(report.opening_balance),
        "opening_balance_lines": ob_lines,
        "closing_balance": str(report.closing_balance),
        "rows": rows,
    }


class BatchPdfService:
    def __init__(self, conn: sqlite3.Connection, backend: StorageBackend) -> None:
        self._conn = conn
        self._backend = backend

    def _active_lot_ids(self) -> list[int]:
        rows = self._conn.execute(
            "SELECT id FROM lots WHERE active_flag = 1 ORDER BY lot_number"
        ).fetchall()
        return [int(r["id"]) for r in rows]

    def run(self, year: int) -> list[PdfResult]:
        from weasyprint import HTML

        lot_ids = self._active_lot_ids()
        svc = LotStatementReportService(self._conn)
        results: list[PdfResult] = []
        now = datetime.now()

        generated_at = now.strftime("%-m/%-d/%Y %-I:%M:%S %p")

        for lot_id in lot_ids:
            try:
                report = svc.generate(lot_id=lot_id, year=year)

                context = _report_to_template_context(report)
                context["generated_at"] = generated_at
                html_str = render_template("pdf_owner_ledger.html", {"summary": context})
                pdf_bytes: bytes = HTML(string=html_str).write_pdf()

                filename = _build_filename(report)
                s3_key = _build_s3_key(report)
                owner_name = _owner_name(report)

                url = self._backend.upload(s3_key, pdf_bytes)

                results.append(PdfResult(
                    lot_id=lot_id,
                    lot_number=report.lot_number,
                    owner_name=owner_name,
                    filename=filename,
                    s3_key=s3_key,
                    url=url,
                    ok=True,
                ))
            except Exception as exc:  # noqa: BLE001
                results.append(PdfResult(
                    lot_id=lot_id,
                    lot_number=str(lot_id),
                    owner_name="",
                    filename="",
                    s3_key="",
                    url="",
                    ok=False,
                    error=str(exc),
                ))

        return results
