import { useEffect, useState, useCallback } from "react";
import { getDb } from "../lib/db";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import type { BankAccount } from "../types/bankAccount";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

// ── AR Aging ──────────────────────────────────────────────────────────────────

type AgingBucket = { lot_number: string; owner_name: string | null; current: number; d30: number; d60: number; d90plus: number; total: number };

async function loadARaging(): Promise<AgingBucket[]> {
  const db = await getDb();
  const today = new Date().toISOString().slice(0, 10);
  const rows = await db.select<AgingBucket[]>(`
    SELECT l.lot_number,
           o.display_name AS owner_name,
           SUM(CASE WHEN julianday(?) - julianday(COALESCE(a.due_date, a.assessment_date)) <= 30 THEN a.amount ELSE 0 END) AS current,
           SUM(CASE WHEN julianday(?) - julianday(COALESCE(a.due_date, a.assessment_date)) BETWEEN 31 AND 60 THEN a.amount ELSE 0 END) AS d30,
           SUM(CASE WHEN julianday(?) - julianday(COALESCE(a.due_date, a.assessment_date)) BETWEEN 61 AND 90 THEN a.amount ELSE 0 END) AS d60,
           SUM(CASE WHEN julianday(?) - julianday(COALESCE(a.due_date, a.assessment_date)) > 90 THEN a.amount ELSE 0 END) AS d90plus,
           SUM(a.amount) AS total
    FROM assessments a
    JOIN lots l ON l.id = a.lot_id
    LEFT JOIN owners o ON o.id = a.owner_id
    WHERE a.status IN ('OPEN', 'PARTIAL')
    GROUP BY l.lot_number, o.display_name
    HAVING total > 0
    ORDER BY total DESC
  `, [today, today, today, today]);
  return rows;
}

// ── Expense Summary ───────────────────────────────────────────────────────────

type ExpenseRow = { category_name: string; total: number };

async function loadExpenseSummary(year: number): Promise<ExpenseRow[]> {
  const db = await getDb();
  const rows = await db.select<ExpenseRow[]>(`
    SELECT c.name AS category_name, SUM(bp.amount) AS total
    FROM bill_payments bp
    JOIN vendor_bills vb ON vb.id = bp.vendor_bill_id
    JOIN categories c ON c.id = vb.category_id
    WHERE strftime('%Y', bp.payment_date) = ?
    GROUP BY c.name
    ORDER BY total DESC
  `, [String(year)]);
  return rows;
}

// ── Income Summary ────────────────────────────────────────────────────────────

type IncomeRow = { category_name: string; total: number };

async function loadIncomeSummary(year: number): Promise<IncomeRow[]> {
  const db = await getDb();
  const [payments, income] = await Promise.all([
    db.select<Array<{ total: number }>>(`
      SELECT SUM(amount) AS total FROM payments
      WHERE strftime('%Y', payment_date) = ?
    `, [String(year)]),
    db.select<IncomeRow[]>(`
      SELECT c.name AS category_name, SUM(ib.amount) AS total
      FROM income_batches ib
      JOIN categories c ON c.id = ib.category_id
      WHERE strftime('%Y', ib.income_date) = ?
      GROUP BY c.name ORDER BY total DESC
    `, [String(year)]),
  ]);
  const rows: IncomeRow[] = [
    { category_name: "HOA Dues Payments", total: payments[0]?.total ?? 0 },
    ...income,
  ];
  return rows.filter((r) => r.total > 0);
}

// ── Transaction History ───────────────────────────────────────────────────────

type TxnRow = { txn_date: string; source_type: string; account_name: string | null; description: string; lot_number: string | null; amount: number };

async function loadTransactionHistory(limit: number): Promise<TxnRow[]> {
  const db = await getDb();
  return db.select<TxnRow[]>(`
    SELECT txn_date, source_type, account_name, description, lot_number, amount FROM (
      SELECT p.payment_date AS txn_date, 'PAYMENT' AS source_type, b.account_name,
             COALESCE('Payment — ' || o.display_name, 'Payment — Lot ' || l.lot_number) AS description, l.lot_number, p.amount
      FROM payments p JOIN lots l ON l.id = p.lot_id LEFT JOIN owners o ON o.id = p.owner_id
      LEFT JOIN deposit_batches d ON d.id = p.deposit_batch_id LEFT JOIN bank_accounts b ON b.id = d.bank_account_id
      UNION ALL
      SELECT bp.payment_date, 'BILL_PAYMENT', b.account_name,
             'Bill — ' || v.vendor_name, NULL, -bp.amount
      FROM bill_payments bp JOIN vendor_bills vb ON vb.id = bp.vendor_bill_id
      JOIN vendors v ON v.id = vb.vendor_id JOIN bank_accounts b ON b.id = bp.bank_account_id
      UNION ALL
      SELECT ib.income_date, 'INCOME', b.account_name,
             COALESCE(ib.description, c.name), l.lot_number, ib.amount
      FROM income_batches ib JOIN categories c ON c.id = ib.category_id
      JOIN bank_accounts b ON b.id = ib.bank_account_id LEFT JOIN lots l ON l.id = ib.lot_id
    ) ORDER BY txn_date DESC LIMIT ?
  `, [limit]);
}

