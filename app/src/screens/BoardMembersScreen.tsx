import { useEffect, useState } from "react";
import { getDb } from "../lib/db";

// ── Types ─────────────────────────────────────────────────────────────────────

type BoardMember = {
  id: number;
  owner_id: number | null;
  display_name: string;
  role: string;
  term_start: string;
  term_end: string | null;
  email: string | null;
  phone: string | null;
  notes: string | null;
  active_flag: number;
};

type FormValues = {
  display_name: string;
  role: string;
  term_start: string;
  term_end: string;
  email: string;
  phone: string;
  notes: string;
  active_flag: number;
};

const ROLES = [
  "PRESIDENT","VICE_PRESIDENT","SECRETARY","TREASURER","MEMBER","AT_LARGE",
];

const ROLE_LABELS: Record<string, string> = {
  PRESIDENT: "President",
  VICE_PRESIDENT: "Vice President",
  SECRETARY: "Secretary",
  TREASURER: "Treasurer",
  MEMBER: "Member",
  AT_LARGE: "Member At-Large",
};

const BLANK: FormValues = {
  display_name: "", role: "MEMBER", term_start: "", term_end: "",
  email: "", phone: "", notes: "", active_flag: 1,
};

// ── DB helpers ────────────────────────────────────────────────────────────────

async function listMembers(): Promise<BoardMember[]> {
  const db = await getDb();
  return db.select<BoardMember[]>(
    "SELECT id, owner_id, display_name, role, term_start, term_end, email, phone, notes, active_flag FROM board_members ORDER BY active_flag DESC, term_start DESC"
  );
}

async function insertMember(v: FormValues): Promise<void> {
  const db = await getDb();
  await db.execute(
    `INSERT INTO board_members (display_name, role, term_start, term_end, email, phone, notes, active_flag)
     VALUES (?,?,?,?,?,?,?,?)`,
    [v.display_name, v.role, v.term_start, v.term_end || null, v.email || null, v.phone || null, v.notes || null, v.active_flag]
  );
}

async function updateMember(id: number, v: FormValues): Promise<void> {
  const db = await getDb();
  await db.execute(
    `UPDATE board_members SET display_name=?, role=?, term_start=?, term_end=?, email=?, phone=?, notes=?, active_flag=?, updated_at=datetime('now') WHERE id=?`,
    [v.display_name, v.role, v.term_start, v.term_end || null, v.email || null, v.phone || null, v.notes || null, v.active_flag, id]
  );
}

async function deleteMember(id: number): Promise<void> {
  const db = await getDb();
  await db.execute("DELETE FROM board_members WHERE id=?", [id]);
}

// ── Form ──────────────────────────────────────────────────────────────────────

