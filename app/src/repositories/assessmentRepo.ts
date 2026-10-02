import { z } from "zod";
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
  lot_number: z.string(),
  owner_name: z.string().nullable(),
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
  const assessmentId = result.lastInsertId ?? 0;
  if (assessmentId > 0) await autoApplyCredit(db, values.lot_id, assessmentId, values.amount);
  return assessmentId;
}

async function autoApplyCredit(
  db: Awaited<ReturnType<typeof getDb>>,
  lotId: number,
  assessmentId: number,
  assessmentAmount: number
): Promise<void> {
  // Find payments with unapplied balance for this lot, oldest first
  const unapplied = await db.select<Array<{ id: number; unapplied: number }>>(
    `SELECT p.id, ROUND(p.amount - COALESCE(SUM(pa.amount), 0), 2) AS unapplied
     FROM payments p
     LEFT JOIN payment_applications pa ON pa.payment_id = p.id
     WHERE p.lot_id = ?
     GROUP BY p.id
     HAVING unapplied > 0.005
     ORDER BY p.payment_date ASC`,
    [lotId]
  );
  if (unapplied.length === 0) return;

  let remaining = assessmentAmount;
  for (const pmt of unapplied) {
    if (remaining <= 0.005) break;
    const apply = Math.min(remaining, pmt.unapplied);
    await db.execute(
      "INSERT OR IGNORE INTO payment_applications (payment_id, assessment_id, amount) VALUES (?, ?, ?)",
      [pmt.id, assessmentId, Math.round(apply * 100) / 100]
    );
    remaining = Math.round((remaining - apply) * 100) / 100;
  }
  // Update assessment status based on how much was applied
  const applied = assessmentAmount - remaining;
  if (applied >= assessmentAmount - 0.005) {
    await db.execute("UPDATE assessments SET status='PAID', updated_at=datetime('now') WHERE id=?", [assessmentId]);
  } else if (applied > 0.005) {
    await db.execute("UPDATE assessments SET status='PARTIAL', updated_at=datetime('now') WHERE id=?", [assessmentId]);
  }
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

export type LotBalance = {
  lot_id: number;
  lot_number: string;
  owner_name: string | null;
  opening_balance: number;
  billed: number;
  paid: number;
  balance_due: number; // positive = owes, negative = credit
};

export async function getLotBalances(): Promise<LotBalance[]> {
  const db = await getDb();
  const rows = await db.select<LotBalance[]>(`
    SELECT
      l.id AS lot_id,
      l.lot_number,
      (SELECT o.display_name FROM lot_ownership lo JOIN owners o ON o.id = lo.owner_id
       WHERE lo.lot_id = l.id AND lo.end_date IS NULL LIMIT 1) AS owner_name,
      COALESCE(ob.amount, 0) AS opening_balance,
      COALESCE((SELECT SUM(a.amount) FROM assessments a
                WHERE a.lot_id = l.id AND a.status NOT IN ('VOID','WRITTEN_OFF')), 0) AS billed,
      COALESCE((SELECT SUM(p.amount) FROM payments p
                WHERE p.lot_id = l.id), 0) AS paid,
      COALESCE(ob.amount, 0)
        + COALESCE((SELECT SUM(a.amount) FROM assessments a
                    WHERE a.lot_id = l.id AND a.status NOT IN ('VOID','WRITTEN_OFF')), 0)
        - COALESCE((SELECT SUM(p.amount) FROM payments p
                    WHERE p.lot_id = l.id), 0) AS balance_due
    FROM lots l
    LEFT JOIN opening_balances ob ON ob.entity_type = 'LOT_DUES' AND ob.entity_id = l.id
    WHERE l.active_flag = 1
    ORDER BY l.lot_number
  `);
  return rows;
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
