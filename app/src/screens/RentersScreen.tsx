import { useEffect, useState } from "react";
import { getDb } from "../lib/db";
import { PageLayout } from "../components/PageLayout";

// ── Types ─────────────────────────────────────────────────────────────────────

type Renter = {
  id: number;
  lot_id: number;
  lot_number: string;
  street_address_1: string | null;
  display_name: string;
  first_name: string | null;
  last_name: string | null;
  email: string | null;
  phone: string | null;
  start_date: string;
  end_date: string | null;
  notes: string | null;
};

type Lot = { id: number; lot_number: string; street_address_1: string | null };

type FormVals = {
  lot_id: number;
  display_name: string;
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  start_date: string;
  end_date: string;
  notes: string;
};

const BLANK = (lotId = 0): FormVals => ({
  lot_id: lotId,
  display_name: "",
  first_name: "",
  last_name: "",
  email: "",
  phone: "",
  start_date: new Date().toISOString().slice(0, 10),
  end_date: "",
  notes: "",
});

// ── DB helpers ────────────────────────────────────────────────────────────────

async function listRenters(activeOnly: boolean): Promise<Renter[]> {
  const db = await getDb();
  const where = activeOnly ? "AND lr.end_date IS NULL" : "";
  return db.select<Renter[]>(`
    SELECT lr.id, lr.lot_id, l.lot_number, l.street_address_1,
           lr.display_name, lr.first_name, lr.last_name,
           lr.email, lr.phone, lr.start_date, lr.end_date, lr.notes
    FROM lot_renters lr
    JOIN lots l ON lr.lot_id = l.id
    WHERE 1=1 ${where}
    ORDER BY lr.end_date IS NULL DESC, l.lot_number, lr.start_date DESC
  `);
}

async function insertRenter(v: FormVals): Promise<void> {
  const db = await getDb();
  await db.execute(
    `INSERT INTO lot_renters (lot_id, display_name, first_name, last_name, email, phone, start_date, end_date, notes)
     VALUES (?,?,?,?,?,?,?,?,?)`,
    [v.lot_id, v.display_name, v.first_name || null, v.last_name || null,
     v.email || null, v.phone || null, v.start_date, v.end_date || null, v.notes || null]
  );
}

async function updateRenter(id: number, v: FormVals): Promise<void> {
  const db = await getDb();
  await db.execute(
    `UPDATE lot_renters SET lot_id=?, display_name=?, first_name=?, last_name=?, email=?, phone=?,
     start_date=?, end_date=?, notes=?, updated_at=datetime('now') WHERE id=?`,
    [v.lot_id, v.display_name, v.first_name || null, v.last_name || null,
     v.email || null, v.phone || null, v.start_date, v.end_date || null, v.notes || null, id]
  );
}

async function deleteRenter(id: number): Promise<void> {
  const db = await getDb();
  await db.execute("DELETE FROM lot_renters WHERE id=?", [id]);
}

// ── Form ──────────────────────────────────────────────────────────────────────

