import { getDb } from "../lib/db";
import { VendorSchema, type Vendor, type VendorFormValues } from "../types/vendor";

export async function listVendors(activeOnly = true): Promise<Vendor[]> {
  const db = await getDb();
  const sql = activeOnly
    ? "SELECT * FROM vendors WHERE active_flag = 1 ORDER BY vendor_name"
    : "SELECT * FROM vendors ORDER BY vendor_name";
  const rows = await db.select<unknown[]>(sql);
  return rows.map((r) => VendorSchema.parse(r));
}

export async function getVendor(id: number): Promise<Vendor | null> {
  const db = await getDb();
  const rows = await db.select<unknown[]>("SELECT * FROM vendors WHERE id = ?", [id]);
  return rows[0] ? VendorSchema.parse(rows[0]) : null;
}

export async function insertVendor(values: VendorFormValues): Promise<number> {
  const db = await getDb();
  const result = await db.execute(
    `INSERT INTO vendors
       (vendor_name, contact_name, email, phone,
        address_1, address_2, city, state, postal_code, notes)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    [
      values.vendor_name,
      values.contact_name ?? null,
      values.email ?? null,
      values.phone ?? null,
      values.address_1 ?? null,
      values.address_2 ?? null,
      values.city ?? null,
      values.state ?? null,
      values.postal_code ?? null,
      values.notes ?? null,
    ]
  );
  return result.lastInsertId ?? 0;
}

export async function updateVendor(id: number, values: VendorFormValues): Promise<void> {
  const db = await getDb();
  await db.execute(
    `UPDATE vendors
     SET vendor_name = ?, contact_name = ?, email = ?, phone = ?,
         address_1 = ?, address_2 = ?, city = ?, state = ?,
         postal_code = ?, notes = ?, active_flag = ?,
         updated_at = datetime('now')
     WHERE id = ?`,
    [
      values.vendor_name,
      values.contact_name ?? null,
      values.email ?? null,
      values.phone ?? null,
      values.address_1 ?? null,
      values.address_2 ?? null,
      values.city ?? null,
      values.state ?? null,
      values.postal_code ?? null,
      values.notes ?? null,
      values.active_flag,
      id,
    ]
  );
}

export async function deleteVendor(id: number): Promise<void> {
  const db = await getDb();
  await db.execute("DELETE FROM vendors WHERE id = ?", [id]);
}

export async function hasBills(id: number): Promise<boolean> {
  const db = await getDb();
  const rows = await db.select<[{ n: number }]>(
    "SELECT COUNT(*) as n FROM vendor_bills WHERE vendor_id = ?",
    [id]
  );
  const row = rows[0];
  return row ? row.n > 0 : false;
}
