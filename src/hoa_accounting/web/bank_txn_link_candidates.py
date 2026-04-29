"""Build the "link this bank line to an existing ledger record" candidate
list — used by the Classify screen to surface payments / income batches
/ bill payments that plausibly correspond to an inbound bank txn.

Pure SQL helpers extracted from ``BankTransactionsPages``. Match rule:
same bank account, same absolute amount (drift-free 2-dp compare),
posting date within ``LINK_DATE_WINDOW_DAYS``. Sign of the bank line
decides which ledger table to search.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from hoa_accounting.validators.common import q2_str

# How many days on either side of a bank line to scan ledger records for.
# Wider than typical clearing latency so a check posted Wed-deposited-Mon
# still surfaces.
LINK_DATE_WINDOW_DAYS = 14


def get_txn(conn: sqlite3.Connection, bank_txn_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT bt.*, ba.account_name, ba.account_last4
        FROM bank_transactions bt
        JOIN bank_accounts ba ON ba.id = bt.bank_account_id
        WHERE bt.id = ?
        """,
        (bank_txn_id,),
    ).fetchone()
    return dict(row) if row else None


def linked_source_ids(conn: sqlite3.Connection, source_type: str) -> set[int]:
    """Source ids already linked to some bank transaction — hide them
    from the candidate list so two bank lines don't claim one ledger
    record."""
    rows = conn.execute(
        "SELECT ledger_source_id FROM bank_transaction_links "
        "WHERE ledger_source_type = ?",
        (source_type,),
    ).fetchall()
    return {int(r["ledger_source_id"]) for r in rows}


def link_candidates(
    conn: sqlite3.Connection, txn: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return ledger records that plausibly correspond to ``txn``."""
    amount = Decimal(str(txn["amount"]))
    abs_amt = q2_str(abs(amount))
    bank_id = int(txn["bank_account_id"])
    try:
        txn_date = date.fromisoformat(str(txn["transaction_date"]))
    except ValueError:
        return []
    lo = (txn_date - timedelta(days=LINK_DATE_WINDOW_DAYS)).isoformat()
    hi = (txn_date + timedelta(days=LINK_DATE_WINDOW_DAYS)).isoformat()

    candidates: list[dict[str, Any]] = []

    if amount > 0:
        linked_payments = linked_source_ids(conn, "PAYMENT")
        for r in conn.execute(
            """
            SELECT p.id, p.payment_date AS dt, p.amount, p.receipt_number,
                   o.first_name || ' ' || o.last_name AS owner_name
            FROM payments p
            LEFT JOIN owners o ON o.id = p.owner_id
            WHERE p.bank_account_id = ?
              AND printf('%.2f', ABS(CAST(p.amount AS NUMERIC))) = ?
              AND p.payment_date BETWEEN ? AND ?
            ORDER BY p.payment_date DESC
            LIMIT 20
            """,
            (bank_id, abs_amt, lo, hi),
        ).fetchall():
            if int(r["id"]) in linked_payments:
                continue
            candidates.append(
                {
                    "source_type": "PAYMENT",
                    "source_id": int(r["id"]),
                    "date": r["dt"],
                    "amount": r["amount"],
                    "label": f"Payment #{r['receipt_number'] or r['id']}"
                    + (f" — {r['owner_name']}" if r["owner_name"] else ""),
                }
            )

        linked_batches = linked_source_ids(conn, "INCOME_BATCH")
        for r in conn.execute(
            """
            SELECT id, posting_date AS dt, total_amount AS amount,
                   income_description
            FROM income_batches
            WHERE bank_account_id = ?
              AND printf('%.2f', ABS(CAST(total_amount AS NUMERIC))) = ?
              AND posting_date BETWEEN ? AND ?
            ORDER BY posting_date DESC
            LIMIT 20
            """,
            (bank_id, abs_amt, lo, hi),
        ).fetchall():
            if int(r["id"]) in linked_batches:
                continue
            candidates.append(
                {
                    "source_type": "INCOME_BATCH",
                    "source_id": int(r["id"]),
                    "date": r["dt"],
                    "amount": r["amount"],
                    "label": f"Income #{r['id']} — " f"{r['income_description'] or ''}",
                }
            )
    else:
        linked_bps = linked_source_ids(conn, "BILL_PAYMENT")
        for r in conn.execute(
            """
            SELECT bp.id, bp.payment_date AS dt, bp.amount, bp.check_number,
                   v.vendor_name
            FROM bill_payments bp
            LEFT JOIN vendor_bills vb ON vb.id = bp.vendor_bill_id
            LEFT JOIN vendors v ON v.id = vb.vendor_id
            WHERE bp.bank_account_id = ?
              AND printf('%.2f', ABS(CAST(bp.amount AS NUMERIC))) = ?
              AND bp.payment_date BETWEEN ? AND ?
            ORDER BY bp.payment_date DESC
            LIMIT 20
            """,
            (bank_id, abs_amt, lo, hi),
        ).fetchall():
            if int(r["id"]) in linked_bps:
                continue
            candidates.append(
                {
                    "source_type": "BILL_PAYMENT",
                    "source_id": int(r["id"]),
                    "date": r["dt"],
                    "amount": r["amount"],
                    "label": (
                        f"Bill payment #{r['check_number'] or r['id']}"
                        + (f" — {r['vendor_name']}" if r["vendor_name"] else "")
                    ),
                }
            )

    return candidates
