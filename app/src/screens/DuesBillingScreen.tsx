import { useEffect, useState, useCallback } from "react";
import { getDb } from "../lib/db";
import { PageLayout } from "../components/PageLayout";
import { insertAssessment } from "../repositories/assessmentRepo";
import { appConfirm } from "../components/AppDialogs";
import { useTableSort } from "../lib/useTableSort";
import { SortableTh } from "../components/SortableTh";
import { CHARGE_TYPE_LABELS } from "../types/assessment";
import type { ChargeTypeValue } from "../types/assessment";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

type LotBillingRow = {
  lot_id: number;
  lot_number: string;
  owner_names: string | null;
  include: boolean;
};

async function loadActiveLots(): Promise<LotBillingRow[]> {
  const db = await getDb();
  const rows = await db.select<LotBillingRow[]>(`
    SELECT l.id AS lot_id, l.lot_number,
           GROUP_CONCAT(o.display_name, ' / ') AS owner_names
    FROM lots l
    LEFT JOIN lot_ownership lo ON lo.lot_id = l.id AND lo.end_date IS NULL
    LEFT JOIN owners o ON o.id = lo.owner_id
    WHERE l.active_flag = 1
    GROUP BY l.id, l.lot_number
    ORDER BY l.lot_number
  `);
  return rows.map((r) => ({ ...r, include: true }));
}

async function postBilling(opts: {
  lots: LotBillingRow[];
  chargeType: ChargeTypeValue;
  amount: number;
  assessmentDate: string;
  dueDate: string;
  description: string;
}): Promise<number> {
  let count = 0;
  for (const lot of opts.lots) {
    if (!lot.include) continue;
    await insertAssessment({
      lot_id: lot.lot_id,
      charge_type: opts.chargeType,
      amount: opts.amount,
      assessment_date: opts.assessmentDate,
      due_date: opts.dueDate || undefined,
      description: opts.description || undefined,
    });
    count++;
  }
  return count;
}

export function DuesBillingScreen() {
  const today = new Date().toISOString().slice(0, 10);
  const [lots, setLots] = useState<LotBillingRow[]>([]);
  const [chargeType, setChargeType] = useState<ChargeTypeValue>("DUES");
  const [amount, setAmount] = useState("");
  const [assessmentDate, setAssessmentDate] = useState(today);
  const [dueDate, setDueDate] = useState("");
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const { sorted, sortKey, sortDir, toggleSort } = useTableSort(lots, {
    lot: (l) => l.lot_number,
    owner: (l) => l.owner_names,
    amount: (l) => (l.include && amount ? Number(amount) : null),
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const l = await loadActiveLots();
      setLots(l);
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
    const label = CHARGE_TYPE_LABELS[chargeType];
    if (!await appConfirm(`Post ${label} of ${fmt(amt)} to ${includedCount} lot${includedCount !== 1 ? "s" : ""} (total ${fmt(totalAmount)})?`)) return;

    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const count = await postBilling({
        lots,
        chargeType,
        amount: amt,
        assessmentDate,
        dueDate,
        description,
      });
      setSuccess(`Posted ${label} to ${count} lot${count !== 1 ? "s" : ""}.`);
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
    <PageLayout
      title="Bill Lots"
      subtitle="Post charges to one or more lots."
      helpId="duesBilling"
    >
    <div>
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
            <label className="block text-xs font-medium text-gray-700 mb-1">Charge Type <span className="text-red-500">*</span></label>
            <select
              value={chargeType}
              onChange={(e) => setChargeType(e.target.value as ChargeTypeValue)}
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {(Object.entries(CHARGE_TYPE_LABELS) as [ChargeTypeValue, string][]).map(([val, label]) => (
                <option key={val} value={val}>{label}</option>
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
            {saving ? "Posting…" : "Post Charges"}
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
            <thead className="sticky top-0 z-10 bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left w-10">
                  <input
                    type="checkbox"
                    checked={lots.every((l) => l.include)}
                    onChange={(e) => toggleAll(e.target.checked)}
                    className="rounded"
                  />
                </th>
                <SortableTh label="Lot" col="lot" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} className="!px-4" />
                <SortableTh label="Owner" col="owner" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} className="!px-4" />
                <SortableTh label="Amount" col="amount" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} right className="!px-4" />
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
              {sorted.map((l) => (
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
                  <td className="px-4 py-2 text-gray-500 text-xs">{l.owner_names ?? "— No owner —"}</td>
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
    </PageLayout>
  );
}