function MemberForm({
  initial,
  onSave,
  onCancel,
}: {
  initial?: BoardMember;
  onSave: (v: FormValues) => Promise<void>;
  onCancel: () => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const [v, setV] = useState<FormValues>(
    initial
      ? {
          display_name: initial.display_name,
          role: initial.role,
          term_start: initial.term_start,
          term_end: initial.term_end ?? "",
          email: initial.email ?? "",
          phone: initial.phone ?? "",
          notes: initial.notes ?? "",
          active_flag: initial.active_flag,
        }
      : { ...BLANK, term_start: today }
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = <K extends keyof FormValues>(k: K, val: FormValues[K]) => setV((p) => ({ ...p, [k]: val }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!v.display_name.trim()) { setError("Name is required."); return; }
    if (!v.term_start) { setError("Term start date is required."); return; }
    setSaving(true);
    setError(null);
    try {
      await onSave(v);
    } catch (e) {
      setError(String(e));
      setSaving(false);
    }
  }

  const inp = (label: string, field: keyof FormValues, type = "text", placeholder?: string) => (
    <div>
      <label className="block text-xs font-medium text-gray-700 mb-1">{label}</label>
      <input
        type={type}
        value={v[field] as string}
        onChange={(e) => set(field, e.target.value as FormValues[keyof FormValues])}
        placeholder={placeholder}
        className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
    </div>
  );

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="bg-white border rounded-lg p-5 space-y-4 mb-5 shadow-sm">
      <h2 className="font-semibold text-gray-800 text-sm">{initial ? "Edit Board Member" : "Add Board Member"}</h2>
      {error && <p className="text-xs text-red-600">{error}</p>}

      <div className="grid grid-cols-2 gap-4">
        {inp("Name", "display_name", "text", "e.g. Jane Smith")}
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Role</label>
          <select value={v.role} onChange={(e) => set("role", e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
          </select>
        </div>
        {inp("Term Start", "term_start", "date")}
        {inp("Term End (leave blank if current)", "term_end", "date")}
        {inp("Email", "email", "email")}
        {inp("Phone", "phone", "tel")}
        <div className="col-span-2">
          {inp("Notes", "notes", "text")}
        </div>
        {initial && (
          <div className="flex items-center gap-2">
            <input type="checkbox" id="active" checked={v.active_flag === 1} onChange={(e) => set("active_flag", e.target.checked ? 1 : 0)} />
            <label htmlFor="active" className="text-sm text-gray-700">Active board member</label>
          </div>
        )}
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

export function BoardMembersScreen() {
  const [members, setMembers] = useState<BoardMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<BoardMember | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    listMembers().then(setMembers).catch((e) => setError(String(e))).finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  async function handleSaveNew(v: FormValues) {
    await insertMember(v);
    setShowForm(false);
    refresh();
  }

  async function handleSaveEdit(v: FormValues) {
    if (!editing) return;
    await updateMember(editing.id, v);
    setEditing(null);
    refresh();
  }

  async function handleDelete(id: number) {
    if (!confirm("Remove this board member?")) return;
    setDeleting(id);
    try {
      await deleteMember(id);
      setMembers((prev) => prev.filter((m) => m.id !== id));
    } catch (e) {
      setError(String(e));
    } finally {
      setDeleting(null);
    }
  }

  const current = members.filter((m) => m.active_flag === 1 && !m.term_end);
  const past = members.filter((m) => m.active_flag === 0 || m.term_end);

  return (
    <div className="p-6 max-w-3xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Board Members</h1>
          <p className="text-sm text-gray-500 mt-1">Current and past board member roster.</p>
        </div>
        <button
          onClick={() => { setShowForm(true); setEditing(null); }}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700"
        >
          + Add Member
        </button>
      </div>

      {error && <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>}

      {(showForm && !editing) && (
        <MemberForm onSave={handleSaveNew} onCancel={() => setShowForm(false)} />
      )}
      {editing && (
        <MemberForm initial={editing} onSave={handleSaveEdit} onCancel={() => setEditing(null)} />
      )}

      {loading ? (
        <p className="text-gray-400 text-sm">Loading…</p>
      ) : members.length === 0 ? (
        <p className="text-gray-400 text-sm">No board members recorded yet. Add the first one above.</p>
      ) : (
        <>
          {current.length > 0 && (
            <>
              <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-3">Current Board</h2>
              <MemberTable members={current} onEdit={setEditing} onDelete={handleDelete} deleting={deleting} />
            </>
          )}
          {past.length > 0 && (
            <div className="mt-6">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-3">Past Members</h2>
              <MemberTable members={past} onEdit={setEditing} onDelete={handleDelete} deleting={deleting} />
            </div>
          )}
        </>
      )}
    </div>
  );
}

function MemberTable({ members, onEdit, onDelete, deleting }: {
  members: BoardMember[];
  onEdit: (m: BoardMember) => void;
  onDelete: (id: number) => void;
  deleting: number | null;
}) {
  return (
    <div className="bg-white border rounded-lg overflow-hidden shadow-sm mb-4">
      <table className="min-w-full text-sm">
        <thead className="bg-gray-50 border-b">
          <tr>
            <th className="text-left px-4 py-2.5 font-medium text-gray-600">Name</th>
            <th className="text-left px-4 py-2.5 font-medium text-gray-600">Role</th>
            <th className="text-left px-4 py-2.5 font-medium text-gray-600">Term</th>
            <th className="text-left px-4 py-2.5 font-medium text-gray-600">Contact</th>
            <th className="px-4 py-2.5" />
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {members.map((m) => (
            <tr key={m.id} className="hover:bg-gray-50">
              <td className="px-4 py-2.5">
                <p className="font-medium text-gray-900">{m.display_name}</p>
                {m.notes && <p className="text-xs text-gray-400 mt-0.5">{m.notes}</p>}
              </td>
              <td className="px-4 py-2.5 text-gray-600">{ROLE_LABELS[m.role] ?? m.role}</td>
              <td className="px-4 py-2.5 text-xs text-gray-500">
                {m.term_start}{m.term_end ? ` → ${m.term_end}` : " → present"}
              </td>
              <td className="px-4 py-2.5 text-xs text-gray-500">
                {m.email && <p>{m.email}</p>}
                {m.phone && <p>{m.phone}</p>}
              </td>
              <td className="px-4 py-2.5 text-right space-x-3">
                <button onClick={() => onEdit(m)} className="text-xs text-blue-600 hover:underline">Edit</button>
                <button
                  onClick={() => onDelete(m.id)}
                  disabled={deleting === m.id}
                  className="text-xs text-red-500 hover:underline disabled:opacity-40"
                >
                  {deleting === m.id ? "…" : "Remove"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
