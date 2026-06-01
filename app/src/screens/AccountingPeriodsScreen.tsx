import { useEffect, useState } from "react";
import { getDb } from "../lib/db";

// ── Types ─────────────────────────────────────────────────────────────────────

type Period = {
  id: number;
  period_year: number;
  period_month: number;
  status: "OPEN" | "LOCKED";
  locked_at: string | null;
  locked_by: string | null;
  notes: string | null;
};

const MONTHS = [
  "January","February","March","April","May","June",
  "July","August","September","October","November","December",
];

// ── Helpers ───────────────────────────────────────────────────────────────────

async function loadPeriods(year: number): Promise<Period[]> {
  const db = await getDb();
  return db.select<Period[]>(
    "SELECT id, period_year, period_month, status, locked_at, locked_by, notes FROM accounting_periods WHERE period_year=? ORDER BY period_month",
    [year]
  );
}

async function ensurePeriods(year: number): Promise<void> {
  const db = await getDb();
  for (let m = 1; m <= 12; m++) {
    await db.execute(
      "INSERT OR IGNORE INTO accounting_periods (period_year, period_month, status) VALUES (?,?,?)",
      [year, m, "OPEN"]
    );
  }
}

async function togglePeriodStatus(id: number, currentStatus: "OPEN" | "LOCKED", lockedBy: string): Promise<void> {
  const db = await getDb();
  if (currentStatus === "OPEN") {
    await db.execute(
      "UPDATE accounting_periods SET status='LOCKED', locked_at=datetime('now'), locked_by=? WHERE id=?",
      [lockedBy, id]
    );
  } else {
    await db.execute(
      "UPDATE accounting_periods SET status='OPEN', locked_at=NULL, locked_by=NULL WHERE id=?",
      [id]
    );
  }
}

async function saveNotes(id: number, notes: string): Promise<void> {
  const db = await getDb();
  await db.execute("UPDATE accounting_periods SET notes=? WHERE id=?", [notes || null, id]);
}

// ── Screen ────────────────────────────────────────────────────────────────────

