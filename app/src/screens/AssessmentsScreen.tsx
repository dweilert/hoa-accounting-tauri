import { useEffect, useState, useCallback } from "react";
import { Modal } from "../components/Modal";
import { PageLayout } from "../components/PageLayout";
import {
  listAssessments,
  insertAssessment,
  updateAssessment,
  voidAssessment,
  writeOffAssessment,
  type AssessmentRow,
} from "../repositories/assessmentRepo";
import { listLots } from "../repositories/lotRepo";
import { listOwners } from "../repositories/ownerRepo";
import { listCategories } from "../repositories/categoryRepo";
import {
  AssessmentFormSchema,
  CHARGE_TYPE_LABELS,
  STATUS_COLORS,
  type AssessmentFormValues,
  type AssessmentStatusValue,
} from "../types/assessment";
import type { Lot } from "../types/lot";
import type { Owner } from "../types/owner";
import type { Category } from "../types/category";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

// ── Form ──────────────────────────────────────────────────────────────────────

type FormProps = {
  initial?: AssessmentRow;
  lots: Lot[];
  owners: Owner[];
  categories: Category[];
  onSave: (v: AssessmentFormValues) => Promise<void>;
  onCancel: () => void;
};

function AssessmentForm({ initial, lots, owners, categories, onSave, onCancel }: FormProps) {
  const today = new Date().toISOString().slice(0, 10);
  const [values, setValues] = useState<AssessmentFormValues>({
    lot_id: initial?.lot_id ?? 0,
    owner_id: initial?.owner_id ?? undefined,
    charge_type: initial?.charge_type ?? "DUES",
    amount: initial?.amount ?? 0,
    assessment_date: initial?.assessment_date ?? today,
    due_date: initial?.due_date ?? undefined,
    description: initial?.description ?? undefined,
    category_id: initial?.category_id ?? undefined,
  });
  const [errors, setErrors] = useState<Partial<Record<string, string>>>({});
  const [saving, setSaving] = useState(false);

  const set = <K extends keyof AssessmentFormValues>(k: K, v: AssessmentFormValues[K]) =>
    setValues((p) => ({ ...p, [k]: v }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const result = AssessmentFormSchema.safeParse(values);
    if (!result.success) {
      const errs: typeof errors = {};
      for (const issue of result.error.issues) errs[String(issue.path[0])] = issue.message;
      setErrors(errs);
      return;
    }
    setSaving(true);
    try { await onSave(result.data); } finally { setSaving(false); }
  }

  const expenseCategories = categories.filter((c) => c.category_type === "EXPENSE" || c.category_type === "INCOME");

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">
          Lot <span className="text-red-500">*</span>
        </label>
        <select
          value={values.lot_id}
          onChange={(e) => set("lot_id", Number(e.target.value))}
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value={0}>— Select lot —</option>
          {lots.map((l) => (
            <option key={l.id} value={l.id}>
              Lot {l.lot_number}{l.street_address_1 ? ` — ${l.street_address_1}` : ""}
            </option>
          ))}
        </select>
        {errors["lot_id"] && <p className="mt-1 text-xs text-red-600">{errors["lot_id"]}</p>}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">
            Charge Type <span className="text-red-500">*</span>
          </label>
          <select
            value={values.charge_type}
            onChange={(e) => set("charge_type", e.target.value as AssessmentFormValues["charge_type"])}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {Object.entries(CHARGE_TYPE_LABELS).map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">
            Amount <span className="text-red-500">*</span>
          </label>
          <input
            type="number"
            step="0.01"
            min="0.01"
            value={values.amount}
            onChange={(e) => set("amount", Number(e.target.value))}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          {errors["amount"] && <p className="mt-1 text-xs text-red-600">{errors["amount"]}</p>}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">
            Assessment Date <span className="text-red-500">*</span>
          </label>
          <input
            type="date"
            value={values.assessment_date}
            onChange={(e) => set("assessment_date", e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          {errors["assessment_date"] && <p className="mt-1 text-xs text-red-600">{errors["assessment_date"]}</p>}
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Due Date</label>
          <input
            type="date"
            value={values.due_date ?? ""}
            onChange={(e) => set("due_date", e.target.value || undefined)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Description</label>
        <input
          type="text"
          value={values.description ?? ""}
          onChange={(e) => set("description", e.target.value || undefined)}
          placeholder="e.g. 2026 Annual Dues Q1"
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Owner (optional)</label>
          <select
            value={values.owner_id ?? ""}
            onChange={(e) => set("owner_id", e.target.value ? Number(e.target.value) : undefined)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">— Auto from lot —</option>
            {owners.map((o) => (
              <option key={o.id} value={o.id}>{o.display_name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Category</label>
          <select
            value={values.category_id ?? ""}
            onChange={(e) => set("category_id", e.target.value ? Number(e.target.value) : undefined)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">— None —</option>
            {expenseCategories.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex justify-end gap-3 pt-2 border-t">
        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : initial ? "Save Changes" : "Add Assessment"}
        </button>
      </div>
    </form>
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

type ModalState =
  | { mode: "add" }
  | { mode: "edit"; assessment: AssessmentRow }
  | null;

const STATUS_FILTERS: { label: string; value: string }[] = [
  { label: "Open & Partial", value: "open" },
  { label: "Open", value: "OPEN" },
  { label: "Partial", value: "PARTIAL" },
  { label: "Paid", value: "PAID" },
  { label: "Void", value: "VOID" },
  { label: "All", value: "all" },
];

export function AssessmentsScreen() {
  const [assessments, setAssessments] = useState<AssessmentRow[]>([]);
  const [lots, setLots] = useState<Lot[]>([]);
  const [owners, setOwners] = useState<Owner[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalState>(null);
  const [statusFilter, setStatusFilter] = useState("open");

  const load = useCallback(async () => {
    try {
      const opts = statusFilter === "open"
        ? undefined
        : statusFilter === "all"
        ? { limit: 200 }
        : { status: statusFilter };
      const [a, l, o, c] = await Promise.all([
        listAssessments(opts),
        listLots(true),
        listOwners(true),
        listCategories(),
      ]);
      setAssessments(a);
      setLots(l);
      setOwners(o);
      setCategories(c);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => { void load(); }, [load]);

  async function handleSave(values: AssessmentFormValues) {
    if (modal?.mode === "edit") {
      await updateAssessment(modal.assessment.id, values);
    } else {
      await insertAssessment(values);
    }
    setModal(null);
    await load();
  }

  async function handleVoid(a: AssessmentRow) {
    if (!confirm(`Void assessment for Lot ${a.lot_number} — ${fmt(a.amount)}?`)) return;
    try { await voidAssessment(a.id); await load(); }
    catch (e) { alert(String(e)); }
  }

  async function handleWriteOff(a: AssessmentRow) {
    if (!confirm(`Write off assessment for Lot ${a.lot_number} — ${fmt(a.amount)}? This marks it uncollectible.`)) return;
    try { await writeOffAssessment(a.id); await load(); }
    catch (e) { alert(String(e)); }
  }

  const displayedList = statusFilter === "open"
    ? assessments.filter((a) => a.status === "OPEN" || a.status === "PARTIAL")
    : assessments;

  return (
    <PageLayout
      title="Assessments"
      subtitle="Lot charges — dues, fees, and special assessments."
      helpId="assessments"
      actions={
        <div className="flex items-center gap-3">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {STATUS_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>{f.label}</option>
            ))}
          </select>
          <button
            onClick={() => setModal({ mode: "add" })}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
          >
            + Add Assessment
          </button>
        </div>
      }
    >
    <div className="max-w-5xl">

      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {!loading && !error && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Date</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Lot</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Owner</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Type</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Due</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Status</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {displayedList.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-6 text-center text-gray-400 text-sm">
                    No assessments found.
                  </td>
                </tr>
              )}
              {displayedList.map((a) => {
                const canEdit = a.status === "OPEN" || a.status === "PARTIAL";
                return (
                  <tr key={a.id} className={a.status === "VOID" || a.status === "WRITTEN_OFF" ? "opacity-50" : ""}>
                    <td className="px-4 py-3 text-gray-600">{a.assessment_date}</td>
                    <td className="px-4 py-3 font-medium text-gray-900">Lot {a.lot_number}</td>
                    <td className="px-4 py-3 text-gray-600 text-xs">{a.owner_name ?? "—"}</td>
                    <td className="px-4 py-3 text-gray-600 text-xs">{CHARGE_TYPE_LABELS[a.charge_type]}</td>
                    <td className="px-4 py-3 text-right font-mono text-gray-700">{fmt(a.amount)}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs">{a.due_date ?? "—"}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[a.status as AssessmentStatusValue]}`}>
                        {a.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right whitespace-nowrap space-x-2">
                      {canEdit && (
                        <button
                          onClick={() => setModal({ mode: "edit", assessment: a })}
                          className="text-xs text-blue-600 hover:underline"
                        >
                          Edit
                        </button>
                      )}
                      {canEdit && (
                        <button
                          onClick={() => void handleVoid(a)}
                          className="text-xs text-gray-500 hover:underline"
                        >
                          Void
                        </button>
                      )}
                      {canEdit && (
                        <button
                          onClick={() => void handleWriteOff(a)}
                          className="text-xs text-red-500 hover:underline"
                        >
                          Write off
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {modal && (
        <Modal
          title={modal.mode === "add" ? "Add Assessment" : `Edit Assessment`}
          onClose={() => setModal(null)}
        >
          {modal.mode === "edit" ? (
            <AssessmentForm
              initial={modal.assessment}
              lots={lots}
              owners={owners}
              categories={categories}
              onSave={handleSave}
              onCancel={() => setModal(null)}
            />
          ) : (
            <AssessmentForm
              lots={lots}
              owners={owners}
              categories={categories}
              onSave={handleSave}
              onCancel={() => setModal(null)}
            />
          )}
        </Modal>
      )}
    </div>
    </PageLayout>
  );
}