function RenterForm({
  lots,
  initial,
  onSave,
  onCancel,
}: {
  lots: Lot[];
  initial?: Renter;
  onSave: (v: FormVals) => Promise<void>;
  onCancel: () => void;
}) {
  const [v, setV] = useState<FormVals>(
    initial
      ? {
          lot_id: initial.lot_id,
          display_name: initial.display_name,
          first_name: initial.first_name ?? "",
          last_name: initial.last_name ?? "",
          email: initial.email ?? "",
          phone: initial.phone ?? "",
          start_date: initial.start_date,
          end_date: initial.end_date ?? "",
          notes: initial.notes ?? "",
        }
      : BLANK(lots[0]?.id ?? 0)
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = <K extends keyof FormVals>(k: K, val: FormVals[K]) => setV((p) => ({ ...p, [k]: val }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!v.display_name.trim()) { setError("Name is required."); return; }
    if (!v.start_date) { setError("Start date is required."); return; }
    setSaving(true); setError(null);
    try { await onSave(v); }
    catch (e) { setError(String(e)); setSaving(false); }
  }

  const inp = (label: string, field: keyof FormVals, type = "text", placeholder?: string) => (
    <div>
      <label className="block text-xs font-medium text-gray-700 mb-1">{label}</label>
      <input type={type} value={v[field] as string} placeholder={placeholder}
        onChange={(e) => set(field, e.target.value as FormVals[keyof FormVals])}
        className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
    </div>
  );

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="bg-white border rounded-lg p-5 space-y-4 mb-5 shadow-sm">
      <h2 className="font-semibold text-gray-800 text-sm">{initial ? "Edit Renter" : "Add Renter"}</h2>
      {error && <p className="text-xs text-red-600">{error}</p>}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Lot</label>
          <select value={v.lot_id} onChange={(e) => set("lot_id", Number(e.target.value))}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            {lots.map((l) => (
              <option key={l.id} value={l.id}>
                Lot {l.lot_number}{l.street_address_1 ? ` — ${l.street_address_1}` : ""}
              </option>
            ))}
          </select>
        </div>
        {inp("Full Name / Display Name", "display_name", "text", "e.g. Jane Smith")}
        {inp("First Name", "first_name")}
        {inp("Last Name", "last_name")}
        {inp("Email", "email", "email")}
        {inp("Phone", "phone", "tel")}
        {inp("Move-In Date", "start_date", "date")}
        {inp("Move-Out Date (blank = current)", "end_date", "date")}
        <div className="col-span-2">{inp("Notes", "notes")}</div>
      </div>
      <div className="flex gap-3">
        <button type="submit" disabled={saving}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50">
          {saving ? "Saving…" : "Save"}
        </button>
        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">Cancel</button>
      </div>
    </form>
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

export function RentersScreen() {
  const [renters, setRenters] = useState<Renter[]>([]);
  const [lots, setLots] = useState<Lot[]>([]);
  const [activeOnly, setActiveOnly] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Renter | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      const [db2, rows] = await Promise.all([
        getDb().then((db) => db.select<Lot[]>("SELECT id, lot_number, street_address_1 FROM lots WHERE active_flag=1 ORDER BY lot_number")),
        listRenters(activeOnly),
      ]);
      setLots(db2);
      setRenters(rows);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void refresh(); }, [activeOnly]);

  async function handleSaveNew(v: FormVals) { await insertRenter(v); setShowForm(false); void refresh(); }
  async function handleSaveEdit(v: FormVals) { if (editing) { await updateRenter(editing.id, v); setEditing(null); void refresh(); } }

  async function handleDelete(id: number) {
    if (!confirm("Remove this renter record?")) return;
    setDeleting(id);
    try { await deleteRenter(id); setRenters((p) => p.filter((r) => r.id !== id)); }
    catch (e) { setError(String(e)); }
    finally { setDeleting(null); }
  }

  return (
    <PageLayout
      title="Renters"
      subtitle="Track tenants living in HOA lots."
      helpId="renters"
      actions={
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-sm text-gray-600 cursor-pointer">
            <input type="checkbox" checked={activeOnly} onChange={(e) => setActiveOnly(e.target.checked)} />
            Current only
          </label>
          <button onClick={() => { setShowForm(true); setEditing(null); }}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">
            + Add Renter
          </button>
        </div>
      }
    >
      <div className="max-w-4xl">
        {error && <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>}

        {showForm && !editing && <RenterForm lots={lots} onSave={handleSaveNew} onCancel={() => setShowForm(false)} />}
        {editing && <RenterForm lots={lots} initial={editing} onSave={handleSaveEdit} onCancel={() => setEditing(null)} />}

        {loading ? (
          <p className="text-gray-400 text-sm">Loading…</p>
        ) : renters.length === 0 ? (
          <p className="text-gray-400 text-sm">No renters{activeOnly ? " currently active" : ""} on record.</p>
        ) : (
          <div className="bg-white border rounded-lg overflow-hidden shadow-sm">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-600">Lot</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-600">Renter</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-600">Contact</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-600">Dates</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-600">Status</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {renters.map((r) => (
                  <tr key={r.id} className={r.end_date ? "opacity-60" : "hover:bg-gray-50"}>
                    <td className="px-4 py-2.5">
                      <p className="font-medium text-gray-900">Lot {r.lot_number}</p>
                      {r.street_address_1 && <p className="text-xs text-gray-400">{r.street_address_1}</p>}
                    </td>
                    <td className="px-4 py-2.5">
                      <p className="text-gray-900">{r.display_name}</p>
                      {r.notes && <p className="text-xs text-gray-400 mt-0.5">{r.notes}</p>}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-500">
                      {r.email && <p>{r.email}</p>}
                      {r.phone && <p>{r.phone}</p>}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-500">
                      {r.start_date}{r.end_date ? ` → ${r.end_date}` : " → present"}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${r.end_date ? "bg-gray-100 text-gray-500" : "bg-green-100 text-green-700"}`}>
                        {r.end_date ? "Past" : "Current"}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right space-x-3">
                      <button onClick={() => setEditing(r)} className="text-xs text-blue-600 hover:underline">Edit</button>
                      <button onClick={() => void handleDelete(r.id)} disabled={deleting === r.id}
                        className="text-xs text-red-500 hover:underline disabled:opacity-40">
                        {deleting === r.id ? "…" : "Remove"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </PageLayout>
  );
}
