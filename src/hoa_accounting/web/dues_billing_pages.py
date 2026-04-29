"""Dues Billing page — periodic dues for all homeowners with cycle tracking.

Bills all active lot-owners the same amount for a selected billing cycle
(monthly, quarterly, semi-annual, or annual).  Every run is recorded in
``dues_billing_history`` so the screen can show the last billed period
and default to the next logical period, preventing accidental skips.
"""

from __future__ import annotations
from typing import Any

import sqlite3
from dataclasses import dataclass
from datetime import date as _date
from decimal import Decimal, InvalidOperation
from http import HTTPStatus

from hoa_accounting.exceptions import AccountingError, NotFoundError, ValidationError
from hoa_accounting.validators.format import format_currency
from hoa_accounting.repositories.dues_billing_repo import DuesBillingRepository
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.web.template_engine import render_template

_MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

_CYCLE_MAX: dict[str, int] = {
    "MONTHLY": 12,
    "QUARTERLY": 4,
    "SEMIANNUAL": 2,
    "ANNUAL": 1,
}

_CYCLE_LABEL: dict[str, str] = {
    "MONTHLY": "Monthly",
    "QUARTERLY": "Quarterly",
    "SEMIANNUAL": "Semi-Annual",
    "ANNUAL": "Annual",
}


def _period_label(cycle_type: str, year: int, sequence: int) -> str:
    if cycle_type == "MONTHLY":
        return f"{_MONTH_NAMES[sequence - 1]} {year}"
    if cycle_type == "QUARTERLY":
        return f"Q{sequence} {year}"
    if cycle_type == "SEMIANNUAL":
        half = "First Half" if sequence == 1 else "Second Half"
        return f"{half} {year}"
    return str(year)  # ANNUAL


def _auto_description(cycle_type: str, label: str) -> str:
    prefix = {
        "MONTHLY": "Monthly Dues",
        "QUARTERLY": "Quarterly Dues",
        "SEMIANNUAL": "Semi-Annual Dues",
        "ANNUAL": "Annual Dues",
    }.get(cycle_type, "Dues")
    return f"{prefix} – {label}"


def _next_period(cycle_type: str, year: int, sequence: int) -> tuple[int, int]:
    """Advance one period; wraps to next year if at the end of a cycle."""
    max_seq = _CYCLE_MAX.get(cycle_type, 1)
    if sequence >= max_seq:
        return year + 1, 1
    return year, sequence + 1


def _default_period_for_today(cycle_type: str) -> tuple[int, int]:
    """Best-guess for the current period when there is no billing history."""
    today = _date.today()
    year, month = today.year, today.month
    if cycle_type == "MONTHLY":
        return year, month
    if cycle_type == "QUARTERLY":
        return year, (month - 1) // 3 + 1
    if cycle_type == "SEMIANNUAL":
        return year, 1 if month <= 6 else 2
    return year, 1  # ANNUAL


def _today() -> str:
    return _date.today().isoformat()


# How many days past the posting date a bill becomes delinquent by default.
# Treasurers can override, but the default matches the typical grace period
# for each cycle length.
_DEFAULT_GRACE_DAYS: dict[str, int] = {
    "MONTHLY": 15,
    "QUARTERLY": 30,
    "SEMIANNUAL": 30,
    "ANNUAL": 30,
}


def _default_due_date(cycle_type: str, entry_date_iso: str) -> str:
    """Return entry_date + grace days. Doesn't floor at today so that
    backdated migration entries get a sensible delinquent date relative
    to the posting date, not today."""
    try:
        base = _date.fromisoformat(entry_date_iso)
    except ValueError:
        base = _date.today()
    grace = _DEFAULT_GRACE_DAYS.get(cycle_type, 15)
    from datetime import timedelta

    return (base + timedelta(days=grace)).isoformat()


@dataclass(frozen=True)
class DuesBillingPageResponse:
    status_code: int
    body_html: str


