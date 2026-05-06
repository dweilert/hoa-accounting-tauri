"""Accounts-receivable ledger — per-lot balance list and lot detail views."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from http import HTTPStatus
from typing import Any

from hoa_accounting.reporting.lot_statement import LotStatementReportService
from hoa_accounting.validators.common import q2
from hoa_accounting.web.template_engine import render_template


@dataclass
class LotARSummary:
    lot_id: int
    lot_number: str
    lot_address: str
    owners: str
    total_balance: Decimal
    current_amount: Decimal
    amount_1_30: Decimal
    amount_31_60: Decimal
    amount_61_90: Decimal
    amount_90_plus: Decimal
    last_payment_date: str | None


@dataclass(frozen=True)
class ARPageResponse:
    status_code: int
    body_html: str


def _classify_due_date(due_date: str, as_of: date) -> str:
    due = date.fromisoformat(due_date)
    days = (as_of - due).days
    if days <= 0:
        return "CURRENT"
    if days <= 30:
        return "1-30"
    if days <= 60:
        return "31-60"
    if days <= 90:
        return "61-90"
    return "90+"


class ARPages:
    """Render AR list and detail pages."""

    LIST_TEMPLATE = "ar_lots_list.html"
    DETAIL_TEMPLATE = "ar_lot_detail.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def render_list(self, *, org: dict[str, Any], theme: str) -> ARPageResponse:
        today = date.today()

        # Open assessment balances per individual assessment (status-based filter
        # excludes VOID; PAID ones will have remaining=0 and get dropped by HAVING).
        open_rows = self.conn.execute(
            """
            SELECT
                a.lot_id,
                a.due_date,
                a.amount - COALESCE(SUM(pa.applied_amount), 0) AS remaining
            FROM assessments a
            LEFT JOIN payment_applications pa ON pa.assessment_id = a.id
            WHERE a.lot_id IS NOT NULL
              AND a.status NOT IN ('VOID')
            GROUP BY a.id
            HAVING remaining > 0
            """,
        ).fetchall()

        # Accumulate per lot
        lot_acc: dict[int, dict[str, Any]] = {}
        for row in open_rows:
            lot_id = int(row["lot_id"])
            remaining = q2(row["remaining"])
            bucket = _classify_due_date(str(row["due_date"]), today)
            if lot_id not in lot_acc:
                lot_acc[lot_id] = dict(
                    total=Decimal("0"),
                    current=Decimal("0"),
                    b_1_30=Decimal("0"),
                    b_31_60=Decimal("0"),
                    b_61_90=Decimal("0"),
                    b_90_plus=Decimal("0"),
                )
            acc = lot_acc[lot_id]
            acc["total"] += remaining
            if bucket == "CURRENT":
                acc["current"] += remaining
            elif bucket == "1-30":
                acc["b_1_30"] += remaining
            elif bucket == "31-60":
                acc["b_31_60"] += remaining
            elif bucket == "61-90":
                acc["b_61_90"] += remaining
            else:
                acc["b_90_plus"] += remaining

        # Last payment date per lot
        payment_rows = self.conn.execute(
            """
            SELECT a.lot_id, MAX(p.payment_date) AS last_payment_date
            FROM payments p
            JOIN payment_applications pa ON pa.payment_id = p.id
            JOIN assessments a ON a.id = pa.assessment_id
            WHERE a.lot_id IS NOT NULL
            GROUP BY a.lot_id
            """,
        ).fetchall()
        last_payment: dict[int, str] = {
            int(r["lot_id"]): str(r["last_payment_date"]) for r in payment_rows
        }

        # All active lots with current owners (first + last name)
        lot_rows = self.conn.execute(
            """
            SELECT
                l.id AS lot_id,
                l.lot_number,
                GROUP_CONCAT(
                    TRIM(COALESCE(o.first_name, '') || ' ' || COALESCE(o.last_name, '')),
                    ', '
                ) AS owners
            FROM lots l
            LEFT JOIN lot_ownership lo ON lo.lot_id = l.id AND lo.end_date IS NULL
            LEFT JOIN owners o ON o.id = lo.owner_id
            WHERE l.active_flag = 1
            GROUP BY l.id
            ORDER BY l.lot_number
            """,
        ).fetchall()

        summaries: list[LotARSummary] = []
        for lot in lot_rows:
            lot_id = int(lot["lot_id"])
            acc = lot_acc.get(lot_id, {})
            summaries.append(
                LotARSummary(
                    lot_id=lot_id,
                    lot_number=str(lot["lot_number"]),
                    lot_address="",
                    owners=str(lot["owners"] or "—"),
                    total_balance=q2(acc.get("total", Decimal("0"))),
                    current_amount=q2(acc.get("current", Decimal("0"))),
                    amount_1_30=q2(acc.get("b_1_30", Decimal("0"))),
                    amount_31_60=q2(acc.get("b_31_60", Decimal("0"))),
                    amount_61_90=q2(acc.get("b_61_90", Decimal("0"))),
                    amount_90_plus=q2(acc.get("b_90_plus", Decimal("0"))),
                    last_payment_date=last_payment.get(lot_id),
                )
            )

        html = render_template(
            self.LIST_TEMPLATE,
            {
                "org": org,
                "theme": theme,
                "page_key": "ar-lots",
                "active_nav": "ar",
                "breadcrumb": "Receivables",
                "summaries": summaries,
                "as_of_date": today.isoformat(),
                "total_balance": q2(sum(s.total_balance for s in summaries)),
                "total_current": q2(sum(s.current_amount for s in summaries)),
                "total_1_30": q2(sum(s.amount_1_30 for s in summaries)),
                "total_31_60": q2(sum(s.amount_31_60 for s in summaries)),
                "total_61_90": q2(sum(s.amount_61_90 for s in summaries)),
                "total_90_plus": q2(sum(s.amount_90_plus for s in summaries)),
            },
        )
        return ARPageResponse(status_code=HTTPStatus.OK, body_html=html)

    def render_lot_detail(
        self, *, lot_id: int, year: int, org: dict[str, Any], theme: str
    ) -> ARPageResponse:
        from hoa_accounting.exceptions import NotFoundError

        try:
            report = LotStatementReportService(self.conn).generate(
                lot_id=lot_id, year=year
            )
        except NotFoundError as exc:
            html = render_template(
                "error_500.html",
                {
                    "org": org,
                    "theme": theme,
                    "error_message": str(exc),
                },
            )
            return ARPageResponse(status_code=HTTPStatus.NOT_FOUND, body_html=html)

        year_rows = self.conn.execute(
            """
            SELECT DISTINCT CAST(strftime('%Y', assessment_date) AS INTEGER) AS yr
            FROM assessments
            WHERE lot_id = ? AND status != 'VOID'
            ORDER BY yr DESC
            """,
            (lot_id,),
        ).fetchall()
        available_years = [int(r["yr"]) for r in year_rows] or [year]

        # Pre-load bank transactions linked to every payment row in this report.
        bank_txns_by_payment: dict[int, list[dict[str, Any]]] = {}
        payment_ids = [r.payment_id for r in report.rows if r.payment_id is not None]
        if payment_ids:
            placeholders = ",".join("?" * len(payment_ids))
            bt_rows = self.conn.execute(
                f"""
                SELECT btl.ledger_source_id            AS payment_id,
                       bt.id,
                       bt.transaction_date,
                       bt.description,
                       bt.amount,
                       COALESCE(bt.external_reference, '') AS external_reference,
                       COALESCE(bt.transaction_type, '')   AS transaction_type,
                       COALESCE(bt.memo, '')               AS memo,
                       COALESCE(ba.account_name, '')       AS bank_account_name,
                       COALESCE(bib.source_filename, '')   AS source_filename
                FROM bank_transactions bt
                JOIN bank_transaction_links btl
                  ON btl.bank_transaction_id = bt.id
                 AND btl.ledger_source_type   = 'PAYMENT'
                 AND btl.ledger_source_id     IN ({placeholders})
                LEFT JOIN bank_accounts ba
                  ON ba.id = bt.bank_account_id
                LEFT JOIN bank_import_batches bib
                  ON bib.id = bt.import_batch_id
                ORDER BY bt.transaction_date
                """,
                payment_ids,
            ).fetchall()
            for bt in bt_rows:
                pid = int(bt["payment_id"])
                bank_txns_by_payment.setdefault(pid, []).append(dict(bt))

        # Pre-load deposit batch info for payments that came through a batch.
        deposit_batches_by_payment: dict[int, dict[str, Any]] = {}
        batch_ids = list(
            {r.deposit_batch_id for r in report.rows if r.deposit_batch_id is not None}
        )
        if batch_ids:
            b_placeholders = ",".join("?" * len(batch_ids))
            db_rows = self.conn.execute(
                f"""
                SELECT db.id              AS batch_id,
                       db.deposit_date,
                       db.total_amount    AS batch_total,
                       db.posting_status,
                       COALESCE(ba.account_name, '') AS bank_account_name,
                       (SELECT COUNT(*) FROM payments p2
                        WHERE p2.deposit_batch_id = db.id)  AS payment_count,
                       (SELECT COUNT(*) FROM income_batches ib
                        WHERE ib.deposit_batch_id = db.id)  AS income_count,
                       bt.id              AS bt_id,
                       bt.transaction_date AS bt_date,
                       COALESCE(bt.description, '')         AS bt_description,
                       bt.amount          AS bt_amount,
                       COALESCE(bt.external_reference, '')  AS bt_fitid,
                       COALESCE(bt.transaction_type, '')    AS bt_type,
                       COALESCE(bib.source_filename, '')    AS bt_source_file
                FROM deposit_batches db
                LEFT JOIN bank_accounts ba ON ba.id = db.bank_account_id
                LEFT JOIN bank_transactions bt
                  ON bt.matched_source_type = 'DEPOSIT_BATCH'
                 AND bt.matched_source_id   = db.id
                LEFT JOIN bank_import_batches bib ON bib.id = bt.import_batch_id
                WHERE db.id IN ({b_placeholders})
                """,
                batch_ids,
            ).fetchall()
            batch_info: dict[int, dict[str, Any]] = {
                int(r["batch_id"]): dict(r) for r in db_rows
            }
            # Map payment_id → batch info
            for row in report.rows:
                if row.deposit_batch_id is not None and row.payment_id is not None:
                    info = batch_info.get(row.deposit_batch_id)
                    if info:
                        deposit_batches_by_payment[row.payment_id] = info

            # Load every payment line in each batch so the template can
            # render the full batch roster and highlight this lot's line.
            bp_rows = self.conn.execute(
                f"""
                SELECT p.deposit_batch_id          AS batch_id,
                       p.id                        AS payment_id,
                       p.amount,
                       p.payment_method,
                       COALESCE(p.receipt_number, '') AS receipt_number,
                       o.display_name              AS owner_name,
                       COALESCE(l.lot_number, '—') AS lot_number,
                       COALESCE(l.id, 0)           AS lot_id
                FROM payments p
                JOIN owners o ON o.id = p.owner_id
                LEFT JOIN lot_ownership lo
                  ON lo.owner_id = o.id AND lo.end_date IS NULL
                LEFT JOIN lots l ON l.id = lo.lot_id
                WHERE p.deposit_batch_id IN ({b_placeholders})
                ORDER BY l.lot_number NULLS LAST, p.receipt_number
                """,
                batch_ids,
            ).fetchall()
            batch_payments: dict[int, list[dict[str, Any]]] = {}
            for bp in bp_rows:
                bid = int(bp["batch_id"])
                batch_payments.setdefault(bid, []).append(dict(bp))
        else:
            batch_payments = {}

        html = render_template(
            self.DETAIL_TEMPLATE,
            {
                "org": org,
                "theme": theme,
                "page_key": "ar-lots",
                "active_nav": "ar",
                "breadcrumb": "Receivables",
                "report": report,
                "year": year,
                "available_years": available_years,
                "bank_txns_by_payment": bank_txns_by_payment,
                "deposit_batches_by_payment": deposit_batches_by_payment,
                "batch_payments": batch_payments,
            },
        )
        return ARPageResponse(status_code=HTTPStatus.OK, body_html=html)

    def render_delinquency_report(
        self, *, org: dict[str, Any], theme: str
    ) -> ARPageResponse:
        """Board-ready delinquency report: only lots with balance > 0, worst bucket first."""
        today = date.today()
        open_rows = self.conn.execute(
            """
            SELECT
                a.lot_id,
                a.due_date,
                a.amount - COALESCE(SUM(pa.applied_amount), 0) AS remaining
            FROM assessments a
            LEFT JOIN payment_applications pa ON pa.assessment_id = a.id
            WHERE a.lot_id IS NOT NULL
              AND a.status NOT IN ('VOID')
            GROUP BY a.id
            HAVING remaining > 0
            """,
        ).fetchall()

        lot_acc: dict[int, dict[str, Any]] = {}
        for row in open_rows:
            lot_id = int(row["lot_id"])
            remaining = q2(row["remaining"])
            bucket = _classify_due_date(str(row["due_date"]), today)
            if lot_id not in lot_acc:
                lot_acc[lot_id] = dict(
                    total=Decimal("0"),
                    current=Decimal("0"),
                    b_1_30=Decimal("0"),
                    b_31_60=Decimal("0"),
                    b_61_90=Decimal("0"),
                    b_90_plus=Decimal("0"),
                )
            acc = lot_acc[lot_id]
            acc["total"] += remaining
            if bucket == "CURRENT":
                acc["current"] += remaining
            elif bucket == "1-30":
                acc["b_1_30"] += remaining
            elif bucket == "31-60":
                acc["b_31_60"] += remaining
            elif bucket == "61-90":
                acc["b_61_90"] += remaining
            else:
                acc["b_90_plus"] += remaining

        payment_rows = self.conn.execute(
            """
            SELECT a.lot_id, MAX(p.payment_date) AS last_payment_date
            FROM payments p
            JOIN payment_applications pa ON pa.payment_id = p.id
            JOIN assessments a ON a.id = pa.assessment_id
            WHERE a.lot_id IS NOT NULL
            GROUP BY a.lot_id
            """,
        ).fetchall()
        last_payment: dict[int, str] = {
            int(r["lot_id"]): str(r["last_payment_date"]) for r in payment_rows
        }

        lot_rows = self.conn.execute(
            """
            SELECT l.id AS lot_id, l.lot_number,
                   GROUP_CONCAT(
                       TRIM(COALESCE(o.first_name, '') || ' ' || COALESCE(o.last_name, '')), ', '
                   ) AS owners
            FROM lots l
            LEFT JOIN lot_ownership lo ON lo.lot_id = l.id AND lo.end_date IS NULL
            LEFT JOIN owners o ON o.id = lo.owner_id
            WHERE l.active_flag = 1
            GROUP BY l.id
            """,
        ).fetchall()

        summaries: list[LotARSummary] = []
        for lot in lot_rows:
            lot_id = int(lot["lot_id"])
            acc_opt = lot_acc.get(lot_id)
            if acc_opt is None or acc_opt["total"] <= Decimal("0"):
                continue
            acc = acc_opt
            summaries.append(
                LotARSummary(
                    lot_id=lot_id,
                    lot_number=str(lot["lot_number"]),
                    lot_address="",
                    owners=str(lot["owners"] or "—"),
                    total_balance=q2(acc["total"]),
                    current_amount=q2(acc["current"]),
                    amount_1_30=q2(acc["b_1_30"]),
                    amount_31_60=q2(acc["b_31_60"]),
                    amount_61_90=q2(acc["b_61_90"]),
                    amount_90_plus=q2(acc["b_90_plus"]),
                    last_payment_date=last_payment.get(lot_id),
                )
            )

        summaries.sort(
            key=lambda s: (
                -s.amount_90_plus,
                -s.amount_61_90,
                -s.amount_31_60,
                -s.amount_1_30,
                -s.current_amount,
            )
        )

        html = render_template(
            "delinquency_report.html",
            {
                "org": org,
                "theme": theme,
                "page_key": "delinquency-report",
                "active_nav": "ar",
                "breadcrumb": "Receivables",
                "summaries": summaries,
                "as_of_date": today.isoformat(),
                "delinquent_count": len(summaries),
                "total_balance": q2(sum(s.total_balance for s in summaries)),
                "total_current": q2(sum(s.current_amount for s in summaries)),
                "total_1_30": q2(sum(s.amount_1_30 for s in summaries)),
                "total_31_60": q2(sum(s.amount_31_60 for s in summaries)),
                "total_61_90": q2(sum(s.amount_61_90 for s in summaries)),
                "total_90_plus": q2(sum(s.amount_90_plus for s in summaries)),
            },
        )
        return ARPageResponse(status_code=HTTPStatus.OK, body_html=html)
