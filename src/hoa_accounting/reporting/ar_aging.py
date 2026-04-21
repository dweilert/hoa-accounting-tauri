"""Accounts receivable aging report."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from hoa_accounting.reporting.dto import (
    ARAgingDetailRow,
    ARAgingOwnerSummary,
    ARAgingReport,
)
from hoa_accounting.validators.common import q2


@dataclass
class _OwnerAgingAccumulator:
    owner_id: int
    owner_name: str
    current_amount: Decimal = Decimal("0.00")
    amount_1_30: Decimal = Decimal("0.00")
    amount_31_60: Decimal = Decimal("0.00")
    amount_61_90: Decimal = Decimal("0.00")
    amount_90_plus: Decimal = Decimal("0.00")
    total_open_amount: Decimal = Decimal("0.00")
    credit_balance: Decimal = Decimal("0.00")
    ledger_balance: Decimal = Decimal("0.00")

    def to_summary(self) -> ARAgingOwnerSummary:
        return ARAgingOwnerSummary(
            owner_id=self.owner_id,
            owner_name=self.owner_name,
            current_amount=q2(self.current_amount),
            amount_1_30=q2(self.amount_1_30),
            amount_31_60=q2(self.amount_31_60),
            amount_61_90=q2(self.amount_61_90),
            amount_90_plus=q2(self.amount_90_plus),
            total_open_amount=q2(self.total_open_amount),
            credit_balance=q2(self.credit_balance),
            ledger_balance=q2(self.ledger_balance),
        )


class ARAgingReportService:
    """Produce owner-level AR aging from open assessment items."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def generate(
        self,
        *,
        as_of_date: str,
        receivable_account_id: int | None = None,
    ) -> ARAgingReport:
        """Generate AR aging as of a date from open assessments."""
        detail_rows = self._load_open_items(as_of_date=as_of_date)
        owner_accumulators: dict[int, _OwnerAgingAccumulator] = {}

        for row in detail_rows:
            acc = owner_accumulators.setdefault(
                row.owner_id,
                _OwnerAgingAccumulator(
                    owner_id=row.owner_id,
                    owner_name=row.owner_name,
                ),
            )
            acc.total_open_amount += row.remaining_amount

            if row.aging_bucket == "CURRENT":
                acc.current_amount += row.remaining_amount
            elif row.aging_bucket == "1-30":
                acc.amount_1_30 += row.remaining_amount
            elif row.aging_bucket == "31-60":
                acc.amount_31_60 += row.remaining_amount
            elif row.aging_bucket == "61-90":
                acc.amount_61_90 += row.remaining_amount
            else:
                acc.amount_90_plus += row.remaining_amount

        owner_summaries = [
            acc.to_summary()
            for acc in sorted(
                owner_accumulators.values(),
                key=lambda item: (item.owner_name.lower(), item.owner_id),
            )
        ]

        total_current_amount = Decimal("0.00")
        total_amount_1_30 = Decimal("0.00")
        total_amount_31_60 = Decimal("0.00")
        total_amount_61_90 = Decimal("0.00")
        total_amount_90_plus = Decimal("0.00")
        total_open_amount = Decimal("0.00")
        total_credit_balance = Decimal("0.00")
        total_ledger_balance = Decimal("0.00")

        for summary in owner_summaries:
            total_current_amount += summary.current_amount
            total_amount_1_30 += summary.amount_1_30
            total_amount_31_60 += summary.amount_31_60
            total_amount_61_90 += summary.amount_61_90
            total_amount_90_plus += summary.amount_90_plus
            total_open_amount += summary.total_open_amount
            total_credit_balance += summary.credit_balance
            total_ledger_balance += summary.ledger_balance

        return ARAgingReport(
            as_of_date=as_of_date,
            receivable_account_id=0,
            receivable_account_number="AR",
            receivable_account_name="Owner Receivables",
            detail_rows=detail_rows,
            owner_summaries=owner_summaries,
            total_current_amount=q2(total_current_amount),
            total_amount_1_30=q2(total_amount_1_30),
            total_amount_31_60=q2(total_amount_31_60),
            total_amount_61_90=q2(total_amount_61_90),
            total_amount_90_plus=q2(total_amount_90_plus),
            total_open_amount=q2(total_open_amount),
            total_credit_balance=q2(total_credit_balance),
            total_ledger_balance=q2(total_ledger_balance),
        )

    def _load_open_items(
        self,
        *,
        as_of_date: str,
    ) -> list[ARAgingDetailRow]:
        rows = self.conn.execute(
            """
            SELECT
                a.id AS assessment_id,
                a.owner_id,
                TRIM(COALESCE(o.first_name, '') || ' ' || COALESCE(o.last_name, '')) AS owner_name,
                a.lot_id,
                l.lot_number,
                a.assessment_date,
                a.due_date,
                a.description,
                a.amount AS original_amount,
                COALESCE(
                    SUM(
                        CASE
                            WHEN p.payment_date <= ? THEN pa.applied_amount
                            ELSE 0
                        END
                    ),
                    0
                ) AS applied_amount
            FROM assessments a
            JOIN owners o ON o.id = a.owner_id
            LEFT JOIN lots l ON l.id = a.lot_id
            LEFT JOIN payment_applications pa ON pa.assessment_id = a.id
            LEFT JOIN payments p ON p.id = pa.payment_id
            WHERE a.assessment_date <= ?
              AND a.status NOT IN ('VOID', 'WRITTEN_OFF')
            GROUP BY
                a.id, a.owner_id, o.first_name, o.last_name, a.lot_id, l.lot_number,
                a.assessment_date, a.due_date, a.description, a.amount
            ORDER BY o.last_name, o.first_name, a.due_date, a.assessment_date, a.id
            """,
            (as_of_date, as_of_date),
        ).fetchall()

        as_of = date.fromisoformat(as_of_date)
        detail_rows: list[ARAgingDetailRow] = []

        for row in rows:
            original_amount = q2(row["original_amount"])
            applied_amount = q2(row["applied_amount"])
            remaining_amount = q2(original_amount - applied_amount)

            if remaining_amount <= Decimal("0.00"):
                continue

            due_date = str(row["due_date"])
            days_past_due, aging_bucket = self._classify_due_date(
                due_date=due_date,
                as_of=as_of,
            )

            detail_rows.append(
                ARAgingDetailRow(
                    owner_id=int(row["owner_id"]),
                    owner_name=str(row["owner_name"]),
                    lot_id=int(row["lot_id"]) if row["lot_id"] is not None else None,
                    lot_number=str(row["lot_number"])
                    if row["lot_number"] is not None
                    else None,
                    assessment_id=int(row["assessment_id"]),
                    assessment_date=str(row["assessment_date"]),
                    due_date=due_date,
                    description=str(row["description"]),
                    original_amount=original_amount,
                    applied_amount=applied_amount,
                    remaining_amount=remaining_amount,
                    days_past_due=days_past_due,
                    aging_bucket=aging_bucket,
                )
            )

        return detail_rows

    def _classify_due_date(self, *, due_date: str, as_of: date) -> tuple[int, str]:
        due = date.fromisoformat(due_date)
        days_past_due = (as_of - due).days

        if days_past_due <= 0:
            return 0, "CURRENT"
        if days_past_due <= 30:
            return days_past_due, "1-30"
        if days_past_due <= 60:
            return days_past_due, "31-60"
        if days_past_due <= 90:
            return days_past_due, "61-90"
        return days_past_due, "90+"