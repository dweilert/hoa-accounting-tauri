"""Pure helpers for the bank-statement ingestion engine.

Read-only / hash-only utilities lifted out of ``BankStatementPages``.
The mutating engine methods (``_apply_rule``, ``_compute_matches``,
``_insert_bank_txn``, ``_store_pending_batch``, ``_auto_post_rule_match``)
remain on the Pages class — they're tightly coupled and moving them
risks reordering side effects relative to their transactional callers.
"""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Any


def batch_member_payment_ids(conn: sqlite3.Connection, batch_id: int) -> list[int]:
    rows = conn.execute(
        "SELECT id FROM payments WHERE deposit_batch_id = ? ORDER BY id",
        (batch_id,),
    ).fetchall()
    return [int(r["id"]) for r in rows]


def load_rules(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("""
        SELECT r.id, r.rule_name, r.description_contains,
               r.match_type, r.match_memo, r.match_amount, r.bank_account_id,
               r.action_type, r.category_id, r.vendor_id, r.lot_id,
               r.default_memo, r.active_flag,
               r.confidence_mode, r.auto_post_after_n, r.confirmed_matches,
               c.name AS category_name,
               v.vendor_name AS vendor_name
        FROM bank_transaction_rules r
        LEFT JOIN categories c ON c.id = r.category_id
        LEFT JOIN vendors    v ON v.id = r.vendor_id
        WHERE r.active_flag = 1
        ORDER BY r.id
        """).fetchall()
    return [dict(r) for r in rows]


def next_receipt_number(conn: sqlite3.Connection, payment_date: str) -> str:
    prefix = "RCT-" + payment_date.replace("-", "") + "-"
    row = conn.execute(
        "SELECT receipt_number FROM payments WHERE receipt_number LIKE ? "
        "ORDER BY receipt_number DESC LIMIT 1",
        (prefix + "%",),
    ).fetchone()
    seq = int(row["receipt_number"].rsplit("-", 1)[1]) + 1 if row else 1
    return f"{prefix}{seq:04d}"


def open_assessments_for_lot(conn: sqlite3.Connection, lot_id: int) -> list[int]:
    """Return IDs of open/partial assessments for a lot, oldest due_date first."""
    rows = conn.execute(
        """
        SELECT a.id
        FROM assessments a
        LEFT JOIN payment_applications pa ON pa.assessment_id = a.id
        WHERE a.lot_id = ? AND a.status IN ('OPEN', 'PARTIAL')
        GROUP BY a.id, a.amount, a.due_date
        HAVING a.amount - COALESCE(SUM(pa.applied_amount), 0) > 0
        ORDER BY a.due_date ASC
        """,
        (lot_id,),
    ).fetchall()
    return [int(r["id"]) for r in rows]


def period_for_date(conn: sqlite3.Connection, date_str: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM accounting_periods "
        "WHERE ? BETWEEN start_date AND end_date LIMIT 1",
        (date_str,),
    ).fetchone()
    return int(row["id"]) if row else None


def dedup_key(txn: Any, bank_account_id: int) -> str:
    """Per-account unique key. Prefers the canonical record's hash so
    identity is bank-agnostic and FITID-independent; falls back to a
    content-based key for legacy ``ParsedTransaction`` callers during
    cutover."""
    from hoa_accounting.web.bank_ingest import CanonicalBankTxn

    if isinstance(txn, CanonicalBankTxn):
        return txn.dedup_key(bank_account_id)
    # Legacy ParsedTransaction — compute the same hash from its fields
    # so mixed callers produce identical keys.
    raw = "|".join(
        [
            str(bank_account_id),
            txn.transaction_date.isoformat(),
            str(txn.amount),
            txn.description or "",
            txn.memo or "",
            (txn.transaction_type or "").upper(),
            "",  # check_number not available on ParsedTransaction
        ]
    )
    return "h:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
