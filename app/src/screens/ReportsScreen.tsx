import { useEffect, useState } from "react";
import { getDb } from "../lib/db";

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

// ── Report types ──────────────────────────────────────────────────────────────

type ReportType = "ar_aging" | "expense_summary" | "income_summary";

const REPORTS: { key: ReportType; title: string; description: string }[] = [
  { key: "ar_aging", title: "AR Aging", description: "Outstanding balances by lot, bucketed by age" },
  { key: "expense_summary", title: "Expense Summary", description: "Total expenses by category for the year" },
  { key: "income_summary", title: "Income Summary", description: "Total income by category for the year" },
];

const CURRENT_YEAR = new Date().getFullYear();

export function ReportsScreen() {
  const [selected, setSelected] = useState<ReportType>("ar_aging");
  const [year, setYear] = useState(CURRENT_YEAR);
  const [arAging, setArAging] = useState<AgingBucket[]>([]);
  const [expenses, setExpenses] = useState<ExpenseRow[]>([]);
  const [income, setIncome] = useState<IncomeRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runReport() {
    setLoading(true);
    setError(null);
    try {
      if (selected === "ar_aging") setArAging(await loadARaging());
      if (selected === "expense_summary") setExpenses(await loadExpenseSummary(year));
      if (selected === "income_summary") setIncome(await loadIncomeSummary(year));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void runReport(); }, [selected, year]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="p-8 max-w-5xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Reports</h1>
        <p className="text-sm text-gray-500 mt-0.5">Financial summaries and aging reports.</p>
      </div>

      {/* Report selector */}
      <div className="flex gap-2 mb-6 flex-wrap">
        {REPORTS.map((r) => (
          <button
            key={r.key}
            onClick={() => setSelected(r.key)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              selected === r.key
                ? "bg-blue-600 text-white"
                : "bg-white border border-gray-300 text-gray-600 hover:bg-gray-50"
            }`}
          >
            {r.title}
          </button>
        ))}
        {(selected === "expense_summary" || selected === "income_summary") && (
          <select
            value={year}
            onChange={(e) => setYear(Number(e.target.value))}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ml-2"
          >
            {[CURRENT_YEAR, CURRENT_YEAR - 1, CURRENT_YEAR - 2].map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        )}
      </div>

      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {/* AR Aging */}
      {!loading && selected === "ar_aging" && (
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
              {arAging.length === 0 && (
                <tr><td colSpan={7} className="px-4 py-6 text-center text-gray-400 text-sm">No outstanding balances.</td></tr>
              )}
              {arAging.map((r) => (
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
              {arAging.length > 0 && (
                <tr className="bg-gray-50 font-semibold">
                  <td colSpan={2} className="px-4 py-2 text-gray-600 text-xs">Total</td>
                  <td className="px-4 py-2 text-right font-mono text-xs">{fmt(arAging.reduce((s, r) => s + r.current, 0))}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs">{fmt(arAging.reduce((s, r) => s + r.d30, 0))}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs">{fmt(arAging.reduce((s, r) => s + r.d60, 0))}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs">{fmt(arAging.reduce((s, r) => s + r.d90plus, 0))}</td>
                  <td className="px-4 py-2 text-right font-mono text-gray-900">{fmt(arAging.reduce((s, r) => s + r.total, 0))}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Expense Summary */}
      {!loading && selected === "expense_summary" && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Category</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Total {year}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {expenses.length === 0 && (
                <tr><td colSpan={2} className="px-4 py-6 text-center text-gray-400 text-sm">No expenses for {year}.</td></tr>
              )}
              {expenses.map((r) => (
                <tr key={r.category_name}>
                  <td className="px-4 py-2 text-gray-700">{r.category_name}</td>
                  <td className="px-4 py-2 text-right font-mono text-red-600">{fmt(r.total)}</td>
                </tr>
              ))}
              {expenses.length > 0 && (
                <tr className="bg-gray-50 font-semibold">
                  <td className="px-4 py-2 text-gray-600">Total</td>
                  <td className="px-4 py-2 text-right font-mono text-red-700">{fmt(expenses.reduce((s, r) => s + r.total, 0))}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Income Summary */}
      {!loading && selected === "income_summary" && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Category</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Total {year}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {income.length === 0 && (
                <tr><td colSpan={2} className="px-4 py-6 text-center text-gray-400 text-sm">No income for {year}.</td></tr>
              )}
              {income.map((r) => (
                <tr key={r.category_name}>
                  <td className="px-4 py-2 text-gray-700">{r.category_name}</td>
                  <td className="px-4 py-2 text-right font-mono text-green-700">{fmt(r.total)}</td>
                </tr>
              ))}
              {income.length > 0 && (
                <tr className="bg-gray-50 font-semibold">
                  <td className="px-4 py-2 text-gray-600">Total</td>
                  <td className="px-4 py-2 text-right font-mono text-green-800">{fmt(income.reduce((s, r) => s + r.total, 0))}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
