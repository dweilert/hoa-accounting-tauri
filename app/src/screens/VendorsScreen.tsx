import { useEffect, useState, useCallback } from "react";
import { Modal } from "../components/Modal";
import { listVendors, insertVendor, updateVendor, deleteVendor, hasBills } from "../repositories/vendorRepo";
import { VendorFormSchema, type Vendor, type VendorFormValues } from "../types/vendor";

// ── Form ─────────────────────────────────────────────────────────────────────

type FormProps = {
  initial?: Vendor;
  onSave: (v: VendorFormValues) => Promise<void>;
  onCancel: () => void;
};

function VendorForm({ initial, onSave, onCancel }: FormProps) {
  const isEdit = !!initial;
  const [values, setValues] = useState<VendorFormValues>({
    vendor_name: initial?.vendor_name ?? "",
    contact_name: initial?.contact_name ?? "",
    email: initial?.email ?? "",
    phone: initial?.phone ?? "",
    address_1: initial?.address_1 ?? "",
    address_2: initial?.address_2 ?? "",
    city: initial?.city ?? "",
    state: initial?.state ?? "",
    postal_code: initial?.postal_code ?? "",
    notes: initial?.notes ?? "",
    active_flag: initial?.active_flag ?? 1,
  });
  const [errors, setErrors] = useState<Partial<Record<string, string>>>({});
  const [saving, setSaving] = useState(false);

  const set = <K extends keyof VendorFormValues>(k: K, v: VendorFormValues[K]) =>
    setValues((p) => ({ ...p, [k]: v }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const result = VendorFormSchema.safeParse(values);
    if (!result.success) {
      const errs: typeof errors = {};
      for (const issue of result.error.issues) errs[String(issue.path[0])] = issue.message;
      setErrors(errs);
      return;
    }
    setSaving(true);
    try { await onSave(result.data); } finally { setSaving(false); }
  }

  const inp = (label: string, field: keyof VendorFormValues, opts?: { placeholder?: string; type?: string; required?: boolean }) => (
    <div>
      <label className="block text-xs font-medium text-gray-700 mb-1">
        {label}{opts?.required && <span className="text-red-500 ml-0.5">*</span>}
      </label>
      <input
        type={opts?.type ?? "text"}
        value={String(values[field] ?? "")}
        onChange={(e) => set(field, e.target.value as VendorFormValues[typeof field])}
        placeholder={opts?.placeholder}
        className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      {errors[field] && <p className="mt-1 text-xs text-red-600">{errors[field]}</p>}
    </div>
  );

  return (
    <form onSubmit={handleSubmit} className="space-y-4 max-h-[70vh] overflow-y-auto pr-1">
      {inp("Vendor Name", "vendor_name", { required: true, placeholder: "e.g. Acme Landscaping" })}

      <div className="grid grid-cols-2 gap-4">
        {inp("Contact Name", "contact_name")}
        {inp("Phone", "phone", { type: "tel", placeholder: "555-555-5555" })}
      </div>

      {inp("Email", "email", { type: "email", placeholder: "billing@vendor.com" })}

      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide pt-1">Address</p>
      {inp("Address Line 1", "address_1")}
      {inp("Address Line 2", "address_2")}
      <div className="grid grid-cols-3 gap-3">
        <div className="col-span-1">{inp("City", "city")}</div>
        <div>{inp("State", "state", { placeholder: "CO" })}</div>
        <div>{inp("Zip", "postal_code")}</div>
      </div>

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
          {saving ? "Saving…" : isEdit ? "Save Changes" : "Add Vendor"}
        </button>
      </div>
    </form>
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

type ModalState = { mode: "add" } | { mode: "edit"; vendor: Vendor } | null;

export function VendorsScreen() {
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalState>(null);
  const [showInactive, setShowInactive] = useState(false);

  const load = useCallback(async () => {
    try { setVendors(await listVendors(false)); }
    catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function handleSave(values: VendorFormValues) {
    if (modal?.mode === "edit") {
      await updateVendor(modal.vendor.id, values);
    } else {
      await insertVendor(values);
    }
    setModal(null);
    await load();
  }

  async function handleDelete(vendor: Vendor) {
    if (await hasBills(vendor.id)) {
      alert("This vendor has bills on record. Mark them inactive instead of deleting.");
      return;
    }
    if (!confirm(`Delete "${vendor.vendor_name}"? This cannot be undone.`)) return;
    try { await deleteVendor(vendor.id); await load(); }
    catch (e) { alert(String(e)); }
  }

  const visible = showInactive ? vendors : vendors.filter((v) => v.active_flag);
  const inactiveCount = vendors.filter((v) => !v.active_flag).length;

  return (
    <div className="p-8 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Vendors</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {vendors.filter((v) => v.active_flag).length} active
            {inactiveCount > 0 && ` · ${inactiveCount} inactive`}
          </p>
        </div>
        <div className="flex items-center gap-4">
          {inactiveCount > 0 && (
            <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
              <input
                type="checkbox"
                checked={showInactive}
                onChange={(e) => setShowInactive(e.target.checked)}
                className="rounded"
              />
              Show inactive
            </label>
          )}
          <button
            onClick={() => setModal({ mode: "add" })}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
          >
            + Add Vendor
          </button>
        </div>
      </div>

      {loading && <p className="text-gray-400 text-sm">Loading…</p>}
      {error && <p className="text-red-600 text-sm">{error}</p>}

      {!loading && !error && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Vendor</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Contact</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Phone</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Email</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">City / State</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Status</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {visible.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-gray-400 text-sm">
                    No vendors yet. Click "Add Vendor" to get started.
                  </td>
                </tr>
              )}
              {visible.map((v) => (
                <tr key={v.id} className={v.active_flag ? "" : "opacity-50"}>
                  <td className="px-4 py-3 font-medium text-gray-900">{v.vendor_name}</td>
                  <td className="px-4 py-3 text-gray-600 text-xs">{v.contact_name ?? "—"}</td>
                  <td className="px-4 py-3 text-gray-600 text-xs">{v.phone ?? "—"}</td>
                  <td className="px-4 py-3 text-gray-600 text-xs">{v.email ?? "—"}</td>
                  <td className="px-4 py-3 text-gray-600 text-xs">
                    {[v.city, v.state].filter(Boolean).join(", ") || "—"}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      v.active_flag ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"
                    }`}>
                      {v.active_flag ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right space-x-2 whitespace-nowrap">
                    <button onClick={() => setModal({ mode: "edit", vendor: v })} className="text-xs text-blue-600 hover:underline">Edit</button>
                    <button onClick={() => handleDelete(v)} className="text-xs text-red-500 hover:underline">Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modal && (
        <Modal
          title={modal.mode === "add" ? "Add Vendor" : `Edit — ${modal.mode === "edit" ? modal.vendor.vendor_name : ""}`}
          onClose={() => setModal(null)}
        >
          {modal.mode === "edit" ? (
            <VendorForm initial={modal.vendor} onSave={handleSave} onCancel={() => setModal(null)} />
          ) : (
            <VendorForm onSave={handleSave} onCancel={() => setModal(null)} />
          )}
        </Modal>
      )}
    </div>
  );
}
