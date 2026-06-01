import { useEffect, useState, useCallback } from "react";
import { listOpenAssessments, type AssessmentRow } from "../repositories/assessmentRepo";
import { CHARGE_TYPE_LABELS, STATUS_COLORS, type AssessmentStatusValue } from "../types/assessment";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

type LotGroup = {
  lot_number: string;
  owner_name: string | null;
  assessments: AssessmentRow[];
  total: number;
};

export function ARScreen() {
  const [groups, setGroups] = useState<LotGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    try {
      const rows = await listOpenAssessments();
      const byLot = new Map<string, LotGroup>();
      for (const r of rows) {
        let g = byLot.get(r.lot_number);
        if (!g) {
          g = { lot_number: r.lot_number, owner_name: r.owner_name, assessments: [], total: 0 };
          byLot.set(r.lot_number, g);
        }
        g.assessments.push(r);
        g.total += r.amount;
      }
      setGroups(Array.from(byLot.values()).sort((a, b) => a.lot_number.localeCompare(b.lot_number)));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  function toggle(lotNumber: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(lotNumber)) next.delete(lotNumber);
      else next.add(lotNumber);
      return next;
    });
  }

  const grandTotal = groups.reduce((s, g) => s + g.total, 0);

  return (
    <div className="p-8 max-w-4xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Accounts Receivable</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          {groups.length} lots with open balances · {fmt(grandTotal)} total outstanding
        </p>
      </div>

      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {!loading && !error && groups.length === 0 && (
        <div className="border rounded-lg px-6 py-10 text-center text-gray-400 bg-white">
          No outstanding balances. All assessments are paid.
        </div>
      )}

      {!loading && !error && groups.length > 0 && (
        <div className="space-y-2">
          {groups.map((g) => (
            <div key={g.lot_number} className="border rounded-lg bg-white overflow-hidden">
              {/* Lot header row */}
              <button
                onClick={() => toggle(g.lot_number)}
                className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-50 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <span className="text-sm font-semibold text-gray-900">Lot {g.lot_number}</span>
                  {g.owner_name && (
                    <span className="text-sm text-gray-500">{g.owner_name}</span>
                  )}
                  <span className="text-xs text-gray-400">{g.assessments.length} item{g.assessments.length !== 1 ? "s" : ""}</span>
                </div>
                <div className="flex items-center gap-4">
                  <span className="font-mono font-semibold text-gray-900">{fmt(g.total)}</span>
                  <span className="text-gray-400 text-xs">{expanded.has(g.lot_number) ? "▲" : "▼"}</span>
                </div>
              </button>

              {/* Detail rows */}
              {expanded.has(g.lot_number) && (
                <table className="w-full text-sm border-t">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-6 py-2 text-left text-xs font-medium text-gray-500">Date</th>
                      <th className="px-6 py-2 text-left text-xs font-medium text-gray-500">Type</th>
                      <th className="px-6 py-2 text-left text-xs font-medium text-gray-500">Description</th>
                      <th className="px-6 py-2 text-left text-xs font-medium text-gray-500">Due</th>
                      <th className="px-6 py-2 text-right text-xs font-medium text-gray-500">Amount</th>
                      <th className="px-6 py-2 text-left text-xs font-medium text-gray-500">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {g.assessments.map((a) => (
                      <tr key={a.id}>
                        <td className="px-6 py-2 text-gray-600">{a.assessment_date}</td>
                        <td className="px-6 py-2 text-gray-600 text-xs">{CHARGE_TYPE_LABELS[a.charge_type]}</td>
                        <td className="px-6 py-2 text-gray-500 text-xs">{a.description ?? "—"}</td>
                        <td className="px-6 py-2 text-gray-500 text-xs">{a.due_date ?? "—"}</td>
                        <td className="px-6 py-2 text-right font-mono text-gray-700">{fmt(a.amount)}</td>
                        <td className="px-6 py-2">
                          <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[a.status as AssessmentStatusValue]}`}>
                            {a.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))}

          {/* Grand total */}
          <div className="flex justify-end px-4 py-3 border-t mt-2">
            <div className="text-sm font-semibold text-gray-900">
              Total Outstanding: <span className="font-mono ml-2">{fmt(grandTotal)}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
