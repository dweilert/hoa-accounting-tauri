import { getDb } from "../lib/db";
import { OwnerSchema, OwnerWithLotsSchema, type Owner, type OwnerWithLots, type OwnerFormValues } from "../types/owner";

export async function listOwners(): Promise<OwnerWithLots[]> {
  const db = await getDb();
  const rows = await db.select<unknown[]>(`
    SELECT o.*,
           GROUP_CONCAT(l.lot_number, ', ') AS lot_numbers
    FROM   owners o
    LEFT JOIN lot_ownership lo ON lo.owner_id = o.id AND lo.end_date IS NULL
    LEFT JOIN lots l            ON l.id = lo.lot_id
    GROUP BY o.id
    ORDER BY o.display_name
  `);
  return rows.map((r) => OwnerWithLotsSchema.parse(r));
}

export async function getOwner(id: number): Promise<Owner | null> {
  const db = await getDb();
  const rows = await db.select<unknown[]>("SELECT * FROM owners WHERE id = ?", [id]);
  return rows[0] ? OwnerSchema.parse(rows[0]) : null;
}

export async function insertOwner(values: OwnerFormValues): Promise<number> {
  const db = await getDb();
  const result = await db.execute(
    `INSERT INTO owners
       (owner_type, display_name, first_name, last_name, entity_name,
        mailing_address_1, mailing_address_2, city, state, postal_code,
        phone, home_phone, email, notes)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    [
      values.owner_type,
      values.display_name,
      values.first_name ?? null,
      values.last_name ?? null,
      values.entity_name ?? null,
      values.mailing_address_1 ?? null,
      values.mailing_address_2 ?? null,
      values.city ?? null,
      values.state ?? null,
      values.postal_code ?? null,
      values.phone ?? null,
      values.home_phone ?? null,
      values.email ?? null,
      values.notes ?? null,
    ]
  );
  return result.lastInsertId ?? 0;
}

export async function updateOwner(id: number, values: OwnerFormValues): Promise<void> {
  const db = await getDb();
  await db.execute(
    `UPDATE owners
     SET owner_type = ?, display_name = ?, first_name = ?, last_name = ?,
         entity_name = ?, mailing_address_1 = ?, mailing_address_2 = ?,
         city = ?, state = ?, postal_code = ?, phone = ?, home_phone = ?,
         email = ?, notes = ?, active_flag = ?, updated_at = datetime('now')
     WHERE id = ?`,
    [
      values.owner_type,
      values.display_name,
      values.first_name ?? null,
      values.last_name ?? null,
      values.entity_name ?? null,
      values.mailing_address_1 ?? null,
      values.mailing_address_2 ?? null,
      values.city ?? null,
      values.state ?? null,
      values.postal_code ?? null,
      values.phone ?? null,
      values.home_phone ?? null,
      values.email ?? null,
      values.notes ?? null,
      values.active_flag,
      id,
    ]
  );
}

export async function deactivateOwner(id: number): Promise<void> {
  const db = await getDb();
  const today = new Date().toISOString().slice(0, 10);
  await db.execute(
    "UPDATE lot_ownership SET end_date = ? WHERE owner_id = ? AND end_date IS NULL",
    [today, id]
  );
  await db.execute(
    "UPDATE owners SET active_flag = 0, updated_at = datetime('now') WHERE id = ?",
    [id]
  );
}
