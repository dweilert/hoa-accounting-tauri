import { getDb } from "../lib/db";
import { AssessmentSchema, type Assessment, type AssessmentFormValues } from "../types/assessment";

const BASE = `
  SELECT a.*,
         l.lot_number,
         o.display_name AS owner_name
  FROM assessments a
  JOIN lots l ON l.id = a.lot_id
  LEFT JOIN owners o ON o.id = a.owner_id
`;

export type AssessmentRow = Assessment & { lot_number: string; owner_name: string | null };

const RowSchema = AssessmentSchema.extend({
  lot_number: AssessmentSchema.shape.description.unwrap(),
  owner_name: AssessmentSchema.shape.description,
});

export async function listAssessments(opts?: {
  lotId?: number;
  status?: string;
  limit?: number;
}): Promise<AssessmentRow[]> {
  const db = await getDb();
  const conditions: string[] = [];
  const params: unknown[] = [];

  if (opts?.lotId) { conditions.push("a.lot_id = ?"); params.push(opts.lotId); }
  if (opts?.status) { conditions.push("a.status = ?"); params.push(opts.status); }

  const where = conditions.length ? `WHERE ${conditions.join(" AND ")}` : "";
  const limit = opts?.limit ? `LIMIT ${opts.limit}` : "";
  const rows = await db.select<unknown[]>(`${BASE} ${where} ORDER BY a.assessment_date DESC ${limit}`, params);
  return rows.map((r) => RowSchema.parse(r));
}

export async function listOpenAssessments(): Promise<AssessmentRow[]> {
  const db = await getDb();
  const rows = await db.select<unknown[]>(
    `${BASE} WHERE a.status IN ('OPEN','PARTIAL') ORDER BY a.due_date ASC, a.assessment_date ASC`
  );
  return rows.map((r) => RowSchema.parse(r));
}

export async function getAssessment(id: number): Promise<AssessmentRow | null> {
  const db = await getDb();
  const rows = await db.select<unknown[]>(`${BASE} WHERE a.id = ?`, [id]);
  return rows[0] ? RowSchema.parse(rows[0]) : null;
}

export async function insertAssessment(values: AssessmentFormValues): Promise<number> {
  const db = await getDb();
  const result = await db.execute(
    `INSERT INTO assessments (lot_id, owner_id, charge_type, amount, assessment_date, due_date, description, category_id)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    [
      values.lot_id,
      values.owner_id ?? null,
      values.charge_type,
      values.amount,
      values.assessment_date,
      values.due_date ?? null,
      values.description ?? null,
      values.category_id ?? null,
    ]
  );
  return result.lastInsertId ?? 0;
}

export async function updateAssessment(id: number, values: AssessmentFormValues): Promise<void> {
  const db = await getDb();
  await db.execute(
    `UPDATE assessments
     SET lot_id = ?, owner_id = ?, charge_type = ?, amount = ?,
         assessment_date = ?, due_date = ?, description = ?, category_id = ?,
         updated_at = datetime('now')
     WHERE id = ? AND status IN ('OPEN','PARTIAL')`,
    [
      values.lot_id,
      values.owner_id ?? null,
      values.charge_type,
      values.amount,
      values.assessment_date,
      values.due_date ?? null,
      values.description ?? null,
      values.category_id ?? null,
      id,
    ]
  );
}

export async function voidAssessment(id: number): Promise<void> {
  const db = await getDb();
  await db.execute(
    "UPDATE assessments SET status = 'VOID', updated_at = datetime('now') WHERE id = ? AND status IN ('OPEN','PARTIAL')",
    [id]
  );
}

export async function writeOffAssessment(id: number): Promise<void> {
  const db = await getDb();
  await db.execute(
    "UPDATE assessments SET status = 'WRITTEN_OFF', updated_at = datetime('now') WHERE id = ? AND status IN ('OPEN','PARTIAL')",
    [id]
  );
}

export async function getAssessmentSummary(): Promise<{
  openCount: number;
  openAmount: number;
  partialCount: number;
  partialAmount: number;
}> {
  const db = await getDb();
  const rows = await db.select<Array<{ status: string; cnt: number; total: number }>>(
    `SELECT status, COUNT(*) as cnt, COALESCE(SUM(amount),0) as total
     FROM assessments WHERE status IN ('OPEN','PARTIAL') GROUP BY status`
  );
  const byStatus = new Map(rows.map((r) => [r.status, r]));
  return {
    openCount: byStatus.get("OPEN")?.cnt ?? 0,
    openAmount: byStatus.get("OPEN")?.total ?? 0,
    partialCount: byStatus.get("PARTIAL")?.cnt ?? 0,
    partialAmount: byStatus.get("PARTIAL")?.total ?? 0,
  };
}
