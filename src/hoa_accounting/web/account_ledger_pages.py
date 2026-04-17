"""Account ledger (transaction history) pages.

Routes handled:
  GET  /accounts/<id>/ledger          — transaction history for one account
                                        optional ?start=YYYY-MM-DD&end=YYYY-MM-DD
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from http import HTTPStatus

from hoa_accounting.exceptions import NotFoundError
from hoa_accounting.reporting.general_ledger import GeneralLedgerReportService
from hoa_accounting.repositories.accounts_repo import AccountsRepository
from hoa_accounting.web.template_engine import render_template

_BASE_CTX = {
    "active_nav": "master-data",
    "page_key": "accounts",
    "breadcrumb": "Master Data · Chart of Accounts",
}

# Human-readable source type labels
_SOURCE_LABELS: dict[str, str] = {
    "ASSESSMENT":  "Assessment",
    "PAYMENT":     "Payment",
    "VENDOR_BILL": "Vendor Bill",
    "BILL_PAYMENT": "Bill Payment",
    "TRANSFER":    "Transfer",
    "ADJUSTMENT":  "Adjustment",
    "REVERSAL":    "Reversal",
    "MANUAL":      "Manual JE",
}

# Normal balance direction per account type
_NORMAL_BALANCE: dict[str, str] = {
    "ASSET":     "DEBIT",
    "LIABILITY": "CREDIT",
    "EQUITY":    "CREDIT",
    "INCOME":    "CREDIT",
    "EXPENSE":   "DEBIT",
}


@dataclass(frozen=True)
class LedgerPageResponse:
    status_code: int
    body_html: str


def _balance_label(amount: Decimal, normal_balance: str) -> str:
    """Return amount as a signed string with Dr/Cr suffix.

    A positive running_balance (in debit-positive convention) means the
    account carries a debit balance.  Whether that is "normal" or
    "contra" depends on the account type.
    """
    if amount == Decimal("0.00"):
        return "0.00"
    if amount > 0:
        return f"{amount} Dr"
    return f"{abs(amount)} Cr"


class AccountLedgerPages:
    """Render the account ledger (transaction history) page."""

    TEMPLATE = "account_ledger.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.accounts_repo = AccountsRepository(conn)
        self.gl_service = GeneralLedgerReportService(conn)

    def render_ledger(
        self,
        *,
        account_id: int,
        org: dict | None,
        theme: str,
        start_date: str = "",
        end_date: str = "",
    ) -> LedgerPageResponse:
        account = self.accounts_repo.get_account(account_id)
        if account is None:
            ctx = {
                **_BASE_CTX,
                "heading": "Account Not Found",
                "org": org or {},
                "theme": theme,
                "error_message": f"Account #{account_id} not found.",
                "account": None,
                "rows": [],
                "total_debits": "0.00",
                "total_credits": "0.00",
                "start_date": start_date,
                "end_date": end_date,
            }
            return LedgerPageResponse(
                status_code=HTTPStatus.NOT_FOUND,
                body_html=render_template(self.TEMPLATE, ctx),
            )

        normal_balance = _NORMAL_BALANCE.get(
            str(account["account_type_code"]), "DEBIT"
        )

        try:
            report = self.gl_service.generate(
                account_id=account_id,
                from_date=start_date or None,
                to_date=end_date or None,
            )
        except NotFoundError:
            report = None

        rows: list[dict] = []
        total_debits = Decimal("0.00")
        total_credits = Decimal("0.00")

        if report:
            for r in report.rows:
                total_debits += r.debit_amount
                total_credits += r.credit_amount
                rows.append({
                    "entry_date":      r.entry_date,
                    "entry_number":    r.entry_number,
                    "source_type":     r.source_type,
                    "source_label":    _SOURCE_LABELS.get(r.source_type, r.source_type),
                    "memo":            r.memo,
                    "line_description": r.line_description,
                    "debit_amount":    str(r.debit_amount) if r.debit_amount else "",
                    "credit_amount":   str(r.credit_amount) if r.credit_amount else "",
                    "running_balance": _balance_label(r.running_balance, normal_balance),
                    "is_manual":       r.source_type == "MANUAL",
                })

        ctx = {
            **_BASE_CTX,
            "heading": f"{account['account_number']} – {account['account_name']}",
            "breadcrumb": "Master Data · Chart of Accounts",
            "org": org or {},
            "theme": theme,
            "account": dict(account),
            "normal_balance": normal_balance,
            "rows": rows,
            "total_debits": str(total_debits),
            "total_credits": str(total_credits),
            "start_date": start_date,
            "end_date": end_date,
            "row_count": len(rows),
        }
        return LedgerPageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.TEMPLATE, ctx),
        )
