import { useEffect, useState, useCallback } from "react";
import { Modal } from "../components/Modal";
import { PageLayout } from "../components/PageLayout";
import { useCurrentUser } from "../contexts/AuthContext";
import {
  listAnnouncements,
  createAnnouncement,
  updateAnnouncement,
  deleteAnnouncement,
  type Announcement,
  type AnnouncementFormValues,
} from "../repositories/announcementRepo";

const SEVERITY_LABEL = { info: "Info", warning: "Warning", urgent: "Urgent" };
const SEVERITY_COLOR = {
  info: "bg-blue-100 text-blue-700",
  warning: "bg-amber-100 text-amber-700",
  urgent: "bg-red-100 text-red-700",
};

function fmt(s: string) {
  return new Date(s).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

// ── Form ──────────────────────────────────────────────────────────────────────

function AnnouncementForm({
  initial,
  onSave,
  onCancel,
}: {
  initial?: Announcement;
  onSave: (v: AnnouncementFormValues) => Promise<void>;
  onCancel: () => void;
}) {
  const isEdit = !!initial;
  const [values, setValues] = useState<AnnouncementFormValues>({
    message: initial?.message ?? "",
    severity: initial?.severity ?? "info",
    expires_at: initial?.expires_at ? initial.expires_at.slice(0, 10) : "",
    is_active: initial?.is_active ?? 1,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = <K extends keyof AnnouncementFormValues>(k: K, v: AnnouncementFormValues[K]) =>
    setValues((p) => ({ ...p, [k]: v }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!values.message.trim()) { setError("Message is required."); return; }
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
        <label className="block text-xs font-medium text-gray-700 mb-1">Message *</label>
        <textarea
          value={values.message}
          onChange={(e) => set("message", e.target.value)}
          rows={3}
          placeholder="e.g. Annual dues are due March 1st."
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Severity</label>
          <select
            value={values.severity}
            onChange={(e) => set("severity", e.target.value as AnnouncementFormValues["severity"])}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="info">Info — blue</option>
            <option value="warning">Warning — amber</option>
            <option value="urgent">Urgent — red</option>
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Expires (optional)</label>
          <input
            type="date"
            value={values.expires_at}
            onChange={(e) => set("expires_at", e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={values.is_active === 1}
          onChange={(e) => set("is_active", e.target.checked ? 1 : 0)}
          className="h-4 w-4 rounded border-gray-300 text-blue-600"
        />
        <span className="text-sm text-gray-700">Active (visible on dashboard)</span>
      </label>
      <div className="flex justify-end gap-3 pt-2 border-t">
        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : isEdit ? "Save Changes" : "Add Announcement"}
        </button>
      </div>
    </form>
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

type ModalState = { mode: "add" } | { mode: "edit"; item: Announcement } | null;

export function AnnouncementsScreen() {
  const currentUser = useCurrentUser();
  const [items, setItems] = useState<Announcement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalState>(null);

  const load = useCallback(async () => {
    try {
      setItems(await listAnnouncements());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function handleSave(values: AnnouncementFormValues) {
    if (modal?.mode === "edit") {
      await updateAnnouncement(modal.item.id, values);
    } else {
      await createAnnouncement(values, currentUser?.displayName ?? currentUser?.email ?? null);
    }
    setModal(null);
    await load();
  }

  async function handleDelete(item: Announcement) {
    if (!confirm("Delete this announcement? This cannot be undone.")) return;
    try {
      await deleteAnnouncement(item.id);
      await load();
    } catch (e) {
      alert(String(e));
    }
  }

  const isExpired = (item: Announcement) =>
    !!item.expires_at && new Date(item.expires_at) < new Date();

  return (
    <PageLayout
      title="Announcements"
      subtitle="Post notices that appear on the dashboard."
      helpId="announcements"
      actions={
        <button
          onClick={() => setModal({ mode: "add" })}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
        >
          + Add Announcement
        </button>
      }
    >
    <div className="max-w-3xl">
      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {!loading && (
        <div className="space-y-2">
          {items.length === 0 && (
            <p className="text-sm text-gray-400 py-6 text-center">No announcements yet.</p>
          )}
          {items.map((item) => {
            const expired = isExpired(item);
            const inactive = !item.is_active;
            return (
              <div
                key={item.id}
                className={`border rounded-lg px-4 py-3 flex items-start justify-between gap-4 ${expired || inactive ? "opacity-50" : ""}`}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${SEVERITY_COLOR[item.severity]}`}>
                      {SEVERITY_LABEL[item.severity]}
                    </span>
                    {inactive && (
                      <span className="px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-500">inactive</span>
                    )}
                    {expired && (
                      <span className="px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-500">expired</span>
                    )}
                    {item.expires_at && !expired && (
                      <span className="text-xs text-gray-400">expires {fmt(item.expires_at)}</span>
                    )}
                  </div>
                  <p className="text-sm text-gray-800">{item.message}</p>
                  <p className="text-xs text-gray-400 mt-1">
                    Added {fmt(item.created_at)}{item.created_by ? ` by ${item.created_by}` : ""}
                  </p>
                </div>
                <div className="flex gap-3 shrink-0">
                  <button
                    onClick={() => setModal({ mode: "edit", item })}
                    className="text-xs text-blue-600 hover:underline"
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => void handleDelete(item)}
                    className="text-xs text-red-500 hover:underline"
                  >
                    Delete
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {modal && (
        <Modal
          title={modal.mode === "add" ? "Add Announcement" : "Edit Announcement"}
          onClose={() => setModal(null)}
        >
          {modal.mode === "edit" ? (
            <AnnouncementForm initial={modal.item} onSave={handleSave} onCancel={() => setModal(null)} />
          ) : (
            <AnnouncementForm onSave={handleSave} onCancel={() => setModal(null)} />
          )}
        </Modal>
      )}
    </div>
    </PageLayout>
  );
}
