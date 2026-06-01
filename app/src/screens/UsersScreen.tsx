import { useEffect, useState, useCallback } from "react";
import { Modal } from "../components/Modal";
import { PageLayout } from "../components/PageLayout";
import { listUsers, createUser, updateUser, setPassword, deleteUser, type LocalUser } from "../repositories/userRepo";
import { useCurrentUser } from "../contexts/AuthContext";

function fmt(s: string | null): string {
  if (!s) return "—";
  return new Date(s).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
}

// ── User form ─────────────────────────────────────────────────────────────────

type UserFormValues = { email: string; display_name: string; role: "admin" | "reports"; password: string; confirm: string };

function UserForm({
  initial,
  onSave,
  onCancel,
}: {
  initial?: LocalUser;
  onSave: (v: UserFormValues) => Promise<void>;
  onCancel: () => void;
}) {
  const isEdit = !!initial;
  const [values, setValues] = useState<UserFormValues>({
    email: initial?.email ?? "",
    display_name: initial?.display_name ?? "",
    role: initial?.role ?? "reports",
    password: "",
    confirm: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = <K extends keyof UserFormValues>(k: K, v: UserFormValues[K]) =>
    setValues((p) => ({ ...p, [k]: v }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!values.email || !values.display_name) { setError("Name and email are required."); return; }
    if (!isEdit && !values.password) { setError("Password is required for new users."); return; }
    if (values.password && values.password !== values.confirm) { setError("Passwords do not match."); return; }
    if (values.password && values.password.length < 8) { setError("Password must be at least 8 characters."); return; }
    setSaving(true);
    setError(null);
    try {
      await onSave(values);
    } catch (e) {
      setError(String(e));
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && <p className="text-sm text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Display Name *</label>
        <input
          value={values.display_name}
          onChange={(e) => set("display_name", e.target.value)}
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Email *</label>
        <input
          type="email"
          value={values.email}
          onChange={(e) => set("email", e.target.value)}
          disabled={isEdit}
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Role</label>
        <select
          value={values.role}
          onChange={(e) => set("role", e.target.value as "admin" | "reports")}
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="admin">Admin — full access</option>
          <option value="reports">Reports — read-only</option>
        </select>
      </div>
      <div className="border-t pt-3">
        <p className="text-xs text-gray-500 mb-2">{isEdit ? "Set new password (leave blank to keep current)" : "Password *"}</p>
        <div className="space-y-2">
          <input
            type="password"
            value={values.password}
            onChange={(e) => set("password", e.target.value)}
            placeholder={isEdit ? "New password (optional)" : "Password"}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          {values.password && (
            <input
              type="password"
              value={values.confirm}
              onChange={(e) => set("confirm", e.target.value)}
              placeholder="Confirm password"
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          )}
        </div>
      </div>
      <div className="flex justify-end gap-3 pt-2 border-t">
        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">Cancel</button>
        <button
          type="submit"
          disabled={saving}
          className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : isEdit ? "Save Changes" : "Add User"}
        </button>
      </div>
    </form>
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

type ModalState = { mode: "add" } | { mode: "edit"; user: LocalUser } | null;

export function UsersScreen() {
  const currentUser = useCurrentUser();
  const [users, setUsers] = useState<LocalUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalState>(null);

  const isAdmin = currentUser?.role === "admin";

  const load = useCallback(async () => {
    try {
      setUsers(await listUsers());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function handleSave(values: UserFormValues) {
    if (modal?.mode === "edit") {
      await updateUser(modal.user.id, values.display_name, values.role, true);
      if (values.password) await setPassword(modal.user.id, values.password);
    } else {
      await createUser(values.email, values.display_name, values.role, values.password);
    }
    setModal(null);
    await load();
  }

  async function handleToggleActive(user: LocalUser) {
    if (user.id === currentUser?.id) {
      alert("You cannot deactivate your own account.");
      return;
    }
    await updateUser(user.id, user.display_name, user.role, !user.is_active);
    await load();
  }

  async function handleDelete(user: LocalUser) {
    if (user.id === currentUser?.id) {
      alert("You cannot delete your own account.");
      return;
    }
    if (!confirm(`Delete user ${user.email}? This cannot be undone.`)) return;
    try {
      await deleteUser(user.id);
      await load();
    } catch (e) {
      alert(String(e));
    }
  }

  const isBcrypt = (hash: string) => hash.startsWith("$2b$") || hash.startsWith("$2a$");

  if (!isAdmin) {
    return (
      <div className="p-8">
        <h1 className="text-2xl font-bold text-gray-900 mb-2">Users</h1>
        <p className="text-sm text-gray-500">You need admin access to manage users.</p>
      </div>
    );
  }

  return (
    <PageLayout
      title="Users"
      subtitle="Manage app user accounts and roles."
      helpId="users"
      actions={
        <button
          onClick={() => setModal({ mode: "add" })}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
        >
          + Add User
        </button>
      }
    >
    <div className="max-w-4xl">
      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {!loading && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Name</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Email</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Role</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Last Login</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Status</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {users.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-6 text-center text-gray-400 text-sm">No users yet.</td></tr>
              )}
              {users.map((u) => (
                <tr key={u.id} className={!u.is_active ? "opacity-50" : ""}>
                  <td className="px-4 py-2 font-medium text-gray-800">
                    {u.display_name || "—"}
                    {u.id === currentUser?.id && (
                      <span className="ml-2 text-xs text-blue-500">(you)</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-gray-600 text-xs">{u.email}</td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${u.role === "admin" ? "bg-purple-100 text-purple-700" : "bg-gray-100 text-gray-600"}`}>
                      {u.role}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-gray-400 text-xs">{fmt(u.last_login_at)}</td>
                  <td className="px-4 py-2">
                    {isBcrypt(u.password_hash) ? (
                      <span className="px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-700" title="Password must be reset — set using the web app format">
                        needs reset
                      </span>
                    ) : (
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${u.is_active ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-400"}`}>
                        {u.is_active ? "active" : "inactive"}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right space-x-2 whitespace-nowrap">
                    <button
                      onClick={() => setModal({ mode: "edit", user: u })}
                      className="text-xs text-blue-600 hover:underline"
                    >
                      Edit
                    </button>
                    {u.id !== currentUser?.id && (
                      <>
                        <button
                          onClick={() => void handleToggleActive(u)}
                          className="text-xs text-gray-500 hover:underline"
                        >
                          {u.is_active ? "Deactivate" : "Activate"}
                        </button>
                        <button
                          onClick={() => void handleDelete(u)}
                          className="text-xs text-red-500 hover:underline"
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {isBcrypt && users.some((u) => isBcrypt(u.password_hash)) && (
        <p className="mt-3 text-xs text-amber-600">
          Users marked "needs reset" have passwords set by the web app (bcrypt format). Edit them to set a new password.
        </p>
      )}

      {modal && (
        <Modal
          title={modal.mode === "add" ? "Add User" : `Edit ${modal.mode === "edit" ? modal.user.display_name || modal.user.email : ""}`}
          onClose={() => setModal(null)}
        >
          {modal.mode === "edit" ? (
            <UserForm initial={modal.user} onSave={handleSave} onCancel={() => setModal(null)} />
          ) : (
            <UserForm onSave={handleSave} onCancel={() => setModal(null)} />
          )}
        </Modal>
      )}
    </div>
    </PageLayout>
  );
}
