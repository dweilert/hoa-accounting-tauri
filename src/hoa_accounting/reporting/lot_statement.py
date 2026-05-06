"""Lot Statement — all charges, payments, and adjustments for a lot in a year.

This replaces the GL-based owner ledger for the report console.  Rather than
reading journal_entry_lines it pulls directly from the source tables
(assessments, payments, owner_adjustments) so that every charge billed to the
lot appears regardless of GL posting status.
"""

from __future__ import annotations

import sqlite3
from typing import Any

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

    def generate(
        self, *, lot_id: int, year: int, owner_id: int | None = None
    ) -> LotStatementReport:
        from_date = f"{year}-01-01"
        to_date = f"{year}-12-31"

        # ── Owner period (when owner_id supplied) ─────────────────────────────
        owner_name: str | None = None
        owner_period_start: str | None = None
        owner_period_end: str | None = None
        # Effective date window for transactions and opening balance cutoff.
        # Defaults to full year; narrowed when owner_id is provided.
        tx_from = from_date
        tx_to = to_date
        ob_cutoff = from_date  # "before this date" cutoff for opening balance

        if owner_id is not None:
            lo_row = self.conn.execute(
                """
                SELECT lo.start_date, lo.end_date,
                       CASE WHEN o.first_name IS NOT NULL OR o.last_name IS NOT NULL
                            THEN TRIM(COALESCE(o.first_name,'') || ' ' || COALESCE(o.last_name,''))
                            ELSE o.display_name END AS owner_name
                FROM lot_ownership lo
                JOIN owners o ON o.id = lo.owner_id
                WHERE lo.lot_id = ? AND lo.owner_id = ?
                  AND lo.start_date <= ?
                  AND (lo.end_date IS NULL OR lo.end_date >= ?)
                ORDER BY lo.start_date DESC
                LIMIT 1
                """,
                (lot_id, owner_id, to_date, from_date),
            ).fetchone()
            if lo_row is None:
                raise NotFoundError(
                    f"Owner {owner_id} has no ownership record for lot {lot_id} in {year}."
                )
            owner_name = str(lo_row["owner_name"])
            raw_end = lo_row["end_date"]
            # Clamp start and end to the report year
            tx_from = max(str(lo_row["start_date"]), from_date)
            tx_to = min(str(raw_end), to_date) if raw_end is not None else to_date
            owner_period_start = tx_from
            owner_period_end = tx_to if raw_end is not None else None
            ob_cutoff = tx_from

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
                CASE WHEN o.first_name IS NOT NULL OR o.last_name IS NOT NULL
                     THEN TRIM(COALESCE(o.first_name,'') || ' ' || COALESCE(o.last_name,''))
                     ELSE o.display_name END AS display_name,
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
            (lot_id, ob_cutoff, lot_id, ob_cutoff, lot_id, ob_cutoff),
        ).fetchone()
        opening_balance = q2(
            (ob_row["opening_balance"] if ob_row else 0) + presystem_total
        )

        # ── Opening balance breakdown by charge type ──────────────────────────
        # Net balance per charge type = billed before year - payments applied
        # before year, then credit/write-off adjustments shown as a single line.
        _ob_owner_filter = "AND a.owner_id = ?" if owner_id is not None else ""
        _ob_params_assess = (
            (ob_cutoff, lot_id, owner_id, ob_cutoff)
            if owner_id is not None
            else (ob_cutoff, lot_id, ob_cutoff)
        )
        ob_detail_rows = self.conn.execute(
            f"""
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
              {_ob_owner_filter}
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
            _ob_params_assess + (lot_id, ob_cutoff),
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
        # Charges: filter to this owner's assessments only.
        #
        # Payments: query directly from the payments table keyed on owner,
        # NOT through payment_applications.  This ensures fully-unapplied
        # advance payments (e.g. Ron Lindsey's $1,860 year-in-advance) appear
        # with their full cheque amount rather than just the applied slice.
        #
        # When owner_id is None: show all payments by ANY owner linked to
        # this lot (via lot_ownership) during the date window.
        #
        # When owner_id is set: show
        #   (a) payments made by THIS owner during their period, AND
        #   (b) payments by OTHER owners that were applied to pre-period lot
        #       assessments — these cleared the inherited opening balance and
        #       must appear so the running balance stays correct.
        _assess_owner_filter = "AND a.owner_id = ?" if owner_id is not None else ""

        # Build param tuples for each branch
        _assess_params: tuple[Any, ...] = (
            (lot_id, owner_id, tx_from, tx_to)
            if owner_id is not None
            else (lot_id, tx_from, tx_to)
        )

        if owner_id is not None:
            # (a) this owner's own payments + (b) other-owner payments that
            # cleared pre-period assessments for this lot
            _pay_owner_filter = (
                "AND ( p.owner_id = ?"
                "    OR p.id IN ("
                "         SELECT pa2.payment_id"
                "         FROM payment_applications pa2"
                "         JOIN assessments a2 ON a2.id = pa2.assessment_id"
                "         WHERE a2.lot_id = ? AND a2.assessment_date < ?"
                "       )"
                "    )"
            )
            _pay_params: tuple[Any, ...] = (owner_id, lot_id, tx_from, tx_from, tx_to)
        else:
            # All payments by any owner ever linked to this lot
            _pay_owner_filter = (
                "AND p.owner_id IN ("
                "    SELECT DISTINCT lo2.owner_id FROM lot_ownership lo2"
                "    WHERE lo2.lot_id = ?"
                ")"
            )
            _pay_params = (lot_id, tx_from, tx_to)
        _adj_params: tuple[Any, ...] = (lot_id, tx_from, tx_to)

        raw_rows = self.conn.execute(
            f"""
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
                payment_id,
                deposit_batch_id,
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
                    NULL                  AS payment_id,
                    NULL                  AS deposit_batch_id,
                    a.assessment_date || '0' || CAST(a.id AS TEXT) AS sort_key
                FROM assessments a
                WHERE a.lot_id = ?
                  {_assess_owner_filter}
                  AND a.assessment_date >= ?
                  AND a.assessment_date <= ?
                  AND a.status NOT IN ('VOID')

                UNION ALL

                -- Payments — full cheque amount, keyed on owner not applications.
                -- Unapplied advance payments show their full amount immediately.
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
                    p.amount              AS credit_amount,
                    'POSTED'              AS status,
                    COALESCE(p.receipt_number, '') AS receipt_number,
                    p.id                  AS payment_id,
                    p.deposit_batch_id    AS deposit_batch_id,
                    p.payment_date || '1' || CAST(p.id AS TEXT) AS sort_key
                FROM payments p
                WHERE 1=1
                  {_pay_owner_filter}
                  AND p.payment_date >= ?
                  AND p.payment_date <= ?

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
                    'POSTED'              AS status,
                    ''                    AS receipt_number,
                    NULL                  AS payment_id,
                    NULL                  AS deposit_batch_id,
                    oa.adjustment_date || '2' || CAST(oa.id AS TEXT) AS sort_key
                FROM owner_adjustments oa
                WHERE oa.lot_id = ?
                  AND oa.adjustment_date >= ?
                  AND oa.adjustment_date <= ?

            ) combined
            ORDER BY sort_key
            """,
            _assess_params + _pay_params + _adj_params,
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
                    payment_id=(
                        int(row["payment_id"])
                        if row["payment_id"] is not None
                        else None
                    ),
                    deposit_batch_id=(
                        int(row["deposit_batch_id"])
                        if row["deposit_batch_id"] is not None
                        else None
                    ),
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
            owner_id=owner_id,
            owner_name=owner_name,
            owner_period_start=owner_period_start,
            owner_period_end=owner_period_end,
        )
