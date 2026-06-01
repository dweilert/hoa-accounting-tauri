import { useEffect, useState, useCallback } from "react";
import { getDb } from "../lib/db";
import { listCategories } from "../repositories/categoryRepo";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import { Modal } from "../components/Modal";
import { PageLayout } from "../components/PageLayout";
import type { Category } from "../types/category";
import type { BankAccount } from "../types/bankAccount";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

// ── Tab: Payments ─────────────────────────────────────────────────────────────

type PaymentEditRow = {
  id: number;
  payment_date: string;
  amount: number;
  payment_method: string;
  check_number: string | null;
  memo: string | null;
  lot_number: string;
  owner_name: string | null;
  deposit_batch_id: number | null;
  lot_id: number;
  owner_id: number | null;
};

function PaymentsTab() {
  const [payments, setPayments] = useState<PaymentEditRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<PaymentEditRow | null>(null);
  const [editValues, setEditValues] = useState<Partial<PaymentEditRow>>({});
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const db = await getDb();
      const rows = await db.select<PaymentEditRow[]>(`
        SELECT p.id, p.payment_date, p.amount, p.payment_method, p.check_number, p.memo,
               p.lot_id, p.owner_id, p.deposit_batch_id,
               l.lot_number, o.display_name AS owner_name
        FROM payments p
        JOIN lots l ON l.id = p.lot_id
        LEFT JOIN owners o ON o.id = p.owner_id
        ORDER BY p.payment_date DESC
        LIMIT 200
      `);
      setPayments(rows);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  function startEdit(p: PaymentEditRow) {
    setEditing(p);
    setEditValues({});
  }

  async function saveEdit() {
    if (!editing) return;
    setSaving(true);
    try {
      const db = await getDb();
      await db.execute(
        `UPDATE payments SET payment_date = ?, amount = ?, payment_method = ?,
         check_number = ?, memo = ? WHERE id = ?`,
        [
          editValues.payment_date ?? editing.payment_date,
          editValues.amount ?? editing.amount,
          editValues.payment_method ?? editing.payment_method,
          editValues.check_number ?? null,
          editValues.memo ?? null,
          editing.id,
        ]
      );
      setEditing(null);
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  const METHODS = ["CHECK", "ACH", "ONLINE", "CASH", "OTHER"];

  return (
    <div>
      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
      {!loading && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Date</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Lot</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Owner</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Method</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Check #</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {payments.length === 0 && (
                <tr><td colSpan={7} className="px-4 py-6 text-center text-gray-400 text-sm">No payments found.</td></tr>
              )}
              {payments.map((p) => (
                <tr key={p.id}>
                  <td className="px-4 py-2 text-gray-600 text-xs">{p.payment_date}</td>
                  <td className="px-4 py-2 font-medium text-gray-900">Lot {p.lot_number}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{p.owner_name ?? "—"}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{p.payment_method}</td>
                  <td className="px-4 py-2 text-gray-400 text-xs">{p.check_number ?? "—"}</td>
                  <td className="px-4 py-2 text-right font-mono text-green-700">{fmt(p.amount)}</td>
                  <td className="px-4 py-2 text-right">
                    <button onClick={() => startEdit(p)} className="text-xs text-blue-600 hover:underline">Edit</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <Modal title="Edit Payment" onClose={() => setEditing(null)}>
          <div className="space-y-4">
            <div className="p-3 bg-gray-50 rounded text-xs text-gray-500">
              Lot {editing.lot_number} · {editing.owner_name ?? "No owner"}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Payment Date</label>
                <input type="date" value={editValues.payment_date ?? editing.payment_date}
                  onChange={(e) => setEditValues((v) => ({ ...v, payment_date: e.target.value }))}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Amount</label>
                <input type="number" step="0.01" min="0.01"
                  value={editValues.amount ?? editing.amount}
                  onChange={(e) => setEditValues((v) => ({ ...v, amount: Number(e.target.value) }))}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Method</label>
                <select value={editValues.payment_method ?? editing.payment_method}
                  onChange={(e) => setEditValues((v) => ({ ...v, payment_method: e.target.value }))}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                  {METHODS.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Check Number</label>
                <input type="text" value={editValues.check_number ?? editing.check_number ?? ""}
                  onChange={(e) => setEditValues((v) => ({ ...v, check_number: e.target.value || null }))}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Memo</label>
              <input type="text" value={editValues.memo ?? editing.memo ?? ""}
                onChange={(e) => setEditValues((v) => ({ ...v, memo: e.target.value || null }))}
                className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div className="flex justify-end gap-3 pt-2 border-t">
              <button onClick={() => setEditing(null)} className="px-4 py-2 text-sm text-gray-600">Cancel</button>
              <button onClick={() => void saveEdit()} disabled={saving}
                className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
                {saving ? "Saving…" : "Save Changes"}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ── Tab: Non-Dues Income ──────────────────────────────────────────────────────

type IncomeEditRow = {
  id: number;
  income_date: string;
  amount: number;
  description: string | null;
  category_id: number;
  category_name: string;
  bank_account_id: number;
  account_name: string;
  lot_number: string | null;
  reference: string | null;
};

function IncomeTab() {
  const [income, setIncome] = useState<IncomeEditRow[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [bankAccounts, setBankAccounts] = useState<BankAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<IncomeEditRow | null>(null);
  const [editValues, setEditValues] = useState<Partial<IncomeEditRow>>({});
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const db = await getDb();
      const [rows, cats, accounts] = await Promise.all([
        db.select<IncomeEditRow[]>(`
          SELECT ib.id, ib.income_date, ib.amount, ib.description, ib.category_id,
                 ib.bank_account_id, ib.reference,
                 c.name AS category_name, b.account_name,
                 l.lot_number
          FROM income_batches ib
          JOIN categories c ON c.id = ib.category_id
          JOIN bank_accounts b ON b.id = ib.bank_account_id
          LEFT JOIN lots l ON l.id = ib.lot_id
          ORDER BY ib.income_date DESC
          LIMIT 200
        `),
        listCategories(),
        listBankAccounts(),
      ]);
      setIncome(rows);
      setCategories(cats);
      setBankAccounts(accounts);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function saveEdit() {
    if (!editing) return;
    setSaving(true);
    try {
      const db = await getDb();
      await db.execute(
        `UPDATE income_batches SET income_date = ?, amount = ?, category_id = ?,
         bank_account_id = ?, description = ?, reference = ? WHERE id = ?`,
        [
          editValues.income_date ?? editing.income_date,
          editValues.amount ?? editing.amount,
          editValues.category_id ?? editing.category_id,
          editValues.bank_account_id ?? editing.bank_account_id,
          editValues.description ?? null,
          editValues.reference ?? null,
          editing.id,
        ]
      );
      setEditing(null);
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
      {!loading && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Date</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Category</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Account</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Description</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {income.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-6 text-center text-gray-400 text-sm">No income records found.</td></tr>
              )}
              {income.map((r) => (
                <tr key={r.id}>
                  <td className="px-4 py-2 text-gray-600 text-xs">{r.income_date}</td>
                  <td className="px-4 py-2 text-gray-700 text-xs">{r.category_name}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{r.account_name}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{r.description ?? "—"}</td>
                  <td className={`px-4 py-2 text-right font-mono text-xs ${r.amount >= 0 ? "text-green-700" : "text-red-600"}`}>{fmt(r.amount)}</td>
                  <td className="px-4 py-2 text-right">
                    <button onClick={() => { setEditing(r); setEditValues({}); }} className="text-xs text-blue-600 hover:underline">Edit</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <Modal title="Edit Income Record" onClose={() => setEditing(null)}>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Date</label>
                <input type="date" value={editValues.income_date ?? editing.income_date}
                  onChange={(e) => setEditValues((v) => ({ ...v, income_date: e.target.value }))}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Amount</label>
                <input type="number" step="0.01"
                  value={editValues.amount ?? editing.amount}
                  onChange={(e) => setEditValues((v) => ({ ...v, amount: Number(e.target.value) }))}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Category</label>
                <select value={editValues.category_id ?? editing.category_id}
                  onChange={(e) => setEditValues((v) => ({ ...v, category_id: Number(e.target.value) }))}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                  {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Bank Account</label>
                <select value={editValues.bank_account_id ?? editing.bank_account_id}
                  onChange={(e) => setEditValues((v) => ({ ...v, bank_account_id: Number(e.target.value) }))}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                  {bankAccounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
                </select>
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Description</label>
              <input type="text" value={editValues.description ?? editing.description ?? ""}
                onChange={(e) => setEditValues((v) => ({ ...v, description: e.target.value || null }))}
                className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Reference</label>
              <input type="text" value={editValues.reference ?? editing.reference ?? ""}
                onChange={(e) => setEditValues((v) => ({ ...v, reference: e.target.value || null }))}
                className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div className="flex justify-end gap-3 pt-2 border-t">
              <button onClick={() => setEditing(null)} className="px-4 py-2 text-sm text-gray-600">Cancel</button>
              <button onClick={() => void saveEdit()} disabled={saving}
                className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
                {saving ? "Saving…" : "Save Changes"}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ── Tab: Assessments ──────────────────────────────────────────────────────────

type AssessmentEditRow = {
  id: number;
  assessment_date: string;
  due_date: string | null;
  amount: number;
  charge_type: string;
  status: string;
  description: string | null;
  lot_number: string;
  owner_name: string | null;
  lot_id: number;
  category_id: number | null;
};

function AssessmentsTab() {
  const [assessments, setAssessments] = useState<AssessmentEditRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<AssessmentEditRow | null>(null);
  const [editValues, setEditValues] = useState<Partial<AssessmentEditRow>>({});
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const db = await getDb();
      const rows = await db.select<AssessmentEditRow[]>(`
        SELECT a.id, a.assessment_date, a.due_date, a.amount, a.charge_type,
               a.status, a.description, a.lot_id, a.category_id,
               l.lot_number, o.display_name AS owner_name
        FROM assessments a
        JOIN lots l ON l.id = a.lot_id
        LEFT JOIN owners o ON o.id = a.owner_id
        WHERE a.status IN ('OPEN','PARTIAL')
        ORDER BY a.assessment_date DESC
        LIMIT 300
      `);
      setAssessments(rows);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function saveEdit() {
    if (!editing) return;
    setSaving(true);
    try {
      const db = await getDb();
      await db.execute(
        `UPDATE assessments SET assessment_date = ?, due_date = ?, amount = ?,
         description = ?, updated_at = datetime('now')
         WHERE id = ? AND status IN ('OPEN','PARTIAL')`,
        [
          editValues.assessment_date ?? editing.assessment_date,
          editValues.due_date ?? editing.due_date ?? null,
          editValues.amount ?? editing.amount,
          editValues.description ?? null,
          editing.id,
        ]
      );
      setEditing(null);
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
      {!loading && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Date</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Lot</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Owner</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Type</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Status</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {assessments.length === 0 && (
                <tr><td colSpan={7} className="px-4 py-6 text-center text-gray-400 text-sm">No open assessments.</td></tr>
              )}
              {assessments.map((a) => (
                <tr key={a.id}>
                  <td className="px-4 py-2 text-gray-600 text-xs">{a.assessment_date}</td>
                  <td className="px-4 py-2 font-medium text-gray-900">Lot {a.lot_number}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{a.owner_name ?? "—"}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{a.charge_type}</td>
                  <td className="px-4 py-2 text-right font-mono text-gray-700">{fmt(a.amount)}</td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      a.status === "OPEN" ? "bg-yellow-100 text-yellow-700" : "bg-orange-100 text-orange-700"
                    }`}>{a.status}</span>
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button onClick={() => { setEditing(a); setEditValues({}); }} className="text-xs text-blue-600 hover:underline">Edit</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <Modal title="Edit Assessment" onClose={() => setEditing(null)}>
          <div className="space-y-4">
            <div className="p-3 bg-gray-50 rounded text-xs text-gray-500">
              Lot {editing.lot_number} · {editing.owner_name ?? "No owner"} · {editing.charge_type}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Assessment Date</label>
                <input type="date" value={editValues.assessment_date ?? editing.assessment_date}
                  onChange={(e) => setEditValues((v) => ({ ...v, assessment_date: e.target.value }))}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Due Date</label>
                <input type="date" value={editValues.due_date ?? editing.due_date ?? ""}
                  onChange={(e) => setEditValues((v) => ({ ...v, due_date: e.target.value || null }))}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Amount</label>
                <input type="number" step="0.01" min="0.01"
                  value={editValues.amount ?? editing.amount}
                  onChange={(e) => setEditValues((v) => ({ ...v, amount: Number(e.target.value) }))}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div className="col-span-2">
                <label className="block text-xs font-medium text-gray-700 mb-1">Description</label>
                <input type="text" value={editValues.description ?? editing.description ?? ""}
                  onChange={(e) => setEditValues((v) => ({ ...v, description: e.target.value || null }))}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
            </div>
            <div className="flex justify-end gap-3 pt-2 border-t">
              <button onClick={() => setEditing(null)} className="px-4 py-2 text-sm text-gray-600">Cancel</button>
              <button onClick={() => void saveEdit()} disabled={saving}
                className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
                {saving ? "Saving…" : "Save Changes"}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ── Main screen ───────────────────────────────────────────────────────────────

type TabKey = "payments" | "income" | "assessments";

const TABS: { key: TabKey; label: string }[] = [
  { key: "payments", label: "Payments" },
  { key: "income", label: "Non-Dues Income" },
  { key: "assessments", label: "Assessments" },
];

export function EditRecordsScreen() {
  const [tab, setTab] = useState<TabKey>("payments");

  return (
    <PageLayout
      title="Edit Records"
      subtitle="Correct posted payments, income, and assessments."
      helpId="editRecords"
    >
      <div className="max-w-5xl">
        <div className="flex gap-1 border-b border-gray-200 mb-6">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ${
                tab === t.key
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === "payments" && <PaymentsTab />}
        {tab === "income" && <IncomeTab />}
        {tab === "assessments" && <AssessmentsTab />}
      </div>
    </PageLayout>
  );
}
