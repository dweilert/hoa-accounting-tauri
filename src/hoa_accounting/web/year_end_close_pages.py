"""Year-End Close web pages.

Routes:
  GET  /year-end-close              — list fiscal years with status
  GET  /year-end-close/<year>       — checklist / preview for one year
  POST /year-end-close/<year>/close — execute the close
  POST /year-end-close/<year>/reopen — re-open a closed year
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from http import HTTPStatus

from hoa_accounting.exceptions import AccountingError, ValidationError
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.journal_repo import JournalRepository
from hoa_accounting.repositories.year_end_close_repo import YearEndCloseRepository
from hoa_accounting.services.year_end_close_service import YearEndCloseService
from hoa_accounting.web.template_engine import render_template

_BASE_CTX: dict = {
    "active_nav": "transactions",
    "page_key": "year-end-close",
    "breadcrumb": "Transactions",
}


@dataclass(frozen=True)
class PageResponse:
    status_code: int
    body_html: str


class YearEndClosePages:
    LIST_TEMPLATE   = "year_end_close_list.html"
    DETAIL_TEMPLATE = "year_end_close_detail.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn        = conn
        self.close_repo  = YearEndCloseRepository(conn)
        self.journal_repo = JournalRepository(conn)
        self.audit_repo  = AuditRepository(conn)
        self.service     = YearEndCloseService(
            conn,
            close_repo=self.close_repo,
            journal_repo=self.journal_repo,
            audit_repo=self.audit_repo,
        )

    def _svc_ctx(self, org: dict | None, theme: str) -> dict:
        return {**_BASE_CTX, "org": org or {}, "theme": theme}

    # ── List ───────────────────────────────────────────────────────────────

    def render_list(self, *, org: dict | None, theme: str) -> PageResponse:
        years = self.close_repo.list_fiscal_years()
        ctx = {
            **self._svc_ctx(org, theme),
            "heading": "Year-End Close",
            "fiscal_years": [
                {
                    "fiscal_year":    int(row["fiscal_year"]),
                    "period_count":   int(row["period_count"]),
                    "closed_count":   int(row["closed_count"]),
                    "year_start":     str(row["year_start"] or ""),
                    "year_end":       str(row["year_end"]   or ""),
                    "formally_closed": row["formally_closed_at"] is not None
                                       and row["reopened_at"] is None,
                    "formally_closed_at": str(row["formally_closed_at"] or ""),
                    "reopened_at":    str(row["reopened_at"] or ""),
                    "je_operating":   row["closing_je_operating_id"] is not None,
                    "je_reserve":     row["closing_je_reserve_id"]   is not None,
                }
                for row in years
            ],
        }
        return PageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.LIST_TEMPLATE, ctx),
        )

    # ── Detail / checklist ─────────────────────────────────────────────────

    def render_detail(
        self,
        fiscal_year: int,
        *,
        org: dict | None,
        theme: str,
        flash_message: str = "",
        flash_type: str = "success",
    ) -> PageResponse:
        checklist  = self.service.build_checklist(fiscal_year)
        close_rec  = self.close_repo.get_close_record(fiscal_year)
        is_closed  = close_rec is not None and close_rec["reopened_at"] is None

        ctx = {
            **self._svc_ctx(org, theme),
            "heading":     f"Year-End Close — {fiscal_year}",
            "fiscal_year": fiscal_year,
            "checklist":   checklist,
            "is_closed":   is_closed,
            "close_rec":   dict(close_rec) if close_rec else None,
            "flash_message": flash_message,
            "flash_type":    flash_type,
        }
        return PageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.DETAIL_TEMPLATE, ctx),
        )

    # ── POST: close ────────────────────────────────────────────────────────

    def handle_close(
        self,
        fiscal_year: int,
        *,
        org: dict | None,
        theme: str,
    ) -> PageResponse:
        try:
            result = self.service.close_year(fiscal_year)
        except (ValidationError, AccountingError) as exc:
            return self.render_detail(
                fiscal_year,
                org=org,
                theme=theme,
                flash_message=str(exc),
                flash_type="error",
            )
        self.conn.commit()

        parts = []
        if result.je_operating_number:
            parts.append(f"Operating: {result.je_operating_number}")
        if result.je_reserve_number:
            parts.append(f"Reserve: {result.je_reserve_number}")
        je_info = (" — Closing entries posted: " + ", ".join(parts)) if parts else ""

        return self.render_detail(
            fiscal_year,
            org=org,
            theme=theme,
            flash_message=f"Fiscal year {fiscal_year} has been closed.{je_info}",
            flash_type="success",
        )

    # ── POST: reopen ───────────────────────────────────────────────────────

    def handle_reopen(
        self,
        fiscal_year: int,
        *,
        org: dict | None,
        theme: str,
    ) -> PageResponse:
        try:
            self.service.reopen_year(fiscal_year)
        except (ValidationError, AccountingError) as exc:
            return self.render_detail(
                fiscal_year,
                org=org,
                theme=theme,
                flash_message=str(exc),
                flash_type="error",
            )
        self.conn.commit()

        return self.render_detail(
            fiscal_year,
            org=org,
            theme=theme,
            flash_message=(
                f"Fiscal year {fiscal_year} has been re-opened. "
                "Closing entries have been reversed. "
                "Reopen individual periods to post corrections."
            ),
            flash_type="success",
        )
