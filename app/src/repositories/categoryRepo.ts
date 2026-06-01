import { getDb } from "../lib/db";
import { CategorySchema, type Category, type CategoryFormValues } from "../types/category";

const SELECT_ALL = `
  SELECT id, code, name, category_type, fund_code, sort_order,
         group_name, description, active_flag, system_required, created_at
  FROM   categories
  ORDER BY
    CASE category_type WHEN 'INCOME' THEN 1 WHEN 'EXPENSE' THEN 2 ELSE 3 END,
    sort_order, code
`;

export async function listCategories(): Promise<Category[]> {
  const db = await getDb();
  const rows = await db.select<unknown[]>(SELECT_ALL);
  return rows.map((r) => CategorySchema.parse(r));
}

export async function getCategory(id: number): Promise<Category | null> {
  const db = await getDb();
  const rows = await db.select<unknown[]>(
    `${SELECT_ALL.replace("ORDER BY", "WHERE id = ? ORDER BY")}`,
    [id]
  );
  return rows[0] ? CategorySchema.parse(rows[0]) : null;
}

export async function insertCategory(values: CategoryFormValues): Promise<number> {
  const db = await getDb();
  const result = await db.execute(
    `INSERT INTO categories (code, name, category_type, fund_code, sort_order, group_name, description)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
    [
      values.code,
      values.name,
      values.category_type,
      values.fund_code,
      values.sort_order,
      values.group_name ?? null,
      values.description ?? null,
    ]
  );
  return result.lastInsertId ?? 0;
}

export async function updateCategory(id: number, values: CategoryFormValues): Promise<void> {
  const db = await getDb();
  await db.execute(
    `UPDATE categories
     SET name = ?, fund_code = ?, sort_order = ?,
         group_name = ?, description = ?, active_flag = ?
     WHERE id = ?`,
    [
      values.name,
      values.fund_code,
      values.sort_order,
      values.group_name ?? null,
      values.description ?? null,
      values.active_flag,
      id,
    ]
  );
}

export async function deleteCategory(id: number): Promise<void> {
  const db = await getDb();
  await db.execute("DELETE FROM categories WHERE id = ? AND system_required = 0", [id]);
}

export async function countCategories(): Promise<number> {
  const db = await getDb();
  const rows = await db.select<[{ n: number }]>("SELECT COUNT(*) as n FROM categories");
  return rows[0]?.n ?? 0;
}

export async function bulkInsertCategories(items: CategoryFormValues[]): Promise<void> {
  const db = await getDb();
  for (const v of items) {
    await db.execute(
      `INSERT OR IGNORE INTO categories (code, name, category_type, fund_code, sort_order, group_name, description)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [v.code, v.name, v.category_type, v.fund_code, v.sort_order, v.group_name ?? null, v.description ?? null]
    );
  }
}

export async function usageCount(id: number): Promise<number> {
  const db = await getDb();
  const rows = await db.select<[{ n: number }]>(
    "SELECT COUNT(*) as n FROM categories WHERE id = ?",
    [id]
  );
  // Will be expanded to check FK tables once they exist
  const row = rows[0];
  return row ? row.n : 0;
}
