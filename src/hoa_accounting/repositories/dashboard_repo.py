"""Repository for dashboard data: financial summary, cards, layout, HOA profile."""

from __future__ import annotations
from typing import Any

import sqlite3
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class BankTile:
    account_name: str
    fund_code: str
    balance: Decimal
    account_type: str


@dataclass
class ReconciliationTile:
    account_name: str
    ending_date: str
    ending_balance: Decimal
    status: str


@dataclass
class BudgetTile:
    fiscal_year: int
    total_budget: Decimal
    actual_spent: Decimal

    @property
    def pct_used(self) -> float:
        if not self.total_budget:
            return 0.0
        return float(self.actual_spent / self.total_budget * 100)

    @property
    def remaining(self) -> Decimal:
        return self.total_budget - self.actual_spent


@dataclass
class BudgetCategoryTile:
    fiscal_year: int
    total_budget: Decimal
    actual_spent: Decimal
    over_budget: int  # number of expense categories where actual > budget
    under_budget: int  # number of expense categories where actual <= budget

    @property
    def pct_used(self) -> float:
        if not self.total_budget:
            return 0.0
        return float(self.actual_spent / self.total_budget * 100)


def _fiscal_year_range(fiscal_year: int, fy_start_month: int = 1) -> tuple[str, str]:
    """Return (start_date, end_date) ISO strings spanning a fiscal year."""
    fy_start = f"{fiscal_year}-{fy_start_month:02d}-01"
    if fy_start_month == 1:
        return fy_start, f"{fiscal_year}-12-31"
    import calendar as _cal

    end_year = fiscal_year + 1
    end_month = fy_start_month - 1
    last_day = _cal.monthrange(end_year, end_month)[1]
    return fy_start, f"{end_year}-{end_month:02d}-{last_day:02d}"


class DashboardRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── HOA Profile ────────────────────────────────────────────────────

    def get_hoa_profile(self) -> sqlite3.Row | None:
        return self._conn.execute(  # type: ignore[no-any-return]
            "SELECT * FROM hoa_profile LIMIT 1"
        ).fetchone()

    def save_hoa_profile(
        self,
        legal_name: str,
        display_name: str,
        theme: str = "warm",
        default_assessment_amount: str = "0.00",
        default_billing_frequency: str = "annual",
    ) -> None:
        existing = self._conn.execute("SELECT id FROM hoa_profile LIMIT 1").fetchone()
        if existing:
            self._conn.execute(
                "UPDATE hoa_profile SET legal_name=?, display_name=?, theme=?, "
                "default_assessment_amount=?, default_billing_frequency=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (
                    legal_name,
                    display_name,
                    theme,
                    default_assessment_amount,
                    default_billing_frequency,
                    existing["id"],
                ),
            )
        else:
            self._conn.execute(
                "INSERT INTO hoa_profile (legal_name, display_name, theme, default_assessment_amount, default_billing_frequency) "
                "VALUES (?,?,?,?,?)",
                (
                    legal_name,
                    display_name,
                    theme,
                    default_assessment_amount,
                    default_billing_frequency,
                ),
            )
        self._conn.commit()

    # ── Financial Summary ──────────────────────────────────────────────

    def get_bank_tiles(self) -> list[BankTile]:
        # Cash basis: each bank's balance is its opening balance plus money in
        # (payments + non-dues income + reserve transfers in) minus money out
        # (bill payments + reserve transfers out).
        #
        # The authoritative opening balance lives in ``opening_balances``
        # (entered via the Starting Balances UI). ``bank_accounts.opening_balance``
        # is a legacy column that often lags behind — fall back to it only
        # when no Starting-Balances row exists for the account yet.
        rows = self._conn.execute("""
            SELECT
                ba.account_name,
                ba.account_type,
                ba.fund_code,
                COALESCE(
                    (SELECT ob.amount
                       FROM opening_balances ob
                      WHERE ob.entity_type = 'BANK_ACCOUNT'
                        AND ob.entity_id   = ba.id
                      LIMIT 1),
                    ba.opening_balance,
                    0
                )
                  + COALESCE((SELECT SUM(p.amount)        FROM payments p
                                WHERE p.bank_account_id = ba.id), 0)
                  + COALESCE((SELECT SUM(ib.total_amount) FROM income_batches ib
                                WHERE ib.bank_account_id = ba.id), 0)
                  - COALESCE((SELECT SUM(bp.amount)       FROM bill_payments bp
                                WHERE bp.bank_account_id = ba.id), 0)
                  + COALESCE((SELECT SUM(rt.amount)       FROM reserve_transfers rt
                                WHERE rt.to_bank_account_id   = ba.id), 0)
                  - COALESCE((SELECT SUM(rt.amount)       FROM reserve_transfers rt
                                WHERE rt.from_bank_account_id = ba.id), 0)
                  AS balance
            FROM bank_accounts ba
            WHERE ba.active_flag = 1
            ORDER BY ba.account_name COLLATE NOCASE
            """).fetchall()
        return [
            BankTile(
                account_name=r["account_name"],
                fund_code=r["fund_code"] or "",
                balance=Decimal(str(r["balance"])),
                account_type=r["account_type"] or "",
            )
            for r in rows
        ]

    def get_last_reconciliation(self) -> ReconciliationTile | None:
        row = self._conn.execute("""
            SELECT ba.account_name, br.statement_ending_date,
                   br.statement_ending_balance, br.status
            FROM bank_reconciliations br
            JOIN bank_accounts ba ON ba.id = br.bank_account_id
            ORDER BY br.statement_ending_date DESC
            LIMIT 1
            """).fetchone()
        if not row:
            return None
        return ReconciliationTile(
            account_name=row["account_name"],
            ending_date=row["statement_ending_date"],
            ending_balance=Decimal(str(row["statement_ending_balance"])),
            status=row["status"],
        )

    def get_budget_tile(
        self, fiscal_year: int, fy_start_month: int = 1
    ) -> BudgetTile | None:
        budget_row = self._conn.execute(
            """
            SELECT SUM(bl.budget_amount) AS total
            FROM budget_lines bl
            JOIN budgets b ON b.id = bl.budget_id
            WHERE b.fiscal_year = ? AND b.status IN ('APPROVED', 'ARCHIVED')
            """,
            (fiscal_year,),
        ).fetchone()
        if not budget_row or not budget_row["total"]:
            return None

        fy_start, fy_end = _fiscal_year_range(fiscal_year, fy_start_month)

        # Cash-basis actual spent = sum of bill_payments in the FY range.
        actual_row = self._conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS spent
            FROM bill_payments
            WHERE payment_date >= ? AND payment_date <= ?
            """,
            (fy_start, fy_end),
        ).fetchone()

        return BudgetTile(
            fiscal_year=fiscal_year,
            total_budget=Decimal(str(budget_row["total"])),
            actual_spent=Decimal(str(actual_row["spent"] if actual_row else 0)),
        )

    def get_budget_category_tile(
        self, fiscal_year: int, fy_start_month: int = 1
    ) -> "BudgetCategoryTile | None":
        """Return per-category over/under budget counts for the fiscal year.

        Cash basis: actual spend = sum of bill_payments in the fiscal-year
        date range, joined to vendor_bills for the category. Budgets and
        bill_payments share `category_id`, so the comparison is direct.
        """
        budget_row = self._conn.execute(
            """
            SELECT SUM(bl.budget_amount) AS total
            FROM budget_lines bl
            JOIN budgets b ON b.id = bl.budget_id
            WHERE b.fiscal_year = ? AND b.status IN ('APPROVED', 'ARCHIVED')
            """,
            (fiscal_year,),
        ).fetchone()
        if not budget_row or not budget_row["total"]:
            return None

        fy_start, fy_end = _fiscal_year_range(fiscal_year, fy_start_month)

        rows = self._conn.execute(
            """
            SELECT
                bl.category_id,
                SUM(bl.budget_amount) AS budgeted,
                COALESCE(
                    (SELECT SUM(bp.amount)
                     FROM bill_payments bp
                     JOIN vendor_bills vb ON vb.id = bp.vendor_bill_id
                     WHERE vb.category_id = bl.category_id
                       AND bp.payment_date >= ?
                       AND bp.payment_date <= ?),
                    0
                ) AS actual
            FROM budget_lines bl
            JOIN budgets b ON b.id = bl.budget_id
            WHERE b.fiscal_year = ? AND b.status IN ('APPROVED', 'ARCHIVED')
              AND bl.category_id IS NOT NULL
            GROUP BY bl.category_id
            HAVING budgeted > 0
            """,
            (fy_start, fy_end, fiscal_year),
        ).fetchall()

        total_actual_row = self._conn.execute(
            """
            SELECT COALESCE(SUM(bp.amount), 0) AS spent
            FROM bill_payments bp
            WHERE bp.payment_date >= ? AND bp.payment_date <= ?
            """,
            (fy_start, fy_end),
        ).fetchone()

        over_count = sum(
            1 for r in rows if Decimal(str(r["actual"])) > Decimal(str(r["budgeted"]))
        )
        under_count = sum(
            1 for r in rows if Decimal(str(r["actual"])) <= Decimal(str(r["budgeted"]))
        )

        return BudgetCategoryTile(
            fiscal_year=fiscal_year,
            total_budget=Decimal(str(budget_row["total"])),
            actual_spent=Decimal(
                str(total_actual_row["spent"] if total_actual_row else 0)
            ),
            over_budget=over_count,
            under_budget=under_count,
        )

    def get_alert_settings(self) -> dict[str, bool]:
        """Return {alert_key: enabled} for all configured alert types."""
        try:
            rows = self._conn.execute(
                "SELECT alert_key, enabled FROM dashboard_alert_settings"
            ).fetchall()
            return {r["alert_key"]: bool(r["enabled"]) for r in rows}
        except Exception:
            return {}

    def get_alert_settings_list(self) -> list[dict[str, Any]]:
        """Return full alert settings rows for display in Dashboard Config."""
        try:
            rows = self._conn.execute(
                "SELECT alert_key, label, description, enabled "
                "FROM dashboard_alert_settings ORDER BY rowid"
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def save_alert_settings(self, enabled_keys: set[str]) -> None:
        """Enable alerts whose key is in enabled_keys; disable the rest."""
        try:
            rows = self._conn.execute(
                "SELECT alert_key FROM dashboard_alert_settings"
            ).fetchall()
            for row in rows:
                key = row["alert_key"]
                self._conn.execute(
                    "UPDATE dashboard_alert_settings SET enabled=? WHERE alert_key=?",
                    (1 if key in enabled_keys else 0, key),
                )
            self._conn.commit()
        except Exception:
            pass

    def get_dismissed_alerts(self) -> set[str]:
        """Return set of alert_keys dismissed this session."""
        try:
            rows = self._conn.execute(
                "SELECT alert_key FROM dashboard_alert_dismissals"
            ).fetchall()
            return {r["alert_key"] for r in rows}
        except Exception:
            return set()

    def dismiss_alert(self, alert_key: str) -> None:
        """Record a dismissal for this session."""
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO dashboard_alert_dismissals (alert_key) VALUES (?)",
                (alert_key,),
            )
            self._conn.commit()
        except Exception:
            pass

    def clear_alert_dismissals(self) -> None:
        """Clear all dismissals — called at server startup so alerts reappear."""
        try:
            self._conn.execute("DELETE FROM dashboard_alert_dismissals")
            self._conn.commit()
        except Exception:
            pass

    def get_next_action_nudges(self) -> list[dict[str, Any]]:
        """Return a prioritised list of actionable nudges for the dashboard."""
        settings = self.get_alert_settings()
        dismissed = self.get_dismissed_alerts()
        nudges: list[dict[str, Any]] = []

        def _add(
            key: str, level: str, icon: str, text: str, href: str, link: str
        ) -> None:
            if not settings.get(key, True):
                return
            if key in dismissed:
                return
            nudges.append(
                {
                    "key": key,
                    "level": level,
                    "icon": icon,
                    "text": text,
                    "href": href,
                    "link": link,
                }
            )

        # ── 90-day overdue (more urgent — shown before 60-day) ────────────
        try:
            row = self._conn.execute("""
                SELECT COUNT(*) c FROM (
                    SELECT a.id,
                           a.amount - COALESCE(SUM(pa.applied_amount), 0) AS remaining
                    FROM assessments a
                    LEFT JOIN payment_applications pa ON pa.assessment_id = a.id
                    WHERE a.status NOT IN ('VOID')
                      AND a.due_date < DATE('now', '-90 days')
                    GROUP BY a.id
                    HAVING remaining > 0
                )
                """).fetchone()
            if row and row["c"] > 0:
                n = row["c"]
                _add(
                    "overdue_90_days",
                    "urgent",
                    "🚨",
                    f"{n} homeowner balance{'s' if n != 1 else ''} "
                    "90+ days past due — consider sending a formal notice.",
                    "/ar-lots",
                    "AR by Lot",
                )
        except Exception:
            pass

        # ── Unclosed periods ──────────────────────────────────────────────
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) c FROM accounting_periods "
                "WHERE is_closed = 0 AND end_date < DATE('now')"
            ).fetchone()
            if row and row["c"] > 0:
                n = row["c"]
                _add(
                    "open_periods",
                    "warn",
                    "🔒",
                    f"{n} accounting period{'s' if n != 1 else ''} "
                    "still open from a prior month — close them to lock the books.",
                    "/accounting-periods",
                    "Accounting Periods",
                )
        except Exception:
            pass

        # ── Open reconciliations ──────────────────────────────────────────
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) c FROM bank_reconciliations WHERE status = 'OPEN'"
            ).fetchone()
            if row and row["c"] > 0:
                n = row["c"]
                _add(
                    "open_reconciliation",
                    "warn",
                    "🏦",
                    f"{n} bank reconciliation{'s' if n != 1 else ''} "
                    "in progress — finish reconciling to close the month.",
                    "/reconciliations",
                    "Reconciliations",
                )
        except Exception:
            pass

        # ── Vendor bills past due ─────────────────────────────────────────
        try:
            row = self._conn.execute("""
                SELECT COUNT(*) c FROM vendor_bills
                WHERE status IN ('APPROVED', 'PARTIALLY_PAID')
                  AND due_date < DATE('now')
                """).fetchone()
            if row and row["c"] > 0:
                n = row["c"]
                _add(
                    "unpaid_vendor_bills",
                    "warn",
                    "📄",
                    f"{n} vendor bill{'s' if n != 1 else ''} past due — "
                    "payment has not been recorded.",
                    "/vendor-bills",
                    "Vendor Bills",
                )
        except Exception:
            pass

        # ── No reconciliation completed this month ────────────────────────
        try:
            row = self._conn.execute("""
                SELECT COUNT(*) c FROM bank_reconciliations
                WHERE status = 'FINALIZED'
                  AND strftime('%Y-%m', statement_ending_date) = strftime('%Y-%m', 'now')
                """).fetchone()
            if row and row["c"] == 0:
                _add(
                    "no_recon_this_month",
                    "info",
                    "📅",
                    "No bank reconciliation completed for this month yet — "
                    "reconcile before closing the period.",
                    "/reconciliations",
                    "Reconciliations",
                )
        except Exception:
            pass

        # ── 60-day overdue (shown after 90-day so they don't both show for same owners)
        try:
            row = self._conn.execute("""
                SELECT COUNT(*) c FROM (
                    SELECT a.id,
                           a.amount - COALESCE(SUM(pa.applied_amount), 0) AS remaining
                    FROM assessments a
                    LEFT JOIN payment_applications pa ON pa.assessment_id = a.id
                    WHERE a.status NOT IN ('VOID')
                      AND a.due_date < DATE('now', '-60 days')
                    GROUP BY a.id
                    HAVING remaining > 0
                )
                """).fetchone()
            if row and row["c"] > 0:
                n = row["c"]
                _add(
                    "overdue_60_days",
                    "info",
                    "📬",
                    f"{n} assessment{'s' if n != 1 else ''} "
                    "60+ days overdue with an outstanding balance.",
                    "/ar-lots",
                    "AR by Lot",
                )
        except Exception:
            pass

        # Year-end-close alert retired with migration 0061 — fiscal_year_closes
        # table dropped. Will return when the close-the-books workflow is
        # rebuilt for the single-entry model.

        # ── Reserve study older than 3 years ─────────────────────────────
        try:
            row = self._conn.execute("""
                SELECT MAX(study_date) AS latest FROM reserve_studies
                """).fetchone()
            latest = row["latest"] if row else None
            if latest is None or latest < str(
                __import__("datetime")
                .date.today()
                .replace(year=__import__("datetime").date.today().year - 3)
            ):
                _add(
                    "reserve_study_old",
                    "info",
                    "🏗️",
                    "No reserve study on record in the past 3 years — "
                    "consider scheduling an updated study.",
                    "/reserve-study",
                    "Reserve Study",
                )
        except Exception:
            pass

        return nudges

    def get_last_auto_backup(self) -> sqlite3.Row | None:
        try:
            return self._conn.execute(  # type: ignore[no-any-return]
                "SELECT backed_up_at, file_path, file_size_bytes FROM startup_backups ORDER BY id DESC LIMIT 1"
            ).fetchone()
        except Exception:
            return None

    # ── Dashboard Cards ────────────────────────────────────────────────

    def get_dashboard_cards(self) -> list[sqlite3.Row]:
        """Cards currently shown on the dashboard, in position order."""
        return self._conn.execute("""
            SELECT dc.id, dc.title, dc.description, dc.card_type,
                   dc.target_url, dc.report_name, dc.color, dc.is_system,
                   dl.position
            FROM dashboard_layout dl
            JOIN dashboard_cards dc ON dc.id = dl.card_id
            WHERE dc.is_active = 1
            ORDER BY dl.position
            """).fetchall()

    def get_all_catalog_cards(self) -> list[sqlite3.Row]:
        """All cards in the catalog (for the admin config page)."""
        return self._conn.execute("""
            SELECT dc.*, dl.position IS NOT NULL AS on_dashboard
            FROM dashboard_cards dc
            LEFT JOIN dashboard_layout dl ON dl.card_id = dc.id
            WHERE dc.is_active = 1
            ORDER BY dc.sort_order, dc.title COLLATE NOCASE
            """).fetchall()

    def upsert_card(
        self,
        *,
        card_id: int | None,
        title: str,
        description: str,
        card_type: str,
        target_url: str,
        report_name: str,
        color: str,
    ) -> int:
        if card_id:
            self._conn.execute(
                """UPDATE dashboard_cards
                   SET title=?, description=?, card_type=?, target_url=?,
                       report_name=?, color=?, updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (
                    title,
                    description,
                    card_type,
                    target_url,
                    report_name,
                    color,
                    card_id,
                ),
            )
            return card_id
        else:
            cur = self._conn.execute(
                """INSERT INTO dashboard_cards
                   (title, description, card_type, target_url, report_name, color, is_system)
                   VALUES (?,?,?,?,?,?,0)""",
                (title, description, card_type, target_url, report_name, color),
            )
            return int(cur.lastrowid)  # type: ignore[arg-type]

    def delete_card(self, card_id: int) -> None:
        self._conn.execute("DELETE FROM dashboard_layout WHERE card_id=?", (card_id,))
        self._conn.execute(
            "DELETE FROM dashboard_cards WHERE id=? AND is_system=0", (card_id,)
        )

    def save_layout(self, card_positions: list[int]) -> None:
        """Persist ordered list of card_ids as the new dashboard layout."""
        self._conn.execute("DELETE FROM dashboard_layout")
        for pos, card_id in enumerate(card_positions):
            self._conn.execute(
                "INSERT INTO dashboard_layout (card_id, position) VALUES (?,?)",
                (card_id, pos),
            )
        self._conn.commit()

    def reset_layout(self) -> None:
        """Restore dashboard layout from the dashboard_default_layout snapshot."""
        rows = self._conn.execute(
            "SELECT card_id FROM dashboard_default_layout ORDER BY position"
        ).fetchall()
        self._conn.execute("DELETE FROM dashboard_layout")
        for pos, row in enumerate(rows):
            self._conn.execute(
                "INSERT INTO dashboard_layout (card_id, position) VALUES (?,?)",
                (row["card_id"], pos),
            )
        self._conn.commit()
