import { z } from "zod";
import { getDb } from "../lib/db";
import { DepositBatchSchema, PaymentSchema, type DepositBatch, type Payment, type PaymentFormValues } from "../types/deposit";

const BATCH_TOTALS_SQL = `
  UPDATE deposit_batches
  SET total_amount = (SELECT COALESCE(SUM(amount),0) FROM payments WHERE deposit_batch_id = ?),
      check_count  = (SELECT COUNT(*) FROM payments WHERE deposit_batch_id = ?),
      updated_at   = datetime('now')
  WHERE id = ?`;

const PAYMENT_BASE = `
  SELECT p.*,
         l.lot_number,
         CASE
           WHEN p.owner_id IS NOT NULL THEN
             (SELECT o2.display_name FROM owners o2 WHERE o2.id = p.owner_id)
           ELSE
             (SELECT GROUP_CONCAT(o2.display_name, ' / ')
              FROM lot_ownership lo2
              JOIN owners o2 ON o2.id = lo2.owner_id
              WHERE lo2.lot_id = p.lot_id
                AND lo2.start_date <= p.payment_date
                AND (lo2.end_date IS NULL OR lo2.end_date >= p.payment_date))
         END AS owner_name
  FROM payments p
  JOIN lots l ON l.id = p.lot_id
`;

export type PaymentRow = Payment & { lot_number: string; owner_name: string | null };

