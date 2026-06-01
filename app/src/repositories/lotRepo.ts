import { getDb } from "../lib/db";
import { LotSchema, LotWithOwnerSchema, type Lot, type LotWithOwner, type LotFormValues } from "../types/lot";

export async function listLots(activeOnly = false): Promise<LotWithOwner[]> {
  const db = await getDb();
  const where = activeOnly ? "WHERE l.active_flag = 1" : "";
  const rows = await db.select<unknown[]>(`
    SELECT l.*,
           GROUP_CONCAT(o.display_name, ', ') AS owner_names
    FROM   lots l
    LEFT JOIN lot_ownership lo ON lo.lot_id = l.id AND lo.end_date IS NULL
    LEFT JOIN owners o         ON o.id = lo.owner_id
    ${where}
    GROUP BY l.id
    ORDER BY l.lot_number
  `);
  return rows.map((r) => LotWithOwnerSchema.parse(r));
}

export async function getLot(id: number): Promise<Lot | null> {
  const db = await getDb();
  const rows = await db.select<unknown[]>("SELECT * FROM lots WHERE id = ?", [id]);
  return rows[0] ? LotSchema.parse(rows[0]) : null;
}

export async function insertLot(values: LotFormValues): Promise<number> {
  const db = await getDb();
  const result = await db.execute(
    `INSERT INTO lots (lot_number, street_address_1, street_address_2, city, state, postal_code, legal_description)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
    [
      values.lot_number,
      values.street_address_1 ?? null,
      values.street_address_2 ?? null,
      values.city ?? null,
      values.state ?? null,
      values.postal_code ?? null,
      values.legal_description ?? null,
    ]
  );
  return result.lastInsertId ?? 0;
}

export async function updateLot(id: number, values: LotFormValues): Promise<void> {
  const db = await getDb();
  await db.execute(
    `UPDATE lots
     SET lot_number = ?, street_address_1 = ?, street_address_2 = ?,
         city = ?, state = ?, postal_code = ?, legal_description = ?,
         active_flag = ?, updated_at = datetime('now')
     WHERE id = ?`,
    [
      values.lot_number,
      values.street_address_1 ?? null,
      values.street_address_2 ?? null,
      values.city ?? null,
      values.state ?? null,
      values.postal_code ?? null,
      values.legal_description ?? null,
      values.active_flag,
      id,
    ]
  );
}

export async function deleteLot(id: number): Promise<void> {
  const db = await getDb();
  await db.execute("DELETE FROM lot_ownership WHERE lot_id = ?", [id]);
  await db.execute("DELETE FROM lot_renters WHERE lot_id = ?", [id]);
  await db.execute("DELETE FROM lots WHERE id = ?", [id]);
}

export async function hasCurrentOwners(lotId: number): Promise<boolean> {
  const db = await getDb();
  const rows = await db.select<[{ n: number }]>(
    "SELECT COUNT(*) as n FROM lot_ownership WHERE lot_id = ? AND end_date IS NULL",
    [lotId]
  );
  const row = rows[0];
  return row ? row.n > 0 : false;
}

// Assign an owner to a lot (closes any existing open ownership first if replacing)
export async function assignOwner(
  lotId: number,
  ownerId: number,
  startDate: string,
  ownershipPercent = 100
): Promise<void> {
  const db = await getDb();
  await db.execute(
    `INSERT INTO lot_ownership (lot_id, owner_id, start_date, ownership_percent)
     VALUES (?, ?, ?, ?)`,
    [lotId, ownerId, startDate, ownershipPercent]
  );
}

export async function endOwnership(lotOwnershipId: number, endDate: string): Promise<void> {
  const db = await getDb();
  await db.execute(
    "UPDATE lot_ownership SET end_date = ? WHERE id = ?",
    [endDate, lotOwnershipId]
  );
}
