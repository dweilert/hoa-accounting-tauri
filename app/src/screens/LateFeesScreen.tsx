import { useEffect, useState } from "react";
import { getDb } from "../lib/db";

// ── Types ─────────────────────────────────────────────────────────────────────

type DelinquentLot = {
  lot_id: number;
  lot_number: string;
  street_address_1: string | null;
  owner_name: string | null;
  days_overdue: number;
  open_balance: number;
  oldest_due_date: string | null;
  selected?: boolean;
};


// ── Helpers ───────────────────────────────────────────────────────────────────

const fmt = (n: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

async function loadDelinquentLots(asOfDate: string, minDaysOverdue: number): Promise<DelinquentLot[]> {
  const db = await getDb();
  const rows = await db.select<DelinquentLot[]>(
    `SELECT
       a.lot_id,
       l.lot_number,
       l.street_address_1,
       o.display_name AS owner_name,
       MIN(julianday(?) - julianday(a.due_date)) AS days_overdue,
       SUM(a.amount) - COALESCE(
         (SELECT SUM(p.amount)
          FROM payments p
          WHERE p.lot_id = a.lot_id
            AND p.payment_date <= ?
            AND p.deposit_batch_id IS NOT NULL), 0
       ) AS open_balance,
       MIN(a.due_date) AS oldest_due_date
     FROM assessments a
     JOIN lots l ON a.lot_id = l.id
     LEFT JOIN lot_ownership lo ON lo.lot_id = l.id AND lo.end_date IS NULL AND lo.is_primary_contact = 1
     LEFT JOIN owners o ON lo.owner_id = o.id
     WHERE a.status IN ('OPEN','PARTIAL')
       AND a.due_date IS NOT NULL
       AND a.due_date < ?
       AND a.charge_type NOT IN ('LATE_FEE','LEGAL_FEE')
     GROUP BY a.lot_id, l.lot_number, l.street_address_1, o.display_name
     HAVING days_overdue >= ?
     ORDER BY days_overdue DESC`,
    [asOfDate, asOfDate, asOfDate, minDaysOverdue]
  );
  return rows;
}

async function loadLateFeeCategoryId(): Promise<number | null> {
  const db = await getDb();
  const rows = await db.select<{ id: number }[]>(
    "SELECT id FROM categories WHERE code = 'LATE_FEE' OR name LIKE '%Late Fee%' ORDER BY id LIMIT 1"
  );
  return rows[0]?.id ?? null;
}

async function postLateFees(
  lots: DelinquentLot[],
  feeAmount: number,
  assessmentDate: string,
  dueDate: string,
  categoryId: number | null,
  description: string
): Promise<number> {
  const db = await getDb();
  let posted = 0;
  for (const lot of lots) {
    await db.execute(
      `INSERT INTO assessments (lot_id, charge_type, amount, assessment_date, due_date, description, status, category_id)
       VALUES (?, 'LATE_FEE', ?, ?, ?, ?, 'OPEN', ?)`,
      [lot.lot_id, feeAmount, assessmentDate, dueDate, description, categoryId]
    );
    posted++;
  }
  return posted;
}

// ── Main screen ───────────────────────────────────────────────────────────────

export function LateFeesScreen() {
  const today = new Date().toISOString().slice(0, 10);

  const [asOfDate, setAsOfDate] = useState(today);
  const [minDays, setMinDays] = useState(30);
  const [feeAmount, setFeeAmount] = useState("25.00");
  const [assessmentDate, setAssessmentDate] = useState(today);
  const [dueDate, setDueDate] = useState(today);
  const [description, setDescription] = useState("Late Fee");
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [lots, setLots] = useState<DelinquentLot[]>([]);
  const [loading, setLoading] = useState(false);
  const [posting, setPosting] = useState(false);
  const [posted, setPosted] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  useEffect(() => {
    loadLateFeeCategoryId().then(setCategoryId).catch(() => {});
  }, []);

  async function handleSearch() {
    setLoading(true);
    setError(null);
    setPosted(null);
    try {
      const rows = await loadDelinquentLots(asOfDate, minDays);
      setLots(rows.map((r) => ({ ...r, selected: true })));
      setSearched(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  function toggleAll(checked: boolean) {
    setLots((prev) => prev.map((l) => ({ ...l, selected: checked })));
  }

  function toggleLot(lotId: number) {
    setLots((prev) => prev.map((l) => l.lot_id === lotId ? { ...l, selected: !l.selected } : l));
  }

  async function handlePost() {
    const selected = lots.filter((l) => l.selected);
    if (selected.length === 0) { setError("No lots selected."); return; }
    const amt = parseFloat(feeAmount);
    if (isNaN(amt) || amt <= 0) { setError("Enter a valid fee amount."); return; }
    if (!confirm(`Post a $${amt.toFixed(2)} late fee to ${selected.length} lot${selected.length > 1 ? "s" : ""}?`)) return;

    setPosting(true);
    setError(null);
    try {
      const count = await postLateFees(selected, amt, assessmentDate, dueDate, categoryId, description);
      setPosted(count);
      setLots([]);
      setSearched(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setPosting(false);
    }
  }

  const selected = lots.filter((l) => l.selected);
  const feeAmt = parseFloat(feeAmount) || 0;
  const totalFees = selected.length * feeAmt;

  return (
    <div className="p-6 max-w-4xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Late Fees</h1>
        <p className="text-sm text-gray-500 mt-1">
          Find overdue lots and post late fee assessments in bulk.
        </p>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>
      )}

      {posted !== null && (
        <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded text-green-700 text-sm">
          ✓ Posted late fees to {posted} lot{posted !== 1 ? "s" : ""}.
        </div>
      )}

      {/* Parameters */}
      <div className="bg-white border rounded-lg p-5 mb-5 space-y-4">
        <h2 className="font-semibold text-gray-800 text-sm">Search Parameters</h2>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">As-of Date</label>
            <input type="date" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Minimum Days Overdue</label>
            <input type="number" min="1" value={minDays} onChange={(e) => setMinDays(Number(e.target.value))}
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
        </div>
        <button
          onClick={() => void handleSearch()}
          disabled={loading}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "Searching…" : "Find Delinquent Lots"}
        </button>
      </div>

      {/* Results */}
      {searched && lots.length === 0 && (
        <p className="text-gray-400 text-sm">No lots are {minDays}+ days overdue as of {asOfDate}.</p>
      )}

      {lots.length > 0 && (
        <>
          <div className="bg-white border rounded-lg overflow-hidden mb-4 shadow-sm">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-3 py-2.5">
                    <input
                      type="checkbox"
                      checked={lots.every((l) => l.selected)}
                      onChange={(e) => toggleAll(e.target.checked)}
                    />
                  </th>
                  <th className="text-left px-3 py-2.5 font-medium text-gray-600">Lot</th>
                  <th className="text-left px-3 py-2.5 font-medium text-gray-600">Owner</th>
                  <th className="text-left px-3 py-2.5 font-medium text-gray-600">Oldest Due</th>
                  <th className="text-right px-3 py-2.5 font-medium text-gray-600">Days Overdue</th>
                  <th className="text-right px-3 py-2.5 font-medium text-gray-600">Open Balance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {lots.map((lot) => (
                  <tr key={lot.lot_id} className={lot.selected ? "" : "opacity-50"}>
                    <td className="px-3 py-2 text-center">
                      <input type="checkbox" checked={lot.selected ?? false} onChange={() => toggleLot(lot.lot_id)} />
                    </td>
                    <td className="px-3 py-2">
                      <span className="font-medium text-gray-900">Lot {lot.lot_number}</span>
                      {lot.street_address_1 && (
                        <span className="text-xs text-gray-400 ml-1">{lot.street_address_1}</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-gray-600">{lot.owner_name ?? "—"}</td>
                    <td className="px-3 py-2 text-gray-500 text-xs">{lot.oldest_due_date ?? "—"}</td>
                    <td className="px-3 py-2 text-right">
                      <span className={`font-medium ${lot.days_overdue >= 60 ? "text-red-600" : "text-amber-600"}`}>
                        {Math.round(lot.days_overdue)}d
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-red-700">{fmt(lot.open_balance)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Fee posting parameters */}
          <div className="bg-white border rounded-lg p-5 space-y-4">
            <h2 className="font-semibold text-gray-800 text-sm">Post Late Fees</h2>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Fee Amount per Lot</label>
                <input type="number" step="0.01" min="0.01" value={feeAmount}
                  onChange={(e) => setFeeAmount(e.target.value)}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Assessment Date</label>
                <input type="date" value={assessmentDate} onChange={(e) => setAssessmentDate(e.target.value)}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Due Date</label>
                <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Description</label>
                <input type="text" value={description} onChange={(e) => setDescription(e.target.value)}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
            </div>

            <div className="flex items-center justify-between">
              <div className="text-sm text-gray-600">
                <span className="font-medium">{selected.length}</span> lots selected ×{" "}
                <span className="font-medium">{fmt(feeAmt)}</span> ={" "}
                <span className="font-semibold text-gray-900">{fmt(totalFees)}</span>
              </div>
              <button
                onClick={() => void handlePost()}
                disabled={posting || selected.length === 0}
                className="px-5 py-2 bg-red-600 text-white text-sm rounded hover:bg-red-700 disabled:opacity-50"
              >
                {posting ? "Posting…" : `Post ${selected.length} Late Fee${selected.length !== 1 ? "s" : ""}`}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
