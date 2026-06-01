import { getDb } from "../lib/db";
import { BankAccountSchema, type BankAccount, type BankAccountFormValues } from "../types/bankAccount";

export async function listBankAccounts(activeOnly = false): Promise<BankAccount[]> {
  const db = await getDb();
  const sql = activeOnly
    ? "SELECT * FROM bank_accounts WHERE active_flag = 1 ORDER BY account_name"
    : "SELECT * FROM bank_accounts ORDER BY account_name";
  const rows = await db.select<unknown[]>(sql);
  return rows.map((r) => BankAccountSchema.parse(r));
}

export async function getBankAccount(id: number): Promise<BankAccount | null> {
  const db = await getDb();
  const rows = await db.select<unknown[]>("SELECT * FROM bank_accounts WHERE id = ?", [id]);
  return rows[0] ? BankAccountSchema.parse(rows[0]) : null;
}

export async function insertBankAccount(values: BankAccountFormValues): Promise<number> {
  const db = await getDb();
  const result = await db.execute(
    `INSERT INTO bank_accounts
       (account_name, institution_name, account_last4, account_type,
        fund_code, opening_balance, opening_balance_date)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
    [
      values.account_name,
      values.institution_name,
      values.account_last4 ?? null,
      values.account_type,
      values.fund_code,
      values.opening_balance,
      values.opening_balance_date ?? null,
    ]
  );
  return result.lastInsertId ?? 0;
}

export async function updateBankAccount(id: number, values: BankAccountFormValues): Promise<void> {
  const db = await getDb();
  await db.execute(
    `UPDATE bank_accounts
     SET account_name = ?, institution_name = ?, account_last4 = ?,
         account_type = ?, fund_code = ?, active_flag = ?,
         opening_balance = ?, opening_balance_date = ?,
         updated_at = datetime('now')
     WHERE id = ?`,
    [
      values.account_name,
      values.institution_name,
      values.account_last4 ?? null,
      values.account_type,
      values.fund_code,
      values.active_flag,
      values.opening_balance,
      values.opening_balance_date ?? null,
      id,
    ]
  );
}

export async function deleteBankAccount(id: number): Promise<void> {
  const db = await getDb();
  await db.execute("DELETE FROM bank_accounts WHERE id = ?", [id]);
}

// Returns true if any transactions reference this account — used to block hard-delete.
export async function hasTransactions(id: number): Promise<boolean> {
  const db = await getDb();
  // Expand this list as transaction tables are added
  const tables = ["bank_transactions", "bank_reconciliations"];
  for (const table of tables) {
    const rows = await db.select<[{ n: number }]>(
      `SELECT COUNT(*) as n FROM ${table} WHERE bank_account_id = ?`,
      [id]
    );
    const row = rows[0];
    if (row && row.n > 0) return true;
  }
  return false;
}
