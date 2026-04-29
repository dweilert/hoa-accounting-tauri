"""Repository for reserve study tables."""

from __future__ import annotations

import sqlite3
from decimal import Decimal


class ReserveStudyRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ── Assumptions ───────────────────────────────────────────────────

    def get_active_assumptions(self) -> sqlite3.Row | None:
        return self.conn.execute(  # type: ignore[no-any-return]
            "SELECT * FROM reserve_study_assumptions WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def update_assumptions(
        self,
        assumptions_id: int,
        *,
        study_year: int,
        reserve_balance_override: Decimal | None,
        annual_contribution: Decimal,
        contribution_growth_rate: Decimal,
        investment_return_rate: Decimal,
        num_lots: int,
        projection_years: int,
        notes: str,
    ) -> None:
        self.conn.execute(
            """
            UPDATE reserve_study_assumptions SET
                study_year                 = ?,
                reserve_balance_override   = ?,
                annual_contribution        = ?,
                contribution_growth_rate   = ?,
                investment_return_rate     = ?,
                num_lots                   = ?,
                projection_years           = ?,
                notes                      = ?,
                updated_at                 = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                study_year,
                str(reserve_balance_override) if reserve_balance_override is not None else None,
                str(annual_contribution),
                str(contribution_growth_rate),
                str(investment_return_rate),
                num_lots,
                projection_years,
                notes,
                assumptions_id,
            ),
        )

    # ── Assets ────────────────────────────────────────────────────────

    def list_assets(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT * FROM reserve_assets
            WHERE active_flag = 1
            ORDER BY sort_order, asset_group, component
            """
        ).fetchall()

    def get_asset(self, asset_id: int) -> sqlite3.Row | None:
        return self.conn.execute(  # type: ignore[no-any-return]
            "SELECT * FROM reserve_assets WHERE id = ?", (asset_id,)
        ).fetchone()

    def insert_asset(
        self,
        *,
        asset_group: str,
        component: str,
        install_year: int,
        useful_life_years: int,
        condition: str,
        replacement_cost: Decimal,
        annual_inflation: Decimal,
        notes: str,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO reserve_assets
                (asset_group, component, install_year, useful_life_years,
                 condition, replacement_cost, annual_inflation, notes, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?,
                    (SELECT COALESCE(MAX(sort_order), 0) + 10 FROM reserve_assets))
            """,
            (
                asset_group, component, install_year, useful_life_years,
                condition, str(replacement_cost), str(annual_inflation), notes,
            ),
        )
        return cur.lastrowid  # type: ignore[return-value]

    def update_asset(
        self,
        asset_id: int,
        *,
        asset_group: str,
        component: str,
        install_year: int,
        useful_life_years: int,
        condition: str,
        replacement_cost: Decimal,
        annual_inflation: Decimal,
        notes: str,
    ) -> None:
        self.conn.execute(
            """
            UPDATE reserve_assets SET
                asset_group       = ?,
                component         = ?,
                install_year      = ?,
                useful_life_years = ?,
                condition         = ?,
                replacement_cost  = ?,
                annual_inflation  = ?,
                notes             = ?,
                updated_at        = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                asset_group, component, install_year, useful_life_years,
                condition, str(replacement_cost), str(annual_inflation),
                notes, asset_id,
            ),
        )

    def deactivate_asset(self, asset_id: int) -> None:
        self.conn.execute(
            "UPDATE reserve_assets SET active_flag = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (asset_id,),
        )

    # ── Scenarios ─────────────────────────────────────────────────────

    def list_scenarios(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT * FROM reserve_study_scenarios
            WHERE active_flag = 1
            ORDER BY sort_order, scenario_name
            """
        ).fetchall()

    def get_scenario(self, scenario_id: int) -> sqlite3.Row | None:
        return self.conn.execute(  # type: ignore[no-any-return]
            "SELECT * FROM reserve_study_scenarios WHERE id = ?", (scenario_id,)
        ).fetchone()

    def insert_scenario(
        self,
        *,
        scenario_name: str,
        description: str,
        emergency_cost: Decimal,
        expected_year: int | None,
        notes: str,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO reserve_study_scenarios
                (scenario_name, description, emergency_cost, expected_year, notes, sort_order)
            VALUES (?, ?, ?, ?,?,
                    (SELECT COALESCE(MAX(sort_order), 0) + 10 FROM reserve_study_scenarios))
            """,
            (scenario_name, description, str(emergency_cost), expected_year, notes),
        )
        return cur.lastrowid  # type: ignore[return-value]

    def update_scenario(
        self,
        scenario_id: int,
        *,
        scenario_name: str,
        description: str,
        emergency_cost: Decimal,
        expected_year: int | None,
        notes: str,
    ) -> None:
        self.conn.execute(
            """
            UPDATE reserve_study_scenarios SET
                scenario_name  = ?,
                description    = ?,
                emergency_cost = ?,
                expected_year  = ?,
                notes          = ?,
                updated_at     = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (scenario_name, description, str(emergency_cost), expected_year, notes, scenario_id),
        )

    def deactivate_scenario(self, scenario_id: int) -> None:
        self.conn.execute(
            "UPDATE reserve_study_scenarios SET active_flag = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (scenario_id,),
        )

    # ── Reserve balance ───────────────────────────────────────────────

    def get_reserve_fund_balance(self) -> Decimal:
        """Sum of all RESERVE fund bank-account balances using the cash-basis
        flow on bank_accounts (the GL was retired in migration 0061)."""
        row = self.conn.execute(
            """
            SELECT
                COALESCE(SUM(ba.opening_balance), 0)
                + COALESCE((SELECT SUM(p.amount) FROM payments p
                             JOIN bank_accounts b ON b.id = p.bank_account_id
                            WHERE b.fund_code = 'RESERVE' AND b.active_flag = 1), 0)
                + COALESCE((SELECT SUM(ib.total_amount) FROM income_batches ib
                             JOIN bank_accounts b ON b.id = ib.bank_account_id
                            WHERE b.fund_code = 'RESERVE' AND b.active_flag = 1), 0)
                - COALESCE((SELECT SUM(bp.amount) FROM bill_payments bp
                             JOIN bank_accounts b ON b.id = bp.bank_account_id
                            WHERE b.fund_code = 'RESERVE' AND b.active_flag = 1), 0)
                AS balance
            FROM bank_accounts ba
            WHERE ba.fund_code = 'RESERVE' AND ba.active_flag = 1
            """
        ).fetchone()
        return Decimal(str(row["balance"] if row and row["balance"] is not None else 0))
