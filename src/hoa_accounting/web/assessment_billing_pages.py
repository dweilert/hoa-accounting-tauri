"""Bill Assessments page — bulk (same amount for everyone) + per-owner.

Single page with two submit actions:

- **Bill all homeowners the same amount** — one Amount + one
  Description, posts N assessments (one per active lot) atomically.
- **Bill individual homeowners** — a per-lot column of amounts, only
  rows with a non-zero amount post. Still one atomic transaction.

A YTD summary column strip on each lot row (Billed / Paid / Balance)
mirrors the user's spreadsheet so the treasurer can see context while
deciding whom to bill.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date as _date
from decimal import Decimal, InvalidOperation
from http import HTTPStatus

from hoa_accounting.exceptions import AccountingError, NotFoundError, ValidationError
from hoa_accounting.repositories.categories_repo import CategoriesRepository
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.services.assessment_billing_service import IndividualAssessmentRow
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.web.template_engine import render_template
from hoa_accounting.validators.forms import parse_int as _parse_int, parse_positive_decimal as _parse_positive_decimal, require as _require


@dataclass(frozen=True)
class BillingPageResponse:
    status_code: int
    body_html: str


_ROW_KEY_RE = re.compile(r"^row_(\d+)_amount$")
_ROW_LOT_RE = re.compile(r"^row_(\d+)_lot_id$")


def _today() -> str:
    return _date.today().isoformat()


def _fiscal_year_range(org: dict[str, object] | None) -> tuple[str, str]:
    """Return (from, to) ISO dates covering the current fiscal year.

    Fiscal year start month comes from config; default is January.
    January start → calendar year (e.g. 2026-01-01 to 2026-12-31).
    Non-January start → fiscal year spans two calendar years (e.g.
    July 2025 start → 2025-07-01 to 2026-06-30).
    """
    today = _date.today()
    start_month = 1
    if org and "fiscal_year_start_month" in org:
        try:
            start_month = int(org.get("fiscal_year_start_month") or 1)  # type: ignore[call-overload]
        except (TypeError, ValueError):
            start_month = 1

    if today.month >= start_month:
        start_year = today.year
    else:
        start_year = today.year - 1

    from_date = f"{start_year:04d}-{start_month:02d}-01"

    if start_month == 1:
        end_year, end_month = start_year, 12
    else:
        end_year, end_month = start_year + 1, start_month - 1
    # Use 31 as a safe upper bound — SQLite's ISO date comparison
    # handles months with fewer days correctly.
    to_date = f"{end_year:04d}-{end_month:02d}-31"
    return from_date, to_date


class AssessmentBillingPages:
    """Render + handle POST for the Bill Assessments page."""

    TEMPLATE = "assessment_billing.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.factory = ServiceFactory(conn)

    # ── Render ──────────────────────────────────────────────────────

    def render_page(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        form_values: dict[str, str] | None = None,
        submitted_individual_rows: list[dict[str, str]] | None = None,
        error_message: str = "",
        success_message: str = "",
    ) -> BillingPageResponse:
        values = form_values or {}
        submitted = {"rows": submitted_individual_rows} if submitted_individual_rows else {}

        resolved_error = error_message
        ar_account_label = ""

        income_categories = [
            {
                "id": r["id"],
                "label": r["name"],
                "fund_code": r["fund_code"],
            }
            for r in CategoriesRepository(self.conn).list_categories(
                category_type="INCOME"
            )
        ]

        # Lot dropdown options for the per-row picker: label each by
        # lot number + street + current owner so the treasurer can
        # identify them at a glance.
        lot_options = []
        for r in LotsRepository(self.conn).list_lots():
            street = r["street_address_1"] or ""
            owner = r["owner_names"] or "(no current owner)"
            bits = [str(r["lot_number"])]
            if street:
                bits.append(street)
            bits.append(owner)
            lot_options.append({
                "id": r["id"],
                "label": " · ".join(bits),
                "has_owner": bool(r["owner_names"]),
            })

        # Individual-billing rows — preserve whatever the user typed on
        # re-render after a validation error, otherwise start with a
        # few blank rows as scratchpad.
        individual_rows = submitted.get("rows") or [
            {"lot_id": "", "amount": ""} for _ in range(3)
        ]

        ctx = {
            "heading": "Bill Assessments",
            "description": (
                "Create an assessment bill for every homeowner at the same "
                "amount, or pick specific lots and amounts. Every "
                "assessment is recorded and shows up immediately in AR Aging and the Owner "
                "Ledger. All-or-nothing — if any row fails validation, the "
                "entire batch rolls back."
            ),
            "org": org or {},
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "bill-assessments",
            # Breadcrumb shows the path TO this page; the heading
            # already says 'Bill Assessments'.
            "breadcrumb": "Transactions",
            "ar_account_label": ar_account_label,
            "income_categories": income_categories,
            "lot_options": lot_options,
            "individual_rows": individual_rows,
            "values": {
                "description": values.get("description", ""),
                "entry_date": values.get("entry_date", _today()),
                "due_date": values.get("due_date", ""),
                "category_id": values.get("category_id", ""),
                "bulk_amount": values.get("bulk_amount") or str((org or {}).get("default_assessment_amount", "") or ""),
            },
            "error_message": resolved_error,
            "success_message": success_message,
        }
        status = HTTPStatus.BAD_REQUEST if resolved_error else HTTPStatus.OK
        return BillingPageResponse(
            status_code=status,
            body_html=render_template(self.TEMPLATE, ctx),
        )

    # ── POST: Bill all ──────────────────────────────────────────────

    def handle_bill_all(
        self,
        *,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, BillingPageResponse | None]:
        try:
            description = _require(form_data.get("description", ""), "Description")
            entry_date = _require(form_data.get("entry_date", ""), "Posting date")
            due_date = (form_data.get("due_date", "") or "").strip() or None
            category_id_raw = (form_data.get("category_id", "") or "").strip()
            category_id = int(category_id_raw) if category_id_raw else None
            amount = _parse_positive_decimal(
                form_data.get("bulk_amount", ""), "Amount"
            )

            result = self.factory.assessment_billing_service().bill_all_at_same_amount(
                entry_date=entry_date,
                amount=amount,
                description=description,
                category_id=category_id,
                due_date=due_date,
            )
        except (ValidationError, NotFoundError, AccountingError) as exc:
            resp = self.render_page(
                org=org, theme=theme,
                form_values=form_data,
                submitted_individual_rows=_extract_individual_rows(form_data),
                error_message=str(exc),
            )
            return (None, resp)
        msg = f"Billed {result.owner_count} homeowner(s), total ${result.total_amount}"
        return (f"/assessments/bill?billed={msg}", None)

    # ── POST: Bill individuals ──────────────────────────────────────

    def handle_bill_individuals(
        self,
        *,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, BillingPageResponse | None]:
        try:
            description = _require(form_data.get("description", ""), "Description")
            entry_date = _require(form_data.get("entry_date", ""), "Posting date")
            due_date = (form_data.get("due_date", "") or "").strip() or None
            category_id_raw = (form_data.get("category_id", "") or "").strip()
            category_id = int(category_id_raw) if category_id_raw else None

            # Parse per-row amounts. Only rows with a non-empty amount post.
            amounts_by_lot: dict[int, str] = {}
            lot_ids_by_index: dict[int, int] = {}
            for key, value in form_data.items():
                m_lot = _ROW_LOT_RE.match(key)
                if m_lot:
                    idx = int(m_lot.group(1))
                    try:
                        lot_ids_by_index[idx] = int(value)
                    except (TypeError, ValueError):
                        continue
                    continue
                m_amt = _ROW_KEY_RE.match(key)
                if m_amt:
                    idx = int(m_amt.group(1))
                    value = (value or "").strip()
                    if value:
                        amounts_by_lot[idx] = value

            rows: list[IndividualAssessmentRow] = []
            for idx, amount_raw in amounts_by_lot.items():
                lot_id = lot_ids_by_index.get(idx)
                if lot_id is None:
                    continue
                rows.append(
                    IndividualAssessmentRow(
                        lot_id=lot_id,
                        amount=_parse_positive_decimal(amount_raw, "Individual amount"),
                    )
                )

            if not rows:
                raise ValidationError(
                    "Enter at least one individual amount before billing."
                )

            result = self.factory.assessment_billing_service().bill_individual_amounts(
                entry_date=entry_date,
                description=description,
                rows=rows,
                category_id=category_id,
                due_date=due_date,
            )
        except (ValidationError, NotFoundError, AccountingError) as exc:
            resp = self.render_page(
                org=org, theme=theme,
                form_values=form_data,
                submitted_individual_rows=_extract_individual_rows(form_data),
                error_message=str(exc),
            )
            return (None, resp)

        msg = f"Billed {result.owner_count} homeowner(s), total ${result.total_amount}"
        return (f"/assessments/bill?billed={msg}", None)


# ── Helpers ────────────────────────────────────────────────────────


def _extract_individual_rows(form_data: dict[str, str]) -> list[dict[str, str]]:
    """Reconstruct the submitted individual-billing rows in row order.

    Used on validation-error re-render so the treasurer doesn't lose
    what they typed. Returns a list ordered by the row index the
    browser submitted.
    """
    by_idx: dict[int, dict[str, str]] = {}
    for key, value in form_data.items():
        m_lot = _ROW_LOT_RE.match(key)
        if m_lot:
            by_idx.setdefault(int(m_lot.group(1)), {})["lot_id"] = value
            continue
        m_amt = _ROW_KEY_RE.match(key)
        if m_amt:
            by_idx.setdefault(int(m_amt.group(1)), {})["amount"] = value
    return [by_idx[i] for i in sorted(by_idx)]


