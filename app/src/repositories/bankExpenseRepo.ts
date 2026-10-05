import type { DbHandle } from "../lib/dbTypes";

type DebitTxn = { id: number; bank_account_id: number; amount: number; transaction_date: string };

export async function findBillPaymentForDebit(
  db: DbHandle,
  txn: DebitTxn,
  maxDays = 5
): Promise<{ id: number; days_diff: number } | null> {
  const rows = await db.select<{ id: number; days_diff: number }[]>(
    `SELECT bp.id, ABS(julianday(bp.payment_date) - julianday(?)) AS days_diff
     FROM bill_payments bp
     WHERE bp.bank_account_id = ?
       AND ABS(bp.amount - ?) < 0.01
       AND ABS(julianday(bp.payment_date) - julianday(?)) <= ?
       AND NOT EXISTS (
         SELECT 1 FROM bank_transaction_links l
         WHERE l.source_type = 'BILL_PAYMENT' AND l.source_id = bp.id
       )
     ORDER BY days_diff, bp.id
     LIMIT 1`,
    [txn.transaction_date, txn.bank_account_id, Math.abs(txn.amount), txn.transaction_date, maxDays]
  );
  return rows[0] ?? null;
}

export async function linkBillPayment(db: DbHandle, txnId: number, billPaymentId: number): Promise<void> {
  await db.execute(
    `INSERT OR IGNORE INTO bank_transaction_links (bank_transaction_id, source_type, source_id)
     VALUES (?, 'BILL_PAYMENT', ?)`,
    [txnId, billPaymentId]
  );
  await db.execute("UPDATE bank_transactions SET validation_status = 'VALIDATED' WHERE id = ?", [txnId]);
}

export async function recordDebitAsBill(
  db: DbHandle,
  txn: DebitTxn,
  opts: { vendorId: number; categoryId: number; amount: number; description: string | null; invoiceSuffix?: string }
): Promise<number> {
  const accounts = await db.select<{ fund_code: string }[]>(
    "SELECT fund_code FROM bank_accounts WHERE id = ?",
    [txn.bank_account_id]
  );
  const fund = accounts[0]?.fund_code ?? "OPERATING";
  const invoice = `BT-${txn.id}${opts.invoiceSuffix ?? ""}`;
  const bill = await db.execute(
    `INSERT INTO vendor_bills (vendor_id, invoice_number, invoice_date, due_date, amount, fund_code, status, category_id, description)
     VALUES (?, ?, ?, ?, ?, ?, 'PAID', ?, ?)`,
    [opts.vendorId, invoice, txn.transaction_date, txn.transaction_date, opts.amount, fund, opts.categoryId, opts.description]
  );
  const billId = bill.lastInsertId ?? 0;
  const payment = await db.execute(
    `INSERT INTO bill_payments (vendor_bill_id, payment_date, amount, bank_account_id, notes)
     VALUES (?, ?, ?, ?, 'Recorded from bank transaction')`,
    [billId, txn.transaction_date, opts.amount, txn.bank_account_id]
  );
  const paymentId = payment.lastInsertId ?? 0;
  await db.execute(
    `INSERT OR IGNORE INTO bank_transaction_links (bank_transaction_id, source_type, source_id)
     VALUES (?, 'BILL_PAYMENT', ?)`,
    [txn.id, paymentId]
  );
  return paymentId;
}
