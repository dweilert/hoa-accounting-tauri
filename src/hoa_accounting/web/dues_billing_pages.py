"""Dues Billing page — periodic dues for all homeowners with cycle tracking.

Bills all active lot-owners the same amount for a selected billing cycle
(monthly, quarterly, semi-annual, or annual).  Every run is recorded in
``dues_billing_history`` so the screen can show the last billed period
and default to the next logical period, preventing accidental skips.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date as _date
from decimal import Decimal, InvalidOperation
from http import HTTPStatus

from hoa_accounting.exceptions import AccountingError, NotFoundError, ValidationError
from hoa_accounting.repositories.accounts_repo import AccountsRepository
from hoa_accounting.repositories.dues_billing_repo import DuesBillingRepository
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.web.template_engine import render_template

_MONTH_NAMES = [
    "January", "February", "March", "April",
    "May", "June", "July", "August",
    "September", "October", "November", "December",
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
        conn: sqlite3.Connection, org: dict
    ) -> tuple[int | None, str]:
        """Return (account_id, display_label) for the configured income account.

        Looks up ``dues_income_account_number`` from org config (default 4000).
        Returns (None, error_message) if the account cannot be found.
        """
        acct_num = str(org.get("dues_income_account_number") or "4000")
        repo = AccountsRepository(conn)
        row = repo.get_by_number(acct_num)
        if row is None:
            return None, f"Income account '{acct_num}' not found in the chart of accounts."
        if int(row["is_active"]) != 1:
            return None, f"Income account '{acct_num}' is inactive."
        label = f"{row['account_number']} · {row['account_name']}"
        return int(row["id"]), label

    def render_page(
        self,
        *,
        org: dict | None,
        theme: str,
        form_values: dict[str, str] | None = None,
        error_message: str = "",
        flash_message: str = "",
    ) -> DuesBillingPageResponse:
        values = form_values or {}
        org = org or {}

        # Auto-resolve the income account — no dropdown needed.
        income_account_id, income_account_label = self._resolve_income_account(self.conn, org)
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
            def_year = int(values.get("period_year", _date.today().year) or _date.today().year)
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
        def_description = values.get("description") or _auto_description(def_cycle, def_label)
        # Fall back to the HOA's configured default assessment amount (set on
        # /setup) so treasurers don't have to re-type it every billing cycle.
        def_amount = (
            values.get("amount")
            or str((org or {}).get("default_assessment_amount") or "").strip()
            or ""
        )
        def_entry_date = values.get("entry_date", _today())

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
        org: dict | None,
        theme: str,
    ) -> tuple[str | None, DuesBillingPageResponse | None]:
        def _err(msg: str) -> tuple[None, DuesBillingPageResponse]:
            return None, self.render_page(
                org=org, theme=theme,
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

            # Both accounts are resolved from config — no user selection needed.
            org_ctx = org or {}
            ar_num = str(org_ctx.get("dues_receivable_account_number") or "1100")
            ar_row = AccountsRepository(self.conn).get_by_number(ar_num)
            if ar_row is None:
                return _err(f"Dues receivable account '{ar_num}' not found.")

            income_account_id, income_err = self._resolve_income_account(self.conn, org_ctx)
            if income_account_id is None:
                return _err(income_err)

            result = self.factory.assessment_billing_service().bill_all_at_same_amount(
                entry_date=entry_date,
                amount=amount,
                description=description,
                receivable_account_id=int(ar_row["id"]),
                income_account_id=income_account_id,
            )

            # Record the cycle in history.
            DuesBillingRepository(self.conn).insert_history(
                cycle_type=cycle_type,
                period_label=label,
                period_year=period_year,
                period_sequence=period_sequence,
                amount=amount,
                owner_count=result.owner_count,
            )

        except (ValidationError, NotFoundError, AccountingError) as exc:
            return _err(str(exc))

        msg = (
            f"Billed {result.owner_count} homeowner(s) ${amount:,.2f} each "
            f"for {label}. Total ${result.total_amount:,.2f}."
        )
        from urllib.parse import quote
        return f"/dues-billing?msg={quote(msg)}", None
