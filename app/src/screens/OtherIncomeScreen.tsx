import { useEffect, useState } from "react";
import { getDb } from "../lib/db";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import type { BankAccount } from "../types/bankAccount";
import { PageLayout } from "../components/PageLayout";
import { SortableTh } from "../components/SortableTh";
import { useTableSort } from "../lib/useTableSort";
import { appConfirm } from "../components/AppDialogs";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

type Category = { id: number; code: string; name: string; category_type: string };

type IncomeRow = {
  id: number;
  income_date: string;
  account_name: string;
  category_name: string;
  category_type: string;
  amount: number;
  description: string | null;
};

async function loadCategories(): Promise<Category[]> {
  const db = await getDb();
  return db.select<Category[]>(
    "SELECT id, code, name, category_type FROM categories WHERE category_type IN ('INCOME','EXPENSE') ORDER BY category_type DESC, sort_order ASC, name ASC"
  );
}

async function loadRows(limit: number): Promise<IncomeRow[]> {
  const db = await getDb();
  return db.select<IncomeRow[]>(
    `SELECT ib.id, ib.income_date, b.account_name, c.name AS category_name, c.category_type,
            ib.amount, ib.description
     FROM income_batches ib
     JOIN bank_accounts b  ON b.id = ib.bank_account_id
     JOIN categories c     ON c.id = ib.category_id
     WHERE ib.lot_id IS NULL
     ORDER BY ib.income_date DESC, ib.id DESC
     LIMIT ?`,
    [limit]
  );
}

async function insertRow(
  income_date: string,
  bank_account_id: number,
  category_id: number,
  rawAmount: number,
  direction: "credit" | "debit",
  description: string
): Promise<void> {
  const db = await getDb();
  const amount = direction === "debit" ? -Math.abs(rawAmount) : Math.abs(rawAmount);
  await db.execute(
    "INSERT INTO income_batches (income_date, bank_account_id, category_id, amount, description) VALUES (?, ?, ?, ?, ?)",
    [income_date, bank_account_id, category_id, amount, description || null]
  );
}

async function deleteRow(id: number): Promise<void> {
  const db = await getDb();
  await db.execute("DELETE FROM income_batches WHERE id = ? AND lot_id IS NULL", [id]);
}

// ── Form ──────────────────────────────────────────────────────────────────────

type FormVals = {
  income_date: string;
  bank_account_id: string;
  category_id: string;
  amount: string;
  direction: "credit" | "debit";
  description: string;
};

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

