"""Unapplied-credit auto-application service.

When an owner pays in advance — or pays more than the current balance —
the surplus sits as unapplied credit on those payment records.  This
service drains that credit onto a newly created (or existing open)
assessment so the ledger self-balances without treasurer intervention.

Typical trigger
---------------
``AssessmentService.post_assessment`` calls
``CreditService.auto_apply_to_assessment`` immediately after inserting
the assessment row.  If the owner had advance payments on file, they
are consumed oldest-first up to the full assessment amount, and the
assessment status is updated to PAID or PARTIAL accordingly.

Retro-apply
-----------
``CreditService.retro_apply_all`` sweeps every owner with unapplied
credit and re-runs the application logic against all of their open /
partial assessments.  Run once after enabling this feature to catch
any payments that pre-date the code change.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal

from hoa_accounting.repositories.assessments_repo import AssessmentsRepository
from hoa_accounting.repositories.payments_repo import PaymentsRepository
from hoa_accounting.validators.common import q2


@dataclass(frozen=True)
class CreditApplication:
    """Record of one credit → assessment link created by the service."""

    payment_id: int
    assessment_id: int
    applied_amount: Decimal


@dataclass
class RetroResult:
    """Summary returned by ``retro_apply_all``."""

    owners_processed: int = 0
    applications_created: int = 0
    total_applied: Decimal = field(default_factory=lambda: Decimal("0.00"))
    details: list[CreditApplication] = field(default_factory=list)


class CreditService:
    """Apply unapplied payment credits to assessments."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        payments_repo: PaymentsRepository,
        assessments_repo: AssessmentsRepository,
    ) -> None:
        self.conn = conn
        self.payments_repo = payments_repo
        self.assessments_repo = assessments_repo

    # ── Forward apply (called at assessment creation time) ────────────────────

    def auto_apply_to_assessment(
        self,
        *,
        assessment_id: int,
        owner_id: int,
        assessment_amount: Decimal,
    ) -> Decimal:
        """Apply any unapplied owner credits to a newly created assessment.

        Drains credits oldest-first until the assessment is fully covered
        or credits are exhausted.  Returns the total amount applied.
        The assessment status is updated to PAID or PARTIAL if any credit
        was applied; callers must ensure they are inside an open transaction.
        """
        credits = self.payments_repo.get_unapplied_credits_for_owner(owner_id)
        if not credits:
            return Decimal("0.00")

        remaining_due = q2(assessment_amount)
        total_applied = Decimal("0.00")

        for credit in credits:
            if remaining_due <= Decimal("0.00"):
                break
            unapplied = q2(credit["unapplied_amount"])
            if unapplied <= Decimal("0.00"):
                continue
            apply_amount = min(unapplied, remaining_due)
            self.payments_repo.insert_payment_application(
                payment_id=int(credit["id"]),
                assessment_id=assessment_id,
                applied_amount=str(apply_amount),
            )
            remaining_due -= apply_amount
            total_applied += apply_amount

        if total_applied > Decimal("0.00"):
            new_status = "PAID" if remaining_due <= Decimal("0.00") else "PARTIAL"
            self.assessments_repo.update_status(assessment_id, new_status)

        return total_applied

    # ── Retro-apply (one-time sweep for pre-existing data) ───────────────────

    def retro_apply_all(self) -> RetroResult:
        """Sweep every owner with unapplied credit and apply it to their
        open / partial assessments, oldest assessment first.

        Safe to run multiple times — ``INSERT OR IGNORE`` on the unique
        ``(payment_id, assessment_id)`` index means re-runs are no-ops
        for already-applied pairs.  Returns a summary of what changed.
        """
        result = RetroResult()

        # Find every owner who has at least one payment with unapplied balance.
        owner_ids = [row[0] for row in self.conn.execute("""
                SELECT DISTINCT p.owner_id
                FROM payments p
                LEFT JOIN payment_applications pa ON pa.payment_id = p.id
                GROUP BY p.id, p.owner_id, p.amount
                HAVING p.amount - COALESCE(SUM(pa.applied_amount), 0) > 0.005
                ORDER BY p.owner_id
                """).fetchall()]

        for owner_id in owner_ids:
            applied = self._apply_credits_to_open_assessments(owner_id, result)
            if applied > Decimal("0.00"):
                result.owners_processed += 1

        return result

    def _apply_credits_to_open_assessments(
        self, owner_id: int, result: RetroResult
    ) -> Decimal:
        """Apply all unapplied credits for one owner to their open assessments."""
        credits = self.payments_repo.get_unapplied_credits_for_owner(owner_id)
        if not credits:
            return Decimal("0.00")

        open_assessments = self.assessments_repo.list_open_for_owner(owner_id)
        if not open_assessments:
            return Decimal("0.00")

        total_applied = Decimal("0.00")

        for assessment in open_assessments:
            assessment_id = int(assessment["id"])
            outstanding = q2(assessment["amount"]) - q2(assessment["already_applied"])
            if outstanding <= Decimal("0.00"):
                continue

            for credit in credits:
                if outstanding <= Decimal("0.00"):
                    break
                unapplied = q2(credit["unapplied_amount"])
                if unapplied <= Decimal("0.00"):
                    continue

                apply_amount = min(unapplied, outstanding)

                # INSERT OR IGNORE — safe to re-run
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO payment_applications
                        (payment_id, assessment_id, applied_amount)
                    VALUES (?, ?, ?)
                    """,
                    (int(credit["id"]), assessment_id, str(apply_amount)),
                )
                # Reflect applied amount in the in-memory credit dict
                credit["unapplied_amount"] = str(
                    q2(credit["unapplied_amount"]) - apply_amount
                )
                outstanding -= apply_amount
                total_applied += apply_amount

                app = CreditApplication(
                    payment_id=int(credit["id"]),
                    assessment_id=assessment_id,
                    applied_amount=apply_amount,
                )
                result.applications_created += 1
                result.total_applied += apply_amount
                result.details.append(app)

            # Recompute status from the DB after applying
            already = self.conn.execute(
                "SELECT COALESCE(SUM(applied_amount),0) FROM payment_applications "
                "WHERE assessment_id=?",
                (assessment_id,),
            ).fetchone()[0]
            full_amount = q2(assessment["amount"])
            new_status = (
                "PAID"
                if q2(already) >= full_amount
                else "PARTIAL" if q2(already) > Decimal("0.00") else "OPEN"
            )
            self.assessments_repo.update_status(assessment_id, new_status)

        return total_applied
