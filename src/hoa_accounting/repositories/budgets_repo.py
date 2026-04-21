"""Repository for budgets and budget lines."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from .base import BaseRepository

_MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


class BudgetsRepository(BaseRepository):
    """Database access for budgets and budget_lines."""

    # ── Queries ───────────────────────────────────────────────────────

    def list_budgets(self) -> list[sqlite3.Row]:
        """Return all budgets newest fiscal year first."""
        return self.conn.execute(
            """
            SELECT id, fiscal_year, fund_code, status, notes,
                   created_at, updated_at
            FROM budgets
            ORDER BY fiscal_year DESC, fund_code ASC
            """
        ).fetchall()

    def get_budget(self, budget_id: int) -> sqlite3.Row | None:
        """Return a budget header row, or None."""
        return self.conn.execute(
            """
            SELECT id, fiscal_year, fund_code, status, notes,
                   created_at, updated_at
            FROM budgets
            WHERE id = ?
            """,
            (budget_id,),
        ).fetchone()

    def get_budget_lines(self, budget_id: int) -> list[sqlite3.Row]:
        """Return all lines for a budget, supporting both category_id and legacy account_id."""
        return self.conn.execute(
            """
            SELECT
                bl.id,
                bl.category_id,
                bl.account_id,
                bl.fiscal_period,
                bl.budget_amount,
                c.code  AS category_code,
                c.name  AS category_name,
                c.group_name,
                a.account_name AS legacy_account_name
            FROM budget_lines bl
            LEFT JOIN categories c ON c.id = bl.category_id
            LEFT JOIN accounts  a ON a.id = bl.account_id AND bl.category_id IS NULL
            WHERE bl.budget_id = ?
            ORDER BY COALESCE(c.sort_order, 999), COALESCE(c.name, a.account_name), bl.fiscal_period
            """,
            (budget_id,),
        ).fetchall()

    def find_budget(
        self, fiscal_year: int, fund_code: str
    ) -> sqlite3.Row | None:
        """Return a budget by year + fund, or None."""
        return self.conn.execute(
            "SELECT id, fiscal_year, fund_code, status FROM budgets "
            "WHERE fiscal_year = ? AND fund_code = ?",
            (fiscal_year, fund_code),
        ).fetchone()

    def list_expense_categories(self) -> list[sqlite3.Row]:
        """Return active EXPENSE categories ordered by sort_order then name."""
        return self.conn.execute(
            """
            SELECT id, code, name, group_name, fund_code
            FROM categories
            WHERE category_type = 'EXPENSE'
              AND active_flag = 1
            ORDER BY sort_order, name
            """
        ).fetchall()

    # ── Mutations ─────────────────────────────────────────────────────

    def insert_budget(
        self,
        *,
        fiscal_year: int,
        fund_code: str,
        notes: str,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO budgets (fiscal_year, fund_code, notes)
            VALUES (?, ?, ?)
            """,
            (fiscal_year, fund_code, notes or None),
        )
        return int(cur.lastrowid)  # type: ignore[arg-type]

    def update_budget_notes(
        self, budget_id: int, *, notes: str
    ) -> None:
        self.conn.execute(
            """
            UPDATE budgets
               SET notes = ?, updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (notes or None, budget_id),
        )

    def upsert_budget_line(
        self,
        budget_id: int,
        category_id: int,
        fiscal_period: int,
        amount: Decimal,
    ) -> None:
        """Insert or update a single budget line."""
        updated = self.conn.execute(
            """
            UPDATE budget_lines
               SET budget_amount = ?
             WHERE budget_id = ? AND category_id = ? AND fiscal_period = ?
            """,
            (str(amount), budget_id, category_id, fiscal_period),
        ).rowcount
        if updated == 0:
            self.conn.execute(
                """
                INSERT INTO budget_lines
                    (budget_id, category_id, fiscal_period, budget_amount, account_id)
                VALUES (?, ?, ?, ?, 0)
                """,
                (budget_id, category_id, fiscal_period, str(amount)),
            )

    def delete_zero_lines(self, budget_id: int) -> None:
        """Remove lines where budget_amount is exactly 0."""
        self.conn.execute(
            "DELETE FROM budget_lines "
            "WHERE budget_id = ? AND CAST(budget_amount AS REAL) = 0",
            (budget_id,),
        )

    def set_status(self, budget_id: int, status: str) -> None:
        self.conn.execute(
            """
            UPDATE budgets
               SET status = ?, updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (status, budget_id),
        )

    def delete_budget(self, budget_id: int) -> None:
        """Hard-delete a DRAFT budget (cascade removes its lines)."""
        self.conn.execute("DELETE FROM budgets WHERE id = ?", (budget_id,))
