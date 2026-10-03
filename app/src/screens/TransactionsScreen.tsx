import { useEffect, useState, useCallback, useMemo } from "react";
import { getDb } from "../lib/db";
import { PageLayout } from "../components/PageLayout";
import { Modal } from "../components/Modal";
import { listCategories } from "../repositories/categoryRepo";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import type { Category } from "../types/category";
import type { BankAccount } from "../types/bankAccount";
import { CHARGE_TYPE_LABELS } from "../types/assessment";
import type { ChargeTypeValue } from "../types/assessment";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

type TxnRow = {
  txn_date: string;
  source_type: string;
  source_id: number;
  account_name: string | null;
  amount: number;
  description: string;
  lot_number: string | null;
  category: string | null;
};

type SortKey = keyof TxnRow;
type SortDir = "asc" | "desc";

async function loadTransactions(limit: number): Promise<TxnRow[]> {
  const db = await getDb();
  const sql = `
    SELECT p.payment_date AS txn_date,
           'PAYMENT'      AS source_type,
           p.id           AS source_id,
           b.account_name,
           p.amount,
           COALESCE('Payment — ' || o.display_name, 'Payment — Lot ' || l.lot_number) AS description,
           l.lot_number,
           'HOA Dues' AS category
    FROM   payments p
    JOIN   lots l              ON l.id = p.lot_id
    LEFT JOIN owners o         ON o.id = p.owner_id
    LEFT JOIN deposit_batches d ON d.id = p.deposit_batch_id
    LEFT JOIN bank_accounts b  ON b.id = d.bank_account_id

    UNION ALL

    SELECT a.assessment_date,
           'ASSESSMENT',
           a.id,
           NULL,
           -a.amount,
           COALESCE(a.description, a.charge_type) || ' — Lot ' || l.lot_number,
           l.lot_number,
           a.charge_type
    FROM   assessments a
    JOIN   lots l ON l.id = a.lot_id

    UNION ALL

    SELECT bp.payment_date,
           'BILL_PAYMENT',
           bp.id,
           b.account_name,
           -bp.amount,
           'Bill payment — ' || v.vendor_name,
           NULL,
           c.name
    FROM   bill_payments bp
    JOIN   vendor_bills vb ON vb.id = bp.vendor_bill_id
    JOIN   vendors v       ON v.id = vb.vendor_id
    LEFT JOIN categories c ON c.id = vb.category_id
    JOIN   bank_accounts b ON b.id = bp.bank_account_id

    UNION ALL

    SELECT ib.income_date,
           'INCOME',
           ib.id,
           b.account_name,
           ib.amount,
           COALESCE(ib.description, c.name),
           l.lot_number,
           c.name
    FROM   income_batches ib
    JOIN   bank_accounts b ON b.id = ib.bank_account_id
    JOIN   categories c    ON c.id = ib.category_id
    LEFT JOIN lots l       ON l.id = ib.lot_id

    ORDER BY txn_date DESC
    LIMIT ?
  `;
  return db.select<TxnRow[]>(sql, [limit]);
}

const SOURCE_LABELS: Record<string, string> = {
  PAYMENT:      "Payment",
  BILL_PAYMENT: "Expense Payment",
  INCOME:       "Income",
  ASSESSMENT:   "Owner Bill",
};

function rowLabel(r: TxnRow): string {
  if (r.source_type === "ASSESSMENT") {
    if (r.category === "DUES")                          return "Bill Dues";
    if (r.category === "LATE_FEE" || r.category === "LEGAL_FEE") return "Bill Special";
    return "Bill Other";
  }
  return SOURCE_LABELS[r.source_type] ?? r.source_type;
}

const SOURCE_COLORS: Record<string, string> = {
  PAYMENT:      "bg-green-100 text-green-700",
  BILL_PAYMENT: "bg-red-100 text-red-700",
  INCOME:       "bg-blue-100 text-blue-700",
  ASSESSMENT:   "bg-orange-100 text-orange-700",
};

function colVal(r: TxnRow, key: SortKey): string | number {
  if (key === "source_type") return rowLabel(r);
  return r[key] ?? "";
}

// ── Impact types ──────────────────────────────────────────────────────────────