const PaymentRowSchema = PaymentSchema.extend({
  lot_number: z.string(),
  owner_name: z.string().nullable(),
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
  return rows.map((r) => DepositBatchSchema.extend({ account_name: z.string() }).parse(r));
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

export async function updateDepositBatch(
  id: number,
  deposit_date: string,
  bank_account_id: number,
  notes: string
): Promise<void> {
  const db = await getDb();
  await db.execute(
    `UPDATE deposit_batches
     SET deposit_date = ?, bank_account_id = ?, notes = ?, updated_at = datetime('now')
     WHERE id = ?`,
    [deposit_date, bank_account_id, notes || null, id]
  );
}

export async function listPaymentsForBatch(batchId: number): Promise<PaymentRow[]> {
  const db = await getDb();
  const rows = await db.select<unknown[]>(`${PAYMENT_BASE} WHERE p.deposit_batch_id = ? ORDER BY p.payment_date ASC`, [batchId]);
  return rows.map((r) => PaymentRowSchema.parse(r));
}

export async function listUnassignedPayments(): Promise<PaymentRow[]> {
  const db = await getDb();
  const rows = await db.select<unknown[]>(`${PAYMENT_BASE} WHERE p.deposit_batch_id IS NULL ORDER BY p.payment_date DESC`);
  return rows.map((r) => PaymentRowSchema.parse(r));
}

export async function assignPaymentsToBatch(paymentIds: number[], batchId: number): Promise<void> {
  if (paymentIds.length === 0) return;
  const db = await getDb();
  const inClause = paymentIds.join(",");
  await db.execute(`UPDATE payments SET deposit_batch_id = ? WHERE id IN (${inClause})`, [batchId]);
  await db.execute(BATCH_TOTALS_SQL, [batchId, batchId, batchId]);
}

export async function unassignPaymentFromBatch(paymentId: number, batchId: number): Promise<void> {
  const db = await getDb();
  await db.execute("UPDATE payments SET deposit_batch_id = NULL WHERE id = ?", [paymentId]);
  await db.execute(BATCH_TOTALS_SQL, [batchId, batchId, batchId]);
}

export async function listPayments(limit = 100): Promise<PaymentRow[]> {
  const db = await getDb();
  const rows = await db.select<unknown[]>(`${PAYMENT_BASE} ORDER BY p.payment_date DESC LIMIT ?`, [limit]);
  return rows.map((r) => PaymentRowSchema.parse(r));
}

export async function listPaymentsForLot(lotId: number, limit = 100): Promise<PaymentRow[]> {
  const db = await getDb();
  const rows = await db.select<unknown[]>(
    `${PAYMENT_BASE} WHERE p.lot_id = ? ORDER BY p.payment_date DESC LIMIT ?`,
    [lotId, limit]
  );
  return rows.map((r) => PaymentRowSchema.parse(r));
}

async function resolveOwnerAtDate(lotId: number, paymentDate: string): Promise<number | null> {
  const db = await getDb();
  const rows = await db.select<{ owner_id: number }[]>(
    `SELECT owner_id FROM lot_ownership
     WHERE lot_id = ? AND start_date <= ? AND (end_date IS NULL OR end_date >= ?)`,
    [lotId, paymentDate, paymentDate]
  );
  return rows.length === 1 ? (rows[0]?.owner_id ?? null) : null;
}

export async function insertPayment(batchId: number | null, values: PaymentFormValues): Promise<number> {
  const db = await getDb();
  const ownerId = values.owner_id ?? await resolveOwnerAtDate(values.lot_id, values.payment_date);
  const result = await db.execute(
    `INSERT INTO payments (lot_id, owner_id, deposit_batch_id, payment_date, amount, payment_method, payment_type, check_number, memo)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    [
      values.lot_id,
      ownerId,
      batchId,
      values.payment_date,
      values.amount,
      values.payment_method,
      values.payment_type ?? "DUES",
      values.check_number ?? null,
      values.memo ?? null,
    ]
  );
  const id = result.lastInsertId ?? 0;
  if (batchId) await db.execute(BATCH_TOTALS_SQL, [batchId, batchId, batchId]);
  return id;
}

// ── OFX / Bank-transaction matching ──────────────────────────────────────────

export type OFXCandidate = {
  id: number;
  transaction_date: string;
  amount: number;
  description: string;
  memo: string | null;
  days_diff: number;
  amount_diff: number;
};

export async function listCandidateBankTxns(
  bankAccountId: number,
  totalAmount: number,
  depositDate: string,
  daysTolerance = 14,
  amountTolerancePct = 0.05
): Promise<OFXCandidate[]> {
  const db = await getDb();
  const amountMin = totalAmount * (1 - amountTolerancePct);
  const amountMax = totalAmount * (1 + amountTolerancePct);
  const rows = await db.select<OFXCandidate[]>(
    `SELECT id, transaction_date, amount, COALESCE(description,'') AS description, memo,
            ABS(julianday(transaction_date) - julianday(?)) AS days_diff,
            ABS(amount - ?) AS amount_diff
     FROM bank_transactions
     WHERE bank_account_id = ?
       AND amount BETWEEN ? AND ?
       AND ABS(julianday(transaction_date) - julianday(?)) <= ?
     ORDER BY days_diff ASC, amount_diff ASC
     LIMIT 20`,
    [depositDate, totalAmount, bankAccountId, amountMin, amountMax, depositDate, daysTolerance]
  );
  return rows;
}

export type CandidateDepositBatch = {
  id: number;
  deposit_date: string;
  total_amount: number;
  check_count: number;
  status: string;
  bank_transaction_id: number | null;
  days_diff: number;
  amount_diff: number;
  same_amount_count: number; // how many deposit batches in account share this amount (±1%)
};

export async function listCandidateDepositBatches(
  bankAccountId: number,
  amount: number,
  txnDate: string,
  daysTolerance = 14,
  amountTolerancePct = 0.05
): Promise<CandidateDepositBatch[]> {
  const db = await getDb();
  const amountMin = amount * (1 - amountTolerancePct);
  const amountMax = amount * (1 + amountTolerancePct);
  // Tight tolerance for uniqueness check (±1%) — determines if amount is unambiguous
  const uniqueMin = amount * 0.99;
  const uniqueMax = amount * 1.01;
  return db.select<CandidateDepositBatch[]>(
    `SELECT id, deposit_date, total_amount, check_count, status, bank_transaction_id,
            ABS(julianday(deposit_date) - julianday(?)) AS days_diff,
            ABS(total_amount - ?) AS amount_diff,
            (SELECT COUNT(*) FROM deposit_batches d2
             WHERE d2.bank_account_id = ? AND d2.total_amount BETWEEN ? AND ?) AS same_amount_count
     FROM deposit_batches
     WHERE bank_account_id = ?
       AND total_amount BETWEEN ? AND ?
       AND ABS(julianday(deposit_date) - julianday(?)) <= ?
     ORDER BY days_diff ASC, amount_diff ASC
     LIMIT 20`,
    [txnDate, amount, bankAccountId, uniqueMin, uniqueMax, bankAccountId, amountMin, amountMax, txnDate, daysTolerance]
  );
}

export async function linkDepositToTxn(batchId: number, txnId: number): Promise<void> {
  const db = await getDb();
  await db.execute(
    "UPDATE deposit_batches SET bank_transaction_id = ?, updated_at = datetime('now') WHERE id = ?",
    [txnId, batchId]
  );
}

export type AutoMatchResult = {
  total: number;           // UNVALIDATED positive txns scanned
  matched: number;         // auto-linked
  skipped: number;         // ambiguous (multiple candidates qualified)
  details: { txn_id: number; txn_date: string; amount: number; batch_id: number; batch_date: string; reason: string }[];
};

export async function autoMatchDeposits(
  bankAccountId?: number,
  dryRun = true
): Promise<AutoMatchResult> {
  const db = await getDb();
  const acctFilter = bankAccountId ? "AND bank_account_id = ?" : "";
  const params: (number | string)[] = bankAccountId ? [bankAccountId] : [];

  // Positive UNVALIDATED transactions only — deposits come in as positive amounts
  const txns = await db.select<{ id: number; bank_account_id: number; amount: number; transaction_date: string; description: string }[]>(
    `SELECT id, bank_account_id, amount, transaction_date, COALESCE(description,'') AS description
     FROM bank_transactions
     WHERE validation_status = 'UNVALIDATED' AND amount > 0 ${acctFilter}
     ORDER BY transaction_date DESC`,
    params
  );

  const details: AutoMatchResult["details"] = [];
  let matched = 0;
  let skipped = 0;

  for (const txn of txns) {
    const candidates = await listCandidateDepositBatches(
      txn.bank_account_id, txn.amount, txn.transaction_date
    );

    // POSTED, unlinked, within 3 days — sorted closest-date-first by the query.
    // Take the closest match; no uniqueness restriction.
    const qualified = candidates.filter(
      (c) => c.status === "POSTED" &&
             c.bank_transaction_id === null &&
             c.days_diff <= 3
    );

    if (qualified[0]) {
      const batch = qualified[0];
      const reason = batch.days_diff === 0 ? "exact date" : `${Math.round(batch.days_diff)}d off`;
      details.push({
        txn_id: txn.id,
        txn_date: txn.transaction_date,
        amount: txn.amount,
        batch_id: batch.id,
        batch_date: batch.deposit_date,
        reason,
      });
      if (!dryRun) {
        await db.execute(
          "UPDATE deposit_batches SET bank_transaction_id = ?, updated_at = datetime('now') WHERE id = ?",
          [txn.id, batch.id]
        );
        await db.execute(
          "UPDATE bank_transactions SET validation_status = 'VALIDATED' WHERE id = ?",
          [txn.id]
        );
      }
      matched++;
    } else {
      skipped++;
    }
  }

  return { total: txns.length, matched, skipped, details };
}

export async function unlinkDepositTxn(batchId: number): Promise<void> {
  const db = await getDb();
  await db.execute(
    "UPDATE deposit_batches SET bank_transaction_id = NULL, updated_at = datetime('now') WHERE id = ?",
    [batchId]
  );
}

export async function deleteDepositBatch(batchId: number): Promise<void> {
  const db = await getDb();
  await db.execute("DELETE FROM deposit_batches WHERE id = ? AND COALESCE(total_amount, 0) = 0", [batchId]);
}

export async function deletePayment(paymentId: number, batchId: number | null): Promise<void> {
  const db = await getDb();
  await db.execute("DELETE FROM payments WHERE id = ?", [paymentId]);
  if (batchId) await db.execute(BATCH_TOTALS_SQL, [batchId, batchId, batchId]);
}
