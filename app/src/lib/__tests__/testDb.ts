/**
 * Shared test-database factory.
 * Creates a fresh in-memory sql.js DB, initialises the full schema and seeds,
 * and returns a DbHandle-compatible object — same interface used by every repo.
 */
import type { DbHandle } from "../dbTypes";
import { initSchema } from "../schema";

export async function createTestDb(): Promise<DbHandle> {
  // sql.js works in Node without a locateFile config (uses bundled WASM)
  const initSqlJs = (await import("sql.js")).default;
  const SQL = await initSqlJs();
  const sqlDb = new SQL.Database();

  const handle: DbHandle = {
    async execute(sql: string, params: unknown[] = []) {
      if (params.length === 0) {
        sqlDb.exec(sql);
        return { rowsAffected: 0 };
      }
      const stmt = sqlDb.prepare(sql);
      try {
        stmt.run(params as Parameters<typeof stmt.run>[0]);
        const rowsAffected = sqlDb.getRowsModified();
        const idRows = sqlDb.exec("SELECT last_insert_rowid()");
        const raw = idRows[0]?.values[0]?.[0];
        const result: { rowsAffected: number; lastInsertId?: number } = { rowsAffected };
        if (typeof raw === "number") result.lastInsertId = raw;
        return result;
      } finally {
        stmt.free();
      }
    },
    async select<T>(sql: string, params: unknown[] = []): Promise<T> {
      const stmt = sqlDb.prepare(sql);
      try {
        if (params.length > 0) stmt.bind(params as Parameters<typeof stmt.bind>[0]);
        const rows: Record<string, unknown>[] = [];
        while (stmt.step()) rows.push(stmt.getAsObject() as Record<string, unknown>);
        return rows as unknown as T;
      } finally {
        stmt.free();
      }
    },
  };

  await initSchema(handle);
  return handle;
}

// ── Seed helpers ──────────────────────────────────────────────────────────────

export async function seedBankAccount(
  db: DbHandle,
  name = "Test Checking",
  opts: { fund_code?: string; opening_balance?: number } = {}
): Promise<number> {
  const r = await db.execute(
    `INSERT INTO bank_accounts
       (account_name, institution_name, account_type, fund_code, active_flag, opening_balance)
     VALUES (?, 'First Bank', 'CHECKING', ?, 1, ?)`,
    [name, opts.fund_code ?? "OPERATING", opts.opening_balance ?? 0]
  );
  return r.lastInsertId!;
}

export async function seedLot(db: DbHandle, lotNumber = "101"): Promise<number> {
  const r = await db.execute(
    "INSERT INTO lots (lot_number, active_flag) VALUES (?, 1)",
    [lotNumber]
  );
  return r.lastInsertId!;
}

export async function seedOwner(db: DbHandle, name = "Jane Doe"): Promise<number> {
  const r = await db.execute(
    "INSERT INTO owners (display_name, owner_type) VALUES (?, 'PERSON')",
    [name]
  );
  return r.lastInsertId!;
}

export async function seedOwnership(
  db: DbHandle,
  lotId: number,
  ownerId: number,
  startDate = "2020-01-01"
): Promise<number> {
  const r = await db.execute(
    `INSERT INTO lot_ownership (lot_id, owner_id, start_date, ownership_percent)
     VALUES (?, ?, ?, 100)`,
    [lotId, ownerId, startDate]
  );
  return r.lastInsertId!;
}

export async function seedAssessment(
  db: DbHandle,
  lotId: number,
  amount: number,
  chargeType = "DUES",
  date = "2024-01-01"
): Promise<number> {
  const r = await db.execute(
    `INSERT INTO assessments (lot_id, charge_type, amount, assessment_date, status)
     VALUES (?, ?, ?, ?, 'OPEN')`,
    [lotId, chargeType, amount, date]
  );
  return r.lastInsertId!;
}

export async function seedPayment(
  db: DbHandle,
  lotId: number,
  amount: number,
  batchId: number | null = null,
  date = "2024-01-15"
): Promise<number> {
  const r = await db.execute(
    `INSERT INTO payments (lot_id, deposit_batch_id, payment_date, amount, payment_method, payment_type)
     VALUES (?, ?, ?, ?, 'CHECK', 'DUES')`,
    [lotId, batchId, date, amount]
  );
  return r.lastInsertId!;
}

export async function seedDepositBatch(
  db: DbHandle,
  accountId: number,
  date = "2024-01-15"
): Promise<number> {
  const r = await db.execute(
    "INSERT INTO deposit_batches (deposit_date, bank_account_id) VALUES (?, ?)",
    [date, accountId]
  );
  return r.lastInsertId!;
}

export async function getCategoryId(db: DbHandle, code: string): Promise<number> {
  const rows = await db.select<{ id: number }[]>(
    "SELECT id FROM categories WHERE code = ?",
    [code]
  );
  if (!rows[0]) throw new Error(`Category '${code}' not found — run initSchema first`);
  return rows[0].id;
}
