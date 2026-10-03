import { useEffect, useState, useCallback, useMemo } from "react";
import { Modal } from "../components/Modal";
import { PageLayout } from "../components/PageLayout";
import {
  listPayments,
  insertPayment,
  deletePayment,
  type PaymentRow,
} from "../repositories/depositRepo";
import { listLots } from "../repositories/lotRepo";
import {
  PaymentFormSchema,
  PAYMENT_TYPE_LABELS,
  type PaymentFormValues,
  type PaymentTypeValue,
} from "../types/deposit";
import type { LotWithOwner } from "../types/lot";
import { appConfirm } from "../components/AppDialogs";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

// ── Payment Form ──────────────────────────────────────────────────────────────

function PaymentForm({ lots, onSave, onCancel }: {
  lots: LotWithOwner[];
  onSave: (v: PaymentFormValues) => Promise<void>;
  onCancel: () => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const [values, setValues] = useState<PaymentFormValues>({
    lot_id: 0,
    payment_date: today,
    amount: 0,
    payment_method: "CHECK",
    payment_type: "DUES",
  });
  const [errors, setErrors] = useState<Partial<Record<string, string>>>({});
  const [saving, setSaving] = useState(false);

  const set = <K extends keyof PaymentFormValues>(k: K, v: PaymentFormValues[K]) =>
    setValues((p) => ({ ...p, [k]: v }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const result = PaymentFormSchema.safeParse(values);
    if (!result.success) {
      const errs: typeof errors = {};
      for (const issue of result.error.issues) errs[String(issue.path[0])] = issue.message;
      setErrors(errs);
      return;
    }
    setSaving(true);
    try { await onSave(result.data); } finally { setSaving(false); }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Lot <span className="text-red-500">*</span></label>
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

      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Payment Type <span className="text-red-500">*</span></label>
        <select
          value={values.payment_type}
          onChange={(e) => set("payment_type", e.target.value as PaymentTypeValue)}
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {(Object.entries(PAYMENT_TYPE_LABELS) as [PaymentTypeValue, string][]).map(([k, label]) => (
            <option key={k} value={k}>{label}</option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Payment Date <span className="text-red-500">*</span></label>
          <input
            type="date" value={values.payment_date}
            onChange={(e) => set("payment_date", e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Amount <span className="text-red-500">*</span></label>
          <input
            type="number" step="0.01" min="0.01" value={values.amount || ""}
            onChange={(e) => set("amount", Number(e.target.value))}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          {errors["amount"] && <p className="mt-1 text-xs text-red-600">{errors["amount"]}</p>}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Method</label>
          <select
            value={values.payment_method}
            onChange={(e) => set("payment_method", e.target.value as PaymentFormValues["payment_method"])}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {(["CHECK", "ACH", "ONLINE", "CASH", "OTHER"] as const).map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Check #</label>
          <input
            type="text" value={values.check_number ?? ""}
            onChange={(e) => set("check_number", e.target.value || undefined)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Memo</label>
        <input
          type="text" value={values.memo ?? ""}
          onChange={(e) => set("memo", e.target.value || undefined)}
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      <div className="flex justify-end gap-3 pt-2 border-t">
        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">
          Cancel
        </button>
        <button
          type="submit" disabled={saving}
          className="px-4 py-2 text-sm text-white rounded disabled:opacity-50"
          style={{ backgroundColor: "#2f6046" }}
        >
          {saving ? "Saving…" : "Save Payment"}
        </button>
      </div>
    </form>
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

type SortKey = "payment_date" | "lot_number" | "owner_name" | "payment_type" | "payment_method" | "amount" | "deposit_batch_id";

export function PaymentsScreen() {
  const [rows, setRows]       = useState<PaymentRow[]>([]);
  const [lots, setLots]       = useState<LotWithOwner[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [limit, setLimit]     = useState(200);

  const [sortKey, setSortKey] = useState<SortKey>("payment_date");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const [fDate, setFDate]     = useState("");
  const [fLot, setFLot]       = useState("");
  const [fOwner, setFOwner]   = useState("");
  const [fType, setFType]     = useState("");
  const [fMethod, setFMethod] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [p, l] = await Promise.all([listPayments(limit), listLots(true)]);
      setRows(p);
      setLots(l);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [limit]);

  useEffect(() => { void load(); }, [load]);

  function handleSort(key: SortKey) {
    if (key === sortKey) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(key); setSortDir(key === "amount" ? "desc" : "asc"); }
  }

  async function handleSave(values: PaymentFormValues) {
    await insertPayment(null, values);
    setShowForm(false);
    await load();
  }

  async function handleDelete(p: PaymentRow) {
    const batchLabel = p.deposit_batch_id ? ` (will be removed from deposit batch #${p.deposit_batch_id})` : "";
    if (!await appConfirm(`Delete this payment?${batchLabel}`)) return;
    await deletePayment(p.id, p.deposit_batch_id ?? null);
    await load();
  }

  const visible = useMemo(() => {
    let out = rows;
    if (fDate)   { const q = fDate.trim();   out = out.filter((r) => r.payment_date.includes(q)); }
    if (fLot)    { const q = fLot.trim().toLowerCase();   out = out.filter((r) => (r.lot_number ?? "").toLowerCase().includes(q)); }
    if (fOwner)  { const q = fOwner.trim().toLowerCase();  out = out.filter((r) => (r.owner_name ?? "").toLowerCase().includes(q)); }
    if (fType)   { const q = fType.trim().toLowerCase();   out = out.filter((r) => (PAYMENT_TYPE_LABELS[r.payment_type as PaymentTypeValue] ?? r.payment_type).toLowerCase().includes(q)); }
    if (fMethod) { const q = fMethod.trim().toLowerCase(); out = out.filter((r) => r.payment_method.toLowerCase().includes(q)); }

    return [...out].sort((a, b) => {
      const av = sortKey === "deposit_batch_id"
        ? (a.deposit_batch_id ?? -1)
        : sortKey === "amount"
          ? a.amount
          : String(a[sortKey] ?? "");
      const bv = sortKey === "deposit_batch_id"
        ? (b.deposit_batch_id ?? -1)
        : sortKey === "amount"
          ? b.amount
          : String(b[sortKey] ?? "");
      const cmp = typeof av === "number" && typeof bv === "number"
        ? av - bv
        : String(av).localeCompare(String(bv));
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [rows, fDate, fLot, fOwner, fType, fMethod, sortKey, sortDir]);

  const hasFilters = fDate || fLot || fOwner || fType || fMethod;

  function SortTh({ col, label, right }: { col: SortKey; label: string; right?: boolean }) {
    const active = sortKey === col;
    return (
      <th
        className={`px-3 py-2 text-xs font-medium text-gray-600 cursor-pointer select-none whitespace-nowrap ${right ? "text-right" : "text-left"}`}
        onClick={() => handleSort(col)}
      >
        {label} <span className="text-gray-400">{active ? (sortDir === "asc" ? "▲" : "▼") : "⇅"}</span>
      </th>
    );
  }

  function Fi({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
    return (
      <input
        type="text" value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder ?? "Filter…"}
        className="w-full border border-gray-200 rounded px-1.5 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white"
      />
    );
  }

  return (
    <PageLayout
      title="Payments"
      subtitle="All owner payments. Record individual payments here; assign to a deposit batch on the Deposits screen."
      helpId="payments"
      actions={
        <div className="flex items-center gap-2">
          {hasFilters && (
            <button
              onClick={() => { setFDate(""); setFLot(""); setFOwner(""); setFType(""); setFMethod(""); }}
              className="text-xs px-2 py-1.5 rounded border border-gray-300 text-gray-600 hover:bg-gray-50"
            >
              Clear filters
            </button>
          )}
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value={100}>Last 100</option>
            <option value={200}>Last 200</option>
            <option value={500}>Last 500</option>
            <option value={9999}>All</option>
          </select>
          <button
            onClick={() => setShowForm(true)}
            className="px-4 py-2 text-sm text-white rounded-lg"
            style={{ backgroundColor: "#2f6046" }}
          >
            + New Payment
          </button>
        </div>
      }
    >
      <div>
        {loading && <p className="text-sm text-gray-400">Loading…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}

        {!loading && !error && (
          <>
            <p className="text-xs text-gray-500 mb-2">
              {visible.length === rows.length
                ? `${rows.length} payments`
                : `${visible.length} of ${rows.length} payments`}
            </p>
            <div className="border rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b">
                  <tr>
                    <SortTh col="payment_date"    label="Date" />
                    <SortTh col="lot_number"      label="Lot" />
                    <SortTh col="owner_name"      label="Owner" />
                    <SortTh col="payment_type"    label="Type" />
                    <SortTh col="payment_method"  label="Method" />
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-600">Check #</th>
                    <SortTh col="deposit_batch_id" label="Deposit" />
                    <SortTh col="amount" label="Amount" right />
                    <th className="px-3 py-2 w-8" />
                  </tr>
                  <tr className="bg-gray-50 border-b border-gray-200">
                    <td className="px-2 py-1"><Fi value={fDate}   onChange={setFDate}   placeholder="2026-01…" /></td>
                    <td className="px-2 py-1"><Fi value={fLot}    onChange={setFLot}    placeholder="4207…" /></td>
                    <td className="px-2 py-1"><Fi value={fOwner}  onChange={setFOwner}  /></td>
                    <td className="px-2 py-1"><Fi value={fType}   onChange={setFType}   placeholder="Dues…" /></td>
                    <td className="px-2 py-1"><Fi value={fMethod} onChange={setFMethod} placeholder="CHECK…" /></td>
                    <td className="px-2 py-1" />
                    <td className="px-2 py-1" />
                    <td className="px-2 py-1" />
                    <td className="px-2 py-1" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {visible.length === 0 && (
                    <tr>
                      <td colSpan={9} className="px-4 py-6 text-center text-gray-400 text-sm">
                        {hasFilters ? "No matches." : "No payments yet."}
                      </td>
                    </tr>
                  )}
                  {visible.map((p) => (
                    <tr key={p.id} className="hover:bg-gray-50">
                      <td className="px-3 py-1.5 font-mono text-xs text-gray-600">{p.payment_date}</td>
                      <td className="px-3 py-1.5 text-xs font-medium text-gray-800">Lot {p.lot_number}</td>
                      <td className="px-3 py-1.5 text-xs text-gray-600">{p.owner_name ?? "—"}</td>
                      <td className="px-3 py-1.5 text-xs text-gray-600">
                        {PAYMENT_TYPE_LABELS[p.payment_type as PaymentTypeValue] ?? p.payment_type}
                      </td>
                      <td className="px-3 py-1.5 text-xs text-gray-500">{p.payment_method}</td>
                      <td className="px-3 py-1.5 text-xs text-gray-500">{p.check_number ?? "—"}</td>
                      <td className="px-3 py-1.5 text-xs">
                        {p.deposit_batch_id
                          ? <span className="px-1.5 py-0.5 rounded bg-green-100 text-green-700 text-xs">Batch #{p.deposit_batch_id}</span>
                          : <span className="px-1.5 py-0.5 rounded bg-orange-100 text-orange-700 text-xs">Unassigned</span>
                        }
                      </td>
                      <td className="px-3 py-1.5 text-right font-mono text-xs text-green-700 font-semibold">{fmt(p.amount)}</td>
                      <td className="px-3 py-1.5 text-center">
                        <button
                          onClick={() => void handleDelete(p)}
                          className="text-red-400 hover:text-red-600 text-xs"
                          title="Delete payment"
                        >
                          ✕
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
                {visible.length > 0 && (
                  <tfoot className="bg-gray-50 border-t">
                    <tr>
                      <td colSpan={7} className="px-3 py-2 text-xs text-gray-500">{visible.length} payments</td>
                      <td className="px-3 py-2 text-right font-mono font-semibold text-gray-800 text-xs">
                        {fmt(visible.reduce((s, r) => s + r.amount, 0))}
                      </td>
                      <td />
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          </>
        )}
      </div>

      {showForm && (
        <Modal title="New Payment" onClose={() => setShowForm(false)}>
          <PaymentForm lots={lots} onSave={handleSave} onCancel={() => setShowForm(false)} />
        </Modal>
      )}
    </PageLayout>
  );
}
