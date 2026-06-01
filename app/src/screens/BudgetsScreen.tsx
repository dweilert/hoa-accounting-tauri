import { useEffect, useState, useCallback, useRef } from "react";
import {
  listBudgets,
  getBudget,
  createBudget,
  updateBudgetStatus,
  getBudgetLines,
  upsertBudgetLine,
  getBudgetTotals,
} from "../repositories/budgetRepo";
import { listCategories } from "../repositories/categoryRepo";
import { MONTHS, STATUS_COLORS, type Budget, type BudgetStatusValue } from "../types/budget";
import type { Category } from "../types/category";

function fmt(n: number) {
  return n === 0
    ? ""
    : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(n);
}

const CURRENT_YEAR = new Date().getFullYear();

// ── Budget List ───────────────────────────────────────────────────────────────

type ListViewProps = {
  budgets: Budget[];
  onSelect: (id: number) => void;
  onCreate: (year: number, fund: string) => void;
};

function BudgetList({ budgets, onSelect, onCreate }: ListViewProps) {
  const [newYear, setNewYear] = useState(CURRENT_YEAR);
  const [newFund, setNewFund] = useState("OPERATING");
  const [creating, setCreating] = useState(false);

  async function handleCreate() {
    setCreating(true);
    try { await onCreate(newYear, newFund); } finally { setCreating(false); }
  }

  return (
    <div>
      {/* Create new */}
      <div className="flex items-end gap-3 mb-6 p-4 bg-gray-50 rounded-lg border">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Fiscal Year</label>
          <input
            type="number"
            value={newYear}
            onChange={(e) => setNewYear(Number(e.target.value))}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm w-24 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Fund</label>
          <select
            value={newFund}
            onChange={(e) => setNewFund(e.target.value)}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="OPERATING">Operating</option>
            <option value="RESERVE">Reserve</option>
            <option value="SPECIAL">Special</option>
          </select>
        </div>
        <button
          onClick={() => void handleCreate()}
          disabled={creating}
          className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {creating ? "Creating…" : "+ New Budget"}
        </button>
      </div>

      {budgets.length === 0 && (
        <p className="text-sm text-gray-400 py-4">No budgets yet. Create one above.</p>
      )}

      <div className="space-y-2">
        {budgets.map((b) => (
          <button
            key={b.id}
            onClick={() => onSelect(b.id)}
            className="w-full flex items-center justify-between px-4 py-3 border rounded-lg bg-white hover:bg-gray-50 text-left transition-colors"
          >
            <div className="flex items-center gap-3">
              <span className="font-semibold text-gray-900">{b.fiscal_year}</span>
              <span className="text-sm text-gray-500">{b.fund_code}</span>
              {b.notes && <span className="text-xs text-gray-400 italic">{b.notes}</span>}
            </div>
            <div className="flex items-center gap-3">
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[b.status as BudgetStatusValue]}`}>
                {b.status}
              </span>
              <span className="text-gray-400 text-xs">Edit →</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Budget Grid Editor ────────────────────────────────────────────────────────

type GridProps = {
  budget: Budget;
  onBack: () => void;
  onRefresh: () => void;
};

function BudgetGrid({ budget, onBack, onRefresh }: GridProps) {
  const [categories, setCategories] = useState<Category[]>([]);
  // grid[categoryId][period 1-12] = amount string
  const [grid, setGrid] = useState<Map<number, string[]>>(new Map());
  const [totals, setTotals] = useState<Map<number, number>>(new Map());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null); // "catId-period"
  const [statusChanging, setStatusChanging] = useState(false);
  const saveTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const isReadOnly = budget.status !== "DRAFT";

  const load = useCallback(async () => {
    const [cats, lines] = await Promise.all([
      listCategories(),
      getBudgetLines(budget.id),
    ]);
    const expCats = cats.filter((c) => c.category_type === "EXPENSE" && c.active_flag);
    setCategories(expCats);

    const g = new Map<number, string[]>();
    for (const cat of expCats) {
      g.set(cat.id, Array(12).fill(""));
    }
    for (const line of lines) {
      const row = g.get(line.category_id);
      if (row && line.fiscal_period >= 1 && line.fiscal_period <= 12) {
        row[line.fiscal_period - 1] = line.budget_amount === 0 ? "" : String(line.budget_amount);
      }
    }
    setGrid(g);
    setTotals(await getBudgetTotals(budget.id));
    setLoading(false);
  }, [budget.id]);

  useEffect(() => { void load(); }, [load]);

  function handleCellChange(catId: number, period: number, value: string) {
    if (isReadOnly) return;
    setGrid((prev) => {
      const next = new Map(prev);
      const row = [...(next.get(catId) ?? Array(12).fill(""))];
      row[period - 1] = value;
      next.set(catId, row);
      return next;
    });

    const key = `${catId}-${period}`;
    const existing = saveTimers.current.get(key);
    if (existing) clearTimeout(existing);
    const timer = setTimeout(async () => {
      setSaving(key);
      try {
        const amount = parseFloat(value) || 0;
        await upsertBudgetLine(budget.id, catId, period, amount);
        setTotals(await getBudgetTotals(budget.id));
      } finally {
        setSaving(null);
        saveTimers.current.delete(key);
      }
    }, 600);
    saveTimers.current.set(key, timer);
  }

  async function handleStatusChange(newStatus: string) {
    if (!confirm(`Set budget to ${newStatus}?`)) return;
    setStatusChanging(true);
    try {
      await updateBudgetStatus(budget.id, newStatus);
      onRefresh();
    } finally {
      setStatusChanging(false);
    }
  }

  const rowTotal = (catId: number) => {
    const row = grid.get(catId) ?? [];
    return row.reduce((s, v) => s + (parseFloat(v) || 0), 0);
  };

  const colTotal = (period: number) =>
    categories.reduce((s, c) => s + (parseFloat((grid.get(c.id) ?? [])[period - 1] ?? "") || 0), 0);

  const grandTotal = categories.reduce((s, c) => s + rowTotal(c.id), 0);

  if (loading) return <p className="text-sm text-gray-400 py-4">Loading…</p>;

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="text-sm text-blue-600 hover:underline">← Budgets</button>
          <span className="text-gray-400">/</span>
          <span className="font-semibold text-gray-900">{budget.fiscal_year} {budget.fund_code}</span>
          <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[budget.status as BudgetStatusValue]}`}>
            {budget.status}
          </span>
          {saving && <span className="text-xs text-gray-400 animate-pulse">Saving…</span>}
        </div>
        <div className="flex gap-2">
          {budget.status === "DRAFT" && (
            <button
              onClick={() => void handleStatusChange("APPROVED")}
              disabled={statusChanging}
              className="px-3 py-1.5 text-sm bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
            >
              Approve
            </button>
          )}
          {budget.status === "APPROVED" && (
            <button
              onClick={() => void handleStatusChange("ARCHIVED")}
              disabled={statusChanging}
              className="px-3 py-1.5 text-sm bg-gray-500 text-white rounded hover:bg-gray-600 disabled:opacity-50"
            >
              Archive
            </button>
          )}
          {budget.status === "APPROVED" && (
            <button
              onClick={() => void handleStatusChange("DRAFT")}
              disabled={statusChanging}
              className="px-3 py-1.5 text-sm border text-gray-600 rounded hover:bg-gray-50 disabled:opacity-50"
            >
              Reopen
            </button>
          )}
        </div>
      </div>

      {isReadOnly && (
        <div className="mb-3 px-3 py-2 bg-yellow-50 border border-yellow-200 rounded text-xs text-yellow-700">
          This budget is {budget.status.toLowerCase()} and cannot be edited.
        </div>
      )}

      {/* Grid */}
      <div className="overflow-x-auto border rounded-lg">
        <table className="text-xs min-w-max">
          <thead className="bg-gray-50 border-b sticky top-0">
            <tr>
              <th className="px-3 py-2 text-left font-medium text-gray-600 w-44">Category</th>
              {MONTHS.map((m, i) => (
                <th key={i} className="px-1 py-2 text-center font-medium text-gray-600 w-20">{m}</th>
              ))}
              <th className="px-3 py-2 text-right font-medium text-gray-600 w-24">Total</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {categories.length === 0 && (
              <tr>
                <td colSpan={14} className="px-3 py-4 text-center text-gray-400">
                  No expense categories found.
                </td>
              </tr>
            )}
            {categories.map((cat) => (
              <tr key={cat.id} className="hover:bg-gray-50">
                <td className="px-3 py-1 text-gray-700 font-medium whitespace-nowrap">{cat.name}</td>
                {Array.from({ length: 12 }, (_, i) => {
                  const period = i + 1;
                  const key = `${cat.id}-${period}`;
                  const value = (grid.get(cat.id) ?? [])[i] ?? "";
                  return (
                    <td key={i} className="px-0.5 py-0.5">
                      {isReadOnly ? (
                        <div className="px-2 py-1 text-right text-gray-600 w-20">{fmt(parseFloat(value) || 0)}</div>
                      ) : (
                        <input
                          type="number"
                          min="0"
                          step="1"
                          value={value}
                          onChange={(e) => handleCellChange(cat.id, period, e.target.value)}
                          className={`w-20 px-2 py-1 text-right border rounded text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 ${
                            saving === key ? "bg-blue-50" : "border-transparent hover:border-gray-300 focus:border-blue-400"
                          }`}
                        />
                      )}
                    </td>
                  );
                })}
                <td className="px-3 py-1 text-right font-mono font-semibold text-gray-700">
                  {fmt(rowTotal(cat.id))}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot className="bg-gray-50 border-t font-semibold">
            <tr>
              <td className="px-3 py-2 text-gray-600">Total</td>
              {Array.from({ length: 12 }, (_, i) => (
                <td key={i} className="px-1 py-2 text-right text-gray-700 font-mono">
                  {fmt(colTotal(i + 1))}
                </td>
              ))}
              <td className="px-3 py-2 text-right font-mono text-gray-900">{fmt(grandTotal)}</td>
            </tr>
          </tfoot>
        </table>
      </div>

      <p className="mt-2 text-xs text-gray-400">
        {isReadOnly ? "Read-only." : "Changes save automatically as you type."}
        {" "}{totals.size > 0 && `${totals.size} categor${totals.size === 1 ? "y" : "ies"} with amounts set.`}
      </p>
    </div>
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

export function BudgetsScreen() {
  const [budgets, setBudgets] = useState<Budget[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [selectedBudget, setSelectedBudget] = useState<Budget | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setBudgets(await listBudgets());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function handleSelect(id: number) {
    const b = await getBudget(id);
    setSelectedBudget(b);
    setSelected(id);
  }

  async function handleCreate(year: number, fund: string) {
    await createBudget(year, fund);
    await load();
  }

  async function handleRefresh() {
    await load();
    if (selected) {
      const b = await getBudget(selected);
      setSelectedBudget(b);
    }
  }

  return (
    <div className="p-8 max-w-6xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Budgets</h1>
        <p className="text-sm text-gray-500 mt-0.5">Annual expense budgets by category and month.</p>
      </div>

      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {!loading && !error && (
        selected && selectedBudget ? (
          <BudgetGrid
            budget={selectedBudget}
            onBack={() => { setSelected(null); setSelectedBudget(null); }}
            onRefresh={() => void handleRefresh()}
          />
        ) : (
          <BudgetList
            budgets={budgets}
            onSelect={(id) => void handleSelect(id)}
            onCreate={(y, f) => void handleCreate(y, f)}
          />
        )
      )}
    </div>
  );
}
