"""Repository for dashboard data: financial summary, cards, layout, HOA profile."""

from __future__ import annotations

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


class DashboardRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── HOA Profile ────────────────────────────────────────────────────

    def get_hoa_profile(self) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM hoa_profile LIMIT 1"
        ).fetchone()

    def save_hoa_profile(self, legal_name: str, display_name: str) -> None:
        existing = self._conn.execute("SELECT id FROM hoa_profile LIMIT 1").fetchone()
        if existing:
            self._conn.execute(
                "UPDATE hoa_profile SET legal_name=?, display_name=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (legal_name, display_name, existing["id"]),
            )
        else:
            self._conn.execute(
                "INSERT INTO hoa_profile (legal_name, display_name) VALUES (?,?)",
                (legal_name, display_name),
            )
        self._conn.commit()

    # ── Financial Summary ──────────────────────────────────────────────

    def get_bank_tiles(self) -> list[BankTile]:
        rows = self._conn.execute(
            """
            SELECT ba.account_name, ba.account_type,
                   a.fund_code,
                   COALESCE(SUM(jl.debit_amount - jl.credit_amount), 0) AS balance
            FROM bank_accounts ba
            JOIN accounts a ON a.id = ba.gl_account_id
            LEFT JOIN journal_entry_lines jl ON jl.account_id = a.id
            WHERE ba.active_flag = 1
            GROUP BY ba.id
            ORDER BY ba.account_name COLLATE NOCASE
            """
        ).fetchall()
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
        row = self._conn.execute(
            """
            SELECT ba.account_name, br.statement_ending_date,
                   br.statement_ending_balance, br.status
            FROM bank_reconciliations br
            JOIN bank_accounts ba ON ba.id = br.bank_account_id
            ORDER BY br.statement_ending_date DESC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        return ReconciliationTile(
            account_name=row["account_name"],
            ending_date=row["statement_ending_date"],
            ending_balance=Decimal(str(row["statement_ending_balance"])),
            status=row["status"],
        )

    def get_budget_tile(self, fiscal_year: int) -> BudgetTile | None:
        budget_row = self._conn.execute(
            """
            SELECT SUM(bl.budget_amount) AS total
            FROM budget_lines bl
            JOIN budgets b ON b.id = bl.budget_id
            WHERE b.fiscal_year = ? AND b.status = 'APPROVED'
            """,
            (fiscal_year,),
        ).fetchone()
        if not budget_row or not budget_row["total"]:
            return None

        actual_row = self._conn.execute(
            """
            SELECT COALESCE(SUM(jl.debit_amount - jl.credit_amount), 0) AS spent
            FROM journal_entry_lines jl
            JOIN accounts a ON a.id = jl.account_id
            JOIN account_types at ON at.id = a.account_type_id
            JOIN journal_entries je ON je.id = jl.journal_entry_id
            WHERE at.code = 'EXPENSE'
              AND strftime('%Y', je.entry_date) = ?
            """,
            (str(fiscal_year),),
        ).fetchone()

        return BudgetTile(
            fiscal_year=fiscal_year,
            total_budget=Decimal(str(budget_row["total"])),
            actual_spent=Decimal(str(actual_row["spent"] if actual_row else 0)),
        )

    def get_last_auto_backup(self) -> sqlite3.Row | None:
        try:
            return self._conn.execute(
                "SELECT backed_up_at, file_path, file_size_bytes FROM startup_backups ORDER BY id DESC LIMIT 1"
            ).fetchone()
        except Exception:
            return None

    # ── Dashboard Cards ────────────────────────────────────────────────

    def get_dashboard_cards(self) -> list[sqlite3.Row]:
        """Cards currently shown on the dashboard, in position order."""
        return self._conn.execute(
            """
            SELECT dc.id, dc.title, dc.description, dc.card_type,
                   dc.target_url, dc.report_name, dc.color, dc.is_system,
                   dl.position
            FROM dashboard_layout dl
            JOIN dashboard_cards dc ON dc.id = dl.card_id
            WHERE dc.is_active = 1
            ORDER BY dl.position
            """
        ).fetchall()

    def get_all_catalog_cards(self) -> list[sqlite3.Row]:
        """All cards in the catalog (for the admin config page)."""
        return self._conn.execute(
            """
            SELECT dc.*, dl.position IS NOT NULL AS on_dashboard
            FROM dashboard_cards dc
            LEFT JOIN dashboard_layout dl ON dl.card_id = dc.id
            WHERE dc.is_active = 1
            ORDER BY dc.sort_order, dc.title COLLATE NOCASE
            """
        ).fetchall()

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
                (title, description, card_type, target_url, report_name, color, card_id),
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
        self._conn.execute(
            "DELETE FROM dashboard_layout WHERE card_id=?", (card_id,)
        )
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
