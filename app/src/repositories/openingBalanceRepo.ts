import { getDb } from "../lib/db";
import { OpeningBalanceSchema, type OpeningBalance, type OpeningBalanceFormValues } from "../types/openingBalance";

export async function getOpeningBalance(entityType: string, entityId: number): Promise<OpeningBalance | null> {
  const db = await getDb();
  const rows = await db.select<unknown[]>(
    "SELECT * FROM opening_balances WHERE entity_type = ? AND entity_id = ?",
    [entityType, entityId]
  );
  return rows[0] ? OpeningBalanceSchema.parse(rows[0]) : null;
}

export async function listOpeningBalances(entityType: string): Promise<OpeningBalance[]> {
  const db = await getDb();
  const rows = await db.select<unknown[]>(
    "SELECT * FROM opening_balances WHERE entity_type = ? ORDER BY entity_id",
    [entityType]
  );
  return rows.map((r) => OpeningBalanceSchema.parse(r));
}

export async function upsertOpeningBalance(
  entityType: string,
  entityId: number,
  values: OpeningBalanceFormValues
): Promise<void> {
  const db = await getDb();
  await db.execute(
    `INSERT INTO opening_balances (entity_type, entity_id, as_of_date, amount, notes)
     VALUES (?, ?, ?, ?, ?)
     ON CONFLICT(entity_type, entity_id) DO UPDATE SET
       as_of_date = excluded.as_of_date,
       amount     = excluded.amount,
       notes      = excluded.notes,
       updated_at = datetime('now')`,
    [entityType, entityId, values.as_of_date, values.amount, values.notes ?? null]
  );
}
