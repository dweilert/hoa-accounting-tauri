"""Accounting period management pages.

Routes handled:
  GET  /accounting-periods                    — list all periods
  GET  /accounting-periods/add                — single-period add form
  POST /accounting-periods/add                — submit new period
  GET  /accounting-periods/generate           — generate-year form
  POST /accounting-periods/generate           — create 12 periods for a year
  POST /accounting-periods/<id>/close         — mark period closed
  POST /accounting-periods/<id>/reopen        — reopen a closed period
  POST /accounting-periods/<id>/delete        — hard-delete (blocked if has JEs)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus

from hoa_accounting.exceptions import ValidationError
from hoa_accounting.repositories.periods_repo import PeriodsRepository
from hoa_accounting.validators.forms import require as _require
from hoa_accounting.web.template_engine import render_template

_BASE_CTX = {
    "active_nav": "transactions",
    "page_key": "accounting-periods",
    "breadcrumb": "Transactions",
}


@dataclass(frozen=True)
class PeriodPageResponse:
    status_code: int
    body_html: str


def _now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


class AccountingPeriodPages:
    """Render and handle the accounting period management pages."""

    LIST_TEMPLATE = "accounting_periods_list.html"
    FORM_TEMPLATE = "accounting_period_form.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.repo = PeriodsRepository(conn)

    # ── List ──────────────────────────────────────────────────────────

    def render_list(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        flash_message: str = "",
        error_message: str = "",
    ) -> PeriodPageResponse:
        rows = self.repo.list_periods()
        periods = [dict(r) for r in rows]
        ctx = {
            **_BASE_CTX,
            "heading": "Accounting Periods",
            "org": org or {},
            "theme": theme,
            "periods": periods,
            "flash_message": flash_message,
            "error_message": error_message,
        }
        return PeriodPageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.LIST_TEMPLATE, ctx),
        )

    # ── Add single period (GET) ────────────────────────────────────────

    def render_add_form(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        form_values: dict[str, str] | None = None,
        error_message: str = "",
    ) -> PeriodPageResponse:
        ctx = {
            **_BASE_CTX,
            "heading": "Add Accounting Period",
            "breadcrumb": "Transactions · Accounting Periods",
            "org": org or {},
            "theme": theme,
            "values": {
                "period_name": (form_values or {}).get("period_name", ""),
                "start_date": (form_values or {}).get("start_date", ""),
                "end_date": (form_values or {}).get("end_date", ""),
                "fiscal_year": (form_values or {}).get("fiscal_year", ""),
                "fiscal_period": (form_values or {}).get("fiscal_period", ""),
            },
            "error_message": error_message,
            "is_generate": False,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return PeriodPageResponse(
            status_code=status,
            body_html=render_template(self.FORM_TEMPLATE, ctx),
        )

    # ── Add single period (POST) ───────────────────────────────────────

    def handle_add(
        self,
        *,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, PeriodPageResponse | None]:
        try:
            period_name = _require(form_data.get("period_name", ""), "Period Name")
            start_date = _require(form_data.get("start_date", ""), "Start Date")
            end_date = _require(form_data.get("end_date", ""), "End Date")
            fiscal_year_raw = _require(form_data.get("fiscal_year", ""), "Fiscal Year")
            fiscal_period_raw = _require(
                form_data.get("fiscal_period", ""), "Fiscal Period"
            )

            if start_date > end_date:
                raise ValidationError("Start Date must be on or before End Date.")

            fiscal_year = int(fiscal_year_raw)
            fiscal_period = int(fiscal_period_raw)
            if not (1 <= fiscal_period <= 12):
                raise ValidationError("Fiscal Period must be between 1 and 12.")

            if self.repo.period_name_exists(period_name):
                raise ValidationError(f"Period {period_name!r} already exists.")

            self.repo.insert_period(
                period_name=period_name,
                start_date=start_date,
                end_date=end_date,
                fiscal_year=fiscal_year,
                fiscal_period=fiscal_period,
            )
            self.conn.commit()
        except (ValidationError, ValueError) as exc:
            return None, self.render_add_form(
                org=org,
                theme=theme,
                form_values=form_data,
                error_message=str(exc),
            )
        except Exception:
            self.conn.rollback()
            raise
        return "/accounting-periods?msg=Period+added.", None

    # ── Generate year form (GET) ───────────────────────────────────────

    def render_generate_form(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        form_values: dict[str, str] | None = None,
        error_message: str = "",
    ) -> PeriodPageResponse:
        ctx = {
            **_BASE_CTX,
            "heading": "Generate Year",
            "breadcrumb": "Transactions · Accounting Periods",
            "org": org or {},
            "theme": theme,
            "values": {
                "fiscal_year": (form_values or {}).get(
                    "fiscal_year",
                    str(datetime.now().year + 1),
                ),
            },
            "error_message": error_message,
            "is_generate": True,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return PeriodPageResponse(
            status_code=status,
            body_html=render_template(self.FORM_TEMPLATE, ctx),
        )

    # ── Generate year (POST) ───────────────────────────────────────────

    def handle_generate_year(
        self,
        *,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, PeriodPageResponse | None]:
        try:
            fiscal_year_raw = _require(form_data.get("fiscal_year", ""), "Fiscal Year")
            fiscal_year = int(fiscal_year_raw)
            if fiscal_year < 2000 or fiscal_year > 2100:
                raise ValidationError("Fiscal Year must be between 2000 and 2100.")
            if self.repo.fiscal_year_exists(fiscal_year):
                raise ValidationError(
                    f"Periods for {fiscal_year} already exist. "
                    "Delete them first or add periods individually."
                )
            self.repo.generate_year(fiscal_year)
            self.conn.commit()
        except (ValidationError, ValueError) as exc:
            return None, self.render_generate_form(
                org=org,
                theme=theme,
                form_values=form_data,
                error_message=str(exc),
            )
        except Exception:
            self.conn.rollback()
            raise
        return f"/accounting-periods?msg={fiscal_year}+periods+generated.", None

    # ── Close period (POST) ────────────────────────────────────────────

    def handle_close(
        self,
        *,
        period_id: int,
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, PeriodPageResponse | None]:
        row = self.repo.get_period(period_id)
        if row is None:
            return "/accounting-periods?msg=Period+not+found.", None
        if int(row["is_closed"]):
            return "/accounting-periods?msg=Period+already+closed.", None
        self.repo.close_period(period_id, closed_at=_now_utc())
        self.conn.commit()
        return f"/accounting-periods?msg={row['period_name']}+closed.", None

    # ── Reopen period (POST) ───────────────────────────────────────────

    def handle_reopen(
        self,
        *,
        period_id: int,
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, PeriodPageResponse | None]:
        row = self.repo.get_period(period_id)
        if row is None:
            return "/accounting-periods?msg=Period+not+found.", None
        if not int(row["is_closed"]):
            return "/accounting-periods?msg=Period+already+open.", None
        self.repo.reopen_period(period_id)
        self.conn.commit()
        return f"/accounting-periods?msg={row['period_name']}+reopened.", None

    # ── Delete period (POST) ───────────────────────────────────────────

    def handle_delete(
        self,
        *,
        period_id: int,
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, PeriodPageResponse | None]:
        if self.repo.has_journal_entries(period_id):
            return None, self.render_list(
                org=org,
                theme=theme,
                error_message=(
                    "Cannot delete a period that has posted transactions. "
                    "Close it instead."
                ),
            )
        row = self.repo.get_period(period_id)
        self.repo.delete_period(period_id)
        self.conn.commit()
        name = row["period_name"] if row else str(period_id)
        return f"/accounting-periods?msg={name}+deleted.", None
