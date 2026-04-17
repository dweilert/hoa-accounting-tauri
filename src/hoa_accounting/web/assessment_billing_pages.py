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
from hoa_accounting.repositories.accounts_repo import AccountsRepository
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.services.assessment_billing_service import IndividualAssessmentRow
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.web.template_engine import render_template


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
            start_month = int(org.get("fiscal_year_start_month") or 1)
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


def _resolve_ar_account(conn: sqlite3.Connection, org: dict[str, object] | None):
    """Look up the configured AR account — same one the deposit form uses.

    Reusing ``dues_receivable_account_number`` here means assessments
    billed for dues + payments received for dues land on the same AR
    account, which is what lets AR Aging net correctly.
    """
    org = org or {}
    number = str(org.get("dues_receivable_account_number") or "1100")
    row = AccountsRepository(conn).get_by_number(number)
    if row is None:
        raise ValidationError(
            f"Dues receivable account '{number}' was not found in the chart."
        )
    if int(row["is_active"]) != 1:
        raise ValidationError(
            f"Dues receivable account '{number}' is inactive."
        )
    return row


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
        submitted_individuals: dict[str, str] | None = None,
        error_message: str = "",
        success_message: str = "",
    ) -> BillingPageResponse:
        values = form_values or {}
        submitted = submitted_individuals or {}

        # AR account is fixed from config; shown read-only on the page.
        resolved_error = error_message
        ar_account_label = ""
        ar_fund = ""
        try:
            ar_row = _resolve_ar_account(self.conn, org)
            ar_account_label = f"{ar_row['account_number']} · {ar_row['account_name']}"
            ar_fund = str(ar_row["fund_code"])
        except ValidationError as exc:
            resolved_error = resolved_error or str(exc)

        # Income dropdown filtered to accounts in the same fund as AR so
        # the fund-balance invariant doesn't reject the post.
        income_accounts_all = AccountsRepository(self.conn).list_accounts_by_type(
            account_type_code="INCOME"
        )
        income_accounts = [
            {
                "id": r["id"],
                "label": f"{r['account_number']} · {r['account_name']}",
                "fund_code": r["fund_code"],
            }
            for r in income_accounts_all
            if (not ar_fund) or str(r["fund_code"]) == ar_fund
        ]

        # Lot table with YTD summary per owner.
        from_date, to_date = _fiscal_year_range(org)
        lots = LotsRepository(self.conn).list_lots_with_ytd_assessments(
            from_date=from_date, to_date=to_date,
        )
        lot_rows = []
        for r in lots:
            billed = Decimal(str(r["ytd_billed"] or 0))
            paid = Decimal(str(r["ytd_paid"] or 0))
            balance = billed - paid
            lot_rows.append({
                "lot_id": r["lot_id"],
                "lot_number": r["lot_number"],
                "street": r["street_address_1"] or "",
                "owner_name": r["owner_name"] or "(no current owner)",
                "has_owner": r["owner_id"] is not None,
                # Prefer whatever the user just typed into the
                # individual-amount box over the default blank.
                "individual_amount": submitted.get(str(r["lot_id"]), ""),
                "ytd_billed": f"{billed:.2f}",
                "ytd_paid": f"{paid:.2f}",
                "ytd_balance": f"{balance:.2f}",
                "balance_is_positive": balance > 0,
            })

        ctx = {
            "heading": "Bill Assessments",
            "description": (
                "Create an assessment bill for every homeowner at the same "
                "amount, or enter individual amounts for specific lots. Every "
                "assessment posts its own balanced journal entry (DR receivable, "
                "CR income) and shows up immediately in AR Aging and the Owner "
                "Ledger. All-or-nothing — if any row fails validation, the "
                "entire batch rolls back."
            ),
            "org": org or {},
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "bill-assessments",
            "breadcrumb": "Transactions · Bill Assessments",
            "ar_account_label": ar_account_label,
            "income_accounts": income_accounts,
            "lot_rows": lot_rows,
            "values": {
                "description": values.get("description", ""),
                "entry_date": values.get("entry_date", _today()),
                "due_date": values.get("due_date", ""),
                "income_account_id": values.get("income_account_id", ""),
                "bulk_amount": values.get("bulk_amount", ""),
            },
            "error_message": resolved_error,
            "success_message": success_message,
            "ytd_period_label": f"{from_date} – {to_date}",
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
            income_account_id = _parse_int(
                form_data.get("income_account_id", ""), "Income account"
            )
            amount = _parse_positive_decimal(
                form_data.get("bulk_amount", ""), "Amount"
            )
            ar_row = _resolve_ar_account(self.conn, org)

            result = self.factory.assessment_billing_service().bill_all_at_same_amount(
                entry_date=entry_date,
                amount=amount,
                description=description,
                receivable_account_id=int(ar_row["id"]),
                income_account_id=income_account_id,
                due_date=due_date,
            )
        except (ValidationError, NotFoundError, AccountingError) as exc:
            resp = self.render_page(
                org=org, theme=theme,
                form_values=form_data,
                submitted_individuals=_extract_individual_amounts(form_data),
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
            income_account_id = _parse_int(
                form_data.get("income_account_id", ""), "Income account"
            )

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

            ar_row = _resolve_ar_account(self.conn, org)
            result = self.factory.assessment_billing_service().bill_individual_amounts(
                entry_date=entry_date,
                description=description,
                rows=rows,
                receivable_account_id=int(ar_row["id"]),
                income_account_id=income_account_id,
                due_date=due_date,
            )
        except (ValidationError, NotFoundError, AccountingError) as exc:
            resp = self.render_page(
                org=org, theme=theme,
                form_values=form_data,
                submitted_individuals=_extract_individual_amounts(form_data),
                error_message=str(exc),
            )
            return (None, resp)

        msg = f"Billed {result.owner_count} homeowner(s), total ${result.total_amount}"
        return (f"/assessments/bill?billed={msg}", None)


# ── Helpers ────────────────────────────────────────────────────────


def _extract_individual_amounts(form_data: dict[str, str]) -> dict[str, str]:
    """Rebuild a lot_id → submitted amount map for re-render."""
    lot_by_idx: dict[int, int] = {}
    amt_by_idx: dict[int, str] = {}
    for key, value in form_data.items():
        m_lot = _ROW_LOT_RE.match(key)
        if m_lot:
            try:
                lot_by_idx[int(m_lot.group(1))] = int(value)
            except (TypeError, ValueError):
                continue
            continue
        m_amt = _ROW_KEY_RE.match(key)
        if m_amt:
            amt_by_idx[int(m_amt.group(1))] = value
    out: dict[str, str] = {}
    for idx, lot_id in lot_by_idx.items():
        if idx in amt_by_idx:
            out[str(lot_id)] = amt_by_idx[idx]
    return out


def _require(raw: str, label: str) -> str:
    value = (raw or "").strip()
    if not value:
        raise ValidationError(f"{label} is required.")
    return value


def _parse_int(raw: str, label: str) -> int:
    try:
        return int((raw or "").strip())
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} is required.") from exc


def _parse_positive_decimal(raw: str, label: str) -> Decimal:
    try:
        value = Decimal((raw or "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"{label} must be a number.") from exc
    if value <= Decimal("0"):
        raise ValidationError(f"{label} must be greater than zero.")
    return value