function EntryForm({
  accounts,
  categories,
  onSaved,
}: {
  accounts: BankAccount[];
  categories: Category[];
  onSaved: () => void;
}) {
  const [vals, setVals] = useState<FormVals>({
    income_date: todayStr(),
    bank_account_id: String(accounts[0]?.id ?? ""),
    category_id: "",
    amount: "",
    direction: "credit",
    description: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = <K extends keyof FormVals>(k: K, v: FormVals[K]) =>
    setVals((p) => ({ ...p, [k]: v }));

  // When category changes, auto-set direction based on category type
  function handleCategoryChange(id: string) {
    const cat = categories.find((c) => String(c.id) === id);
    set("category_id", id);
    if (cat?.category_type === "EXPENSE") set("direction", "debit");
    if (cat?.category_type === "INCOME")  set("direction", "credit");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const amt = parseFloat(vals.amount);
    if (!vals.bank_account_id || !vals.category_id || isNaN(amt) || amt <= 0) {
      setError("Fill all required fields with a positive amount.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await insertRow(
        vals.income_date,
        Number(vals.bank_account_id),
        Number(vals.category_id),
        amt,
        vals.direction,
        vals.description
      );
      setVals((p) => ({ ...p, amount: "", description: "" }));
      onSaved();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  const incomeCats  = categories.filter((c) => c.category_type === "INCOME");
  const expenseCats = categories.filter((c) => c.category_type === "EXPENSE");

  return (
    <form onSubmit={handleSubmit} className="bg-white border rounded-lg p-5 space-y-4 max-w-xl mb-6">
      <h2 className="font-semibold text-gray-800">Record Entry</h2>
      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Date <span className="text-red-500">*</span></label>
          <input type="date" value={vals.income_date} onChange={(e) => set("income_date", e.target.value)} required
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Bank Account <span className="text-red-500">*</span></label>
          <select value={vals.bank_account_id} onChange={(e) => set("bank_account_id", e.target.value)} required
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
          </select>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Category <span className="text-red-500">*</span></label>
          <select value={vals.category_id} onChange={(e) => handleCategoryChange(e.target.value)} required
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">— select —</option>
            <optgroup label="Income">
              {incomeCats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </optgroup>
            <optgroup label="Expense / Debit">
              {expenseCats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </optgroup>
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Direction <span className="text-red-500">*</span></label>
          <div className="flex gap-3 mt-1.5">
            <label className="flex items-center gap-1.5 cursor-pointer text-sm text-gray-700">
              <input type="radio" name="direction" value="credit" checked={vals.direction === "credit"}
                onChange={() => set("direction", "credit")} /> Credit (bank +)
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer text-sm text-gray-700">
              <input type="radio" name="direction" value="debit" checked={vals.direction === "debit"}
                onChange={() => set("direction", "debit")} /> Debit (bank −)
            </label>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Amount <span className="text-red-500">*</span></label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
            <input type="number" step="0.01" min="0.01" value={vals.amount}
              onChange={(e) => set("amount", e.target.value)} placeholder="0.00" required
              className="w-full border border-gray-300 rounded pl-6 pr-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Description / Memo</label>
          <input type="text" value={vals.description} onChange={(e) => set("description", e.target.value)}
            placeholder="e.g. Bank service charge, Hall rental"
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
      </div>

      <div>
        <button type="submit" disabled={saving}
          className="px-5 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50">
          {saving ? "Saving…" : "Save Entry"}
        </button>
      </div>
    </form>
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

export function OtherIncomeScreen() {
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [rows, setRows] = useState<IncomeRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(50);

  const { sorted, sortKey, sortDir, toggleSort } = useTableSort<IncomeRow>(rows, {
    date: (r) => r.income_date,
    account: (r) => r.account_name,
    category: (r) => r.category_name,
    description: (r) => r.description,
    amount: (r) => r.amount,
  });

  async function load() {
    try {
      const [accts, cats, r] = await Promise.all([
        listBankAccounts(),
        loadCategories(),
        loadRows(limit),
      ]);
      setAccounts(accts);
      setCategories(cats);
      setRows(r);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [limit]);

  async function handleDelete(row: IncomeRow) {
    if (!await appConfirm(`Delete this ${fmt(Math.abs(row.amount))} entry? Cannot be undone.`)) return;
    await deleteRow(row.id);
    await load();
  }

  if (loading) return <div className="p-8"><p className="text-sm text-gray-400">Loading…</p></div>;

  return (
    <PageLayout
      title="Other Income & Adjustments"
      subtitle="Bank interest, bank fees, hall rentals, reimbursements, and any non-lot income or debit."
      helpId="otherIncome"
    >
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {accounts.length > 0 && categories.length > 0 && (
        <EntryForm accounts={accounts} categories={categories} onSaved={() => void load()} />
      )}

      <div className="overflow-auto max-h-[calc(100vh-200px)] rounded-lg border border-gray-200">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10 bg-gray-50 border-b">
            <tr>
              <SortableTh label="Date" col="date" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} className="w-28" />
              <SortableTh label="Account" col="account" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortableTh label="Category" col="category" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortableTh label="Description" col="description" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortableTh label="Amount" col="amount" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} right className="w-28" />
              <th className="px-4 py-2.5 w-8" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-sm text-gray-400">No entries yet.</td></tr>
            )}
            {sorted.map((r) => (
              <tr key={r.id} className="hover:bg-gray-50">
                <td className="px-4 py-2 text-xs font-mono text-gray-600">{r.income_date}</td>
                <td className="px-4 py-2 text-xs text-gray-700">{r.account_name}</td>
                <td className="px-4 py-2">
                  <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${
                    r.category_type === "INCOME"
                      ? "bg-green-100 text-green-700"
                      : "bg-red-100 text-red-700"
                  }`}>
                    {r.category_name}
                  </span>
                </td>
                <td className="px-4 py-2 text-xs text-gray-600">{r.description ?? "—"}</td>
                <td className={`px-4 py-2 text-right font-mono text-xs font-semibold ${r.amount < 0 ? "text-red-600" : "text-green-700"}`}>
                  {r.amount < 0 ? `(${fmt(Math.abs(r.amount))})` : fmt(r.amount)}
                </td>
                <td className="px-4 py-2 text-center">
                  <button onClick={() => void handleDelete(r)} className="text-red-400 hover:text-red-600 text-xs" title="Delete">✕</button>
                </td>
              </tr>
            ))}
          </tbody>
          {rows.length > 0 && (
            <tfoot className="bg-gray-50 border-t">
              <tr>
                <td colSpan={4} className="px-4 py-2 text-xs text-gray-500">{rows.length} entries</td>
                <td className={`px-4 py-2 text-right font-mono text-xs font-semibold ${
                  rows.reduce((s, r) => s + r.amount, 0) < 0 ? "text-red-600" : "text-green-700"
                }`}>
                  {fmt(rows.reduce((s, r) => s + r.amount, 0))}
                </td>
                <td />
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      {rows.length >= limit && (
        <button onClick={() => setLimit((l) => l + 50)}
          className="mt-3 text-xs text-blue-600 hover:underline">
          Show more…
        </button>
      )}
    </PageLayout>
  );
}
