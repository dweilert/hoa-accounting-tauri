import { useEffect, useState, useCallback } from "react";
import { getDb } from "../lib/db";

// ── Types ─────────────────────────────────────────────────────────────────────

type AuditRow = {
  id: number;
  event_time: string;
  entity_type: string;
  entity_id: number;
  action: string;
  before_json: string | null;
  after_json: string | null;
  changed_by: string | null;
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function actionBadge(action: string) {
  const map: Record<string, string> = {
    INSERT:          "bg-green-100 text-green-800",
    UPDATE:          "bg-blue-100 text-blue-800",
    DELETE:          "bg-red-100 text-red-800",
    CREATE_AND_POST: "bg-purple-100 text-purple-800",
  };
  return `inline-flex px-2 py-0.5 rounded text-xs font-medium ${map[action] ?? "bg-gray-100 text-gray-700"}`;
}

function fmtTime(s: string) {
  try {
    return new Date(s + "Z").toLocaleString();
  } catch {
    return s;
  }
}

function JsonDiff({ before, after }: { before: string | null; after: string | null }) {
  const [open, setOpen] = useState(false);
  if (!before && !after) return null;

  function parse(s: string | null): Record<string, unknown> {
    if (!s) return {};
    try { return JSON.parse(s) as Record<string, unknown>; } catch { return {}; }
  }

  const bObj = parse(before);
  const aObj = parse(after);
  const keys = Array.from(new Set([...Object.keys(bObj), ...Object.keys(aObj)]));
  const changed = keys.filter((k) => JSON.stringify(bObj[k]) !== JSON.stringify(aObj[k]));

  return (
    <div className="mt-1">
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-xs text-blue-600 hover:underline"
      >
        {open ? "Hide" : "Show"} details {changed.length > 0 ? `(${changed.length} change${changed.length > 1 ? "s" : ""})` : ""}
      </button>
      {open && (
        <div className="mt-1 border border-gray-200 rounded bg-gray-50 text-xs font-mono overflow-x-auto">
          <table className="min-w-full">
            <thead>
              <tr className="bg-gray-100 text-gray-600">
                <th className="text-left px-2 py-1">Field</th>
                <th className="text-left px-2 py-1">Before</th>
                <th className="text-left px-2 py-1">After</th>
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => {
                const bv = bObj[k] === undefined ? "—" : JSON.stringify(bObj[k]);
                const av = aObj[k] === undefined ? "—" : JSON.stringify(aObj[k]);
                const diff = bv !== av;
                return (
                  <tr key={k} className={diff ? "bg-yellow-50" : ""}>
                    <td className="px-2 py-0.5 font-semibold text-gray-700 whitespace-nowrap">{k}</td>
                    <td className={`px-2 py-0.5 ${diff ? "text-red-700" : "text-gray-600"} max-w-xs truncate`}>{bv}</td>
                    <td className={`px-2 py-0.5 ${diff ? "text-green-700" : "text-gray-600"} max-w-xs truncate`}>{av}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Main screen ───────────────────────────────────────────────────────────────

const PAGE_SIZE = 50;

export function AuditLogScreen() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [entityFilter, setEntityFilter] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const [search, setSearch] = useState("");
  const [entityTypes, setEntityTypes] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load distinct entity types once for the filter dropdown
  useEffect(() => {
    getDb()
      .then((db) =>
        db.select<{ entity_type: string }[]>(
          "SELECT DISTINCT entity_type FROM audit_log ORDER BY entity_type"
        )
      )
      .then((r) => setEntityTypes(r.map((x) => x.entity_type)))
      .catch(() => {});
  }, []);

  const load = useCallback(() => {
    setLoading(true);
    const conditions: string[] = [];
    const params: unknown[] = [];

    if (entityFilter) { conditions.push("entity_type = ?"); params.push(entityFilter); }
    if (actionFilter) { conditions.push("action = ?"); params.push(actionFilter); }
    if (search.trim()) {
      conditions.push("(changed_by LIKE ? OR before_json LIKE ? OR after_json LIKE ?)");
      const like = `%${search.trim()}%`;
      params.push(like, like, like);
    }

    const where = conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";

    getDb()
      .then((db) =>
        Promise.all([
          db.select<{ cnt: number }[]>(`SELECT COUNT(*) AS cnt FROM audit_log ${where}`, params),
          db.select<AuditRow[]>(
            `SELECT id, event_time, entity_type, entity_id, action, before_json, after_json, changed_by
             FROM audit_log ${where}
             ORDER BY event_time DESC, id DESC
             LIMIT ? OFFSET ?`,
            [...params, PAGE_SIZE, page * PAGE_SIZE]
          ),
        ])
      )
      .then(([counts, data]) => {
        setTotal(counts[0]?.cnt ?? 0);
        setRows(data);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [entityFilter, actionFilter, search, page]);

  useEffect(() => { load(); }, [load]);

  // Reset to page 0 when filters change
  useEffect(() => { setPage(0); }, [entityFilter, actionFilter, search]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Audit Log</h1>
        <p className="text-sm text-gray-500 mt-1">
          Read-only history of all data changes — {total.toLocaleString()} entries
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4">
        <select
          value={entityFilter}
          onChange={(e) => setEntityFilter(e.target.value)}
          className="border border-gray-300 rounded px-3 py-1.5 text-sm bg-white"
        >
          <option value="">All tables</option>
          {entityTypes.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>

        <select
          value={actionFilter}
          onChange={(e) => setActionFilter(e.target.value)}
          className="border border-gray-300 rounded px-3 py-1.5 text-sm bg-white"
        >
          <option value="">All actions</option>
          <option value="INSERT">INSERT</option>
          <option value="UPDATE">UPDATE</option>
          <option value="DELETE">DELETE</option>
          <option value="CREATE_AND_POST">CREATE_AND_POST</option>
        </select>

        <input
          type="text"
          placeholder="Search user or JSON…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="border border-gray-300 rounded px-3 py-1.5 text-sm w-56"
        />

        <button
          onClick={() => { setEntityFilter(""); setActionFilter(""); setSearch(""); }}
          className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded bg-white"
        >
          Clear
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>
      )}

      {/* Table */}
      <div className="bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-2.5 font-medium text-gray-600 w-40">Time</th>
              <th className="text-left px-4 py-2.5 font-medium text-gray-600 w-32">Table</th>
              <th className="text-left px-4 py-2.5 font-medium text-gray-600 w-16">ID</th>
              <th className="text-left px-4 py-2.5 font-medium text-gray-600 w-28">Action</th>
              <th className="text-left px-4 py-2.5 font-medium text-gray-600 w-40">Changed By</th>
              <th className="text-left px-4 py-2.5 font-medium text-gray-600">Details</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-gray-400 text-sm">Loading…</td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-gray-400 text-sm">No entries match the current filters.</td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={r.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 text-gray-600 whitespace-nowrap text-xs">{fmtTime(r.event_time)}</td>
                  <td className="px-4 py-2 text-gray-800 font-mono text-xs whitespace-nowrap">{r.entity_type}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{r.entity_id}</td>
                  <td className="px-4 py-2">
                    <span className={actionBadge(r.action)}>{r.action}</span>
                  </td>
                  <td className="px-4 py-2 text-gray-600 text-xs truncate max-w-[10rem]">{r.changed_by ?? "—"}</td>
                  <td className="px-4 py-2">
                    <JsonDiff before={r.before_json} after={r.after_json} />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between mt-4 text-sm text-gray-600">
        <span>
          {total === 0 ? "No results" : `Showing ${page * PAGE_SIZE + 1}–${Math.min((page + 1) * PAGE_SIZE, total)} of ${total.toLocaleString()}`}
        </span>
        <div className="flex gap-2">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="px-3 py-1 border border-gray-300 rounded disabled:opacity-40 bg-white hover:bg-gray-50"
          >
            ← Prev
          </button>
          <span className="px-2 py-1 text-gray-500">
            Page {page + 1} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
            className="px-3 py-1 border border-gray-300 rounded disabled:opacity-40 bg-white hover:bg-gray-50"
          >
            Next →
          </button>
        </div>
      </div>
    </div>
  );
}
