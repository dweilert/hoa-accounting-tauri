import { getDb } from "../lib/db";
import { BankReconciliationSchema, BankTransactionSchema, type BankReconciliation, type BankTransaction } from "../types/reconciliation";

export async function listReconciliations(bankAccountId?: number): Promise<(BankReconciliation & { account_name: string })[]> {
  const db = await getDb();
  const where = bankAccountId ? `WHERE r.bank_account_id = ${bankAccountId}` : "";
  const rows = await db.select<unknown[]>(
    `SELECT r.*, b.account_name
     FROM bank_reconciliations r
     JOIN bank_accounts b ON b.id = r.bank_account_id
     ${where}
     ORDER BY r.statement_ending_date DESC`
  );
  return rows.map((r) =>
    BankReconciliationSchema.extend({ account_name: BankReconciliationSchema.shape.notes.unwrap() }).parse(r)
  );
}

export async function getReconciliation(id: number): Promise<BankReconciliation | null> {
  const db = await getDb();
  const rows = await db.select<unknown[]>("SELECT * FROM bank_reconciliations WHERE id = ?", [id]);
  return rows[0] ? BankReconciliationSchema.parse(rows[0]) : null;
}

export async function createReconciliation(
  bankAccountId: number,
  statementEndingDate: string,
  statementEndingBalance: number,
  beginningBalance: number,
  notes?: string
): Promise<number> {
  const db = await getDb();
  const result = await db.execute(
    `INSERT INTO bank_reconciliations
       (bank_account_id, statement_ending_date, statement_ending_balance, beginning_balance, notes)
     VALUES (?, ?, ?, ?, ?)`,
    [bankAccountId, statementEndingDate, statementEndingBalance, beginningBalance, notes ?? null]
  );
  return result.lastInsertId ?? 0;
}

export async function finalizeReconciliation(id: number, bookBalance: number): Promise<void> {
  const db = await getDb();
  await db.execute(
    "UPDATE bank_reconciliations SET status = 'FINALIZED', book_balance = ?, updated_at = datetime('now') WHERE id = ?",
    [bookBalance, id]
  );
}

export async function reopenReconciliation(id: number): Promise<void> {
  const db = await getDb();
  await db.execute(
    "UPDATE bank_reconciliations SET status = 'OPEN', updated_at = datetime('now') WHERE id = ?",
    [id]
  );
}

export async function deleteReconciliation(id: number): Promise<void> {
  const db = await getDb();
  await db.execute("DELETE FROM reconciliation_clears WHERE reconciliation_id = ?", [id]);
  await db.execute("DELETE FROM bank_reconciliations WHERE id = ? AND status = 'OPEN'", [id]);
}

export async function listBankTransactions(bankAccountId: number, opts?: {
  excludeIgnored?: boolean;
  limit?: number;
}): Promise<BankTransaction[]> {
  const db = await getDb();
  const conditions = [`bank_account_id = ?`];
  if (opts?.excludeIgnored) conditions.push("validation_status != 'IGNORED'");
  const limit = opts?.limit ? `LIMIT ${opts.limit}` : "";
  const rows = await db.select<unknown[]>(
    `SELECT * FROM bank_transactions WHERE ${conditions.join(" AND ")} ORDER BY transaction_date DESC ${limit}`,
    [bankAccountId]
  );
  return rows.map((r) => BankTransactionSchema.parse(r));
}

export async function listAllBankTransactions(opts?: { limit?: number }): Promise<(BankTransaction & { account_name: string })[]> {
  const db = await getDb();
  const limit = opts?.limit ? `LIMIT ${opts.limit}` : "LIMIT 200";
  const rows = await db.select<unknown[]>(
    `SELECT t.*, b.account_name
     FROM bank_transactions t
     JOIN bank_accounts b ON b.id = t.bank_account_id
     WHERE t.validation_status != 'IGNORED'
     ORDER BY t.transaction_date DESC ${limit}`
  );
  return rows.map((r) =>
    BankTransactionSchema.extend({ account_name: BankTransactionSchema.shape.description.unwrap() }).parse(r)
  );
}

export async function getClearedTransactionIds(reconciliationId: number): Promise<Set<number>> {
  const db = await getDb();
  const rows = await db.select<Array<{ bank_transaction_id: number }>>(
    "SELECT bank_transaction_id FROM reconciliation_clears WHERE reconciliation_id = ?",
    [reconciliationId]
  );
  return new Set(rows.map((r) => r.bank_transaction_id));
}

