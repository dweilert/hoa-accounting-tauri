import { getDb } from "../lib/db";
import { BudgetSchema, BudgetLineSchema, type Budget, type BudgetLine } from "../types/budget";

export async function listBudgets(): Promise<Budget[]> {
  const db = await getDb();
  const rows = await db.select<unknown[]>(
    "SELECT * FROM budgets ORDER BY fiscal_year DESC, fund_code"
  );
  return rows.map((r) => BudgetSchema.parse(r));
}

export async function getBudget(id: number): Promise<Budget | null> {
  const db = await getDb();
  const rows = await db.select<unknown[]>("SELECT * FROM budgets WHERE id = ?", [id]);
  return rows[0] ? BudgetSchema.parse(rows[0]) : null;
}

export async function createBudget(fiscalYear: number, fundCode: string, notes?: string): Promise<number> {
  const db = await getDb();
  const result = await db.execute(
    "INSERT INTO budgets (fiscal_year, fund_code, notes) VALUES (?, ?, ?)",
    [fiscalYear, fundCode, notes ?? null]
  );
  return result.lastInsertId ?? 0;
}

export async function updateBudgetStatus(id: number, status: string): Promise<void> {
  const db = await getDb();
  await db.execute(
    "UPDATE budgets SET status = ?, updated_at = datetime('now') WHERE id = ?",
    [status, id]
  );
}

export async function updateBudgetNotes(id: number, notes: string): Promise<void> {
  const db = await getDb();
  await db.execute(
    "UPDATE budgets SET notes = ?, updated_at = datetime('now') WHERE id = ?",
    [notes, id]
  );
}

export async function getBudgetLines(budgetId: number): Promise<BudgetLine[]> {
  const db = await getDb();
  const rows = await db.select<unknown[]>(
    "SELECT * FROM budget_lines WHERE budget_id = ?",
    [budgetId]
  );
  return rows.map((r) => BudgetLineSchema.parse(r));
}

export async function upsertBudgetLine(
  budgetId: number,
  categoryId: number,
  fiscalPeriod: number,
  amount: number
): Promise<void> {
  const db = await getDb();
  if (amount === 0) {
    await db.execute(
      "DELETE FROM budget_lines WHERE budget_id = ? AND category_id = ? AND fiscal_period = ?",
      [budgetId, categoryId, fiscalPeriod]
    );
  } else {
    await db.execute(
      `INSERT INTO budget_lines (budget_id, category_id, fiscal_period, budget_amount)
       VALUES (?, ?, ?, ?)
       ON CONFLICT(budget_id, category_id, fiscal_period) DO UPDATE SET budget_amount = excluded.budget_amount`,
      [budgetId, categoryId, fiscalPeriod, amount]
    );
  }
}

export async function getBudgetTotals(budgetId: number): Promise<Map<number, number>> {
  const db = await getDb();
  const rows = await db.select<Array<{ category_id: number; total: number }>>(
    "SELECT category_id, SUM(budget_amount) as total FROM budget_lines WHERE budget_id = ? GROUP BY category_id",
    [budgetId]
  );
  return new Map(rows.map((r) => [r.category_id, r.total]));
}
