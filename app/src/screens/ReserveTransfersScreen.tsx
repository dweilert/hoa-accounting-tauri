import { useEffect, useState } from "react";
import { getDb } from "../lib/db";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import { listCategories } from "../repositories/categoryRepo";
import type { BankAccount } from "../types/bankAccount";
import type { Category } from "../types/category";

// ── Types ─────────────────────────────────────────────────────────────────────

type Transfer = {
  id: number;
  transfer_date: string;
  from_account: string;
  to_account: string;
  amount: number;
  category_name: string | null;
  description: string | null;
};

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmt = (n: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

async function loadTransfers(): Promise<Transfer[]> {
  const db = await getDb();
  return db.select<Transfer[]>(`
    SELECT rt.id,
           rt.transfer_date,
           fa.account_name AS from_account,
           ta.account_name AS to_account,
           rt.amount,
           c.name          AS category_name,
           rt.description
    FROM reserve_transfers rt
    JOIN bank_accounts fa ON rt.from_bank_account_id = fa.id
    JOIN bank_accounts ta ON rt.to_bank_account_id   = ta.id
    LEFT JOIN categories c ON rt.category_id = c.id
    ORDER BY rt.transfer_date DESC, rt.id DESC
  `);
}

async function insertTransfer(
  transfer_date: string,
  from_bank_account_id: number,
  to_bank_account_id: number,
  amount: number,
  category_id: number | null,
  description: string
): Promise<void> {
  const db = await getDb();
  await db.execute(
    `INSERT INTO reserve_transfers
       (transfer_date, from_bank_account_id, to_bank_account_id, amount, category_id, description)
     VALUES (?, ?, ?, ?, ?, ?)`,
    [transfer_date, from_bank_account_id, to_bank_account_id, amount, category_id, description || null]
  );
}

async function deleteTransfer(id: number): Promise<void> {
  const db = await getDb();
  await db.execute("DELETE FROM reserve_transfers WHERE id=?", [id]);
}

// ── New Transfer form ─────────────────────────────────────────────────────────

function NewTransferForm({
  accounts,
  categories,
  onSaved,
}: {
  accounts: BankAccount[];
  categories: Category[];
  onSaved: () => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate] = useState(today);
  const [fromId, setFromId] = useState<number>(accounts[0]?.id ?? 0);
  const [toId, setToId] = useState<number>(accounts[1]?.id ?? 0);
  const [amount, setAmount] = useState("");
  const [catId, setCatId] = useState<number | null>(null);
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reserveCategories = categories.filter(
    (c) => c.fund_code === "RESERVE" || c.name?.toLowerCase().includes("reserve")
  );

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const amt = parseFloat(amount);
    if (!date || isNaN(amt) || amt <= 0) { setError("Date and a positive amount are required."); return; }
    if (fromId === toId) { setError("From and To accounts must be different."); return; }
    setSaving(true);
    setError(null);
    try {
      await insertTransfer(date, fromId, toId, amt, catId, description);
      setAmount("");
      setDescription("");
      onSaved();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="bg-white border rounded-lg p-5 space-y-4">
      <h2 className="font-semibold text-gray-800 text-sm">New Transfer</h2>

      {error && <p className="text-xs text-red-600">{error}</p>}

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Date</label>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            required
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Amount</label>
          <input
            type="number"
            step="0.01"
            min="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="0.00"
            required
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">From Account</label>
          <select
            value={fromId}
            onChange={(e) => setFromId(Number(e.target.value))}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
          </select>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">To Account</label>
          <select
            value={toId}
            onChange={(e) => setToId(Number(e.target.value))}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
          </select>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Category (optional)</label>
          <select
            value={catId ?? ""}
            onChange={(e) => setCatId(e.target.value ? Number(e.target.value) : null)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">— None —</option>
            {reserveCategories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            {reserveCategories.length === 0 &&
              categories.filter((c) => c.category_type === "INCOME" || c.category_type === "EXPENSE")
                .map((c) => <option key={c.id} value={c.id}>{c.name}</option>)
            }
          </select>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Description (optional)</label>
          <input
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Monthly reserve contribution"
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>

      <button
        type="submit"
        disabled={saving}
        className="px-5 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
      >
        {saving ? "Posting…" : "Post Transfer"}
      </button>
    </form>
  );
}

// ── Main screen ───────────────────────────────────────────────────────────────

export function ReserveTransfersScreen() {
  const [transfers, setTransfers] = useState<Transfer[]>([]);
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);

  function refresh() {
    loadTransfers()
      .then(setTransfers)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    Promise.all([
      listBankAccounts(true),
      listCategories(),
    ])
      .then(([accts, cats]) => {
        setAccounts(accts);
        setCategories(cats);
      })
      .catch((e) => setError(String(e)));
    refresh();
  }, []);

  async function handleDelete(id: number) {
    if (!confirm("Delete this transfer? This cannot be undone.")) return;
    setDeleting(id);
    try {
      await deleteTransfer(id);
      setTransfers((prev) => prev.filter((t) => t.id !== id));
    } catch (e) {
      alert(String(e));
    } finally {
      setDeleting(null);
    }
  }

  const totalTransferred = transfers.reduce((sum, t) => sum + t.amount, 0);

  return (
    <div className="p-6 max-w-4xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Reserve Transfers</h1>
        <p className="text-sm text-gray-500 mt-1">
          Record fund transfers between operating and reserve bank accounts.
        </p>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>
      )}

      {accounts.length >= 2 && categories.length > 0 && (
        <div className="mb-6">
          <NewTransferForm accounts={accounts} categories={categories} onSaved={refresh} />
        </div>
      )}

      {accounts.length < 2 && (
        <div className="mb-6 p-4 bg-amber-50 border border-amber-200 rounded text-amber-800 text-sm">
          At least two bank accounts are required to record a transfer.
          Add another bank account under Bank → Accounts.
        </div>
      )}

      {/* Transfer history */}
      {loading ? (
        <p className="text-gray-400 text-sm">Loading…</p>
      ) : transfers.length === 0 ? (
        <p className="text-gray-400 text-sm">No transfers recorded yet.</p>
      ) : (
        <>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-800">Transfer History</h2>
            <span className="text-xs text-gray-500">Total transferred: <strong>{fmt(totalTransferred)}</strong></span>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-600">Date</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-600">From</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-600">To</th>
                  <th className="text-right px-4 py-2.5 font-medium text-gray-600">Amount</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-600">Category</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-600">Description</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {transfers.map((t) => (
                  <tr key={t.id} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-gray-600 whitespace-nowrap">{t.transfer_date}</td>
                    <td className="px-4 py-2 text-gray-700">{t.from_account}</td>
                    <td className="px-4 py-2 text-gray-700">{t.to_account}</td>
                    <td className="px-4 py-2 text-right font-mono font-medium text-blue-700">{fmt(t.amount)}</td>
                    <td className="px-4 py-2 text-gray-500 text-xs">{t.category_name ?? "—"}</td>
                    <td className="px-4 py-2 text-gray-500 text-xs truncate max-w-xs">{t.description ?? "—"}</td>
                    <td className="px-4 py-2 text-right">
                      <button
                        onClick={() => void handleDelete(t.id)}
                        disabled={deleting === t.id}
                        className="text-xs text-red-500 hover:underline disabled:opacity-40"
                      >
                        {deleting === t.id ? "…" : "Delete"}
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
  );
}