export async function toggleClear(reconciliationId: number, transactionId: number, cleared: boolean): Promise<void> {
  const db = await getDb();
  if (cleared) {
    await db.execute(
      "INSERT OR IGNORE INTO reconciliation_clears (reconciliation_id, bank_transaction_id) VALUES (?, ?)",
      [reconciliationId, transactionId]
    );
  } else {
    await db.execute(
      "DELETE FROM reconciliation_clears WHERE reconciliation_id = ? AND bank_transaction_id = ?",
      [reconciliationId, transactionId]
    );
  }
}

export async function insertBankTransaction(
  bankAccountId: number,
  date: string,
  amount: number,
  description: string,
  memo?: string,
  batchId?: number
): Promise<number> {
  const db = await getDb();
  const dedupKey = `manual-${date}-${amount}-${description}`.slice(0, 100);
  const result = await db.execute(
    `INSERT OR IGNORE INTO bank_transactions
       (bank_account_id, transaction_date, amount, description, memo, dedup_key, import_batch_id)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
    [bankAccountId, date, amount, description, memo ?? null, dedupKey, batchId ?? null]
  );
  return result.lastInsertId ?? 0;
}

export async function getExistingDedupKeys(bankAccountId: number): Promise<Set<string>> {
  const db = await getDb();
  const rows = await db.select<{ dedup_key: string }[]>(
    "SELECT dedup_key FROM bank_transactions WHERE bank_account_id = ? AND dedup_key IS NOT NULL",
    [bankAccountId]
  );
  return new Set(rows.map((r) => r.dedup_key));
}

export type ImportBatch = {
  id: number;
  bank_account_id: number;
  filename: string | null;
  imported_count: number;
  skipped_count: number;
  imported_at: string;
  account_name?: string;
};

export async function createImportBatch(bankAccountId: number, filename: string | null): Promise<number> {
  const db = await getDb();
  const result = await db.execute(
    "INSERT INTO bank_import_batches (bank_account_id, filename) VALUES (?, ?)",
    [bankAccountId, filename ?? null]
  );
  return result.lastInsertId ?? 0;
}

export async function finalizeImportBatch(batchId: number, importedCount: number, skippedCount: number): Promise<void> {
  const db = await getDb();
  await db.execute(
    "UPDATE bank_import_batches SET imported_count = ?, skipped_count = ? WHERE id = ?",
    [importedCount, skippedCount, batchId]
  );
}

export async function listImportBatches(limit = 10): Promise<ImportBatch[]> {
  const db = await getDb();
  return db.select<ImportBatch[]>(
    `SELECT b.*, a.account_name
     FROM bank_import_batches b
     JOIN bank_accounts a ON a.id = b.bank_account_id
     ORDER BY b.imported_at DESC LIMIT ?`,
    [limit]
  );
}

export async function undoImportBatch(batchId: number): Promise<number> {
  const db = await getDb();
  // Only delete transactions not yet used in a reconciliation
  const rows = await db.select<{ n: number }[]>(
    `SELECT COUNT(*) as n FROM bank_transactions
     WHERE import_batch_id = ?
       AND id NOT IN (SELECT bank_transaction_id FROM reconciliation_clears)`,
    [batchId]
  );
  const count = rows[0]?.n ?? 0;
  if (count > 0) {
    await db.execute(
      `DELETE FROM bank_transactions
       WHERE import_batch_id = ?
         AND id NOT IN (SELECT bank_transaction_id FROM reconciliation_clears)`,
      [batchId]
    );
  }
  await db.execute("DELETE FROM bank_import_batches WHERE id = ?", [batchId]);
  return count;
}

export async function updateTransactionStatus(id: number, status: string): Promise<void> {
  const db = await getDb();
  await db.execute("UPDATE bank_transactions SET validation_status = ? WHERE id = ?", [status, id]);
}

export async function getLastReconBalance(bankAccountId: number): Promise<number> {
  const db = await getDb();
  const rows = await db.select<Array<{ book_balance: number | null }>>(
    `SELECT book_balance FROM bank_reconciliations
     WHERE bank_account_id = ? AND status = 'FINALIZED'
     ORDER BY statement_ending_date DESC LIMIT 1`,
    [bankAccountId]
  );
  return rows[0]?.book_balance ?? 0;
}
