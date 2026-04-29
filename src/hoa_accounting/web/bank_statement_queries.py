"""Read-only SQL accessors for the bank statement / import flow.

Pure queries over a sqlite3.Connection — no Pages object, no rendering.
Extracted from ``bank_statement_pages.py`` so the page service can stay
focused on render/POST orchestration.
"""

from __future__ import annotations

import sqlite3
from typing import Any


def get_unmatched_items(
    conn: sqlite3.Connection, bank_account_id: int
) -> list[dict[str, Any]]:
    """Return single-entry records for this bank account that have no
    linked bank transaction yet (i.e. no prior OFX import has claimed
    them via ``matched_source_type`` / ``matched_source_id``).

    Each item exposes ``source_type``, ``source_id``, ``item_date``,
    signed ``amount`` (positive = deposit, negative = withdrawal), and
    a short ``description`` — the matcher's expected shape. Payments
    that belong to a deposit batch are excluded; they clear as a unit
    via ``get_unmatched_batches``.

    Exclusion scope is "any bank_transactions row has already linked
    this record" — regardless of reconciliation state. That makes OFX
    import independent from the monthly reconciliation workflow.
    """
    rows = conn.execute(
        """
        WITH matched AS (
            SELECT bt.matched_source_type AS source_type,
                   bt.matched_source_id   AS source_id
            FROM bank_transactions bt
            WHERE bt.matched_source_type IS NOT NULL
              AND bt.matched_source_id   IS NOT NULL
        )
        SELECT 'PAYMENT' AS source_type, p.id AS source_id,
               p.payment_date AS item_date,
               CAST(p.amount AS REAL) AS amount,
               COALESCE(p.notes, '') AS description
        FROM payments p
        WHERE p.bank_account_id = ?
          AND p.deposit_batch_id IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM matched m
              WHERE m.source_type = 'PAYMENT' AND m.source_id = p.id
          )
        UNION ALL
        SELECT 'INCOME_BATCH', ib.id,
               ib.posting_date,
               CAST(ib.total_amount AS REAL),
               COALESCE(ib.income_description, '')
        FROM income_batches ib
        WHERE ib.bank_account_id = ?
          AND NOT EXISTS (
              SELECT 1 FROM matched m
              WHERE m.source_type = 'INCOME_BATCH' AND m.source_id = ib.id
          )
        UNION ALL
        SELECT 'BILL_PAYMENT', bp.id,
               bp.payment_date,
               -CAST(bp.amount AS REAL),
               COALESCE(bp.notes, '')
        FROM bill_payments bp
        WHERE bp.bank_account_id = ?
          AND NOT EXISTS (
              SELECT 1 FROM matched m
              WHERE m.source_type = 'BILL_PAYMENT' AND m.source_id = bp.id
          )
        UNION ALL
        SELECT 'RESERVE_TRANSFER', rt.id,
               rt.transfer_date,
               CASE WHEN rt.to_bank_account_id = ?
                    THEN  CAST(rt.amount AS REAL)
                    ELSE -CAST(rt.amount AS REAL) END,
               COALESCE(rt.notes, '')
        FROM reserve_transfers rt
        WHERE (rt.from_bank_account_id = ? OR rt.to_bank_account_id = ?)
          AND NOT EXISTS (
              SELECT 1 FROM matched m
              WHERE m.source_type = 'RESERVE_TRANSFER' AND m.source_id = rt.id
          )
        ORDER BY item_date ASC
        """,
        (
            bank_account_id,
            bank_account_id,
            bank_account_id,
            bank_account_id,
            bank_account_id,
            bank_account_id,
        ),
    ).fetchall()
    return [dict(r) for r in rows]


def get_unmatched_batches(
    conn: sqlite3.Connection, bank_account_id: int
) -> list[dict[str, Any]]:
    """Return deposit batches for this bank account that no prior OFX
    import has already matched. A batch is considered matched only when
    its deposit_batch_id appears in ``bank_transactions.matched_source_id``
    with ``matched_source_type = 'DEPOSIT_BATCH'``.
    """
    rows = conn.execute(
        """
        SELECT db.id AS batch_id,
               db.deposit_date AS batch_date,
               CAST(db.total_amount AS REAL) AS total_amount,
               COALESCE(db.notes, '') AS notes,
               (SELECT COUNT(*) FROM payments p
                WHERE p.deposit_batch_id = db.id) AS member_count
        FROM deposit_batches db
        WHERE db.bank_account_id = ?
          AND NOT EXISTS (
              SELECT 1 FROM bank_transactions bt
              WHERE bt.matched_source_type = 'DEPOSIT_BATCH'
                AND bt.matched_source_id   = db.id
          )
        ORDER BY db.deposit_date ASC
        """,
        (bank_account_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_bank_account(
    conn: sqlite3.Connection, bank_account_id: int
) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT id, account_name, account_last4, institution_name, fund_code "
        "FROM bank_accounts WHERE id = ?",
        (bank_account_id,),
    ).fetchone()
    return row


def get_all_bank_accounts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, account_name, account_last4, institution_name "
        "FROM bank_accounts ORDER BY account_name"
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_batches(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Last 50 standalone import batches with LIVE matched_count / status.

    The stored ``matched_count`` / ``status`` columns are written once at
    upload time and never updated as the user validates rows — relying
    on them showed batches as PENDING with 0 matched even after every
    row was processed. Compute them from bank_transactions instead.
    """
    rows = conn.execute("""
        SELECT b.id, b.bank_account_id, b.source_filename, b.file_format,
               b.transaction_count,
               COALESCE((SELECT COUNT(*) FROM bank_transactions bt
                          WHERE bt.import_batch_id = b.id
                            AND bt.match_type != 'UNMATCHED'), 0) AS matched_count,
               CASE
                 WHEN (SELECT COUNT(*) FROM bank_transactions bt2
                        WHERE bt2.import_batch_id = b.id
                          AND bt2.validation_status = 'UNVALIDATED') > 0
                   THEN 'PENDING'
                 WHEN (SELECT COUNT(*) FROM bank_transactions bt3
                        WHERE bt3.import_batch_id = b.id) = 0
                   THEN 'EMPTY'
                 ELSE 'COMPLETE'
               END AS status,
               b.imported_at,
               ba.account_name, ba.account_last4
        FROM bank_import_batches b
        JOIN bank_accounts ba ON ba.id = b.bank_account_id
        WHERE b.reconciliation_id IS NULL
        ORDER BY b.imported_at DESC
        LIMIT 50
        """).fetchall()
    return [dict(r) for r in rows]
