"""All-transactions ledger view.

Route handled:
  GET  /ledger/transactions  — every posted transaction across all source tables

Accepts:
  ?start=YYYY-MM-DD   — filter from date (inclusive)
  ?end=YYYY-MM-DD     — filter to date (inclusive)
  ?sort=asc|desc      — date order (default: asc)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from http import HTTPStatus
from typing import Any

from hoa_accounting.web.template_engine import render_template


@dataclass(frozen=True)
class LedgerResponse:
    status_code: int
    body_html: str


def _fetch_transactions(
    conn: sqlite3.Connection,
    *,
    start_date: str,
    end_date: str,
    order: str,  # "ASC" or "DESC"
) -> list[sqlite3.Row]:
    """UNION across all source transaction tables."""
    outer_conditions = []
    params: list[object] = []
    if start_date:
        outer_conditions.append("txn_date >= ?")
        params.append(start_date)
    if end_date:
        outer_conditions.append("txn_date <= ?")
        params.append(end_date)
    outer_where = (
        ("WHERE " + " AND ".join(outer_conditions)) if outer_conditions else ""
    )

    return conn.execute(
        f"""
        SELECT txn_date, txn_type, party, category_name, amount, memo, fund_code
        FROM (

            -- Vendor bills (expenses)
            SELECT
                vb.invoice_date              AS txn_date,
                'Vendor Bill'                AS txn_type,
                COALESCE(v.vendor_name, '')  AS party,
                COALESCE(c.name, '')         AS category_name,
                vb.amount                    AS amount,
                COALESCE(vb.description, vb.invoice_number, '') AS memo,
                COALESCE(vb.fund_code, c.fund_code, 'OPERATING') AS fund_code
            FROM vendor_bills vb
            LEFT JOIN vendors v    ON v.id = vb.vendor_id
            LEFT JOIN categories c ON c.id = vb.category_id
            WHERE vb.status != 'VOID'

            UNION ALL

            -- Income batches (non-dues income)
            SELECT
                ib.posting_date              AS txn_date,
                'Income'                     AS txn_type,
                ''                           AS party,
                COALESCE(c.name, ib.income_description) AS category_name,
                ib.total_amount              AS amount,
                ib.income_description        AS memo,
                COALESCE(c.fund_code, 'OPERATING')      AS fund_code
            FROM income_batches ib
            LEFT JOIN categories c ON c.id = ib.category_id

            UNION ALL

            -- Assessments (dues billed to owners)
            SELECT
                a.assessment_date            AS txn_date,
                'Assessment'                 AS txn_type,
                CASE WHEN o.first_name IS NOT NULL OR o.last_name IS NOT NULL
                     THEN TRIM(COALESCE(o.first_name,'') || ' ' || COALESCE(o.last_name,''))
                     ELSE COALESCE(o.display_name, '') END AS party,
                COALESCE(c.name, a.description) AS category_name,
                a.amount                     AS amount,
                a.description                AS memo,
                COALESCE(c.fund_code, 'OPERATING') AS fund_code
            FROM assessments a
            JOIN owners o ON o.id = a.owner_id
            LEFT JOIN categories c ON c.id = a.category_id
            WHERE a.status != 'VOID'

            UNION ALL

            -- Payments received from owners
            SELECT
                p.payment_date               AS txn_date,
                'Payment'                    AS txn_type,
                CASE WHEN o.first_name IS NOT NULL OR o.last_name IS NOT NULL
                     THEN TRIM(COALESCE(o.first_name,'') || ' ' || COALESCE(o.last_name,''))
                     ELSE COALESCE(o.display_name, '') END AS party,
                ''                           AS category_name,
                p.amount                     AS amount,
                COALESCE(p.notes, p.reference_number, '') AS memo,
                'OPERATING'                  AS fund_code
            FROM payments p
            JOIN owners o ON o.id = p.owner_id

            UNION ALL

            -- Reserve transfers
            SELECT
                rt.transfer_date             AS txn_date,
                CASE rt.transfer_type
                    WHEN 'FUND'     THEN 'Reserve Funding'
                    WHEN 'WITHDRAW' THEN 'Reserve Withdrawal'
                    ELSE 'Reserve Transfer'
                END                          AS txn_type,
                ''                           AS party,
                COALESCE(c.name, '')         AS category_name,
                rt.amount                    AS amount,
                COALESCE(rt.purpose, rt.notes, '') AS memo,
                'RESERVE'                    AS fund_code
            FROM reserve_transfers rt
            LEFT JOIN categories c ON c.id = rt.category_id

        ) combined
        {outer_where}
        ORDER BY txn_date {order}, txn_type, party
        """,
        params,
    ).fetchall()


_TYPE_PILL_CLASS = {
    "Vendor Bill": "pill--warn",
    "Income": "pill--ok",
    "Assessment": "pill--info",
    "Payment": "pill--ok",
    "Reserve Funding": "pill--info",
    "Reserve Withdrawal": "pill--warn",
    "Reserve Transfer": "pill--muted",
}

_MONEY_OUT = {"Vendor Bill", "Reserve Funding"}


class AllLedgerPages:
    """Flat transactions view across all source tables."""

    FLAT_TEMPLATE = "all_transactions.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _parse_params(
        self, start_date: str, end_date: str, sort: str
    ) -> tuple[str, str, str]:
        sort_dir = "DESC" if sort.lower() == "desc" else "ASC"
        return start_date.strip(), end_date.strip(), sort_dir

    def render_all_transactions(
        self,
        *,
        org: dict[str, Any] | None,
        theme: str,
        start_date: str = "",
        end_date: str = "",
        sort: str = "asc",
    ) -> LedgerResponse:
        start, end, order = self._parse_params(start_date, end_date, sort)
        raw = _fetch_transactions(
            self.conn,
            start_date=start,
            end_date=end,
            order=order,
        )

        rows: list[dict[str, Any]] = []
        total_in = Decimal("0.00")
        total_out = Decimal("0.00")

        for r in raw:
            txn_type = str(r["txn_type"])
            amount = Decimal(str(r["amount"]))
            money_out = txn_type in _MONEY_OUT

            if money_out:
                total_out += amount
            else:
                total_in += amount

            rows.append(
                {
                    "txn_date": r["txn_date"],
                    "txn_type": txn_type,
                    "pill_class": _TYPE_PILL_CLASS.get(txn_type, "pill--muted"),
                    "party": str(r["party"] or ""),
                    "category_name": str(r["category_name"] or ""),
                    "amount": str(amount),
                    "money_out": money_out,
                    "memo": str(r["memo"] or ""),
                    "fund_code": str(r["fund_code"] or ""),
                }
            )

        ctx = {
            "active_nav": "transactions",
            "page_key": "all-transactions",
            "breadcrumb": "Transactions",
            "heading": "All Transactions",
            "org": org or {},
            "theme": theme,
            "rows": rows,
            "row_count": len(rows),
            "total_in": str(total_in),
            "total_out": str(total_out),
            "start_date": start,
            "end_date": end,
            "sort": sort.lower(),
        }
        return LedgerResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.FLAT_TEMPLATE, ctx),
        )

    # kept for any route that still calls render_by_account
    def render_by_account(self, **kwargs: Any) -> LedgerResponse:
        return self.render_all_transactions(**kwargs)
