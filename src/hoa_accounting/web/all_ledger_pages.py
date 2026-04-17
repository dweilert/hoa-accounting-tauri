"""All-accounts ledger views.

Routes handled:
  GET  /ledger/transactions     — every posted JE line, date-ordered
  GET  /ledger/by-account       — same lines grouped per account

Both accept:
  ?start=YYYY-MM-DD   — filter from date (inclusive)
  ?end=YYYY-MM-DD     — filter to date (inclusive)
  ?sort=asc|desc      — date order within each group (default: asc)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from http import HTTPStatus

from hoa_accounting.web.template_engine import render_template

_SOURCE_LABELS: dict[str, str] = {
    "ASSESSMENT":   "Assessment",
    "PAYMENT":      "Payment",
    "VENDOR_BILL":  "Vendor Bill",
    "BILL_PAYMENT": "Bill Payment",
    "TRANSFER":     "Transfer",
    "ADJUSTMENT":   "Adjustment",
    "REVERSAL":     "Reversal",
    "MANUAL":       "Manual JE",
}

_NORMAL_BALANCE: dict[str, str] = {
    "ASSET":     "DEBIT",
    "LIABILITY": "CREDIT",
    "EQUITY":    "CREDIT",
    "INCOME":    "CREDIT",
    "EXPENSE":   "DEBIT",
}


@dataclass(frozen=True)
class LedgerResponse:
    status_code: int
    body_html: str


def _balance_label(amount: Decimal) -> str:
    if amount == Decimal("0.00"):
        return "0.00"
    if amount > 0:
        return f"{amount} Dr"
    return f"{abs(amount)} Cr"


def _fetch_lines(
    conn: sqlite3.Connection,
    *,
    start_date: str,
    end_date: str,
    order: str,          # "ASC" or "DESC"
    group_by_account: bool,
) -> list[sqlite3.Row]:
    """Shared query for both views."""
    conditions = ["je.status = 'POSTED'"]
    params: list[object] = []

    if start_date:
        conditions.append("je.entry_date >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("je.entry_date <= ?")
        params.append(end_date)

    where = " AND ".join(conditions)

    if group_by_account:
        order_sql = (
            f"a.account_number ASC, "
            f"je.entry_date {order}, je.entry_number {order}, jel.line_number ASC"
        )
    else:
        order_sql = (
            f"je.entry_date {order}, je.entry_number {order}, jel.line_number ASC"
        )

    return conn.execute(
        f"""
        SELECT
            je.id               AS journal_entry_id,
            je.entry_date,
            je.entry_number,
            je.source_type,
            COALESCE(je.memo, '')         AS memo,
            COALESCE(jel.description, '') AS line_description,
            CAST(COALESCE(jel.debit_amount,  0) AS TEXT) AS debit_amount,
            CAST(COALESCE(jel.credit_amount, 0) AS TEXT) AS credit_amount,
            a.id                AS account_id,
            a.account_number,
            a.account_name,
            a.fund_code,
            at.code             AS account_type_code
        FROM journal_entry_lines jel
        JOIN journal_entries je ON je.id = jel.journal_entry_id
        JOIN accounts a         ON a.id  = jel.account_id
        JOIN account_types at   ON at.id = a.account_type_id
        WHERE {where}
        ORDER BY {order_sql}
        """,
        params,
    ).fetchall()


class AllLedgerPages:
    """Flat and grouped ledger views across all accounts."""

    FLAT_TEMPLATE    = "all_transactions.html"
    GROUPED_TEMPLATE = "ledger_by_account.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ── helpers ───────────────────────────────────────────────────────

    def _parse_params(
        self, start_date: str, end_date: str, sort: str
    ) -> tuple[str, str, str]:
        sort_dir = "DESC" if sort.lower() == "desc" else "ASC"
        return start_date.strip(), end_date.strip(), sort_dir

    # ── flat list ─────────────────────────────────────────────────────

    def render_all_transactions(
        self,
        *,
        org: dict | None,
        theme: str,
        start_date: str = "",
        end_date: str = "",
        sort: str = "asc",
    ) -> LedgerResponse:
        start, end, order = self._parse_params(start_date, end_date, sort)
        raw = _fetch_lines(
            self.conn,
            start_date=start, end_date=end,
            order=order, group_by_account=False,
        )

        rows: list[dict] = []
        total_debits = Decimal("0.00")
        total_credits = Decimal("0.00")

        for r in raw:
            dr = Decimal(str(r["debit_amount"]))
            cr = Decimal(str(r["credit_amount"]))
            total_debits  += dr
            total_credits += cr
            rows.append({
                "entry_date":       r["entry_date"],
                "entry_number":     r["entry_number"],
                "source_type":      r["source_type"],
                "source_label":     _SOURCE_LABELS.get(r["source_type"], r["source_type"]),
                "is_manual":        r["source_type"] == "MANUAL",
                "journal_entry_id": r["journal_entry_id"],
                "memo":             r["memo"],
                "line_description": r["line_description"],
                "account_number":   r["account_number"],
                "account_name":     r["account_name"],
                "fund_code":        r["fund_code"],
                "debit_amount":     str(dr) if dr else "",
                "credit_amount":    str(cr) if cr else "",
            })

        ctx = {
            "active_nav": "transactions",
            "page_key": "all-transactions",
            "breadcrumb": "Transactions",
            "heading": "All Transactions",
            "org": org or {},
            "theme": theme,
            "rows": rows,
            "row_count": len(rows),
            "total_debits":  str(total_debits),
            "total_credits": str(total_credits),
            "start_date": start,
            "end_date":   end,
            "sort":       sort.lower(),
        }
        return LedgerResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.FLAT_TEMPLATE, ctx),
        )

    # ── grouped by account ────────────────────────────────────────────

    def render_by_account(
        self,
        *,
        org: dict | None,
        theme: str,
        start_date: str = "",
        end_date: str = "",
        sort: str = "asc",
    ) -> LedgerResponse:
        start, end, order = self._parse_params(start_date, end_date, sort)
        raw = _fetch_lines(
            self.conn,
            start_date=start, end_date=end,
            order=order, group_by_account=True,
        )

        # Group into account buckets, preserving order
        from collections import OrderedDict
        accounts: OrderedDict[int, dict] = OrderedDict()

        for r in raw:
            aid = r["account_id"]
            if aid not in accounts:
                nb = _NORMAL_BALANCE.get(r["account_type_code"], "DEBIT")
                accounts[aid] = {
                    "account_id":       aid,
                    "account_number":   r["account_number"],
                    "account_name":     r["account_name"],
                    "fund_code":        r["fund_code"],
                    "account_type_code": r["account_type_code"],
                    "normal_balance":   nb,
                    "rows":             [],
                    "total_debits":     Decimal("0.00"),
                    "total_credits":    Decimal("0.00"),
                    "running_balance":  Decimal("0.00"),
                }

            acct = accounts[aid]
            dr = Decimal(str(r["debit_amount"]))
            cr = Decimal(str(r["credit_amount"]))
            acct["total_debits"]  += dr
            acct["total_credits"] += cr
            acct["running_balance"] += dr - cr

            acct["rows"].append({
                "entry_date":       r["entry_date"],
                "entry_number":     r["entry_number"],
                "source_type":      r["source_type"],
                "source_label":     _SOURCE_LABELS.get(r["source_type"], r["source_type"]),
                "is_manual":        r["source_type"] == "MANUAL",
                "journal_entry_id": r["journal_entry_id"],
                "memo":             r["memo"],
                "line_description": r["line_description"],
                "debit_amount":     str(dr) if dr else "",
                "credit_amount":    str(cr) if cr else "",
                "running_balance":  _balance_label(acct["running_balance"]),
            })

        # Stringify totals for template
        grand_dr = Decimal("0.00")
        grand_cr = Decimal("0.00")
        account_list = []
        for acct in accounts.values():
            grand_dr += acct["total_debits"]
            grand_cr += acct["total_credits"]
            account_list.append({
                **{k: v for k, v in acct.items() if k not in ("total_debits", "total_credits", "running_balance")},
                "total_debits":  str(acct["total_debits"]),
                "total_credits": str(acct["total_credits"]),
                "ending_balance": _balance_label(acct["running_balance"]),
            })

        ctx = {
            "active_nav": "transactions",
            "page_key": "ledger-by-account",
            "breadcrumb": "Transactions",
            "heading": "Ledger by Account",
            "org": org or {},
            "theme": theme,
            "accounts": account_list,
            "account_count": len(account_list),
            "grand_debits":  str(grand_dr),
            "grand_credits": str(grand_cr),
            "start_date": start,
            "end_date":   end,
            "sort":       sort.lower(),
        }
        return LedgerResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.GROUPED_TEMPLATE, ctx),
        )