type PaymentAppImpact = {
  id: number; amount: number;
  charge_type: string; assessment_date: string; lot_number: string;
};

type AssessmentAppImpact = {
  id: number; amount: number;
  payment_date: string; payment_method: string; check_number: string | null;
};

type BillImpact = {
  vendor_name: string; bill_date: string;
  total_amount: number; paid_total: number; status: string;
};

type ImpactData =
  | { kind: "payment_apps"; rows: PaymentAppImpact[]; total: number }
  | { kind: "assessment_apps"; rows: AssessmentAppImpact[]; total: number }
  | { kind: "bill"; data: BillImpact }
  | { kind: "none" };

// ── Per-type detail types ──────────────────────────────────────────────────────

type PaymentDetail = {
  id: number; payment_date: string; amount: number; payment_method: string;
  check_number: string | null; memo: string | null; lot_number: string; owner_name: string | null;
};

type AssessmentDetail = {
  id: number; assessment_date: string; due_date: string | null; amount: number;
  charge_type: string; description: string | null; lot_number: string;
  owner_name: string | null; status: string;
};

type IncomeDetail = {
  id: number; income_date: string; amount: number; category_id: number;
  category_name: string; category_type: string; bank_account_id: number;
  account_name: string; description: string | null; reference: string | null;
};

type BillPaymentDetail = {
  id: number; payment_date: string; amount: number;
  bank_account_id: number; account_name: string; vendor_name: string;
};

type EditDetail =
  | { kind: "PAYMENT"; data: PaymentDetail }
  | { kind: "ASSESSMENT"; data: AssessmentDetail }
  | { kind: "INCOME"; data: IncomeDetail }
  | { kind: "BILL_PAYMENT"; data: BillPaymentDetail };

// ── Edit modal ─────────────────────────────────────────────────────────────────

const PAYMENT_METHODS = ["CHECK", "ACH", "ONLINE", "CASH", "OTHER"];

