import { z } from "zod";
import { getDb } from "../lib/db";
import { BankAccountSchema, type BankAccount } from "../types/bankAccount";

// ── Fund accounts ─────────────────────────────────────────────────────────────

export async function listPettyCashAccounts(): Promise<BankAccount[]> {
  const db = await getDb();
  const rows = await db.select<unknown[]>(
    "SELECT * FROM bank_accounts WHERE is_petty_cash = 1 AND active_flag = 1 ORDER BY account_name"
  );
  return rows.map((r) => BankAccountSchema.parse(r));
}

export async function getPettyCashBalance(bankAccountId: number): Promise<number> {
  const db = await getDb();
  const rows = await db.select<{ balance: number }[]>(
    `SELECT
       b.opening_balance
       + COALESCE((SELECT SUM(amount) FROM account_transfers WHERE to_account_id   = b.id), 0)
       - COALESCE((SELECT SUM(amount) FROM account_transfers WHERE from_account_id = b.id), 0)
       - COALESCE((SELECT SUM(amount) FROM petty_cash_transactions WHERE bank_account_id = b.id), 0)
       AS balance
     FROM bank_accounts b WHERE b.id = ?`,
    [bankAccountId]
  );
  return rows[0]?.balance ?? 0;
}

// ── Expenditures ──────────────────────────────────────────────────────────────

export const PettyCashTxnSchema = z.object({
  id: z.number(),
  bank_account_id: z.number(),
  txn_date: z.string(),
  amount: z.number(),
  category_id: z.number().nullable(),
  category_name: z.string().nullable(),
  description: z.string(),
  receipt_ref: z.string().nullable(),
  created_at: z.string(),
});

export type PettyCashTxn = z.infer<typeof PettyCashTxnSchema>;

export async function listPettyCashTxns(bankAccountId: number): Promise<PettyCashTxn[]> {
  const db = await getDb();
  const rows = await db.select<unknown[]>(
    `SELECT p.*, c.name AS category_name
     FROM petty_cash_transactions p
     LEFT JOIN categories c ON c.id = p.category_id
     WHERE p.bank_account_id = ?
     ORDER BY p.txn_date DESC, p.id DESC`,
    [bankAccountId]
  );
  return rows.map((r) => PettyCashTxnSchema.parse(r));
}

export async function insertPettyCashTxn(
  bankAccountId: number,
  txn_date: string,
  amount: number,
  description: string,
  category_id: number | null,
  receipt_ref: string | null
): Promise<void> {
  const db = await getDb();
  await db.execute(
    `INSERT INTO petty_cash_transactions
       (bank_account_id, txn_date, amount, category_id, description, receipt_ref)
     VALUES (?, ?, ?, ?, ?, ?)`,
    [bankAccountId, txn_date, amount, category_id, description, receipt_ref]
  );
}

export async function deletePettyCashTxn(id: number): Promise<void> {
  const db = await getDb();
  await db.execute("DELETE FROM petty_cash_transactions WHERE id = ?", [id]);
}

// ── Replenishments (account_transfers) ───────────────────────────────────────

export const ReplenishmentSchema = z.object({
  id: z.number(),
  transfer_date: z.string(),
  from_account_id: z.number(),
  from_account_name: z.string(),
  to_account_id: z.number(),
  amount: z.number(),
  description: z.string().nullable(),
});

export type Replenishment = z.infer<typeof ReplenishmentSchema>;

export async function listReplenishments(bankAccountId: number): Promise<Replenishment[]> {
  const db = await getDb();
  const rows = await db.select<unknown[]>(
    `SELECT t.id, t.transfer_date, t.from_account_id, b.account_name AS from_account_name,
            t.to_account_id, t.amount, t.description
     FROM account_transfers t
     JOIN bank_accounts b ON b.id = t.from_account_id
     WHERE t.to_account_id = ?
     ORDER BY t.transfer_date DESC, t.id DESC`,
    [bankAccountId]
  );
  return rows.map((r) => ReplenishmentSchema.parse(r));
}

export async function insertReplenishment(
  from_account_id: number,
  to_account_id: number,
  transfer_date: string,
  amount: number,
  description: string | null
): Promise<void> {
  const db = await getDb();
  await db.execute(
    `INSERT INTO account_transfers (transfer_date, from_account_id, to_account_id, amount, description)
     VALUES (?, ?, ?, ?, ?)`,
    [transfer_date, from_account_id, to_account_id, amount, description]
  );
}