class DuesBillingPages:
    """Render + handle POST for the Bill Dues page."""

    TEMPLATE = "dues_billing.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.factory = ServiceFactory(conn)
        self._dues_repo = DuesBillingRepository(conn)

    # ── Render ──────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_income_account(
        conn: sqlite3.Connection,
        org: dict[str, Any],  # noqa: ARG004 — kept for signature stability
    ) -> tuple[int | None, str]:
        """Return (category_id, display_label) for the dues income category.

        After Chart of Accounts removal, billing income is driven by the DUES
        category (or whichever code is configured via dues_category_code).
        Returns (None, error_message) if the category isn't found.
        """
        cat_code = str(org.get("dues_category_code") or "DUES").upper()
        row = conn.execute(
            "SELECT id, code, name, active_flag "
            "FROM categories WHERE UPPER(code) = ?",
            (cat_code,),
        ).fetchone()
        if row is None:
            return (
                None,
                f"Dues category '{cat_code}' not found. Add it on the Categories page.",
            )
        if int(row["active_flag"]) != 1:
            return None, f"Dues category '{cat_code}' is inactive."
        return int(row["id"]), f"{row['code']} · {row['name']}"

    def render_page(
        self,
        *,
        org: dict[str, Any] | None,
        theme: str,
        form_values: dict[str, str] | None = None,
        error_message: str = "",
        flash_message: str = "",
    ) -> DuesBillingPageResponse:
        values = form_values or {}
        org = org or {}

        # Auto-resolve the income account — no dropdown needed.
        income_account_id, income_account_label = self._resolve_income_account(
            self.conn, org
        )
        if income_account_id is None:
            error_message = error_message or income_account_label
            income_account_label = ""

        # Last billing record (may be None).
        last = self._dues_repo.get_last_billing()

        # Compute defaults for the form fields.
        # If the user submitted a bad form (error re-render), keep their
        # values.  Otherwise default to the next logical period.
        if values:
            def_cycle = values.get("cycle_type", "MONTHLY")
            def_year = int(
                values.get("period_year", _date.today().year) or _date.today().year
            )
            def_seq = int(values.get("period_sequence", 1) or 1)
        elif last:
            def_cycle = last["cycle_type"]
            def_year, def_seq = _next_period(
                last["cycle_type"],
                int(last["period_year"]),
                int(last["period_sequence"]),
            )
        else:
            def_cycle = "MONTHLY"
            def_year, def_seq = _default_period_for_today("MONTHLY")

        def_label = _period_label(def_cycle, def_year, def_seq)
        def_description = values.get("description") or _auto_description(
            def_cycle, def_label
        )
        # Fall back to the HOA's configured default assessment amount (set on
        # /setup) so treasurers don't have to re-type it every billing cycle.
        def_amount = (
            values.get("amount")
            or str((org or {}).get("default_assessment_amount") or "").strip()
            or ""
        )
        def_entry_date = values.get("entry_date", _today())
        def_due_date = values.get("due_date") or _default_due_date(
            def_cycle, def_entry_date
        )

        ctx = {
            "heading": "Bill Dues",
            "org": org,
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "bill-dues",
            "breadcrumb": "Transactions",
            "income_account_id": income_account_id,
            "income_account_label": income_account_label,
            "last_billing": last,
            "default_cycle_type": def_cycle,
            "default_year": def_year,
            "default_sequence": def_seq,
            "default_label": def_label,
            "values": {
                "amount": def_amount,
                "description": def_description,
                "entry_date": def_entry_date,
                "due_date": def_due_date,
            },
            "error_message": error_message,
            "flash_message": flash_message,
            "cycle_max": _CYCLE_MAX,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return DuesBillingPageResponse(
            status_code=status,
            body_html=render_template(self.TEMPLATE, ctx),
        )

    # ── POST ────────────────────────────────────────────────────────────

    def handle_bill(
        self,
        *,
        form_data: dict[str, str],
        org: dict[str, Any] | None,
        theme: str,
    ) -> tuple[str | None, DuesBillingPageResponse | None]:
        def _err(msg: str) -> tuple[None, DuesBillingPageResponse]:
            return None, self.render_page(
                org=org,
                theme=theme,
                form_values=form_data,
                error_message=msg,
            )

        try:
            cycle_type = (form_data.get("cycle_type") or "").strip().upper()
            if cycle_type not in _CYCLE_MAX:
                return _err("Please select a billing cycle.")

            try:
                period_year = int((form_data.get("period_year") or "").strip())
                if period_year < 2000 or period_year > 2100:
                    raise ValueError
            except (TypeError, ValueError):
                return _err("Year must be a valid 4-digit year.")

            try:
                period_sequence = int((form_data.get("period_sequence") or "").strip())
                max_seq = _CYCLE_MAX[cycle_type]
                if period_sequence < 1 or period_sequence > max_seq:
                    raise ValueError
            except (TypeError, ValueError):
                return _err("Invalid billing period selection.")

            label = _period_label(cycle_type, period_year, period_sequence)

            # Block re-billing the same period — dues_billing_history is the
            # canonical record of which cycles have already gone out.
            existing = self._dues_repo.get_billing_for_period(
                cycle_type=cycle_type,
                period_year=period_year,
                period_sequence=period_sequence,
            )
            if existing:
                return _err(
                    f"{label} has already been billed "
                    f"({existing['owner_count']} homeowners on "
                    f"{str(existing['billed_at'])[:10]}). "
                    "Pick a different period."
                )

            try:
                amount = Decimal((form_data.get("amount") or "").strip())
            except (InvalidOperation, ValueError):
                return _err("Amount must be a number.")
            if amount <= Decimal("0"):
                return _err("Amount must be greater than zero.")

            description = (form_data.get("description") or "").strip()
            if not description:
                return _err("Description is required.")

            entry_date = (form_data.get("entry_date") or "").strip()
            if not entry_date:
                return _err("Posting date is required.")
            try:
                entry_dt = _date.fromisoformat(entry_date)
            except ValueError:
                return _err("Posting date must be a valid date.")

            due_date = (form_data.get("due_date") or "").strip()
            if not due_date:
                return _err("Delinquent date is required.")
            try:
                due_dt = _date.fromisoformat(due_date)
            except ValueError:
                return _err("Delinquent date must be a valid date.")
            # Delinquent date must be on or after the posting date — supports
            # back-dated migration entries (posting date is the operative
            # reference, not today's date).
            if due_dt < entry_dt:
                return _err("Delinquent date cannot be before the posting date.")

            # Chart of accounts retired — bill against the DUES category.
            org_ctx = org or {}
            category_id, cat_err = self._resolve_income_account(self.conn, org_ctx)
            if category_id is None:
                return _err(cat_err)

            result = self.factory.assessment_billing_service().bill_all_at_same_amount(
                entry_date=entry_date,
                amount=amount,
                description=description,
                category_id=category_id,
                due_date=due_date,
            )

            # Record the cycle in history. The billing service committed the
            # assessments inside its own transaction; the history INSERT is
            # outside that transaction and must be committed explicitly.
            DuesBillingRepository(self.conn).insert_history(
                cycle_type=cycle_type,
                period_label=label,
                period_year=period_year,
                period_sequence=period_sequence,
                amount=amount,
                owner_count=result.owner_count,
            )
            self.conn.commit()

        except (ValidationError, NotFoundError, AccountingError) as exc:
            return _err(str(exc))

        msg = (
            f"Billed {result.owner_count} homeowner(s) {format_currency(amount)} each "
            f"for {label}. Total {format_currency(result.total_amount)}."
        )
        from urllib.parse import quote

        return f"/dues-billing?msg={quote(msg)}", None