export function AccountingPeriodsScreen() {
  const currentYear = new Date().getFullYear();
  const [year, setYear] = useState(currentYear);
  const [periods, setPeriods] = useState<Period[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);
  const [editNotes, setEditNotes] = useState<{ id: number; text: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      await ensurePeriods(year);
      const rows = await loadPeriods(year);
      setPeriods(rows);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void refresh(); }, [year]);

  async function handleToggle(p: Period) {
    setBusy(p.id);
    try {
      await togglePeriodStatus(p.id, p.status, "admin");
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function handleSaveNotes() {
    if (!editNotes) return;
    setBusy(editNotes.id);
    try {
      await saveNotes(editNotes.id, editNotes.text);
      setEditNotes(null);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function lockAllThrough(throughMonth: number) {
    setBusy(-1);
    try {
      await ensurePeriods(year);
      const db = await getDb();
      for (let m = 1; m <= throughMonth; m++) {
        await db.execute(
          `UPDATE accounting_periods SET status='LOCKED', locked_at=datetime('now'), locked_by='admin'
           WHERE period_year=? AND period_month=? AND status='OPEN'`,
          [year, m]
        );
      }
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  const locked = periods.filter((p) => p.status === "LOCKED").length;
  const lastLocked = periods.filter((p) => p.status === "LOCKED").pop();

  return (
    <div className="p-6 max-w-3xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Accounting Periods</h1>
        <p className="text-sm text-gray-500 mt-1">
          Lock closed months to prevent backdated entries. Locked periods are advisory — they serve as a
          reminder that the period is closed.
        </p>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>
      )}

      {/* Year picker + summary */}
      <div className="flex items-center gap-4 mb-6">
        <div className="flex items-center gap-2">
          <button onClick={() => setYear((y) => y - 1)} className="px-2 py-1 border rounded hover:bg-gray-50">←</button>
          <span className="font-semibold text-gray-800 w-16 text-center">{year}</span>
          <button onClick={() => setYear((y) => y + 1)} className="px-2 py-1 border rounded hover:bg-gray-50">→</button>
        </div>
        <span className="text-sm text-gray-500">
          {locked} of 12 months locked
        </span>
        {lastLocked && (
          <button
            onClick={() => void lockAllThrough(lastLocked.period_month + 1 <= 12 ? lastLocked.period_month + 1 : 12)}
            disabled={busy !== null || lastLocked.period_month >= 12}
            className="ml-auto px-3 py-1.5 text-xs bg-gray-700 text-white rounded hover:bg-gray-800 disabled:opacity-40"
          >
            Lock through {lastLocked.period_month < 12 ? MONTHS[lastLocked.period_month] : "December"}
          </button>
        )}
        {locked === 0 && (
          <button
            onClick={() => void lockAllThrough(new Date().getMonth())}
            disabled={busy !== null}
            className="ml-auto px-3 py-1.5 text-xs bg-gray-700 text-white rounded hover:bg-gray-800 disabled:opacity-40"
          >
            Lock through last month
          </button>
        )}
      </div>

      {loading ? (
        <p className="text-gray-400 text-sm">Loading…</p>
      ) : (
        <div className="bg-white border rounded-lg overflow-hidden shadow-sm">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-4 py-2.5 font-medium text-gray-600 w-32">Period</th>
                <th className="text-left px-4 py-2.5 font-medium text-gray-600 w-24">Status</th>
                <th className="text-left px-4 py-2.5 font-medium text-gray-600">Locked</th>
                <th className="text-left px-4 py-2.5 font-medium text-gray-600">Notes</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {periods.map((p) => (
                <tr key={p.id} className={p.status === "LOCKED" ? "bg-gray-50" : ""}>
                  <td className="px-4 py-2.5 font-medium text-gray-900">
                    {MONTHS[(p.period_month - 1)]} {p.period_year}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${
                      p.status === "LOCKED" ? "bg-red-100 text-red-700" : "bg-green-100 text-green-700"
                    }`}>
                      {p.status === "LOCKED" ? "Locked" : "Open"}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-xs text-gray-400">
                    {p.locked_at ? `${p.locked_at.slice(0, 10)} by ${p.locked_by ?? "—"}` : "—"}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-gray-500">
                    {editNotes?.id === p.id ? (
                      <div className="flex gap-1">
                        <input
                          type="text"
                          value={editNotes.text}
                          onChange={(e) => setEditNotes({ id: p.id, text: e.target.value })}
                          className="border border-gray-300 rounded px-2 py-0.5 text-xs w-40"
                          autoFocus
                          onKeyDown={(e) => {
                            if (e.key === "Enter") void handleSaveNotes();
                            if (e.key === "Escape") setEditNotes(null);
                          }}
                        />
                        <button onClick={() => void handleSaveNotes()} className="text-xs text-blue-600">Save</button>
                        <button onClick={() => setEditNotes(null)} className="text-xs text-gray-400">Cancel</button>
                      </div>
                    ) : (
                      <span
                        className="cursor-pointer hover:text-gray-700"
                        onClick={() => setEditNotes({ id: p.id, text: p.notes ?? "" })}
                      >
                        {p.notes ?? <span className="text-gray-300 italic">add note…</span>}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <button
                      onClick={() => void handleToggle(p)}
                      disabled={busy !== null}
                      className={`text-xs px-3 py-1 rounded border transition-colors disabled:opacity-40 ${
                        p.status === "LOCKED"
                          ? "border-green-300 text-green-700 hover:bg-green-50"
                          : "border-red-300 text-red-700 hover:bg-red-50"
                      }`}
                    >
                      {busy === p.id ? "…" : p.status === "LOCKED" ? "Unlock" : "Lock"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
