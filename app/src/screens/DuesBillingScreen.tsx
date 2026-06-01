import { useEffect, useState, useCallback } from "react";
import { getDb } from "../lib/db";
import { listCategories } from "../repositories/categoryRepo";
import type { Category } from "../types/category";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

type LotBillingRow = {
  lot_id: number;
  lot_number: string;
  owner_id: number | null;
  owner_name: string | null;
  include: boolean;
};

async function loadActiveLots(): Promise<LotBillingRow[]> {
  const db = await getDb();
  const rows = await db.select<LotBillingRow[]>(`
    SELECT l.id AS lot_id, l.lot_number,
           o.id AS owner_id, o.display_name AS owner_name
    FROM lots l
    LEFT JOIN lot_ownership lo ON lo.lot_id = l.id AND lo.end_date IS NULL
    LEFT JOIN owners o ON o.id = lo.owner_id
    WHERE l.active_flag = 1
    ORDER BY l.lot_number
  `);
  return rows.map((r) => ({ ...r, include: true }));
}

async function postDuesBilling(opts: {
  lots: LotBillingRow[];
  amount: number;
  assessmentDate: string;
  dueDate: string;
  description: string;
  categoryId: number | null;
}): Promise<number> {
  const db = await getDb();
  let count = 0;
  for (const lot of opts.lots) {
    if (!lot.include) continue;
    await db.execute(
      `INSERT INTO assessments
         (lot_id, owner_id, charge_type, amount, assessment_date, due_date, description, category_id)
       VALUES (?, ?, 'DUES', ?, ?, ?, ?, ?)`,
      [
        lot.lot_id,
        lot.owner_id ?? null,
        opts.amount,
        opts.assessmentDate,
        opts.dueDate || null,
        opts.description || null,
        opts.categoryId ?? null,
      ]
    );
    count++;
  }
  return count;
}

export function DuesBillingScreen() {
  const today = new Date().toISOString().slice(0, 10);
  const [lots, setLots] = useState<LotBillingRow[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [amount, setAmount] = useState("");
  const [assessmentDate, setAssessmentDate] = useState(today);
  const [dueDate, setDueDate] = useState("");
  const [description, setDescription] = useState("");
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [l, c] = await Promise.all([loadActiveLots(), listCategories()]);
      setLots(l);
      const duesCat = c.find((cat) => cat.code === "DUES");
      setCategoryId(duesCat?.id ?? null);
      setCategories(c.filter((cat) => cat.category_type === "INCOME"));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const toggleLot = (lotId: number) =>
    setLots((prev) => prev.map((l) => l.lot_id === lotId ? { ...l, include: !l.include } : l));

  const toggleAll = (checked: boolean) =>
    setLots((prev) => prev.map((l) => ({ ...l, include: checked })));

  const includedCount = lots.filter((l) => l.include).length;
  const totalAmount = includedCount * (Number(amount) || 0);

  async function handlePost() {
    const amt = Number(amount);
    if (!amt || amt <= 0) { setError("Enter a valid amount per lot."); return; }
    if (!assessmentDate) { setError("Assessment date is required."); return; }
    if (includedCount === 0) { setError("Select at least one lot."); return; }
    if (!confirm(`Post dues of ${fmt(amt)} to ${includedCount} lots (total ${fmt(totalAmount)})?`)) return;

    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const count = await postDuesBilling({
        lots,
        amount: amt,
        assessmentDate,
        dueDate,
        description,
        categoryId,
      });
      setSuccess(`Successfully posted dues to ${count} lots.`);
      // Reset for next run
      setAmount("");
      setDueDate("");
      setDescription("");
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="p-8 max-w-4xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Dues Billing</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Bulk-post dues charges to all active lots in one operation.
        </p>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">{error}</div>
      )}
      {success && (
        <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700">{success}</div>
      )}

      {/* Billing parameters */}
      <div className="bg-white border border-gray-200 rounded-xl p-6 mb-6">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Billing Parameters</h2>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">
              Amount Per Lot <span className="text-red-500">*</span>
            </label>
            <input
              type="number"
              step="0.01"
              min="0.01"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="0.00"
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Category</label>
            <select
              value={categoryId ?? ""}
              onChange={(e) => setCategoryId(e.target.value ? Number(e.target.value) : null)}
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">— None —</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">
              Assessment Date <span className="text-red-500">*</span>
            </label>
            <input
              type="date"
              value={assessmentDate}
              onChange={(e) => setAssessmentDate(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Due Date</label>
            <input
              type="date"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div className="col-span-2">
            <label className="block text-xs font-medium text-gray-700 mb-1">Description</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="e.g. 2026 Annual HOA Dues"
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        <div className="mt-4 p-3 bg-blue-50 rounded-lg flex items-center justify-between">
          <div className="text-sm text-blue-700">
            <span className="font-semibold">{includedCount}</span> lots selected ·{" "}
            <span className="font-semibold">{fmt(totalAmount)}</span> total
          </div>
          <button
            onClick={() => void handlePost()}
            disabled={saving || loading}
            className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? "Posting…" : "Post Dues Charges"}
          </button>
        </div>
      </div>

      {/* Lot selector */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b bg-gray-50 flex items-center justify-between">
          <span className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
            Active Lots ({lots.length})
          </span>
          <div className="flex gap-3">
            <button
              onClick={() => toggleAll(true)}
              className="text-xs text-blue-600 hover:underline"
            >
              Select All
            </button>
            <button
              onClick={() => toggleAll(false)}
              className="text-xs text-gray-500 hover:underline"
            >
              Deselect All
            </button>
          </div>
        </div>
        {loading && <p className="px-4 py-6 text-sm text-gray-400">Loading lots…</p>}
        {!loading && (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left w-10">
                  <input
                    type="checkbox"
                    checked={lots.every((l) => l.include)}
                    onChange={(e) => toggleAll(e.target.checked)}
                    className="rounded"
                  />
                </th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Lot</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Owner</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {lots.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-gray-400 text-sm">
                    No active lots found.
                  </td>
                </tr>
              )}
              {lots.map((l) => (
                <tr key={l.lot_id} className={l.include ? "" : "opacity-40"}>
                  <td className="px-4 py-2">
                    <input
                      type="checkbox"
                      checked={l.include}
                      onChange={() => toggleLot(l.lot_id)}
                      className="rounded"
                    />
                  </td>
                  <td className="px-4 py-2 font-medium text-gray-900">Lot {l.lot_number}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{l.owner_name ?? "— No owner —"}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-gray-700">
                    {l.include && amount ? fmt(Number(amount)) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
