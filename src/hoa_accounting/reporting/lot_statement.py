"""Lot Statement — all charges, payments, and adjustments for a lot in a year.

This replaces the GL-based owner ledger for the report console.  Rather than
reading journal_entry_lines it pulls directly from the source tables
(assessments, payments, owner_adjustments) so that every charge billed to the
lot appears regardless of GL posting status.
"""

from __future__ import annotations

import sqlite3

from hoa_accounting.exceptions import NotFoundError
from hoa_accounting.reporting.dto import (
    LotOwnerInfo,
    LotStatementReport,
    LotStatementRow,
    OpeningBalanceLine,
)
from hoa_accounting.validators.common import q2


class LotStatementReportService:
    """Generate a full-year lot statement from source billing tables."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def generate(self, *, lot_id: int, year: int) -> LotStatementReport:
        from_date = f"{year}-01-01"
        to_date = f"{year}-12-31"

        # ── Lot info ──────────────────────────────────────────────────────────
        lot = self.conn.execute(
            """
            SELECT id, lot_number,
                   COALESCE(street_address_1, '') AS street_address_1
            FROM lots WHERE id = ?
            """,
            (lot_id,),
        ).fetchone()
        if lot is None:
            raise NotFoundError(f"Lot {lot_id} not found.")

        lot_number = str(lot["lot_number"])
        lot_address = str(lot["street_address_1"])

        # All current owners with full contact details
        owner_rows = self.conn.execute(
            """
            SELECT
                o.display_name,
                COALESCE(o.first_name, '')  AS first_name,
                COALESCE(o.last_name, '')   AS last_name,
                COALESCE(o.email, '')       AS email,
                COALESCE(o.phone, '')       AS phone
            FROM lot_ownership lo
            JOIN owners o ON o.id = lo.owner_id
            WHERE lo.lot_id = ? AND lo.end_date IS NULL
            ORDER BY lo.id ASC
            """,
            (lot_id,),
        ).fetchall()
        owners = [
            LotOwnerInfo(
                display_name=str(r["display_name"]),
                first_name=str(r["first_name"]),
                last_name=str(r["last_name"]),
                email=str(r["email"]),
                phone=str(r["phone"]),
            )
            for r in owner_rows
        ]

        # ── Pre-system opening balance ────────────────────────────────────────
        # Amounts entered on the Opening Balances page represent AR that existed
        # before the system was set up (not captured in assessments/payments).
        ob_presystem = self.conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN entity_type='LOT_DUES'       THEN amount ELSE 0 END), 0) AS dues_amount,
                COALESCE(SUM(CASE WHEN entity_type='LOT_ASSESSMENT'  THEN amount ELSE 0 END), 0) AS assess_amount
            FROM opening_balances
            WHERE entity_id = ? AND entity_type IN ('LOT_DUES', 'LOT_ASSESSMENT')
            """,
            (lot_id,),
        ).fetchone()
        presystem_dues = q2(ob_presystem["dues_amount"] if ob_presystem else 0)
        presystem_assess = q2(ob_presystem["assess_amount"] if ob_presystem else 0)
        presystem_total = presystem_dues + presystem_assess

        # ── Opening balance ───────────────────────────────────────────────────
        # = pre-system balance + charges before this year (non-voided assessments
        #   + adjustments that add charges) minus payments applied before this
        #   year minus credit/write-off adjustments before this year.
        ob_row = self.conn.execute(
            """
            SELECT
                COALESCE((
                    SELECT SUM(a.amount)
                    FROM assessments a
                    WHERE a.lot_id = ?
                      AND a.assessment_date < ?
                      AND a.status NOT IN ('VOID')
                ), 0)
                -
                COALESCE((
                    SELECT SUM(pa.applied_amount)
                    FROM payment_applications pa
                    JOIN payments p ON p.id = pa.payment_id
                    JOIN assessments a ON a.id = pa.assessment_id
                    WHERE a.lot_id = ?
                      AND p.payment_date < ?
                ), 0)
                -
                COALESCE((
                    SELECT SUM(oa.amount)
                    FROM owner_adjustments oa
                    WHERE oa.lot_id = ?
                      AND oa.adjustment_date < ?
                      AND oa.adjustment_type IN ('CREDIT_MEMO', 'WRITE_OFF')
                ), 0)
                AS opening_balance
            """,
            (lot_id, from_date, lot_id, from_date, lot_id, from_date),
        ).fetchone()
        opening_balance = q2(
            (ob_row["opening_balance"] if ob_row else 0) + presystem_total
        )

        # ── Opening balance breakdown by charge type ──────────────────────────
        # Net balance per charge type = billed before year - payments applied
        # before year, then credit/write-off adjustments shown as a single line.
        ob_detail_rows = self.conn.execute(
            """
            SELECT
                a.charge_type,
                COALESCE(SUM(a.amount), 0)
                  - COALESCE(SUM(pa_pre.applied), 0) AS net_balance
            FROM assessments a
            LEFT JOIN (
                SELECT pa.assessment_id, SUM(pa.applied_amount) AS applied
                FROM payment_applications pa
                JOIN payments p ON p.id = pa.payment_id
                WHERE p.payment_date < ?
                GROUP BY pa.assessment_id
            ) pa_pre ON pa_pre.assessment_id = a.id
            WHERE a.lot_id = ?
              AND a.assessment_date < ?
              AND a.status NOT IN ('VOID')
            GROUP BY a.charge_type
            HAVING COALESCE(SUM(a.amount), 0) - COALESCE(SUM(pa_pre.applied), 0) != 0

            UNION ALL

            SELECT
                'ADJUSTMENT' AS charge_type,
                -COALESCE(SUM(amount), 0) AS net_balance
            FROM owner_adjustments
            WHERE lot_id = ?
              AND adjustment_date < ?
              AND adjustment_type IN ('CREDIT_MEMO', 'WRITE_OFF')
            HAVING COALESCE(SUM(amount), 0) != 0
            """,
            (from_date, lot_id, from_date, lot_id, from_date),
        ).fetchall()

        _charge_labels = {
            "DUES": "Dues",
            "LATE_FEE": "Late Fees",
            "LEGAL_FEE": "Legal Fees",
            "ADJUSTMENT": "Adjustments / Credits",
        }

        # Pre-system lines first, then in-system calculated lines
        opening_balance_lines: list[OpeningBalanceLine] = []
        if presystem_dues:
            opening_balance_lines.append(
                OpeningBalanceLine(
                    charge_type="OB_DUES",
                    label="Prior Balance — Dues",
                    amount=presystem_dues,
                )
            )
        if presystem_assess:
            opening_balance_lines.append(
                OpeningBalanceLine(
                    charge_type="OB_ASSESSMENT",
                    label="Prior Balance — Assessment",
                    amount=presystem_assess,
                )
            )
        opening_balance_lines += [
            OpeningBalanceLine(
                charge_type=str(r["charge_type"]),
                label=_charge_labels.get(str(r["charge_type"]), str(r["charge_type"])),
                amount=q2(r["net_balance"]),
            )
            for r in ob_detail_rows
        ]

        # ── In-period transactions ────────────────────────────────────────────
        raw_rows = self.conn.execute(
            """
            SELECT
                entry_date,
                entry_type,
                charge_type,
                description,
                due_date,
                debit_amount,
                credit_amount,
                status,
                receipt_number,
                sort_key
            FROM (

                -- Charges (assessments)
                SELECT
                    a.assessment_date     AS entry_date,
                    'CHARGE'              AS entry_type,
                    a.charge_type         AS charge_type,
                    a.description         AS description,
                    a.due_date            AS due_date,
                    a.amount              AS debit_amount,
                    0                     AS credit_amount,
                    a.status              AS status,
                    ''                    AS receipt_number,
                    a.assessment_date || '0' || CAST(a.id AS TEXT) AS sort_key
                FROM assessments a
                WHERE a.lot_id = ?
                  AND a.assessment_date >= ?
                  AND a.assessment_date <= ?
                  AND a.status NOT IN ('VOID')

                UNION ALL

                -- Payments (summed per payment across all applications to this lot)
                SELECT
                    p.payment_date        AS entry_date,
                    'PAYMENT'             AS entry_type,
                    'PAYMENT'             AS charge_type,
                    p.payment_method
                      || CASE WHEN p.receipt_number IS NOT NULL
                              THEN ' · Receipt ' || p.receipt_number
                              ELSE '' END AS description,
                    ''                    AS due_date,
                    0                     AS debit_amount,
                    SUM(pa.applied_amount) AS credit_amount,
                    ''                    AS status,
                    COALESCE(p.receipt_number, '') AS receipt_number,
                    p.payment_date || '1' || CAST(p.id AS TEXT) AS sort_key
                FROM payments p
                JOIN payment_applications pa ON pa.payment_id = p.id
                JOIN assessments a          ON a.id = pa.assessment_id
                WHERE a.lot_id = ?
                  AND p.payment_date >= ?
                  AND p.payment_date <= ?
                GROUP BY p.id, p.payment_date, p.payment_method,
                         p.receipt_number, p.reference_number

                UNION ALL

                -- Owner adjustments
                SELECT
                    oa.adjustment_date    AS entry_date,
                    'ADJUSTMENT'          AS entry_type,
                    oa.adjustment_type    AS charge_type,
                    oa.description        AS description,
                    ''                    AS due_date,
                    CASE WHEN oa.adjustment_type NOT IN ('CREDIT_MEMO', 'WRITE_OFF')
                         THEN oa.amount ELSE 0 END AS debit_amount,
                    CASE WHEN oa.adjustment_type IN ('CREDIT_MEMO', 'WRITE_OFF')
                         THEN oa.amount ELSE 0 END AS credit_amount,
                    ''                    AS status,
                    ''                    AS receipt_number,
                    oa.adjustment_date || '2' || CAST(oa.id AS TEXT) AS sort_key
                FROM owner_adjustments oa
                WHERE oa.lot_id = ?
                  AND oa.adjustment_date >= ?
                  AND oa.adjustment_date <= ?

            ) combined
            ORDER BY sort_key
            """,
            (
                lot_id,
                from_date,
                to_date,  # assessments
                lot_id,
                from_date,
                to_date,  # payments
                lot_id,
                from_date,
                to_date,  # adjustments
            ),
        ).fetchall()

        running_balance = opening_balance
        report_rows: list[LotStatementRow] = []

        for row in raw_rows:
            debit = q2(row["debit_amount"])
            credit = q2(row["credit_amount"])
            running_balance = q2(running_balance + debit - credit)
            report_rows.append(
                LotStatementRow(
                    entry_date=str(row["entry_date"]),
                    entry_type=str(row["entry_type"]),
                    charge_type=str(row["charge_type"]),
                    description=str(row["description"]),
                    due_date=str(row["due_date"]),
                    debit_amount=debit,
                    credit_amount=credit,
                    running_balance=running_balance,
                    status=str(row["status"]),
                    receipt_number=str(row["receipt_number"]),
                )
            )

        return LotStatementReport(
            lot_id=lot_id,
            lot_number=lot_number,
            lot_address=lot_address,
            owners=owners,
            year=year,
            from_date=from_date,
            to_date=to_date,
            opening_balance=opening_balance,
            opening_balance_lines=opening_balance_lines,
            closing_balance=running_balance,
            rows=report_rows,
        )
