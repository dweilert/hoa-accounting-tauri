import { getDb } from "../lib/db";
import { DepositBatchSchema, PaymentSchema, type DepositBatch, type Payment, type PaymentFormValues } from "../types/deposit";

const PAYMENT_BASE = `
  SELECT p.*,
         l.lot_number,
         o.display_name AS owner_name
  FROM payments p
  JOIN lots l ON l.id = p.lot_id
  LEFT JOIN owners o ON o.id = p.owner_id
`;

export type PaymentRow = Payment & { lot_number: string; owner_name: string | null };

const PaymentRowSchema = PaymentSchema.extend({
  lot_number: PaymentSchema.shape.memo.unwrap(),
  owner_name: PaymentSchema.shape.memo,
});

export async function listDepositBatches(limit = 100): Promise<(DepositBatch & { account_name: string })[]> {
  const db = await getDb();
  const rows = await db.select<unknown[]>(
    `SELECT d.*, b.account_name
     FROM deposit_batches d
     JOIN bank_accounts b ON b.id = d.bank_account_id
     ORDER BY d.deposit_date DESC LIMIT ?`,
    [limit]
  );
  return rows.map((r) => DepositBatchSchema.extend({ account_name: DepositBatchSchema.shape.notes.unwrap() }).parse(r));
}

export async function insertDepositBatch(
  deposit_date: string,
  bank_account_id: number,
  notes?: string
): Promise<number> {
  const db = await getDb();
  const result = await db.execute(
    "INSERT INTO deposit_batches (deposit_date, bank_account_id, notes) VALUES (?, ?, ?)",
    [deposit_date, bank_account_id, notes ?? null]
  );
  return result.lastInsertId ?? 0;
}

export async function postDepositBatch(id: number): Promise<void> {
  const db = await getDb();
  await db.execute(
    "UPDATE deposit_batches SET status = 'POSTED', updated_at = datetime('now') WHERE id = ?",
    [id]
  );
}

export async function listPaymentsForBatch(batchId: number): Promise<PaymentRow[]> {
  const db = await getDb();
  const rows = await db.select<unknown[]>(`${PAYMENT_BASE} WHERE p.deposit_batch_id = ?`, [batchId]);
  return rows.map((r) => PaymentRowSchema.parse(r));
}

export async function listPayments(limit = 100): Promise<PaymentRow[]> {
  const db = await getDb();
  const rows = await db.select<unknown[]>(`${PAYMENT_BASE} ORDER BY p.payment_date DESC LIMIT ?`, [limit]);
  return rows.map((r) => PaymentRowSchema.parse(r));
}

export async function insertPayment(batchId: number | null, values: PaymentFormValues): Promise<number> {
  const db = await getDb();
  const result = await db.execute(
    `INSERT INTO payments (lot_id, owner_id, deposit_batch_id, payment_date, amount, payment_method, check_number, memo)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    [
      values.lot_id,
      values.owner_id ?? null,
      batchId,
      values.payment_date,
      values.amount,
      values.payment_method,
      values.check_number ?? null,
      values.memo ?? null,
    ]
  );
  const id = result.lastInsertId ?? 0;

  if (batchId) {
    await db.execute(
      `UPDATE deposit_batches
       SET total_amount = (SELECT COALESCE(SUM(amount),0) FROM payments WHERE deposit_batch_id = ?),
           check_count  = (SELECT COUNT(*) FROM payments WHERE deposit_batch_id = ?),
           updated_at   = datetime('now')
       WHERE id = ?`,
      [batchId, batchId, batchId]
    );
  }
  return id;
}

export async function deletePayment(paymentId: number, batchId: number | null): Promise<void> {
  const db = await getDb();
  await db.execute("DELETE FROM payments WHERE id = ?", [paymentId]);
  if (batchId) {
    await db.execute(
      `UPDATE deposit_batches
       SET total_amount = (SELECT COALESCE(SUM(amount),0) FROM payments WHERE deposit_batch_id = ?),
           check_count  = (SELECT COUNT(*) FROM payments WHERE deposit_batch_id = ?),
           updated_at   = datetime('now')
       WHERE id = ?`,
      [batchId, batchId, batchId]
    );
  }
}