function EditModal({ type, id, onClose, onSaved }: {
  type: string; id: number; onClose: () => void; onSaved: () => void;
}) {
  const [detail, setDetail] = useState<EditDetail | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [categories, setCategories] = useState<Category[]>([]);
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [impact, setImpact] = useState<ImpactData | null>(null);
  const [showImpact, setShowImpact] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { void load(); }, []);

  async function load() {
    setLoading(true);
    try {
      const db = await getDb();
      if (type === "PAYMENT") {
        const [rows, appRows] = await Promise.all([
          db.select<PaymentDetail[]>(`
            SELECT p.id, p.payment_date, p.amount, p.payment_method, p.check_number, p.memo,
                   l.lot_number,
                   (SELECT GROUP_CONCAT(o2.display_name, ' / ')
                    FROM lot_ownership lo2 JOIN owners o2 ON o2.id = lo2.owner_id
                    WHERE lo2.lot_id = p.lot_id AND lo2.end_date IS NULL) AS owner_name
            FROM payments p JOIN lots l ON l.id = p.lot_id WHERE p.id = ?`, [id]),
          db.select<PaymentAppImpact[]>(`
            SELECT pa.id, pa.amount, a.charge_type, a.assessment_date, l.lot_number
            FROM payment_applications pa
            JOIN assessments a ON a.id = pa.assessment_id
            JOIN lots l ON l.id = a.lot_id
            WHERE pa.payment_id = ?`, [id]),
        ]);
        if (rows[0]) setDetail({ kind: "PAYMENT", data: rows[0] });
        const total = appRows.reduce((s, r) => s + r.amount, 0);
        setImpact(appRows.length > 0
          ? { kind: "payment_apps", rows: appRows, total }
          : { kind: "none" });
      } else if (type === "ASSESSMENT") {
        const [rows, appRows] = await Promise.all([
          db.select<AssessmentDetail[]>(`
            SELECT a.id, a.assessment_date, a.due_date, a.amount, a.charge_type,
                   a.description, a.status, l.lot_number,
                   (SELECT GROUP_CONCAT(o2.display_name, ' / ')
                    FROM lot_ownership lo2 JOIN owners o2 ON o2.id = lo2.owner_id
                    WHERE lo2.lot_id = a.lot_id AND lo2.end_date IS NULL) AS owner_name
            FROM assessments a JOIN lots l ON l.id = a.lot_id WHERE a.id = ?`, [id]),
          db.select<AssessmentAppImpact[]>(`
            SELECT pa.id, pa.amount, p.payment_date, p.payment_method, p.check_number
            FROM payment_applications pa
            JOIN payments p ON p.id = pa.payment_id
            WHERE pa.assessment_id = ?`, [id]),
        ]);
        if (rows[0]) setDetail({ kind: "ASSESSMENT", data: rows[0] });
        const total = appRows.reduce((s, r) => s + r.amount, 0);
        setImpact(appRows.length > 0
          ? { kind: "assessment_apps", rows: appRows, total }
          : { kind: "none" });
      } else if (type === "INCOME") {
        const [rows, cats, accts] = await Promise.all([
          db.select<IncomeDetail[]>(`
            SELECT ib.id, ib.income_date, ib.amount, ib.category_id, ib.bank_account_id,
                   ib.description, ib.reference,
                   c.name AS category_name, c.category_type, b.account_name
            FROM income_batches ib
            JOIN categories c ON c.id = ib.category_id
            JOIN bank_accounts b ON b.id = ib.bank_account_id
            WHERE ib.id = ?`, [id]),
          listCategories(),
          listBankAccounts(),
        ]);
        if (rows[0]) {
          const incomeRow = rows[0];
          setDetail({ kind: "INCOME", data: incomeRow });
          setCategories(cats.filter((c) => c.category_type === incomeRow.category_type));
          setAccounts(accts);
        }
        setImpact({ kind: "none" });
      } else if (type === "BILL_PAYMENT") {
        const [rows, accts, billRows] = await Promise.all([
          db.select<BillPaymentDetail[]>(`
            SELECT bp.id, bp.payment_date, bp.amount, bp.bank_account_id,
                   b.account_name, v.vendor_name
            FROM bill_payments bp
            JOIN vendor_bills vb ON vb.id = bp.vendor_bill_id
            JOIN vendors v ON v.id = vb.vendor_id
            JOIN bank_accounts b ON b.id = bp.bank_account_id
            WHERE bp.id = ?`, [id]),
          listBankAccounts(),
          db.select<BillImpact[]>(`
            SELECT v.vendor_name, vb.invoice_date AS bill_date, vb.amount AS total_amount, vb.status,
                   (SELECT COALESCE(SUM(bp2.amount), 0)
                    FROM bill_payments bp2 WHERE bp2.vendor_bill_id = vb.id) AS paid_total
            FROM bill_payments bp
            JOIN vendor_bills vb ON vb.id = bp.vendor_bill_id
            JOIN vendors v ON v.id = vb.vendor_id
            WHERE bp.id = ?`, [id]),
        ]);
        if (rows[0]) { setDetail({ kind: "BILL_PAYMENT", data: rows[0] }); setAccounts(accts); }
        setImpact(billRows[0] ? { kind: "bill", data: billRows[0] } : { kind: "none" });
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  function v<T>(key: string, fallback: T): T {
    return (key in values ? values[key] : fallback) as T;
  }

  function set(key: string, val: unknown) {
    setValues((prev) => ({ ...prev, [key]: val }));
  }

  async function save() {
    if (!detail) return;
    setSaving(true);
    setError(null);
    try {
      const db = await getDb();
      if (detail.kind === "PAYMENT") {
        const d = detail.data;
        await db.execute(
          `UPDATE payments SET payment_date=?, amount=?, payment_method=?, check_number=?, memo=? WHERE id=?`,
          [v("payment_date", d.payment_date), v("amount", d.amount),
           v("payment_method", d.payment_method), v("check_number", d.check_number) ?? null,
           v("memo", d.memo) ?? null, d.id]
        );
      } else if (detail.kind === "ASSESSMENT") {
        const d = detail.data;
        await db.execute(
          `UPDATE assessments SET assessment_date=?, due_date=?, amount=?, description=?,
           updated_at=datetime('now') WHERE id=?`,
          [v("assessment_date", d.assessment_date), v("due_date", d.due_date) ?? null,
           v("amount", d.amount), v("description", d.description) ?? null, d.id]
        );
      } else if (detail.kind === "INCOME") {
        const d = detail.data;
        await db.execute(
          `UPDATE income_batches SET income_date=?, amount=?, category_id=?,
           bank_account_id=?, description=?, reference=? WHERE id=?`,
          [v("income_date", d.income_date), v("amount", d.amount),
           v("category_id", d.category_id), v("bank_account_id", d.bank_account_id),
           v("description", d.description) ?? null, v("reference", d.reference) ?? null, d.id]
        );
      } else if (detail.kind === "BILL_PAYMENT") {
        const d = detail.data;
        await db.execute(
          `UPDATE bill_payments SET payment_date=?, amount=?, bank_account_id=? WHERE id=?`,
          [v("payment_date", d.payment_date), v("amount", d.amount),
           v("bank_account_id", d.bank_account_id), d.id]
        );
      }
      onSaved();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  const MODAL_TITLES: Record<string, string> = {
    PAYMENT: "Edit Payment", BILL_PAYMENT: "Edit Expense Payment",
    INCOME: "Edit Income / Expense", ASSESSMENT: "Edit Owner Bill",
  };
  const title = MODAL_TITLES[type] ?? `Edit ${type}`;

  return (
    <Modal title={title} onClose={onClose}>
      {loading && <p className="text-sm text-gray-400 py-4">Loading…</p>}
      {error && <p className="text-sm text-red-600 mb-3">{error}</p>}

      {!loading && detail && (
        <div className="space-y-4">
          {/* Context line */}
          {(detail.kind === "PAYMENT" || detail.kind === "ASSESSMENT") && (
            <div className="p-3 bg-gray-50 rounded text-xs text-gray-500">
              Lot {detail.data.lot_number}
              {detail.data.owner_name ? ` · ${detail.data.owner_name}` : ""}
              {detail.kind === "ASSESSMENT" ? ` · ${CHARGE_TYPE_LABELS[detail.data.charge_type as ChargeTypeValue] ?? detail.data.charge_type} · ${detail.data.status}` : ""}
            </div>
          )}
          {detail.kind === "BILL_PAYMENT" && (
            <div className="p-3 bg-gray-50 rounded text-xs text-gray-500">
              {detail.data.vendor_name}
            </div>
          )}

          {/* Impact section */}
          {impact && impact.kind !== "none" && (
            <div className={`rounded border px-3 py-2 text-xs ${
              impact.kind === "payment_apps" || impact.kind === "assessment_apps"
                ? "bg-amber-50 border-amber-200 text-amber-800"
                : "bg-blue-50 border-blue-200 text-blue-800"
            }`}>
              <div className="flex items-center justify-between">
                <span className="font-medium">
                  {impact.kind === "payment_apps" && (
                    <>⚠ {impact.rows.length} payment application{impact.rows.length !== 1 ? "s" : ""} totaling {fmt(impact.total)} — changing amount may leave unapplied balance</>
                  )}
                  {impact.kind === "assessment_apps" && (
                    <>⚠ {impact.rows.length} payment{impact.rows.length !== 1 ? "s" : ""} applied totaling {fmt(impact.total)} — changing amount recalculates balance owed</>
                  )}
                  {impact.kind === "bill" && (
                    <>Bill: {impact.data.vendor_name} · {impact.data.bill_date} · {fmt(impact.data.total_amount)} total · {fmt(impact.data.paid_total)} paid · {impact.data.status}</>
                  )}
                </span>
                {(impact.kind === "payment_apps" || impact.kind === "assessment_apps") && (
                  <button
                    onClick={() => setShowImpact((s) => !s)}
                    className="ml-3 underline whitespace-nowrap hover:no-underline"
                  >
                    {showImpact ? "Hide" : "View details"}
                  </button>
                )}
              </div>

              {showImpact && impact.kind === "payment_apps" && (
                <table className="mt-2 w-full text-xs">
                  <thead className="bg-gray-50 border-b sticky top-0 z-10"><tr className="text-amber-700">
                    <th className="text-left py-0.5">Lot</th>
                    <th className="text-left py-0.5">Type</th>
                    <th className="text-left py-0.5">Assessment Date</th>
                    <th className="text-right py-0.5">Applied</th>
                  </tr></thead>
                  <tbody>
                    {impact.rows.map((r) => (
                      <tr key={r.id} className="border-t border-amber-200">
                        <td className="py-0.5">Lot {r.lot_number}</td>
                        <td className="py-0.5">{CHARGE_TYPE_LABELS[r.charge_type as ChargeTypeValue] ?? r.charge_type}</td>
                        <td className="py-0.5">{r.assessment_date}</td>
                        <td className="text-right py-0.5 font-mono">{fmt(r.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {showImpact && impact.kind === "assessment_apps" && (
                <table className="mt-2 w-full text-xs">
                  <thead className="bg-gray-50 border-b sticky top-0 z-10"><tr className="text-amber-700">
                    <th className="text-left py-0.5">Payment Date</th>
                    <th className="text-left py-0.5">Method</th>
                    <th className="text-left py-0.5">Check #</th>
                    <th className="text-right py-0.5">Applied</th>
                  </tr></thead>
                  <tbody>
                    {impact.rows.map((r) => (
                      <tr key={r.id} className="border-t border-amber-200">
                        <td className="py-0.5">{r.payment_date}</td>
                        <td className="py-0.5">{r.payment_method}</td>
                        <td className="py-0.5">{r.check_number ?? "—"}</td>
                        <td className="text-right py-0.5 font-mono">{fmt(r.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            {/* PAYMENT fields */}
            {detail.kind === "PAYMENT" && (<>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Payment Date</label>
                <input type="date" value={v("payment_date", detail.data.payment_date)}
                  onChange={(e) => set("payment_date", e.target.value)}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Amount</label>
                <input type="number" step="0.01" min="0.01"
                  value={v("amount", detail.data.amount)}
                  onChange={(e) => set("amount", Number(e.target.value))}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Method</label>
                <select value={v("payment_method", detail.data.payment_method)}
                  onChange={(e) => set("payment_method", e.target.value)}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                  {PAYMENT_METHODS.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Check #</label>
                <input type="text" value={v("check_number", detail.data.check_number ?? "")}
                  onChange={(e) => set("check_number", e.target.value || null)}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div className="col-span-2">
                <label className="block text-xs font-medium text-gray-700 mb-1">Memo</label>
                <input type="text" value={v("memo", detail.data.memo ?? "")}
                  onChange={(e) => set("memo", e.target.value || null)}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
            </>)}

            {/* ASSESSMENT fields */}
            {detail.kind === "ASSESSMENT" && (<>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Assessment Date</label>
                <input type="date" value={v("assessment_date", detail.data.assessment_date)}
                  onChange={(e) => set("assessment_date", e.target.value)}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Due Date</label>
                <input type="date" value={v("due_date", detail.data.due_date ?? "")}
                  onChange={(e) => set("due_date", e.target.value || null)}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Amount</label>
                <input type="number" step="0.01" min="0.01"
                  value={v("amount", detail.data.amount)}
                  onChange={(e) => set("amount", Number(e.target.value))}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div className="col-span-2">
                <label className="block text-xs font-medium text-gray-700 mb-1">Description</label>
                <input type="text" value={v("description", detail.data.description ?? "")}
                  onChange={(e) => set("description", e.target.value || null)}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
            </>)}

            {/* INCOME fields */}
            {detail.kind === "INCOME" && (<>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Date</label>
                <input type="date" value={v("income_date", detail.data.income_date)}
                  onChange={(e) => set("income_date", e.target.value)}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Amount</label>
                <input type="number" step="0.01"
                  value={v("amount", detail.data.amount)}
                  onChange={(e) => set("amount", Number(e.target.value))}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Category</label>
                <select value={v("category_id", detail.data.category_id)}
                  onChange={(e) => set("category_id", Number(e.target.value))}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                  {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Account</label>
                <select value={v("bank_account_id", detail.data.bank_account_id)}
                  onChange={(e) => set("bank_account_id", Number(e.target.value))}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                  {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Description</label>
                <input type="text" value={v("description", detail.data.description ?? "")}
                  onChange={(e) => set("description", e.target.value || null)}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Reference</label>
                <input type="text" value={v("reference", detail.data.reference ?? "")}
                  onChange={(e) => set("reference", e.target.value || null)}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
            </>)}

            {/* BILL_PAYMENT fields */}
            {detail.kind === "BILL_PAYMENT" && (<>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Payment Date</label>
                <input type="date" value={v("payment_date", detail.data.payment_date)}
                  onChange={(e) => set("payment_date", e.target.value)}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Amount</label>
                <input type="number" step="0.01" min="0.01"
                  value={v("amount", detail.data.amount)}
                  onChange={(e) => set("amount", Number(e.target.value))}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div className="col-span-2">
                <label className="block text-xs font-medium text-gray-700 mb-1">Account</label>
                <select value={v("bank_account_id", detail.data.bank_account_id)}
                  onChange={(e) => set("bank_account_id", Number(e.target.value))}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                  {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
                </select>
              </div>
            </>)}
          </div>

          <div className="flex justify-end gap-3 pt-2 border-t">
            <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600">Cancel</button>
            <button onClick={() => void save()} disabled={saving}
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
              {saving ? "Saving…" : "Save Changes"}
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}

// ── Main screen ────────────────────────────────────────────────────────────────

export function TransactionsScreen() {
  const [rows, setRows]       = useState<TxnRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [limit, setLimit]     = useState(250);
  const [editing, setEditing] = useState<{ type: string; id: number } | null>(null);

  // Sort
  const [sortKey, setSortKey] = useState<SortKey>("txn_date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  // Per-column filters
  const [fDate, setFDate]     = useState("");
  const [fType, setFType]     = useState("");
  const [fDesc, setFDesc]     = useState("");
  const [fCat, setFCat]       = useState("");
  const [fAcct, setFAcct]     = useState("");
  const [fLot, setFLot]       = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRows(await loadTransactions(limit));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [limit]);

  useEffect(() => { void load(); }, [load]);

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "amount" ? "desc" : "asc");
    }
  }

  const visible = useMemo(() => {
    let out = rows;

    if (fDate) out = out.filter((r) => r.txn_date.includes(fDate.trim()));
    if (fType) {
      const q = fType.trim().toLowerCase();
      out = out.filter((r) => rowLabel(r).toLowerCase().includes(q));
    }
    if (fDesc) { const q = fDesc.trim().toLowerCase(); out = out.filter((r) => r.description.toLowerCase().includes(q)); }
    if (fCat)  { const q = fCat.trim().toLowerCase();  out = out.filter((r) => (r.category ?? "").toLowerCase().includes(q)); }
    if (fAcct) { const q = fAcct.trim().toLowerCase(); out = out.filter((r) => (r.account_name ?? "").toLowerCase().includes(q)); }
    if (fLot)  { const q = fLot.trim().toLowerCase();  out = out.filter((r) => (r.lot_number ?? "").toLowerCase().includes(q)); }

    out = [...out].sort((a, b) => {
      const av = colVal(a, sortKey);
      const bv = colVal(b, sortKey);
      const cmp = typeof av === "number" && typeof bv === "number"
        ? av - bv
        : String(av).localeCompare(String(bv));
      return sortDir === "asc" ? cmp : -cmp;
    });

    return out;
  }, [rows, fDate, fType, fDesc, fCat, fAcct, fLot, sortKey, sortDir]);

  const hasFilters = fDate || fType || fDesc || fCat || fAcct || fLot;

  function SortTh({ col, label, right }: { col: SortKey; label: string; right?: boolean }) {
    const active = sortKey === col;
    return (
      <th
        className={`px-3 py-2 text-xs font-medium text-gray-600 cursor-pointer select-none whitespace-nowrap ${right ? "text-right" : "text-left"}`}
        onClick={() => handleSort(col)}
      >
        {label}
        <span className="ml-1 text-gray-400">
          {active ? (sortDir === "asc" ? "▲" : "▼") : "⇅"}
        </span>
      </th>
    );
  }

  function FilterInput({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
    return (
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder ?? "Filter…"}
        className="w-full border border-gray-200 rounded px-1.5 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white"
      />
    );
  }

  return (
    <PageLayout
      title="All Transactions"
      subtitle="Payments, assessments, income, and expenses in date order."
      helpId="transactions"
      actions={
        <div className="flex items-center gap-2">
          {hasFilters && (
            <button
              onClick={() => { setFDate(""); setFType(""); setFDesc(""); setFCat(""); setFAcct(""); setFLot(""); }}
              className="text-xs px-2 py-1.5 rounded border border-gray-300 text-gray-600 hover:bg-gray-50"
            >
              Clear filters
            </button>
          )}
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value={100}>Last 100</option>
            <option value={250}>Last 250</option>
            <option value={500}>Last 500</option>
            <option value={1000}>Last 1000</option>
            <option value={9999}>All</option>
          </select>
        </div>
      }
    >
      <div>
        {loading && <p className="text-sm text-gray-400">Loading…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}

        {!loading && !error && (
          <>
            <p className="text-xs text-gray-500 mb-2">
              {visible.length === rows.length
                ? `${rows.length} transactions`
                : `${visible.length} of ${rows.length} transactions`}
            </p>
            <div className="border rounded-lg">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b sticky top-0 z-10">
                  <tr>
                    <SortTh col="txn_date"     label="Date" />
                    <SortTh col="source_type"  label="Type" />
                    <SortTh col="description"  label="Description" />
                    <SortTh col="category"     label="Category" />
                    <SortTh col="account_name" label="Account" />
                    <SortTh col="lot_number"   label="Lot" />
                    <SortTh col="amount"       label="Amount" right />
                    <th className="px-3 py-2" />
                  </tr>
                  <tr className="bg-gray-50 border-b border-gray-200">
                    <td className="px-2 py-1"><FilterInput value={fDate} onChange={setFDate} placeholder="2026-01…" /></td>
                    <td className="px-2 py-1"><FilterInput value={fType} onChange={setFType} placeholder="Payment…" /></td>
                    <td className="px-2 py-1"><FilterInput value={fDesc} onChange={setFDesc} /></td>
                    <td className="px-2 py-1"><FilterInput value={fCat}  onChange={setFCat}  /></td>
                    <td className="px-2 py-1"><FilterInput value={fAcct} onChange={setFAcct} /></td>
                    <td className="px-2 py-1"><FilterInput value={fLot}  onChange={setFLot}  placeholder="4207…" /></td>
                    <td className="px-2 py-1" />
                    <td className="px-2 py-1" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {visible.length === 0 && (
                    <tr>
                      <td colSpan={8} className="px-4 py-6 text-center text-gray-400 text-sm">
                        {hasFilters ? "No matches." : "No transactions yet."}
                      </td>
                    </tr>
                  )}
                  {visible.map((r, i) => (
                    <tr key={i} className="hover:bg-gray-50">
                      <td className="px-3 py-1.5 text-gray-600 font-mono text-xs">{r.txn_date}</td>
                      <td className="px-3 py-1.5">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${SOURCE_COLORS[r.source_type] ?? "bg-gray-100 text-gray-700"}`}>
                          {rowLabel(r)}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 text-gray-700 text-xs">{r.description}</td>
                      <td className="px-3 py-1.5 text-gray-500 text-xs">{r.category ?? "—"}</td>
                      <td className="px-3 py-1.5 text-gray-500 text-xs">{r.account_name ?? "—"}</td>
                      <td className="px-3 py-1.5 text-gray-500 text-xs">{r.lot_number ? `Lot ${r.lot_number}` : "—"}</td>
                      <td className={`px-3 py-1.5 text-right font-mono text-xs ${r.amount < 0 ? "text-red-600" : "text-green-700"}`}>
                        {fmt(r.amount)}
                      </td>
                      <td className="px-3 py-1.5 text-right">
                        <button
                          onClick={() => setEditing({ type: r.source_type, id: r.source_id })}
                          className="text-xs text-blue-600 hover:underline"
                        >
                          Edit
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>

      {editing && (
        <EditModal
          type={editing.type}
          id={editing.id}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); void load(); }}
        />
      )}
    </PageLayout>
  );
}
