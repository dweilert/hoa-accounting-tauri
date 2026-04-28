"""Deposits report — list of deposit batches in a date range.

Each row corresponds to one ``deposit_batches`` entry — the slip the
treasurer took to the bank — with rolled-up counts for the owner
payments and the other-source income lines that posted under the
same batch id.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from hoa_accounting.reporting.dto import (
    DepositsReport,
    DepositsReportLine,
    DepositsReportRow,
)
from hoa_accounting.validators.common import q2


class DepositsReportService:
    """Produce a chronological list of deposit batches."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def generate(self, *, from_date: str, to_date: str) -> DepositsReport:
        rows = self.conn.execute(
            """
            SELECT
                db.id                                       AS batch_id,
                db.deposit_date                             AS deposit_date,
                ba.account_name                             AS bank_account,
                ba.account_last4                            AS bank_account_last4,
                db.total_amount                             AS total_amount,
                ''                                          AS journal_entry,
                COALESCE(db.notes, '')                      AS memo,
                (SELECT COUNT(*) FROM payments p
                   WHERE p.deposit_batch_id = db.id)        AS owner_payment_count,
                (SELECT COALESCE(SUM(p.amount), 0) FROM payments p
                   WHERE p.deposit_batch_id = db.id)        AS owner_payment_total,
                (SELECT COUNT(*) FROM income_batches ib
                   WHERE ib.deposit_batch_id = db.id)       AS other_source_count,
                (SELECT COALESCE(SUM(ib.total_amount), 0) FROM income_batches ib
                   WHERE ib.deposit_batch_id = db.id)       AS other_source_total
            FROM deposit_batches db
            JOIN bank_accounts ba ON ba.id = db.bank_account_id
            WHERE db.deposit_date >= ?
              AND db.deposit_date <= ?
            ORDER BY db.deposit_date, db.id
            """,
            (from_date, to_date),
        ).fetchall()

        report_rows: list[DepositsReportRow] = []
        grand_total = Decimal("0.00")

        for row in rows:
            total = q2(row["total_amount"])
            grand_total += total
            report_rows.append(
                DepositsReportRow(
                    batch_id=int(row["batch_id"]),
                    deposit_date=str(row["deposit_date"]),
                    bank_account=str(row["bank_account"] or ""),
                    bank_account_last4=str(row["bank_account_last4"] or ""),
                    total_amount=total,
                    journal_entry=str(row["journal_entry"] or ""),
                    memo=str(row["memo"] or ""),
                    owner_payment_count=int(row["owner_payment_count"] or 0),
                    owner_payment_total=q2(row["owner_payment_total"] or 0),
                    other_source_count=int(row["other_source_count"] or 0),
                    other_source_total=q2(row["other_source_total"] or 0),
                    lines=self._lines_for_batch(int(row["batch_id"])),
                )
            )

        return DepositsReport(
            from_date=from_date,
            to_date=to_date,
            rows=report_rows,
            grand_total=grand_total,
        )

    def _lines_for_batch(self, batch_id: int) -> list[DepositsReportLine]:
        """Return all lines that posted under a deposit batch — both
        owner payments (with the charge types they applied to) and
        non-owner income lines (with their category)."""
        lines: list[DepositsReportLine] = []

        owner_rows = self.conn.execute(
            """
            SELECT
                p.id              AS payment_id,
                p.amount          AS amount,
                p.reference_number AS reference,
                COALESCE(
                    NULLIF(TRIM(COALESCE(o.first_name,'') || ' ' || COALESCE(o.last_name,'')), ''),
                    o.display_name,
                    ''
                )                 AS owner_name,
                l.lot_number      AS lot_number,
                (SELECT GROUP_CONCAT(DISTINCT a.charge_type)
                   FROM payment_applications pa
                   JOIN assessments a ON a.id = pa.assessment_id
                  WHERE pa.payment_id = p.id) AS applied_types
            FROM payments p
            JOIN owners o ON o.id = p.owner_id
            LEFT JOIN payment_applications pa ON pa.payment_id = p.id
            LEFT JOIN assessments a ON a.id = pa.assessment_id
            LEFT JOIN lots l ON l.id = a.lot_id
            WHERE p.deposit_batch_id = ?
            GROUP BY p.id
            ORDER BY p.id
            """,
            (batch_id,),
        ).fetchall()

        for row in owner_rows:
            owner = (row["owner_name"] or "").strip()
            lot = (row["lot_number"] or "")
            desc = f"Lot {lot} · {owner}" if lot and owner else (owner or f"Lot {lot}".strip())
            lines.append(
                DepositsReportLine(
                    line_type="OWNER",
                    description=desc or "Owner payment",
                    detail=str(row["applied_types"] or ""),
                    reference=str(row["reference"] or ""),
                    amount=q2(row["amount"]),
                )
            )

        other_rows = self.conn.execute(
            """
            SELECT
                ib.id                 AS income_batch_id,
                ib.total_amount       AS amount,
                ib.income_description AS description,
                ib.notes              AS notes,
                COALESCE(c.name, '')  AS category_name
            FROM income_batches ib
            LEFT JOIN categories c ON c.id = ib.category_id
            WHERE ib.deposit_batch_id = ?
            ORDER BY ib.id
            """,
            (batch_id,),
        ).fetchall()

        for row in other_rows:
            cat = (row["category_name"] or "").strip()
            lines.append(
                DepositsReportLine(
                    line_type="OTHER",
                    description=cat or "Other income",
                    detail=str(row["description"] or row["notes"] or ""),
                    reference="",
                    amount=q2(row["amount"]),
                )
            )

        return lines