const SOURCE_LABELS: Record<string, string> = { PAYMENT: "Payment", BILL_PAYMENT: "Bill Payment", INCOME: "Income" };

// ── Homeowner Contact List ────────────────────────────────────────────────────

type ContactRow = {
  lot_number: string;
  owner_name: string | null;
  owner_type: string | null;
  email: string | null;
  phone: string | null;
  home_phone: string | null;
  mailing_address_1: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
};

async function loadContactList(): Promise<ContactRow[]> {
  const db = await getDb();
  return db.select<ContactRow[]>(`
    SELECT l.lot_number,
           o.display_name AS owner_name, o.owner_type,
           o.email, o.phone, o.home_phone,
           o.mailing_address_1, o.city, o.state, o.postal_code
    FROM lots l
    LEFT JOIN lot_ownership lo ON lo.lot_id = l.id AND lo.end_date IS NULL
    LEFT JOIN owners o ON o.id = lo.owner_id
    WHERE l.active_flag = 1
    ORDER BY l.lot_number
  `);
}

function ContactListReport() {
  const [rows, setRows] = useState<ContactRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadContactList()
      .then(setRows)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!loading && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Lot</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Owner</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Email</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Phone</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Mailing Address</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {rows.map((r) => (
                <tr key={r.lot_number}>
                  <td className="px-4 py-2 font-medium text-gray-900">Lot {r.lot_number}</td>
                  <td className="px-4 py-2 text-gray-700 text-xs">{r.owner_name ?? "— No owner —"}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{r.email ?? "—"}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{r.phone ?? r.home_phone ?? "—"}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">
                    {r.mailing_address_1
                      ? `${r.mailing_address_1}${r.city ? `, ${r.city}` : ""}${r.state ? ` ${r.state}` : ""}${r.postal_code ? ` ${r.postal_code}` : ""}`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Owner Ledger ──────────────────────────────────────────────────────────────

type OwnerLedgerRow = {
  txn_date: string;
  type: string;
  description: string;
  amount: number;
  running_balance: number;
};

type OwnerSummary = { id: number; display_name: string; lot_number: string | null };

async function loadOwners(): Promise<OwnerSummary[]> {
  const db = await getDb();
  return db.select<OwnerSummary[]>(`
    SELECT o.id, o.display_name,
           GROUP_CONCAT(l.lot_number) AS lot_number
    FROM owners o
    LEFT JOIN lot_ownership lo ON lo.owner_id = o.id AND lo.end_date IS NULL
    LEFT JOIN lots l ON l.id = lo.lot_id
    WHERE o.active_flag = 1
    GROUP BY o.id
    ORDER BY o.display_name
  `);
}

async function loadOwnerLedger(ownerId: number): Promise<OwnerLedgerRow[]> {
  const db = await getDb();
  const rows = await db.select<Omit<OwnerLedgerRow, "running_balance">[]>(`
    SELECT txn_date, type, description, amount FROM (
      SELECT a.assessment_date AS txn_date, 'CHARGE' AS type,
             COALESCE(a.description, a.charge_type) AS description,
             -a.amount AS amount
      FROM assessments a WHERE a.owner_id = ?
      UNION ALL
      SELECT p.payment_date, 'PAYMENT', COALESCE(p.memo, 'Payment'), p.amount
      FROM payments p WHERE p.owner_id = ?
    ) ORDER BY txn_date ASC
  `, [ownerId, ownerId]);

  let balance = 0;
  return rows.map((r) => {
    balance += r.amount;
    return { ...r, running_balance: balance };
  }).reverse();
}

function OwnerLedgerReport({ ownerId = 0 }: { ownerId?: number }) {
  const [rows, setRows] = useState<OwnerLedgerRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!ownerId) { setLoading(false); return; }
    setLoading(true);
    loadOwnerLedger(ownerId)
      .then(setRows)
      .finally(() => setLoading(false));
  }, [ownerId]);

  const balance = rows[0]?.running_balance ?? 0;

  return (
    <div className="space-y-3">
      {!loading && ownerId > 0 && (
        <div className={`p-3 rounded-lg text-sm font-medium ${balance >= 0 ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
          Current Balance: {fmt(balance)} {balance >= 0 ? "(credit)" : "(balance due)"}
        </div>
      )}
      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {!loading && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Date</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Type</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Description</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Balance</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {rows.length === 0 && <tr><td colSpan={5} className="px-4 py-6 text-center text-gray-400 text-sm">No transactions for this owner.</td></tr>}
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="px-4 py-2 text-gray-600 text-xs">{r.txn_date}</td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${r.type === "PAYMENT" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>{r.type}</span>
                  </td>
                  <td className="px-4 py-2 text-gray-700 text-xs">{r.description}</td>
                  <td className={`px-4 py-2 text-right font-mono text-xs ${r.amount >= 0 ? "text-green-700" : "text-red-600"}`}>{fmt(r.amount)}</td>
                  <td className={`px-4 py-2 text-right font-mono text-xs ${r.running_balance >= 0 ? "text-gray-700" : "text-red-600"}`}>{fmt(r.running_balance)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Budget vs Actual ──────────────────────────────────────────────────────────

type BvARow = { category_name: string; budget_amount: number; actual_amount: number; variance: number };

async function loadBudgetVsActual(year: number): Promise<BvARow[]> {
  const db = await getDb();
  return db.select<BvARow[]>(`
    SELECT c.name AS category_name,
           COALESCE(SUM(bl.budget_amount), 0) AS budget_amount,
           COALESCE(SUM(bp.amount), 0) AS actual_amount,
           COALESCE(SUM(bl.budget_amount), 0) - COALESCE(SUM(bp.amount), 0) AS variance
    FROM categories c
    LEFT JOIN budgets b ON b.fiscal_year = ? AND b.fund_code = c.fund_code
    LEFT JOIN budget_lines bl ON bl.budget_id = b.id AND bl.category_id = c.id
    LEFT JOIN vendor_bills vb ON vb.category_id = c.id
    LEFT JOIN bill_payments bp ON bp.vendor_bill_id = vb.id AND strftime('%Y', bp.payment_date) = ?
    WHERE c.category_type = 'EXPENSE'
    GROUP BY c.id, c.name
    HAVING budget_amount > 0 OR actual_amount > 0
    ORDER BY c.sort_order, c.name
  `, [year, String(year)]);
}

function BudgetVsActualReport({ year }: { year: number }) {
  const [rows, setRows] = useState<BvARow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    loadBudgetVsActual(year).then(setRows).finally(() => setLoading(false));
  }, [year]);

  const totalBudget = rows.reduce((s, r) => s + r.budget_amount, 0);
  const totalActual = rows.reduce((s, r) => s + r.actual_amount, 0);

  return (
    <div>
      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {!loading && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Category</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Budget</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Actual</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Variance</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">vs Budget</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {rows.length === 0 && <tr><td colSpan={5} className="px-4 py-6 text-center text-gray-400 text-sm">No budget or expense data for {year}.</td></tr>}
              {rows.map((r) => {
                const pct = r.budget_amount > 0 ? (r.actual_amount / r.budget_amount) * 100 : null;
                return (
                  <tr key={r.category_name}>
                    <td className="px-4 py-2 text-gray-700">{r.category_name}</td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-gray-500">{fmt(r.budget_amount)}</td>
                    <td className="px-4 py-2 text-right font-mono text-xs text-red-600">{fmt(r.actual_amount)}</td>
                    <td className={`px-4 py-2 text-right font-mono text-xs ${r.variance >= 0 ? "text-green-700" : "text-red-600"}`}>{fmt(r.variance)}</td>
                    <td className="px-4 py-2 text-xs">
                      {pct !== null ? (
                        <div className="flex items-center gap-2">
                          <div className="w-20 bg-gray-200 rounded-full h-1.5">
                            <div className={`h-1.5 rounded-full ${pct > 100 ? "bg-red-500" : pct > 80 ? "bg-orange-400" : "bg-green-500"}`}
                              style={{ width: `${Math.min(pct, 100)}%` }} />
                          </div>
                          <span className="text-gray-500">{pct.toFixed(0)}%</span>
                        </div>
                      ) : "—"}
                    </td>
                  </tr>
                );
              })}
              {rows.length > 0 && (
                <tr className="bg-gray-50 font-semibold">
                  <td className="px-4 py-2 text-gray-600 text-xs">Total</td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-gray-600">{fmt(totalBudget)}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-red-700">{fmt(totalActual)}</td>
                  <td className={`px-4 py-2 text-right font-mono text-xs ${totalBudget - totalActual >= 0 ? "text-green-700" : "text-red-600"}`}>{fmt(totalBudget - totalActual)}</td>
                  <td className="px-4 py-2" />
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Expense Detail ────────────────────────────────────────────────────────────

type ExpenseDetailRow = {
  payment_date: string;
  vendor_name: string;
  invoice_number: string;
  category_name: string;
  amount: number;
  check_number: string | null;
};

async function loadExpenseDetail(year: number): Promise<ExpenseDetailRow[]> {
  const db = await getDb();
  return db.select<ExpenseDetailRow[]>(`
    SELECT bp.payment_date, v.vendor_name, vb.invoice_number,
           c.name AS category_name, bp.amount, bp.check_number
    FROM bill_payments bp
    JOIN vendor_bills vb ON vb.id = bp.vendor_bill_id
    JOIN vendors v ON v.id = vb.vendor_id
    LEFT JOIN categories c ON c.id = vb.category_id
    WHERE strftime('%Y', bp.payment_date) = ?
    ORDER BY bp.payment_date DESC
  `, [String(year)]);
}

function ExpenseDetailReport({ year }: { year: number }) {
  const [rows, setRows] = useState<ExpenseDetailRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    loadExpenseDetail(year).then(setRows).finally(() => setLoading(false));
  }, [year]);

  return (
    <div>
      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {!loading && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Date</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Vendor</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Invoice</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Category</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Check #</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {rows.length === 0 && <tr><td colSpan={6} className="px-4 py-6 text-center text-gray-400 text-sm">No expense payments for {year}.</td></tr>}
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="px-4 py-2 text-gray-600 text-xs">{r.payment_date}</td>
                  <td className="px-4 py-2 text-gray-700 text-xs">{r.vendor_name}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{r.invoice_number}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{r.category_name ?? "—"}</td>
                  <td className="px-4 py-2 text-gray-400 text-xs">{r.check_number ?? "—"}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-red-600">{fmt(r.amount)}</td>
                </tr>
              ))}
              {rows.length > 0 && (
                <tr className="bg-gray-50 font-semibold">
                  <td colSpan={5} className="px-4 py-2 text-gray-600 text-xs">Total</td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-red-700">{fmt(rows.reduce((s, r) => s + r.amount, 0))}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Vendor Expenses ───────────────────────────────────────────────────────────

type VendorExpenseRow = { vendor_name: string; paid: number; open: number; total: number };

async function loadVendorExpenses(year: number): Promise<VendorExpenseRow[]> {
  const db = await getDb();
  return db.select<VendorExpenseRow[]>(`
    SELECT v.vendor_name,
           COALESCE(SUM(CASE WHEN vb.status IN ('PAID','PARTIAL') THEN bp.amount ELSE 0 END), 0) AS paid,
           COALESCE(SUM(CASE WHEN vb.status = 'OPEN' THEN vb.amount ELSE 0 END), 0) AS open,
           COALESCE(SUM(vb.amount), 0) AS total
    FROM vendors v
    JOIN vendor_bills vb ON vb.vendor_id = v.id AND strftime('%Y', vb.invoice_date) = ?
    LEFT JOIN bill_payments bp ON bp.vendor_bill_id = vb.id
    GROUP BY v.id, v.vendor_name
    ORDER BY total DESC
  `, [String(year)]);
}

function VendorExpensesReport({ year }: { year: number }) {
  const [rows, setRows] = useState<VendorExpenseRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    loadVendorExpenses(year).then(setRows).finally(() => setLoading(false));
  }, [year]);

  return (
    <div>
      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {!loading && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Vendor</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Paid</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Open</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Total Invoiced</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {rows.length === 0 && <tr><td colSpan={4} className="px-4 py-6 text-center text-gray-400 text-sm">No vendor invoices for {year}.</td></tr>}
              {rows.map((r) => (
                <tr key={r.vendor_name}>
                  <td className="px-4 py-2 text-gray-700">{r.vendor_name}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-green-700">{fmt(r.paid)}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-orange-600">{r.open > 0 ? fmt(r.open) : "—"}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs font-semibold text-gray-900">{fmt(r.total)}</td>
                </tr>
              ))}
              {rows.length > 0 && (
                <tr className="bg-gray-50 font-semibold">
                  <td className="px-4 py-2 text-gray-600 text-xs">Total</td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-green-800">{fmt(rows.reduce((s, r) => s + r.paid, 0))}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-orange-700">{fmt(rows.reduce((s, r) => s + r.open, 0))}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-gray-900">{fmt(rows.reduce((s, r) => s + r.total, 0))}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Deposits Report ───────────────────────────────────────────────────────────

type DepositReportRow = {
  deposit_date: string;
  account_name: string;
  check_count: number;
  total_amount: number;
  status: string;
};

async function loadDepositsReport(year: number): Promise<DepositReportRow[]> {
  const db = await getDb();
  return db.select<DepositReportRow[]>(`
    SELECT d.deposit_date, b.account_name, d.check_count, d.total_amount, d.status
    FROM deposit_batches d
    JOIN bank_accounts b ON b.id = d.bank_account_id
    WHERE strftime('%Y', d.deposit_date) = ?
    ORDER BY d.deposit_date DESC
  `, [String(year)]);
}

function DepositsReport({ year }: { year: number }) {
  const [rows, setRows] = useState<DepositReportRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    loadDepositsReport(year).then(setRows).finally(() => setLoading(false));
  }, [year]);

  return (
    <div>
      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {!loading && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Date</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Account</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Checks</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {rows.length === 0 && <tr><td colSpan={5} className="px-4 py-6 text-center text-gray-400 text-sm">No deposits for {year}.</td></tr>}
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="px-4 py-2 text-gray-600 text-xs">{r.deposit_date}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{r.account_name}</td>
                  <td className="px-4 py-2 text-right text-gray-500 text-xs">{r.check_count}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-green-700">{fmt(r.total_amount)}</td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${r.status === "POSTED" ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"}`}>
                      {r.status}
                    </span>
                  </td>
                </tr>
              ))}
              {rows.length > 0 && (
                <tr className="bg-gray-50 font-semibold">
                  <td colSpan={2} className="px-4 py-2 text-gray-600 text-xs">Total</td>
                  <td className="px-4 py-2 text-right text-xs">{rows.reduce((s, r) => s + r.check_count, 0)}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-green-800">{fmt(rows.reduce((s, r) => s + r.total_amount, 0))}</td>
                  <td className="px-4 py-2" />
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Delinquency Report ────────────────────────────────────────────────────────

type DelinquencyRow = {
  lot_number: string;
  owner_name: string | null;
  email: string | null;
  phone: string | null;
  open_amount: number;
  oldest_due_date: string | null;
  days_overdue: number;
};

async function loadDelinquency(): Promise<DelinquencyRow[]> {
  const db = await getDb();
  const today = new Date().toISOString().slice(0, 10);
  return db.select<DelinquencyRow[]>(`
    SELECT l.lot_number, o.display_name AS owner_name, o.email, o.phone,
           SUM(a.amount) AS open_amount,
           MIN(COALESCE(a.due_date, a.assessment_date)) AS oldest_due_date,
           CAST(julianday(?) - julianday(MIN(COALESCE(a.due_date, a.assessment_date))) AS INTEGER) AS days_overdue
    FROM assessments a
    JOIN lots l ON l.id = a.lot_id
    LEFT JOIN owners o ON o.id = a.owner_id
    WHERE a.status IN ('OPEN','PARTIAL')
      AND julianday(?) > julianday(COALESCE(a.due_date, a.assessment_date))
    GROUP BY l.id
    ORDER BY days_overdue DESC
  `, [today, today]);
}

function DelinquencyReport() {
  const [rows, setRows] = useState<DelinquencyRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadDelinquency()
      .then(setRows)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!loading && rows.length === 0 && (
        <div className="p-6 text-center text-sm text-green-700 bg-green-50 rounded-lg border border-green-200">
          No delinquent accounts — all assessments are current.
        </div>
      )}
      {!loading && rows.length > 0 && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Lot</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Owner</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Contact</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Oldest Due</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Days Overdue</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Balance Due</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {rows.map((r) => (
                <tr key={r.lot_number} className={r.days_overdue > 90 ? "bg-red-50" : r.days_overdue > 30 ? "bg-orange-50" : ""}>
                  <td className="px-4 py-2 font-medium text-gray-900">Lot {r.lot_number}</td>
                  <td className="px-4 py-2 text-gray-700 text-xs">{r.owner_name ?? "—"}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{r.email ?? r.phone ?? "—"}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{r.oldest_due_date ?? "—"}</td>
                  <td className={`px-4 py-2 text-right font-mono text-xs font-semibold ${r.days_overdue > 90 ? "text-red-600" : r.days_overdue > 30 ? "text-orange-600" : "text-yellow-700"}`}>
                    {r.days_overdue}d
                  </td>
                  <td className="px-4 py-2 text-right font-mono font-semibold text-red-700">{fmt(r.open_amount)}</td>
                </tr>
              ))}
              <tr className="bg-gray-50 font-semibold">
                <td colSpan={5} className="px-4 py-2 text-gray-600 text-xs">Total ({rows.length} lots)</td>
                <td className="px-4 py-2 text-right font-mono text-xs text-red-700">{fmt(rows.reduce((s, r) => s + r.open_amount, 0))}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function TransactionHistoryReport({ limit = 500 }: { limit?: number }) {
  const [rows, setRows] = useState<TxnRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try { setRows(await loadTransactionHistory(limit)); }
    catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [limit]);

  useEffect(() => { void load(); }, [load]);

  return (
    <div className="space-y-3">
      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!loading && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Date</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Type</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Description</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Account</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Lot</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {rows.length === 0 && <tr><td colSpan={6} className="px-4 py-6 text-center text-gray-400 text-sm">No transactions yet.</td></tr>}
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="px-4 py-2 text-gray-600 text-xs">{r.txn_date}</td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${r.source_type === "PAYMENT" ? "bg-green-100 text-green-700" : r.source_type === "BILL_PAYMENT" ? "bg-red-100 text-red-700" : "bg-blue-100 text-blue-700"}`}>
                      {SOURCE_LABELS[r.source_type] ?? r.source_type}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-gray-700 text-xs">{r.description}</td>
                  <td className="px-4 py-2 text-gray-400 text-xs">{r.account_name ?? "—"}</td>
                  <td className="px-4 py-2 text-gray-400 text-xs">{r.lot_number ? `Lot ${r.lot_number}` : "—"}</td>
                  <td className={`px-4 py-2 text-right font-mono text-xs ${r.amount < 0 ? "text-red-600" : "text-green-700"}`}>{fmt(r.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Account Detail (Ledger) ───────────────────────────────────────────────────

type LedgerRow = { txn_date: string; source_type: string; description: string; amount: number; lot_number: string | null; running_balance?: number };

async function loadLedger(bankAccountId: number, limit: number): Promise<LedgerRow[]> {
  const db = await getDb();
  const rows = await db.select<LedgerRow[]>(`
    SELECT p.payment_date AS txn_date, 'PAYMENT' AS source_type,
           COALESCE('Payment — ' || o.display_name, 'Payment — Lot ' || l.lot_number) AS description,
           p.amount, l.lot_number
    FROM payments p JOIN lots l ON l.id = p.lot_id LEFT JOIN owners o ON o.id = p.owner_id
    LEFT JOIN deposit_batches d ON d.id = p.deposit_batch_id WHERE d.bank_account_id = ?
    UNION ALL
    SELECT bp.payment_date, 'BILL_PAYMENT', 'Bill — ' || v.vendor_name, -bp.amount, NULL
    FROM bill_payments bp JOIN vendor_bills vb ON vb.id = bp.vendor_bill_id
    JOIN vendors v ON v.id = vb.vendor_id WHERE bp.bank_account_id = ?
    UNION ALL
    SELECT ib.income_date, 'INCOME', COALESCE(ib.description, c.name), ib.amount, l.lot_number
    FROM income_batches ib JOIN categories c ON c.id = ib.category_id
    LEFT JOIN lots l ON l.id = ib.lot_id WHERE ib.bank_account_id = ?
    ORDER BY txn_date ASC LIMIT ?
  `, [bankAccountId, bankAccountId, bankAccountId, limit]);
  let balance = 0;
  for (const r of rows) { balance += r.amount; r.running_balance = balance; }
  return rows.reverse();
}

function AccountDetailReport({ accountId = 0, limit = 500 }: { accountId?: number; limit?: number }) {
  const [rows, setRows] = useState<LedgerRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accountId) { setLoading(false); return; }
    setLoading(true);
    try { setRows(await loadLedger(accountId, limit)); }
    catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [accountId, limit]);

  useEffect(() => { if (accountId) void load(); }, [load, accountId]);

  return (
    <div className="space-y-3">
      {!accountId && !loading && <p className="text-sm text-gray-500">No bank account selected. Select one above and click Run Report.</p>}
      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!loading && rows.length > 0 && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Date</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Type</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Description</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Lot</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Balance</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {rows.length === 0 && <tr><td colSpan={6} className="px-4 py-6 text-center text-gray-400 text-sm">No transactions for this account.</td></tr>}
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="px-4 py-2 text-gray-600 text-xs">{r.txn_date}</td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${r.source_type === "PAYMENT" ? "bg-green-100 text-green-700" : r.source_type === "BILL_PAYMENT" ? "bg-red-100 text-red-700" : "bg-blue-100 text-blue-700"}`}>
                      {SOURCE_LABELS[r.source_type] ?? r.source_type}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-gray-700 text-xs">{r.description}</td>
                  <td className="px-4 py-2 text-gray-400 text-xs">{r.lot_number ? `Lot ${r.lot_number}` : "—"}</td>
                  <td className={`px-4 py-2 text-right font-mono text-xs ${r.amount < 0 ? "text-red-600" : "text-green-700"}`}>{fmt(r.amount)}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-gray-700">{r.running_balance !== undefined ? fmt(r.running_balance) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Report types ──────────────────────────────────────────────────────────────

// ── Inline summary report components ─────────────────────────────────────────

function ARAgingReport() {
  const [rows, setRows] = useState<AgingBucket[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => { loadARaging().then(setRows).finally(() => setLoading(false)); }, []);
  if (loading) return <p className="text-sm text-gray-400">Loading…</p>;
  return (
    <div className="border rounded-lg overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 border-b">
          <tr>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Lot</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Owner</th>
            <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Current (0–30d)</th>
            <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">31–60d</th>
            <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">61–90d</th>
            <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">90d+</th>
            <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Total</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {rows.length === 0 && <tr><td colSpan={7} className="px-4 py-6 text-center text-gray-400 text-sm">No outstanding balances.</td></tr>}
          {rows.map((r) => (
            <tr key={r.lot_number}>
              <td className="px-4 py-2 font-medium text-gray-900">Lot {r.lot_number}</td>
              <td className="px-4 py-2 text-gray-600 text-xs">{r.owner_name ?? "—"}</td>
              <td className="px-4 py-2 text-right font-mono text-xs">{r.current > 0 ? fmt(r.current) : "—"}</td>
              <td className="px-4 py-2 text-right font-mono text-xs">{r.d30 > 0 ? fmt(r.d30) : "—"}</td>
              <td className="px-4 py-2 text-right font-mono text-xs text-orange-600">{r.d60 > 0 ? fmt(r.d60) : "—"}</td>
              <td className="px-4 py-2 text-right font-mono text-xs text-red-600">{r.d90plus > 0 ? fmt(r.d90plus) : "—"}</td>
              <td className="px-4 py-2 text-right font-mono font-semibold text-gray-900">{fmt(r.total)}</td>
            </tr>
          ))}
          {rows.length > 0 && (
            <tr className="bg-gray-50 font-semibold">
              <td colSpan={2} className="px-4 py-2 text-gray-600 text-xs">Total</td>
              <td className="px-4 py-2 text-right font-mono text-xs">{fmt(rows.reduce((s, r) => s + r.current, 0))}</td>
              <td className="px-4 py-2 text-right font-mono text-xs">{fmt(rows.reduce((s, r) => s + r.d30, 0))}</td>
              <td className="px-4 py-2 text-right font-mono text-xs">{fmt(rows.reduce((s, r) => s + r.d60, 0))}</td>
              <td className="px-4 py-2 text-right font-mono text-xs">{fmt(rows.reduce((s, r) => s + r.d90plus, 0))}</td>
              <td className="px-4 py-2 text-right font-mono text-gray-900">{fmt(rows.reduce((s, r) => s + r.total, 0))}</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function IncomeSummaryReport({ year }: { year: number }) {
  const [rows, setRows] = useState<IncomeRow[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => { setLoading(true); loadIncomeSummary(year).then(setRows).finally(() => setLoading(false)); }, [year]);
  if (loading) return <p className="text-sm text-gray-400">Loading…</p>;
  return (
    <div className="border rounded-lg overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 border-b">
          <tr>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Category</th>
            <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Total {year}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {rows.length === 0 && <tr><td colSpan={2} className="px-4 py-6 text-center text-gray-400 text-sm">No income for {year}.</td></tr>}
          {rows.map((r) => (
            <tr key={r.category_name}>
              <td className="px-4 py-2 text-gray-700">{r.category_name}</td>
              <td className="px-4 py-2 text-right font-mono text-green-700">{fmt(r.total)}</td>
            </tr>
          ))}
          {rows.length > 0 && (
            <tr className="bg-gray-50 font-semibold">
              <td className="px-4 py-2 text-gray-600">Total</td>
              <td className="px-4 py-2 text-right font-mono text-green-800">{fmt(rows.reduce((s, r) => s + r.total, 0))}</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function ExpenseSummaryReport({ year }: { year: number }) {
  const [rows, setRows] = useState<ExpenseRow[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => { setLoading(true); loadExpenseSummary(year).then(setRows).finally(() => setLoading(false)); }, [year]);
  if (loading) return <p className="text-sm text-gray-400">Loading…</p>;
  return (
    <div className="border rounded-lg overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 border-b">
          <tr>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Category</th>
            <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Total {year}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {rows.length === 0 && <tr><td colSpan={2} className="px-4 py-6 text-center text-gray-400 text-sm">No expenses for {year}.</td></tr>}
          {rows.map((r) => (
            <tr key={r.category_name}>
              <td className="px-4 py-2 text-gray-700">{r.category_name}</td>
              <td className="px-4 py-2 text-right font-mono text-red-600">{fmt(r.total)}</td>
            </tr>
          ))}
          {rows.length > 0 && (
            <tr className="bg-gray-50 font-semibold">
              <td className="px-4 py-2 text-gray-600">Total</td>
              <td className="px-4 py-2 text-right font-mono text-red-700">{fmt(rows.reduce((s, r) => s + r.total, 0))}</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ── Report definitions ────────────────────────────────────────────────────────

type ReportType =
  | "ar_aging" | "expense_summary" | "income_summary" | "txn_history"
  | "account_detail" | "contact_list" | "owner_ledger" | "budget_vs_actual"
  | "expense_detail" | "vendor_expenses" | "deposits" | "delinquency";

type ParamType = "year" | "owner" | "account" | "limit" | "none";

const REPORT_DEFS: { key: ReportType; title: string; description: string; params: ParamType[] }[] = [
  { key: "ar_aging",         title: "AR Aging",            description: "Outstanding balances by lot, bucketed by age",              params: ["none"] },
  { key: "delinquency",      title: "Delinquency",         description: "Overdue accounts ranked by days past due",                  params: ["none"] },
  { key: "contact_list",     title: "Contact List",        description: "Homeowner directory with addresses and contact info",       params: ["none"] },
  { key: "income_summary",   title: "Income Summary",      description: "Total income by category for the year",                    params: ["year"] },
  { key: "expense_summary",  title: "Expense Summary",     description: "Total expenses by category for the year",                  params: ["year"] },
  { key: "expense_detail",   title: "Expense Detail",      description: "Every expense payment with vendor and check number",       params: ["year"] },
  { key: "vendor_expenses",  title: "Vendor Expenses",     description: "Total invoiced and paid per vendor for the year",          params: ["year"] },
  { key: "budget_vs_actual", title: "Budget vs Actual",    description: "Compare budgeted vs actual spending by category",         params: ["year"] },
  { key: "deposits",         title: "Deposits",            description: "All deposit batches for the year",                        params: ["year"] },
  { key: "txn_history",      title: "Transaction History", description: "All transactions across all accounts",                    params: ["limit"] },
  { key: "account_detail",   title: "Account Detail",      description: "Ledger with running balance for one bank account",        params: ["account", "limit"] },
  { key: "owner_ledger",     title: "Owner Ledger",        description: "Full charge and payment history for a specific owner",    params: ["owner"] },
];

// Preserved for type compatibility — not used in new UI
const REPORTS = REPORT_DEFS;
// eslint-disable-next-line @typescript-eslint/no-unused-vars
void REPORTS;

const CURRENT_YEAR = new Date().getFullYear();

// ── Main screen ───────────────────────────────────────────────────────────────

import { PageLayout } from "../components/PageLayout";

export function ReportsScreen() {
  const [selected, setSelected] = useState<ReportType | "">("");
  const [year, setYear] = useState(CURRENT_YEAR);
  const [ownerId, setOwnerId] = useState(0);
  const [owners, setOwners] = useState<OwnerSummary[]>([]);
  const [accountId, setAccountId] = useState(0);
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [txnLimit, setTxnLimit] = useState(100);
  const [runKey, setRunKey] = useState(0);
  const [hasRun, setHasRun] = useState(false);

  const def = REPORT_DEFS.find((r) => r.key === selected);
  const needsYear    = def?.params.includes("year");
  const needsOwner   = def?.params.includes("owner");
  const needsAccount = def?.params.includes("account");
  const needsLimit   = def?.params.includes("limit");

  useEffect(() => {
    loadOwners().then((o) => { setOwners(o); if (o[0]) setOwnerId(o[0].id); }).catch(() => {});
    listBankAccounts().then((a) => { setAccounts(a); if (a[0]) setAccountId(a[0].id); }).catch(() => {});
  }, []);

  useEffect(() => { setHasRun(false); }, [selected]);

  function handleRun() {
    setRunKey((k) => k + 1);
    setHasRun(true);
  }

  return (
    <PageLayout title="Reports" subtitle="Financial summaries and operational reports." helpId="reports">
      <div className="max-w-5xl">
        {/* Selector + params */}
        <div className="bg-white border rounded-lg p-4 mb-5 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <div className="lg:col-span-1">
              <label className="block text-xs font-medium text-gray-700 mb-1">Report</label>
              <select
                value={selected}
                onChange={(e) => setSelected(e.target.value as ReportType | "")}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
              >
                <option value="">— Select a report —</option>
                <optgroup label="AR &amp; Collections">
                  {REPORT_DEFS.filter((r) => ["ar_aging","delinquency"].includes(r.key)).map((r) => (
                    <option key={r.key} value={r.key}>{r.title}</option>
                  ))}
                </optgroup>
                <optgroup label="Income &amp; Expenses">
                  {REPORT_DEFS.filter((r) => ["income_summary","expense_summary","expense_detail","vendor_expenses","budget_vs_actual","deposits"].includes(r.key)).map((r) => (
                    <option key={r.key} value={r.key}>{r.title}</option>
                  ))}
                </optgroup>
                <optgroup label="Transactions &amp; Ledgers">
                  {REPORT_DEFS.filter((r) => ["txn_history","account_detail","owner_ledger"].includes(r.key)).map((r) => (
                    <option key={r.key} value={r.key}>{r.title}</option>
                  ))}
                </optgroup>
                <optgroup label="Directory">
                  {REPORT_DEFS.filter((r) => ["contact_list"].includes(r.key)).map((r) => (
                    <option key={r.key} value={r.key}>{r.title}</option>
                  ))}
                </optgroup>
              </select>
              {def && <p className="mt-1 text-xs text-gray-500">{def.description}</p>}
            </div>

            {needsYear && (
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Year</label>
                <select
                  value={year}
                  onChange={(e) => setYear(Number(e.target.value))}
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                >
                  {[CURRENT_YEAR, CURRENT_YEAR - 1, CURRENT_YEAR - 2, CURRENT_YEAR - 3].map((y) => (
                    <option key={y} value={y}>{y}</option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-gray-400">Jan 1 – Dec 31, {year}</p>
              </div>
            )}

            {needsOwner && (
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Owner</label>
                <select
                  value={ownerId}
                  onChange={(e) => setOwnerId(Number(e.target.value))}
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                >
                  {owners.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.display_name}{o.lot_number ? ` (Lot ${o.lot_number})` : ""}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {needsAccount && (
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Bank Account</label>
                <select
                  value={accountId}
                  onChange={(e) => setAccountId(Number(e.target.value))}
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                >
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>{a.account_name}</option>
                  ))}
                </select>
              </div>
            )}

            {needsLimit && (
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Row Limit</label>
                <select
                  value={txnLimit}
                  onChange={(e) => setTxnLimit(Number(e.target.value))}
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                >
                  <option value={50}>Last 50</option>
                  <option value={100}>Last 100</option>
                  <option value={250}>Last 250</option>
                  <option value={500}>Last 500</option>
                </select>
              </div>
            )}
          </div>

          <div className="flex items-center gap-3 pt-1 border-t border-gray-100">
            <button
              onClick={handleRun}
              disabled={!selected}
              className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Run Report
            </button>
            {hasRun && def && (
              <span className="text-xs text-gray-400">
                Showing: <strong>{def.title}</strong>
                {needsYear && ` — ${year}`}
              </span>
            )}
          </div>
        </div>

        {/* Report output */}
        {!hasRun && (
          <div className="text-center py-12 text-gray-400 text-sm border border-dashed border-gray-200 rounded-lg">
            Select a report above and click <strong className="text-gray-500">Run Report</strong>.
          </div>
        )}

        {hasRun && selected === "ar_aging"         && <ARAgingReport        key={runKey} />}
        {hasRun && selected === "delinquency"       && <DelinquencyReport    key={runKey} />}
        {hasRun && selected === "contact_list"      && <ContactListReport    key={runKey} />}
        {hasRun && selected === "income_summary"    && <IncomeSummaryReport  key={runKey} year={year} />}
        {hasRun && selected === "expense_summary"   && <ExpenseSummaryReport key={runKey} year={year} />}
        {hasRun && selected === "expense_detail"    && <ExpenseDetailReport  key={runKey} year={year} />}
        {hasRun && selected === "vendor_expenses"   && <VendorExpensesReport key={runKey} year={year} />}
        {hasRun && selected === "budget_vs_actual"  && <BudgetVsActualReport key={runKey} year={year} />}
        {hasRun && selected === "deposits"          && <DepositsReport       key={runKey} year={year} />}
        {hasRun && selected === "txn_history"       && <TransactionHistoryReport key={runKey} limit={txnLimit} />}
        {hasRun && selected === "account_detail"    && <AccountDetailReport  key={runKey} accountId={accountId} limit={txnLimit} />}
        {hasRun && selected === "owner_ledger"      && <OwnerLedgerReport    key={runKey} ownerId={ownerId} />}
      </div>
    </PageLayout>
  );
}
