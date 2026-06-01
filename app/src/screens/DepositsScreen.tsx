import { useEffect, useState, useCallback } from "react";
import { Modal } from "../components/Modal";
import {
  listDepositBatches,
  listPaymentsForBatch,
  insertDepositBatch,
  insertPayment,
  deletePayment,
  postDepositBatch,
  type PaymentRow,
} from "../repositories/depositRepo";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import { listLots } from "../repositories/lotRepo";
import { listOwners } from "../repositories/ownerRepo";
import { PaymentFormSchema, type PaymentFormValues } from "../types/deposit";
import type { BankAccount } from "../types/bankAccount";
import type { Lot } from "../types/lot";
import type { Owner } from "../types/owner";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

type BatchRow = { id: number; deposit_date: string; account_name: string; total_amount: number; check_count: number; notes: string | null; status: string };

// ── Add Payment Form ──────────────────────────────────────────────────────────

type PaymentFormProps = {
  lots: Lot[];
  owners: Owner[];
  onSave: (v: PaymentFormValues) => Promise<void>;
  onCancel: () => void;
};

function PaymentForm({ lots, owners, onSave, onCancel }: PaymentFormProps) {
  const today = new Date().toISOString().slice(0, 10);
  const [values, setValues] = useState<PaymentFormValues>({
    lot_id: 0,
    payment_date: today,
    amount: 0,
    payment_method: "CHECK",
    check_number: undefined,
    memo: undefined,
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
            <option key={l.id} value={l.id}>Lot {l.lot_number}{l.street_address_1 ? ` — ${l.street_address_1}` : ""}</option>
          ))}
        </select>
        {errors["lot_id"] && <p className="mt-1 text-xs text-red-600">{errors["lot_id"]}</p>}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Payment Date <span className="text-red-500">*</span></label>
          <input
            type="date"
            value={values.payment_date}
            onChange={(e) => set("payment_date", e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Amount <span className="text-red-500">*</span></label>
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
            type="text"
            value={values.check_number ?? ""}
            onChange={(e) => set("check_number", e.target.value || undefined)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Owner (optional)</label>
        <select
          value={values.owner_id ?? ""}
          onChange={(e) => set("owner_id", e.target.value ? Number(e.target.value) : undefined)}
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">— Auto from lot —</option>
          {owners.map((o) => <option key={o.id} value={o.id}>{o.display_name}</option>)}
        </select>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Memo</label>
        <input
          type="text"
          value={values.memo ?? ""}
          onChange={(e) => set("memo", e.target.value || undefined)}
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      <div className="flex justify-end gap-3 pt-2 border-t">
        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">Cancel</button>
        <button type="submit" disabled={saving} className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
          {saving ? "Saving…" : "Add Payment"}
        </button>
      </div>
    </form>
  );
}

// ── New Deposit Batch Form ────────────────────────────────────────────────────

function NewBatchForm({ accounts, onCreate, onCancel }: {
  accounts: BankAccount[];
  onCreate: (date: string, accountId: number, notes: string) => Promise<void>;
  onCancel: () => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate] = useState(today);
  const [accountId, setAccountId] = useState(accounts[0]?.id ?? 0);
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!accountId) return;
    setSaving(true);
    try { await onCreate(date, accountId, notes); } finally { setSaving(false); }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Deposit Date <span className="text-red-500">*</span></label>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Bank Account <span className="text-red-500">*</span></label>
          <select
            value={accountId}
            onChange={(e) => setAccountId(Number(e.target.value))}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
          </select>
        </div>
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Notes</label>
        <input
          type="text"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      <div className="flex justify-end gap-3 pt-2 border-t">
        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">Cancel</button>
        <button type="submit" disabled={saving} className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
          {saving ? "Creating…" : "Create Deposit"}
        </button>
      </div>
    </form>
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

type ModalState =
  | { mode: "newBatch" }
  | { mode: "addPayment"; batchId: number }
  | null;

export function DepositsScreen() {
  const [batches, setBatches] = useState<BatchRow[]>([]);
  const [payments, setPayments] = useState<Map<number, PaymentRow[]>>(new Map());
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [lots, setLots] = useState<Lot[]>([]);
  const [owners, setOwners] = useState<Owner[]>([]);
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalState>(null);

  const loadBatches = useCallback(async () => {
    const [b, l, o, a] = await Promise.all([
      listDepositBatches(),
      listLots(true),
      listOwners(true),
      listBankAccounts(true),
    ]);
    setBatches(b as BatchRow[]);
    setLots(l);
    setOwners(o);
    setAccounts(a);
    setLoading(false);
  }, []);

  useEffect(() => { void loadBatches().catch((e) => setError(String(e))); }, [loadBatches]);

  async function loadPaymentsForBatch(batchId: number) {
    const rows = await listPaymentsForBatch(batchId);
    setPayments((prev) => new Map(prev).set(batchId, rows));
  }

  async function toggle(batchId: number) {
    const next = new Set(expanded);
    if (next.has(batchId)) {
      next.delete(batchId);
    } else {
      next.add(batchId);
      if (!payments.has(batchId)) await loadPaymentsForBatch(batchId);
    }
    setExpanded(next);
  }

  async function handleCreateBatch(date: string, accountId: number, notes: string) {
    await insertDepositBatch(date, accountId, notes);
    setModal(null);
    await loadBatches();
  }

  async function handleAddPayment(batchId: number, values: PaymentFormValues) {
    await insertPayment(batchId, values);
    setModal(null);
    await loadBatches();
    await loadPaymentsForBatch(batchId);
  }

  async function handleDeletePayment(paymentId: number, batchId: number) {
    if (!confirm("Remove this payment?")) return;
    await deletePayment(paymentId, batchId);
    await loadBatches();
    await loadPaymentsForBatch(batchId);
  }

  async function handlePost(batchId: number) {
    if (!confirm("Post this deposit batch? It will be locked.")) return;
    await postDepositBatch(batchId);
    await loadBatches();
  }

  return (
    <div className="p-8 max-w-4xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Deposits</h1>
          <p className="text-sm text-gray-500 mt-0.5">{batches.length} deposit batches</p>
        </div>
        <button
          onClick={() => setModal({ mode: "newBatch" })}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
        >
          + New Deposit
        </button>
      </div>

      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {!loading && !error && batches.length === 0 && (
        <div className="border rounded-lg px-6 py-10 text-center text-gray-400 bg-white">
          No deposit batches yet. Click "New Deposit" to record owner payments.
        </div>
      )}

      {!loading && !error && (
        <div className="space-y-2">
          {batches.map((batch) => (
            <div key={batch.id} className="border rounded-lg bg-white overflow-hidden">
              <div className="flex items-center justify-between px-4 py-3">
                <button
                  onClick={() => void toggle(batch.id)}
                  className="flex items-center gap-3 text-left hover:opacity-80 flex-1"
                >
                  <span className="text-sm font-semibold text-gray-900">{batch.deposit_date}</span>
                  <span className="text-sm text-gray-500">{batch.account_name}</span>
                  <span className="text-xs text-gray-400">{batch.check_count} payment{batch.check_count !== 1 ? "s" : ""}</span>
                  {batch.notes && <span className="text-xs text-gray-400 italic">{batch.notes}</span>}
                </button>
                <div className="flex items-center gap-3">
                  <span className="font-mono font-semibold text-gray-900">{fmt(batch.total_amount)}</span>
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                    batch.status === "POSTED" ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"
                  }`}>
                    {batch.status}
                  </span>
                  {batch.status === "OPEN" && (
                    <>
                      <button
                        onClick={() => setModal({ mode: "addPayment", batchId: batch.id })}
                        className="text-xs text-blue-600 hover:underline"
                      >
                        + Payment
                      </button>
                      <button
                        onClick={() => void handlePost(batch.id)}
                        className="text-xs text-green-600 hover:underline"
                      >
                        Post
                      </button>
                    </>
                  )}
                  <span className="text-gray-400 text-xs">{expanded.has(batch.id) ? "▲" : "▼"}</span>
                </div>
              </div>

              {expanded.has(batch.id) && (
                <table className="w-full text-sm border-t">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-6 py-2 text-left text-xs font-medium text-gray-500">Date</th>
                      <th className="px-6 py-2 text-left text-xs font-medium text-gray-500">Lot</th>
                      <th className="px-6 py-2 text-left text-xs font-medium text-gray-500">Owner</th>
                      <th className="px-6 py-2 text-left text-xs font-medium text-gray-500">Method</th>
                      <th className="px-6 py-2 text-left text-xs font-medium text-gray-500">Check #</th>
                      <th className="px-6 py-2 text-right text-xs font-medium text-gray-500">Amount</th>
                      <th className="px-6 py-2" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {(payments.get(batch.id) ?? []).length === 0 && (
                      <tr>
                        <td colSpan={7} className="px-6 py-4 text-center text-gray-400 text-xs">
                          No payments in this batch.
                        </td>
                      </tr>
                    )}
                    {(payments.get(batch.id) ?? []).map((p) => (
                      <tr key={p.id}>
                        <td className="px-6 py-2 text-gray-600">{p.payment_date}</td>
                        <td className="px-6 py-2 font-medium text-gray-900">Lot {p.lot_number}</td>
                        <td className="px-6 py-2 text-gray-500 text-xs">{p.owner_name ?? "—"}</td>
                        <td className="px-6 py-2 text-gray-500 text-xs">{p.payment_method}</td>
                        <td className="px-6 py-2 text-gray-500 text-xs">{p.check_number ?? "—"}</td>
                        <td className="px-6 py-2 text-right font-mono text-gray-700">{fmt(p.amount)}</td>
                        <td className="px-6 py-2 text-right">
                          {batch.status === "OPEN" && (
                            <button
                              onClick={() => void handleDeletePayment(p.id, batch.id)}
                              className="text-xs text-red-500 hover:underline"
                            >
                              Remove
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))}
        </div>
      )}

      {modal?.mode === "newBatch" && (
        <Modal title="New Deposit Batch" onClose={() => setModal(null)}>
          <NewBatchForm
            accounts={accounts}
            onCreate={handleCreateBatch}
            onCancel={() => setModal(null)}
          />
        </Modal>
      )}

      {modal?.mode === "addPayment" && (
        <Modal title="Add Payment" onClose={() => setModal(null)}>
          <PaymentForm
            lots={lots}
            owners={owners}
            onSave={(v) => handleAddPayment(modal.batchId, v)}
            onCancel={() => setModal(null)}
          />
        </Modal>
      )}
    </div>
  );
}
