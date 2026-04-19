"""Repository for fiscal year close tracking."""

from __future__ import annotations

import sqlite3

from .base import BaseRepository


class YearEndCloseRepository(BaseRepository):
    """Database access for fiscal_year_closes."""

    # ── Queries ────────────────────────────────────────────────────────

    def is_fiscal_year_closed(self, fiscal_year: int) -> bool:
        """Return True if the fiscal year has been formally closed and not re-opened."""
        row = self.conn.execute(
            """
            SELECT id FROM fiscal_year_closes
            WHERE fiscal_year = ? AND reopened_at IS NULL
            """,
            (fiscal_year,),
        ).fetchone()
        return row is not None

    def get_close_record(self, fiscal_year: int) -> sqlite3.Row | None:
        """Return the close record for a fiscal year, or None."""
        return self.conn.execute(
            """
            SELECT id, fiscal_year, closed_at,
                   closing_je_operating_id, closing_je_reserve_id,
                   reopened_at
            FROM fiscal_year_closes
            WHERE fiscal_year = ?
            """,
            (fiscal_year,),
        ).fetchone()

    def list_fiscal_years(self) -> list[sqlite3.Row]:
        """Return all fiscal years that have accounting periods, with close status."""
        return list(
            self.conn.execute(
                """
                SELECT
                    ap.fiscal_year,
                    COUNT(ap.id)                           AS period_count,
                    SUM(ap.is_closed)                      AS closed_count,
                    MIN(ap.start_date)                     AS year_start,
                    MAX(ap.end_date)                       AS year_end,
                    fyc.closed_at                          AS formally_closed_at,
                    fyc.reopened_at                        AS reopened_at,
                    fyc.closing_je_operating_id,
                    fyc.closing_je_reserve_id
                FROM accounting_periods ap
                LEFT JOIN fiscal_year_closes fyc
                       ON fyc.fiscal_year = ap.fiscal_year
                GROUP BY ap.fiscal_year
                ORDER BY ap.fiscal_year DESC
                """
            ).fetchall()
        )

    def get_open_periods(self, fiscal_year: int) -> list[sqlite3.Row]:
        """Return periods in the fiscal year that are still open."""
        return list(
            self.conn.execute(
                """
                SELECT id, period_name FROM accounting_periods
                WHERE fiscal_year = ? AND is_closed = 0
                ORDER BY start_date
                """,
                (fiscal_year,),
            ).fetchall()
        )

    def get_draft_entries(self, fiscal_year: int) -> int:
        """Count DRAFT journal entries in the fiscal year."""
        row = self.conn.execute(
            """
            SELECT COUNT(*) FROM journal_entries je
            JOIN accounting_periods ap ON ap.id = je.accounting_period_id
            WHERE ap.fiscal_year = ? AND je.status = 'DRAFT'
            """,
            (fiscal_year,),
        ).fetchone()
        return int(row[0])

    def get_income_expense_balances(
        self, fiscal_year: int
    ) -> list[sqlite3.Row]:
        """
        Return net balances for all INCOME and EXPENSE accounts with activity
        in the fiscal year, grouped by fund and account type.

        net_balance is expressed in the account's normal-balance direction:
          INCOME  accounts → net credits minus net debits  (positive = income earned)
          EXPENSE accounts → net debits  minus net credits (positive = expense incurred)
        """
        return list(
            self.conn.execute(
                """
                SELECT
                    a.id            AS account_id,
                    a.account_number,
                    a.account_name,
                    a.fund_code,
                    at.code         AS account_type,
                    at.normal_balance,
                    COALESCE(SUM(jel.debit_amount),  0) AS total_debits,
                    COALESCE(SUM(jel.credit_amount), 0) AS total_credits,
                    CASE at.normal_balance
                        WHEN 'DEBIT'
                            THEN COALESCE(SUM(jel.debit_amount),  0)
                               - COALESCE(SUM(jel.credit_amount), 0)
                        ELSE
                             COALESCE(SUM(jel.credit_amount), 0)
                           - COALESCE(SUM(jel.debit_amount),  0)
                    END             AS net_balance
                FROM accounts a
                JOIN account_types at ON at.id = a.account_type_id
                JOIN journal_entry_lines jel ON jel.account_id = a.id
                JOIN journal_entries je      ON je.id = jel.journal_entry_id
                JOIN accounting_periods ap   ON ap.id = je.accounting_period_id
                WHERE ap.fiscal_year = ?
                  AND at.code IN ('INCOME', 'EXPENSE')
                  AND je.status = 'POSTED'
                GROUP BY a.id, a.account_number, a.account_name,
                         a.fund_code, at.code, at.normal_balance
                HAVING net_balance <> 0
                ORDER BY a.fund_code, at.code, a.account_number
                """,
                (fiscal_year,),
            ).fetchall()
        )

    def get_fund_balance_account(self, fund_code: str) -> sqlite3.Row | None:
        """Return the equity / fund-balance account for the given fund."""
        return self.conn.execute(
            """
            SELECT a.id, a.account_number, a.account_name
            FROM accounts a
            JOIN account_types at ON at.id = a.account_type_id
            WHERE at.code = 'EQUITY'
              AND a.fund_code = ?
              AND a.is_active = 1
            ORDER BY a.account_number
            LIMIT 1
            """,
            (fund_code,),
        ).fetchone()

    def get_last_period_end_date(self, fiscal_year: int) -> str | None:
        """Return the last day of the fiscal year's last period."""
        row = self.conn.execute(
            """
            SELECT end_date, id FROM accounting_periods
            WHERE fiscal_year = ?
            ORDER BY end_date DESC LIMIT 1
            """,
            (fiscal_year,),
        ).fetchone()
        return str(row["end_date"]) if row else None

    def get_last_period_id(self, fiscal_year: int) -> int | None:
        """Return the id of the last period in the fiscal year."""
        row = self.conn.execute(
            """
            SELECT id FROM accounting_periods
            WHERE fiscal_year = ?
            ORDER BY end_date DESC LIMIT 1
            """,
            (fiscal_year,),
        ).fetchone()
        return int(row["id"]) if row else None

    # ── Mutations ──────────────────────────────────────────────────────

    def insert_close(
        self,
        *,
        fiscal_year: int,
        closed_at: str,
        closing_je_operating_id: int | None,
        closing_je_reserve_id: int | None,
    ) -> int:
        """Record a fiscal year as formally closed."""
        cur = self.conn.execute(
            """
            INSERT INTO fiscal_year_closes
                (fiscal_year, closed_at,
                 closing_je_operating_id, closing_je_reserve_id)
            VALUES (?, ?, ?, ?)
            """,
            (
                fiscal_year,
                closed_at,
                closing_je_operating_id,
                closing_je_reserve_id,
            ),
        )
        return int(cur.lastrowid)  # type: ignore[arg-type]

    def mark_reopened(self, fiscal_year: int, reopened_at: str) -> None:
        """Mark a closed fiscal year as re-opened."""
        self.conn.execute(
            """
            UPDATE fiscal_year_closes
               SET reopened_at = ?
             WHERE fiscal_year = ? AND reopened_at IS NULL
            """,
            (reopened_at, fiscal_year),
        )
