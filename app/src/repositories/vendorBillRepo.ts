import { getDb } from "../lib/db";
import {
  VendorBillSchema,
  BillPaymentSchema,
  type VendorBill,
  type BillPayment,
  type VendorBillFormValues,
  type BillPaymentFormValues,
} from "../types/vendorBill";

export async function listVendorBills(statusFilter?: string): Promise<VendorBill[]> {
  const db = await getDb();
  const filtered = statusFilter && statusFilter !== "ALL";
  const rows = await db.select<unknown[]>(
    `SELECT vb.*,
            v.vendor_name,
            c.code AS category_code,
            COALESCE((SELECT SUM(bp.amount) FROM bill_payments bp WHERE bp.vendor_bill_id = vb.id), 0) AS amount_paid
     FROM   vendor_bills vb
     JOIN   vendors v   ON v.id = vb.vendor_id
     LEFT JOIN categories c ON c.id = vb.category_id
     ${filtered ? "WHERE vb.status = ?" : ""}
     ORDER BY vb.invoice_date DESC, vb.id DESC
     LIMIT 200`,
    filtered ? [statusFilter] : []
  );
  return rows.map((r) => VendorBillSchema.parse(r));
}

export async function getVendorBill(id: number): Promise<VendorBill | null> {
  const db = await getDb();
  const rows = await db.select<unknown[]>(`
    SELECT vb.*, v.vendor_name, c.code AS category_code,
           COALESCE((SELECT SUM(bp.amount) FROM bill_payments bp WHERE bp.vendor_bill_id = vb.id), 0) AS amount_paid
    FROM   vendor_bills vb
    JOIN   vendors v ON v.id = vb.vendor_id
    LEFT JOIN categories c ON c.id = vb.category_id
    WHERE  vb.id = ?
  `, [id]);
  return rows[0] ? VendorBillSchema.parse(rows[0]) : null;
}

export async function insertVendorBill(values: VendorBillFormValues): Promise<number> {
  const db = await getDb();
  const result = await db.execute(
    `INSERT INTO vendor_bills
       (vendor_id, invoice_number, invoice_date, due_date,
        amount, fund_code, category_id, description, status)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')`,
    [
      values.vendor_id,
      values.invoice_number,
      values.invoice_date,
      values.due_date ?? null,
      values.amount,
      values.fund_code,
      values.category_id ?? null,
      values.description ?? null,
    ]
  );
  return result.lastInsertId ?? 0;
}

export async function updateVendorBill(id: number, values: VendorBillFormValues): Promise<void> {
  const db = await getDb();
  // Amount is only updated if no payments exist
  const hasPayments = await billHasPayments(id);
  if (hasPayments) {
    await db.execute(
      `UPDATE vendor_bills
       SET invoice_number = ?, invoice_date = ?, due_date = ?,
           fund_code = ?, category_id = ?, description = ?,
           updated_at = datetime('now')
       WHERE id = ?`,
      [values.invoice_number, values.invoice_date, values.due_date ?? null,
       values.fund_code, values.category_id ?? null, values.description ?? null, id]
    );
  } else {
    await db.execute(
      `UPDATE vendor_bills
       SET invoice_number = ?, invoice_date = ?, due_date = ?,
           amount = ?, fund_code = ?, category_id = ?, description = ?,
           updated_at = datetime('now')
       WHERE id = ?`,
      [values.invoice_number, values.invoice_date, values.due_date ?? null,
       values.amount, values.fund_code, values.category_id ?? null,
       values.description ?? null, id]
    );
  }
}

export async function voidBill(id: number): Promise<void> {
  const db = await getDb();
  await db.execute(
    "UPDATE vendor_bills SET status = 'VOID', updated_at = datetime('now') WHERE id = ?",
    [id]
  );
}

export async function billHasPayments(id: number): Promise<boolean> {
  const db = await getDb();
  const rows = await db.select<[{ n: number }]>(
    "SELECT COUNT(*) as n FROM bill_payments WHERE vendor_bill_id = ?",
    [id]
  );
  const row = rows[0];
  return row ? row.n > 0 : false;
}

export async function listPaymentsForBill(billId: number): Promise<BillPayment[]> {
  const db = await getDb();
  const rows = await db.select<unknown[]>(`
    SELECT bp.*, ba.account_name AS bank_account_name
    FROM   bill_payments bp
    JOIN   bank_accounts ba ON ba.id = bp.bank_account_id
    WHERE  bp.vendor_bill_id = ?
    ORDER BY bp.payment_date DESC
  `, [billId]);
  return rows.map((r) => BillPaymentSchema.parse(r));
}

export async function insertBillPayment(
  billId: number,
  values: BillPaymentFormValues
): Promise<void> {
  const db = await getDb();
  await db.execute(
    `INSERT INTO bill_payments
       (vendor_bill_id, payment_date, amount, bank_account_id, check_number, notes)
     VALUES (?, ?, ?, ?, ?, ?)`,
    [billId, values.payment_date, values.amount, values.bank_account_id,
     values.check_number ?? null, values.notes ?? null]
  );
  // Recalculate status
  await refreshBillStatus(billId);
}

export async function deleteBillPayment(paymentId: number, billId: number): Promise<void> {
  const db = await getDb();
  await db.execute("DELETE FROM bill_payments WHERE id = ?", [paymentId]);
  await refreshBillStatus(billId);
}

async function refreshBillStatus(billId: number): Promise<void> {
  const db = await getDb();
  const rows = await db.select<[{ amount: number; paid: number }]>(`
    SELECT vb.amount,
           COALESCE((SELECT SUM(bp.amount) FROM bill_payments bp WHERE bp.vendor_bill_id = vb.id), 0) AS paid
    FROM vendor_bills vb WHERE vb.id = ?
  `, [billId]);
  const row = rows[0];
  if (!row) return;
  let status = "OPEN";
  if (row.paid >= row.amount) status = "PAID";
  else if (row.paid > 0) status = "PARTIAL";
  await db.execute(
    "UPDATE vendor_bills SET status = ?, updated_at = datetime('now') WHERE id = ?",
    [status, billId]
  );
}
