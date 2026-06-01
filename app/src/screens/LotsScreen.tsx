import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Modal } from "../components/Modal";
import { listLots, insertLot, updateLot, deleteLot, hasCurrentOwners } from "../repositories/lotRepo";
import { LotFormSchema, type LotWithOwner, type LotFormValues } from "../types/lot";

// ── Form ─────────────────────────────────────────────────────────────────────

type FormProps = {
  initial?: LotWithOwner;
  onSave: (v: LotFormValues) => Promise<void>;
  onCancel: () => void;
};

export function LotForm({ initial, onSave, onCancel }: FormProps) {
  const isEdit = !!initial;
  const [values, setValues] = useState<LotFormValues>({
    lot_number: initial?.lot_number ?? "",
    street_address_1: initial?.street_address_1 ?? "",
    street_address_2: initial?.street_address_2 ?? "",
    city: initial?.city ?? "",
    state: initial?.state ?? "",
    postal_code: initial?.postal_code ?? "",
    legal_description: initial?.legal_description ?? "",
    active_flag: initial?.active_flag ?? 1,
  });
  const [errors, setErrors] = useState<Partial<Record<string, string>>>({});
  const [saving, setSaving] = useState(false);

  const set = <K extends keyof LotFormValues>(k: K, v: LotFormValues[K]) =>
    setValues((p) => ({ ...p, [k]: v }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const result = LotFormSchema.safeParse(values);
    if (!result.success) {
      const errs: typeof errors = {};
      for (const issue of result.error.issues) errs[String(issue.path[0])] = issue.message;
      setErrors(errs);
      return;
    }
    setSaving(true);
    try { await onSave(result.data); } finally { setSaving(false); }
  }

  const inp = (label: string, field: keyof LotFormValues, placeholder?: string) => (
    <div>
      <label className="block text-xs font-medium text-gray-700 mb-1">{label}</label>
      <input
        value={String(values[field] ?? "")}
        onChange={(e) => set(field, e.target.value as LotFormValues[typeof field])}
        placeholder={placeholder}
        disabled={field === "lot_number" && isEdit}
        className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
      />
      {errors[field] && <p className="mt-1 text-xs text-red-600">{errors[field]}</p>}
    </div>
  );

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {inp("Lot Number *", "lot_number", "e.g. 42")}
      {inp("Street Address", "street_address_1", "123 Main St")}
      {inp("Address Line 2", "street_address_2")}
      <div className="grid grid-cols-3 gap-3">
        <div className="col-span-1">{inp("City", "city")}</div>
        <div>{inp("State", "state", "CO")}</div>
        <div>{inp("Zip", "postal_code", "80302")}</div>
      </div>
      {inp("Legal Description", "legal_description")}
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
      <div className="flex justify-end gap-3 pt-2 border-t">
        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : isEdit ? "Save Changes" : "Add Lot"}
        </button>
      </div>
    </form>
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

type ModalState = { mode: "add" } | { mode: "edit"; lot: LotWithOwner } | null;

export function LotsScreen() {
  const navigate = useNavigate();
  const [lots, setLots] = useState<LotWithOwner[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalState>(null);

  const load = useCallback(async () => {
    try { setLots(await listLots()); }
    catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function handleSave(values: LotFormValues) {
    if (modal?.mode === "edit") {
      await updateLot(modal.lot.id, values);
    } else {
      await insertLot(values);
    }
    setModal(null);
    await load();
  }

  async function handleDelete(lot: LotWithOwner) {
    if (await hasCurrentOwners(lot.id)) {
      alert("Cannot delete a lot with current owners. Transfer or end ownership first.");
      return;
    }
    if (!confirm(`Delete lot ${lot.lot_number}? This cannot be undone.`)) return;
    try { await deleteLot(lot.id); await load(); }
    catch (e) { alert(String(e)); }
  }

  const active = lots.filter((l) => l.active_flag);
  const inactive = lots.filter((l) => !l.active_flag);

  return (
    <div className="p-8 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Lots</h1>
          <p className="text-sm text-gray-500 mt-0.5">{active.length} active · {inactive.length} inactive</p>
        </div>
        <button
          onClick={() => setModal({ mode: "add" })}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
        >
          + Add Lot
        </button>
      </div>

      {loading && <p className="text-gray-400 text-sm">Loading…</p>}
      {error && <p className="text-red-600 text-sm">{error}</p>}

      {!loading && !error && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Lot #</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Address</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">City / State</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Current Owner(s)</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Status</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {lots.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-gray-400 text-sm">
                    No lots yet. Click "Add Lot" to get started.
                  </td>
                </tr>
              )}
              {lots.map((lot) => (
                <tr key={lot.id} className={lot.active_flag ? "" : "opacity-50"}>
                  <td className="px-4 py-2 font-semibold text-blue-600 hover:underline cursor-pointer" onClick={() => navigate(`/lots/${lot.id}`)}>{lot.lot_number}</td>
                  <td className="px-4 py-2 text-gray-700">
                    {lot.street_address_1 ?? <span className="text-gray-300">—</span>}
                    {lot.street_address_2 && <span className="block text-xs text-gray-400">{lot.street_address_2}</span>}
                  </td>
                  <td className="px-4 py-2 text-gray-600 text-xs">
                    {[lot.city, lot.state, lot.postal_code].filter(Boolean).join(", ") || "—"}
                  </td>
                  <td className="px-4 py-2 text-gray-600 text-sm">
                    {lot.owner_names ?? <span className="text-gray-300 italic">Unassigned</span>}
                  </td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${lot.active_flag ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"}`}>
                      {lot.active_flag ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right space-x-2">
                    <button onClick={() => setModal({ mode: "edit", lot })} className="text-xs text-blue-600 hover:underline">Edit</button>
                    <button onClick={() => handleDelete(lot)} className="text-xs text-red-500 hover:underline">Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modal && (
        <Modal
          title={modal.mode === "add" ? "Add Lot" : `Edit Lot ${modal.mode === "edit" ? modal.lot.lot_number : ""}`}
          onClose={() => setModal(null)}
        >
          {modal.mode === "edit" ? (
            <LotForm initial={modal.lot} onSave={handleSave} onCancel={() => setModal(null)} />
          ) : (
            <LotForm onSave={handleSave} onCancel={() => setModal(null)} />
          )}
        </Modal>
      )}
    </div>
  );
}
