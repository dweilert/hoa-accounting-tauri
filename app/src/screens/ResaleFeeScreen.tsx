import { useEffect, useState } from "react";
import { getDb } from "../lib/db";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import type { BankAccount } from "../types/bankAccount";

// ── Types ─────────────────────────────────────────────────────────────────────

type Lot = { id: number; lot_number: string; street_address_1: string | null };
type RecentFee = {
  id: number;
  income_date: string;
  amount: number;
  lot_number: string;
  account_name: string | null;
  description: string | null;
};

const fmt = (n: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

// ── DB helpers ────────────────────────────────────────────────────────────────

async function loadLots(): Promise<Lot[]> {
  const db = await getDb();
  return db.select<Lot[]>(
    "SELECT id, lot_number, street_address_1 FROM lots WHERE active_flag=1 ORDER BY lot_number"
  );
}

async function loadResaleCategoryId(): Promise<number | null> {
  const db = await getDb();
  const rows = await db.select<{ id: number }[]>(
    "SELECT id FROM categories WHERE code='RESALE_FEE' OR name LIKE '%Resale%' ORDER BY id LIMIT 1"
  );
  return rows[0]?.id ?? null;
}

async function loadRecentFees(): Promise<RecentFee[]> {
  const db = await getDb();
  return db.select<RecentFee[]>(`
    SELECT ib.id, ib.income_date, ib.amount,
           l.lot_number,
           ba.account_name,
           ib.description
    FROM income_batches ib
    JOIN categories c ON ib.category_id = c.id AND c.code = 'RESALE_FEE'
    JOIN lots l ON ib.lot_id = l.id
    JOIN bank_accounts ba ON ib.bank_account_id = ba.id
    ORDER BY ib.income_date DESC
    LIMIT 20
  `);
}

async function postResaleFee(
  lotId: number,
  bankAccountId: number,
  categoryId: number,
  incomeDate: string,
  amount: number,
  description: string
): Promise<void> {
  const db = await getDb();
  await db.execute(
    `INSERT INTO income_batches (lot_id, bank_account_id, category_id, income_date, amount, description)
     VALUES (?,?,?,?,?,?)`,
    [lotId, bankAccountId, categoryId, incomeDate, amount, description]
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

export function ResaleFeeScreen() {
  const today = new Date().toISOString().slice(0, 10);
  const [lots, setLots] = useState<Lot[]>([]);
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [recentFees, setRecentFees] = useState<RecentFee[]>([]);

  const [lotId, setLotId] = useState<number>(0);
  const [accountId, setAccountId] = useState<number>(0);
  const [date, setDate] = useState(today);
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("Resale / Transfer Fee");

  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  function refreshRecent() {
    loadRecentFees().then(setRecentFees).catch(() => {});
  }

  useEffect(() => {
    Promise.all([loadLots(), listBankAccounts(true), loadResaleCategoryId()])
      .then(([ls, accts, catId]) => {
        setLots(ls);
        setAccounts(accts);
        setCategoryId(catId);
        if (ls[0]) setLotId(ls[0].id);
        if (accts[0]) setAccountId(accts[0].id);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
    refreshRecent();
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const amt = parseFloat(amount);
    if (!lotId || !accountId || isNaN(amt) || amt <= 0) {
      setError("Select a lot and account, and enter a positive fee amount.");
      return;
    }
    if (!categoryId) {
      setError("No 'Resale Fee' category found — add one under Chart of Accounts.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await postResaleFee(lotId, accountId, categoryId, date, amt, description);
      setSaved(true);
      setAmount("");
      setTimeout(() => setSaved(false), 3000);
      refreshRecent();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="p-8 text-gray-400 text-sm">Loading…</div>;

  return (
    <div className="p-6 max-w-2xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Resale / Transfer Fee</h1>
        <p className="text-sm text-gray-500 mt-1">
          Record a resale certificate or transfer fee collected at closing.
          Posts as non-dues income to the selected bank account.
        </p>
      </div>

      {error && <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>}

      <form onSubmit={(e) => void handleSubmit(e)} className="bg-white border rounded-lg p-5 space-y-4 mb-6">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Lot (property sold)</label>
            <select value={lotId} onChange={(e) => setLotId(Number(e.target.value))}
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              {lots.map((l) => (
                <option key={l.id} value={l.id}>
                  Lot {l.lot_number}{l.street_address_1 ? ` — ${l.street_address_1}` : ""}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Deposit to Account</label>
            <select value={accountId} onChange={(e) => setAccountId(Number(e.target.value))}
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Date Received</label>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Fee Amount</label>
            <input type="number" step="0.01" min="0.01" value={amount}
              onChange={(e) => setAmount(e.target.value)} placeholder="0.00" required
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>

          <div className="col-span-2">
            <label className="block text-xs font-medium text-gray-700 mb-1">Description</label>
            <input type="text" value={description} onChange={(e) => setDescription(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
        </div>

        <div className="flex items-center gap-4">
          <button type="submit" disabled={saving}
            className="px-5 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50">
            {saving ? "Posting…" : "Post Fee"}
          </button>
          {saved && <span className="text-sm text-green-600">✓ Fee posted</span>}
        </div>
      </form>

      {/* Recent fees */}
      {recentFees.length > 0 && (
        <>
          <h2 className="text-sm font-semibold text-gray-800 mb-2">Recent Resale Fees</h2>
          <div className="bg-white border rounded-lg overflow-hidden">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="text-left px-4 py-2 text-xs font-medium text-gray-600">Date</th>
                  <th className="text-left px-4 py-2 text-xs font-medium text-gray-600">Lot</th>
                  <th className="text-left px-4 py-2 text-xs font-medium text-gray-600">Account</th>
                  <th className="text-left px-4 py-2 text-xs font-medium text-gray-600">Description</th>
                  <th className="text-right px-4 py-2 text-xs font-medium text-gray-600">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {recentFees.map((f) => (
                  <tr key={f.id}>
                    <td className="px-4 py-2 text-xs text-gray-500">{f.income_date}</td>
                    <td className="px-4 py-2 text-xs text-gray-700">Lot {f.lot_number}</td>
                    <td className="px-4 py-2 text-xs text-gray-500">{f.account_name ?? "—"}</td>
                    <td className="px-4 py-2 text-xs text-gray-500 truncate max-w-xs">{f.description ?? "—"}</td>
                    <td className="px-4 py-2 text-right text-sm font-medium text-green-700">{fmt(f.amount)}</td>
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
