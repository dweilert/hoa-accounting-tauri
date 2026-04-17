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
        """Return all lines for a budget joined to account info."""
        return self.conn.execute(
            """
            SELECT
                bl.id,
                bl.account_id,
                bl.fiscal_period,
                bl.budget_amount,
                a.account_number,
                a.account_name,
                a.group_code,
                at.code AS account_type_code
            FROM budget_lines bl
            JOIN accounts a   ON a.id  = bl.account_id
            JOIN account_types at ON at.id = a.account_type_id
            WHERE bl.budget_id = ?
            ORDER BY a.account_number, bl.fiscal_period
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

    def list_expense_accounts(self) -> list[sqlite3.Row]:
        """Return active EXPENSE accounts ordered by account_number."""
        return self.conn.execute(
            """
            SELECT a.id, a.account_number, a.account_name,
                   a.group_code, a.fund_code
            FROM accounts a
            JOIN account_types at ON at.id = a.account_type_id
            WHERE at.code = 'EXPENSE'
              AND a.is_active = 1
            ORDER BY a.account_number
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
        account_id: int,
        fiscal_period: int,
        amount: Decimal,
    ) -> None:
        """Insert or replace a single budget line."""
        self.conn.execute(
            """
            INSERT INTO budget_lines
                (budget_id, account_id, fiscal_period, budget_amount)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (budget_id, account_id, fiscal_period)
            DO UPDATE SET budget_amount = excluded.budget_amount
            """,
            (budget_id, account_id, fiscal_period, str(amount)),
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
