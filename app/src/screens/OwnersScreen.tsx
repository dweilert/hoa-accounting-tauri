import { useEffect, useState, useCallback } from "react";
import { Modal } from "../components/Modal";
import { PageLayout } from "../components/PageLayout";
import { listOwners, insertOwner, updateOwner, deactivateOwner } from "../repositories/ownerRepo";
import { OwnerFormSchema, type OwnerWithLots, type OwnerFormValues, type OwnerTypeValue } from "../types/owner";

// ── Form ─────────────────────────────────────────────────────────────────────

type FormProps = {
  initial?: OwnerWithLots;
  onSave: (v: OwnerFormValues) => Promise<void>;
  onCancel: () => void;
};

function OwnerForm({ initial, onSave, onCancel }: FormProps) {
  const isEdit = !!initial;
  const [values, setValues] = useState<OwnerFormValues>({
    owner_type: initial?.owner_type ?? "PERSON",
    display_name: initial?.display_name ?? "",
    first_name: initial?.first_name ?? "",
    last_name: initial?.last_name ?? "",
    entity_name: initial?.entity_name ?? "",
    mailing_address_1: initial?.mailing_address_1 ?? "",
    mailing_address_2: initial?.mailing_address_2 ?? "",
    city: initial?.city ?? "",
    state: initial?.state ?? "",
    postal_code: initial?.postal_code ?? "",
    phone: initial?.phone ?? "",
    home_phone: initial?.home_phone ?? "",
    email: initial?.email ?? "",
    notes: initial?.notes ?? "",
    active_flag: initial?.active_flag ?? 1,
  });
  const [errors, setErrors] = useState<Partial<Record<string, string>>>({});
  const [saving, setSaving] = useState(false);

  const set = <K extends keyof OwnerFormValues>(k: K, v: OwnerFormValues[K]) =>
    setValues((p) => ({ ...p, [k]: v }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const result = OwnerFormSchema.safeParse(values);
    if (!result.success) {
      const errs: typeof errors = {};
      for (const issue of result.error.issues) errs[String(issue.path[0])] = issue.message;
      setErrors(errs);
      return;
    }
    setSaving(true);
    try { await onSave(result.data); } finally { setSaving(false); }
  }

  const inp = (label: string, field: keyof OwnerFormValues, placeholder?: string, type = "text") => (
    <div>
      <label className="block text-xs font-medium text-gray-700 mb-1">{label}</label>
      <input
        type={type}
        value={String(values[field] ?? "")}
        onChange={(e) => set(field, e.target.value as OwnerFormValues[typeof field])}
        placeholder={placeholder}
        className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      {errors[field] && <p className="mt-1 text-xs text-red-600">{errors[field]}</p>}
    </div>
  );

  const isPerson = values.owner_type === "PERSON";

  return (
    <form onSubmit={handleSubmit} className="space-y-4 max-h-[70vh] overflow-y-auto pr-1">
      {/* Type + Display Name */}
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Type</label>
          <select
            value={values.owner_type}
            onChange={(e) => set("owner_type", e.target.value as OwnerTypeValue)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="PERSON">Person</option>
            <option value="ENTITY">Entity</option>
            <option value="TRUST">Trust</option>
          </select>
        </div>
        <div className="col-span-2">{inp("Display Name *", "display_name")}</div>
      </div>

      {isPerson ? (
        <div className="grid grid-cols-2 gap-3">
          {inp("First Name", "first_name")}
          {inp("Last Name", "last_name")}
        </div>
      ) : (
        inp("Entity / Trust Name", "entity_name")
      )}

      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide pt-1">Mailing Address</p>
      {inp("Address Line 1", "mailing_address_1")}
      {inp("Address Line 2", "mailing_address_2")}
      <div className="grid grid-cols-3 gap-3">
        <div className="col-span-1">{inp("City", "city")}</div>
        <div>{inp("State", "state", "CO")}</div>
        <div>{inp("Zip", "postal_code")}</div>
      </div>

      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide pt-1">Contact</p>
      <div className="grid grid-cols-2 gap-3">
        {inp("Cell Phone", "phone", "555-555-5555", "tel")}
        {inp("Home Phone", "home_phone", "555-555-5555", "tel")}
      </div>
      {inp("Email", "email", "owner@example.com", "email")}
      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Notes</label>
        <textarea
          value={String(values.notes ?? "")}
          onChange={(e) => set("notes", e.target.value)}
          rows={2}
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
        />
      </div>

      {isEdit && (
        <div className="flex gap-4">
          {([1, 0] as const).map((v) => (
            <label key={v} className="flex items-center gap-2 text-sm cursor-pointer">
              <input
                type="radio"
                name="active_flag"
                value={v}
                checked={values.active_flag === v}
                onChange={() => set("active_flag", v)}
              />
              {v === 1 ? "Active" : "Inactive"}
            </label>
          ))}
        </div>
      )}

      <div className="flex justify-end gap-3 pt-2 border-t sticky bottom-0 bg-white pb-1">
        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : isEdit ? "Save Changes" : "Add Owner"}
        </button>
      </div>
    </form>
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

type ModalState = { mode: "add" } | { mode: "edit"; owner: OwnerWithLots } | null;

const TYPE_LABEL: Record<string, string> = { PERSON: "Person", ENTITY: "Entity", TRUST: "Trust" };
const TYPE_COLOR: Record<string, string> = {
  PERSON: "bg-blue-100 text-blue-700",
  ENTITY: "bg-purple-100 text-purple-700",
  TRUST: "bg-yellow-100 text-yellow-700",
};

export function OwnersScreen() {
  const [owners, setOwners] = useState<OwnerWithLots[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalState>(null);

  const load = useCallback(async () => {
    try { setOwners(await listOwners()); }
    catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function handleSave(values: OwnerFormValues) {
    if (modal?.mode === "edit") {
      await updateOwner(modal.owner.id, values);
    } else {
      await insertOwner(values);
    }
    setModal(null);
    await load();
  }

  async function handleDeactivate(owner: OwnerWithLots) {
    if (!confirm(`Deactivate "${owner.display_name}"? This will end all current lot ownership.`)) return;
    try { await deactivateOwner(owner.id); await load(); }
    catch (e) { alert(String(e)); }
  }

  return (
    <PageLayout
      title="Owners"
      subtitle="Property owner directory."
      helpId="owners"
      actions={
        <button
          onClick={() => setModal({ mode: "add" })}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
        >
          + Add Owner
        </button>
      }
    >
      <div className="max-w-5xl">

      {loading && <p className="text-gray-400 text-sm">Loading…</p>}
      {error && <p className="text-red-600 text-sm">{error}</p>}

      {!loading && !error && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Name</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Type</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Phone</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Email</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Lots</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Status</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {owners.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-gray-400 text-sm">
                    No owners yet. Click "Add Owner" to get started.
                  </td>
                </tr>
              )}
              {owners.map((owner) => (
                <tr key={owner.id} className={owner.active_flag ? "" : "opacity-50"}>
                  <td className="px-4 py-2 font-medium text-gray-900">{owner.display_name}</td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${TYPE_COLOR[owner.owner_type] ?? ""}`}>
                      {TYPE_LABEL[owner.owner_type] ?? owner.owner_type}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-gray-600 text-xs">{owner.phone ?? "—"}</td>
                  <td className="px-4 py-2 text-gray-600 text-xs">{owner.email ?? "—"}</td>
                  <td className="px-4 py-2 text-gray-600 text-xs">{owner.lot_numbers ?? <span className="text-gray-300 italic">None</span>}</td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${owner.active_flag ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"}`}>
                      {owner.active_flag ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right space-x-2 whitespace-nowrap">
                    <button onClick={() => setModal({ mode: "edit", owner })} className="text-xs text-blue-600 hover:underline">Edit</button>
                    {!!owner.active_flag && (
                      <button onClick={() => handleDeactivate(owner)} className="text-xs text-red-500 hover:underline">Deactivate</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modal && (
        <Modal
          title={modal.mode === "add" ? "Add Owner" : `Edit — ${modal.mode === "edit" ? modal.owner.display_name : ""}`}
          onClose={() => setModal(null)}
        >
          {modal.mode === "edit" ? (
            <OwnerForm initial={modal.owner} onSave={handleSave} onCancel={() => setModal(null)} />
          ) : (
            <OwnerForm onSave={handleSave} onCancel={() => setModal(null)} />
          )}
        </Modal>
      )}
      </div>
    </PageLayout>
  );
}
