import { getDb } from "../lib/db";

export type Assumptions = {
  id: number;
  study_year: number;
  reserve_balance_override: number | null;
  annual_contribution: number;
  contribution_growth_rate: number;
  investment_return_rate: number;
  num_lots: number;
  projection_years: number;
  notes: string | null;
};

export type AssumptionsFormValues = Omit<Assumptions, "id">;

export type ReserveAsset = {
  id: number;
  asset_group: string;
  component: string;
  install_year: number;
  useful_life_years: number;
  condition: "Excellent" | "Good" | "Moderate" | "Poor" | "Critical";
  replacement_cost: number;
  annual_inflation: number;
  notes: string | null;
  sort_order: number;
};

export type AssetFormValues = Omit<ReserveAsset, "id" | "sort_order">;

export type Scenario = {
  id: number;
  scenario_name: string;
  description: string | null;
  emergency_cost: number;
  expected_year: number | null;
  notes: string | null;
  sort_order: number;
};

export type ScenarioFormValues = Omit<Scenario, "id" | "sort_order">;

// ── Assumptions ───────────────────────────────────────────────────────────────

export async function getAssumptions(): Promise<Assumptions | null> {
  const db = await getDb();
  const rows = await db.select<Assumptions[]>(
    "SELECT * FROM reserve_study_assumptions WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
  );
  return rows[0] ?? null;
}

export async function saveAssumptions(values: AssumptionsFormValues): Promise<void> {
  const db = await getDb();
  const existing = await getAssumptions();
  if (existing) {
    await db.execute(
      `UPDATE reserve_study_assumptions
       SET study_year = ?, reserve_balance_override = ?, annual_contribution = ?,
           contribution_growth_rate = ?, investment_return_rate = ?,
           num_lots = ?, projection_years = ?, notes = ?, updated_at = datetime('now')
       WHERE id = ?`,
      [
        values.study_year,
        values.reserve_balance_override ?? null,
        values.annual_contribution,
        values.contribution_growth_rate,
        values.investment_return_rate,
        values.num_lots,
        values.projection_years,
        values.notes ?? null,
        existing.id,
      ]
    );
  } else {
    await db.execute(
      `INSERT INTO reserve_study_assumptions
         (study_year, reserve_balance_override, annual_contribution,
          contribution_growth_rate, investment_return_rate, num_lots, projection_years, notes)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      [
        values.study_year,
        values.reserve_balance_override ?? null,
        values.annual_contribution,
        values.contribution_growth_rate,
        values.investment_return_rate,
        values.num_lots,
        values.projection_years,
        values.notes ?? null,
      ]
    );
  }
}

// ── Assets ────────────────────────────────────────────────────────────────────

export async function listAssets(): Promise<ReserveAsset[]> {
  const db = await getDb();
  return db.select<ReserveAsset[]>(
    "SELECT * FROM reserve_assets WHERE active_flag = 1 ORDER BY sort_order, asset_group, component"
  );
}

export async function insertAsset(values: AssetFormValues): Promise<number> {
  const db = await getDb();
  const result = await db.execute(
    `INSERT INTO reserve_assets
       (asset_group, component, install_year, useful_life_years, condition,
        replacement_cost, annual_inflation, notes,
        sort_order)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?,
             (SELECT COALESCE(MAX(sort_order), 0) + 10 FROM reserve_assets))`,
    [
      values.asset_group,
      values.component,
      values.install_year,
      values.useful_life_years,
      values.condition,
      values.replacement_cost,
      values.annual_inflation,
      values.notes ?? null,
    ]
  );
  return result.lastInsertId ?? 0;
}

export async function updateAsset(id: number, values: AssetFormValues): Promise<void> {
  const db = await getDb();
  await db.execute(
    `UPDATE reserve_assets
     SET asset_group = ?, component = ?, install_year = ?, useful_life_years = ?,
         condition = ?, replacement_cost = ?, annual_inflation = ?, notes = ?,
         updated_at = datetime('now')
     WHERE id = ?`,
    [
      values.asset_group,
      values.component,
      values.install_year,
      values.useful_life_years,
      values.condition,
      values.replacement_cost,
      values.annual_inflation,
      values.notes ?? null,
      id,
    ]
  );
}

export async function deleteAsset(id: number): Promise<void> {
  const db = await getDb();
  await db.execute(
    "UPDATE reserve_assets SET active_flag = 0, updated_at = datetime('now') WHERE id = ?",
    [id]
  );
}

// ── Scenarios ─────────────────────────────────────────────────────────────────

export async function listScenarios(): Promise<Scenario[]> {
  const db = await getDb();
  return db.select<Scenario[]>(
    "SELECT * FROM reserve_study_scenarios WHERE active_flag = 1 ORDER BY sort_order, scenario_name"
  );
}

export async function insertScenario(values: ScenarioFormValues): Promise<number> {
  const db = await getDb();
  const result = await db.execute(
    `INSERT INTO reserve_study_scenarios
       (scenario_name, description, emergency_cost, expected_year, notes,
        sort_order)
     VALUES (?, ?, ?, ?, ?,
             (SELECT COALESCE(MAX(sort_order), 0) + 10 FROM reserve_study_scenarios))`,
    [
      values.scenario_name,
      values.description ?? null,
      values.emergency_cost,
      values.expected_year ?? null,
      values.notes ?? null,
    ]
  );
  return result.lastInsertId ?? 0;
}

export async function updateScenario(id: number, values: ScenarioFormValues): Promise<void> {
  const db = await getDb();
  await db.execute(
    `UPDATE reserve_study_scenarios
     SET scenario_name = ?, description = ?, emergency_cost = ?,
         expected_year = ?, notes = ?, updated_at = datetime('now')
     WHERE id = ?`,
    [
      values.scenario_name,
      values.description ?? null,
      values.emergency_cost,
      values.expected_year ?? null,
      values.notes ?? null,
      id,
    ]
  );
}

export async function deleteScenario(id: number): Promise<void> {
  const db = await getDb();
  await db.execute(
    "UPDATE reserve_study_scenarios SET active_flag = 0, updated_at = datetime('now') WHERE id = ?",
    [id]
  );
}
