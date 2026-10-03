import { useEffect, useState, useCallback } from "react";
import { Modal } from "../components/Modal";
import { PageLayout } from "../components/PageLayout";
import {
  listDepositBatches,
  listPaymentsForBatch,
  listUnassignedPayments,
  insertDepositBatch,
  insertPayment,
  deletePayment,
  postDepositBatch,
  updateDepositBatch,
  assignPaymentsToBatch,
  unassignPaymentFromBatch,
  listCandidateBankTxns,
  linkDepositToTxn,
  unlinkDepositTxn,
  type PaymentRow,
  type OFXCandidate,
} from "../repositories/depositRepo";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import { listLots } from "../repositories/lotRepo";
import {
  PaymentFormSchema,
  PAYMENT_TYPE_LABELS,
  type PaymentFormValues,
  type PaymentTypeValue,
} from "../types/deposit";
import type { BankAccount } from "../types/bankAccount";
import type { LotWithOwner } from "../types/lot";
import { appConfirm } from "../components/AppDialogs";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

type BatchRow = {
  id: number;
  deposit_date: string;
  bank_account_id: number;
  account_name: string;
  total_amount: number;
  check_count: number;
  notes: string | null;
  status: string;
  bank_transaction_id: number | null;
};

type SortCol = "date" | "account" | "payments" | "total" | "status";

// ── Payment Form ──────────────────────────────────────────────────────────────

function PaymentForm({ lots, onSave, onCancel, initialValues }: {
  lots: LotWithOwner[];
  onSave: (v: PaymentFormValues) => Promise<void>;
  onCancel: () => void;
  initialValues?: Partial<PaymentFormValues>;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const [values, setValues] = useState<PaymentFormValues>({
    lot_id: 0,
    payment_date: today,
    amount: 0,
    payment_method: "CHECK",
    payment_type: "DUES",
    check_number: undefined,
    memo: undefined,
    ...initialValues,
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
          <input type="date" value={values.payment_date}
            onChange={(e) => set("payment_date", e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Amount <span className="text-red-500">*</span></label>
          <input type="number" step="0.01" min="0.01" value={values.amount || ""}
            onChange={(e) => set("amount", Number(e.target.value))}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          {errors["amount"] && <p className="mt-1 text-xs text-red-600">{errors["amount"]}</p>}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Method</label>
          <select value={values.payment_method}
            onChange={(e) => set("payment_method", e.target.value as PaymentFormValues["payment_method"])}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            {(["CHECK", "ACH", "ONLINE", "CASH", "OTHER"] as const).map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Check #</label>
          <input type="text" value={values.check_number ?? ""}
            onChange={(e) => set("check_number", e.target.value || undefined)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Memo</label>
        <input type="text" value={values.memo ?? ""}
          onChange={(e) => set("memo", e.target.value || undefined)}
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
      </div>

      <div className="flex justify-end gap-3 pt-2 border-t">
        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">Cancel</button>
        <button type="submit" disabled={saving} className="px-4 py-2 text-sm text-white rounded disabled:opacity-50" style={{ backgroundColor: "#2f6046" }}>
          {saving ? "Saving…" : "Save Payment"}
        </button>
      </div>
    </form>
  );
}

// ── Batch form ─────────────────────────────────────────────────────────────────

function BatchForm({ accounts, initial, onSave, onCancel, submitLabel }: {
  accounts: BankAccount[];
  initial?: { date: string; accountId: number; notes: string };
  onSave: (date: string, accountId: number, notes: string) => Promise<void>;
  onCancel: () => void;
  submitLabel: string;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate]         = useState(initial?.date ?? today);
  const [accountId, setAccountId] = useState(initial?.accountId ?? accounts[0]?.id ?? 0);
  const [notes, setNotes]       = useState(initial?.notes ?? "");
  const [saving, setSaving]     = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!accountId) return;
    setSaving(true);
    try { await onSave(date, accountId, notes); } finally { setSaving(false); }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Deposit Date <span className="text-red-500">*</span></label>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Bank Account <span className="text-red-500">*</span></label>
          <select value={accountId} onChange={(e) => setAccountId(Number(e.target.value))}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
          </select>
        </div>
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Notes</label>
        <input type="text" value={notes} onChange={(e) => setNotes(e.target.value)}
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
      </div>
      <div className="flex justify-end gap-3 pt-2 border-t">
        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">Cancel</button>
        <button type="submit" disabled={saving} className="px-4 py-2 text-sm text-white rounded disabled:opacity-50" style={{ backgroundColor: "#2f6046" }}>
          {saving ? "Saving…" : submitLabel}
        </button>
      </div>
    </form>
  );
}

// ── Sort header ────────────────────────────────────────────────────────────────

function SortTh({ col, active, dir, onClick, children, right }: {
  col: SortCol; active: SortCol; dir: "asc" | "desc";
  onClick: (c: SortCol) => void; children: React.ReactNode; right?: boolean;
}) {
  return (
    <th
      onClick={() => onClick(col)}
      className={`px-4 py-2.5 text-xs font-medium text-gray-600 cursor-pointer select-none hover:text-blue-600 ${right ? "text-right" : "text-left"}`}
    >
      {children}{active === col ? (dir === "asc" ? " ↑" : " ↓") : ""}
    </th>
  );
}

// ── Assign-unassigned picker ───────────────────────────────────────────────────

function AssignPaymentsPicker({ unassigned, onAssign, onCancel }: {
  unassigned: PaymentRow[];
  onAssign: (ids: number[]) => Promise<void>;
  onCancel: () => void;
}) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [saving, setSaving] = useState(false);

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function handleAssign() {
    if (selected.size === 0) return;
    setSaving(true);
    try { await onAssign(Array.from(selected)); } finally { setSaving(false); }
  }

  return (
    <div className="space-y-3">
      {unassigned.length === 0 ? (
        <p className="text-sm text-gray-500">No unassigned payments.</p>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-gray-50 border-b">
              <th className="px-3 py-2 w-8" />
              <th className="px-3 py-2 text-left font-medium text-gray-600">Date</th>
              <th className="px-3 py-2 text-left font-medium text-gray-600">Lot</th>
              <th className="px-3 py-2 text-left font-medium text-gray-600">Type</th>
              <th className="px-3 py-2 text-left font-medium text-gray-600">Method</th>
              <th className="px-3 py-2 text-right font-medium text-gray-600">Amount</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {unassigned.map((p) => (
              <tr key={p.id} className={`cursor-pointer ${selected.has(p.id) ? "bg-blue-50" : "hover:bg-gray-50"}`} onClick={() => toggle(p.id)}>
                <td className="px-3 py-1.5 text-center">
                  <input type="checkbox" checked={selected.has(p.id)} onChange={() => toggle(p.id)} onClick={(e) => e.stopPropagation()} />
                </td>
                <td className="px-3 py-1.5 font-mono text-gray-700">{p.payment_date}</td>
                <td className="px-3 py-1.5 text-gray-700">Lot {p.lot_number}</td>
                <td className="px-3 py-1.5 text-gray-500">{PAYMENT_TYPE_LABELS[p.payment_type as PaymentTypeValue] ?? p.payment_type}</td>
                <td className="px-3 py-1.5 text-gray-500">{p.payment_method}</td>
                <td className="px-3 py-1.5 text-right font-mono text-gray-800">{fmt(p.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="flex justify-between items-center pt-2 border-t">
        <span className="text-xs text-gray-500">{selected.size} selected</span>
        <div className="flex gap-2">
          <button onClick={onCancel} className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900">Cancel</button>
          <button
            onClick={() => void handleAssign()}
            disabled={selected.size === 0 || saving}
            className="px-3 py-1.5 text-sm text-white rounded disabled:opacity-50"
            style={{ backgroundColor: "#2f6046" }}
          >
            {saving ? "Assigning…" : `Assign ${selected.size > 0 ? selected.size : ""}`}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Screen ─────────────────────────────────────────────────────────────────────

type ModalState =
  | { mode: "newBatch" }
  | { mode: "editBatch"; batch: BatchRow }
  | { mode: "recordPayment" }
  | { mode: "addPayment"; batchId: number }
  | { mode: "assignToBatch"; batchId: number }
  | null;

type MatchingState = { batchId: number; candidates: OFXCandidate[]; loading: boolean } | null;

export function DepositsScreen() {
  const [batches, setBatches]         = useState<BatchRow[]>([]);
  const [payments, setPayments]       = useState<Map<number, PaymentRow[]>>(new Map());
  const [unassigned, setUnassigned]   = useState<PaymentRow[]>([]);
  const [unassignedOpen, setUnassignedOpen] = useState(false);
  const [selectedId, setSelectedId]   = useState<number | null>(null);
  const [lots, setLots]               = useState<LotWithOwner[]>([]);
  const [accounts, setAccounts]       = useState<BankAccount[]>([]);
  const [loading, setLoading]         = useState(true);
  const [error, setError]             = useState<string | null>(null);
  const [modal, setModal]             = useState<ModalState>(null);
  const [sortCol, setSortCol]         = useState<SortCol>("date");
  const [sortDir, setSortDir]         = useState<"asc" | "desc">("desc");
  const [loadingIds, setLoadingIds]   = useState<Set<number>>(new Set());
  const [matching, setMatching]       = useState<MatchingState>(null);

  function toggleSort(col: SortCol) {
    if (sortCol === col) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortCol(col); setSortDir("asc"); }
  }

  const loadAll = useCallback(async () => {
    const [b, u, l, a] = await Promise.all([
      listDepositBatches(),
      listUnassignedPayments(),
      listLots(true),
      listBankAccounts(true),
    ]);
    setBatches(b as BatchRow[]);
    setUnassigned(u);
    setLots(l);
    setAccounts(a);
    setLoading(false);
  }, []);

  useEffect(() => { void loadAll().catch((e) => setError(String(e))); }, [loadAll]);

  async function reloadBatchPayments(batchId: number) {
    const rows = await listPaymentsForBatch(batchId);
    setPayments((prev) => new Map(prev).set(batchId, rows));
  }

  async function toggleBatch(batchId: number) {
    if (selectedId === batchId) { setSelectedId(null); return; }
    setSelectedId(batchId);
    if (!payments.has(batchId)) {
      setLoadingIds((s) => new Set(s).add(batchId));
      try { await reloadBatchPayments(batchId); }
      finally { setLoadingIds((s) => { const n = new Set(s); n.delete(batchId); return n; }); }
    }
  }

  async function handleCreateBatch(date: string, accountId: number, notes: string) {
    await insertDepositBatch(date, accountId, notes);
    setModal(null);
    await loadAll();
  }

  async function handleEditBatch(batchId: number, date: string, accountId: number, notes: string) {
    await updateDepositBatch(batchId, date, accountId, notes);
    setModal(null);
    await loadAll();
  }

  async function handleRecordPayment(values: PaymentFormValues) {
    await insertPayment(null, values);
    setModal(null);
    const u = await listUnassignedPayments();
    setUnassigned(u);
    setUnassignedOpen(true);
  }

  async function handleAddPayment(batchId: number, values: PaymentFormValues) {
    await insertPayment(batchId, values);
    setModal(null);
    await loadAll();
    await reloadBatchPayments(batchId);
  }

  async function handleAssignToBatch(batchId: number, ids: number[]) {
    await assignPaymentsToBatch(ids, batchId);
    setModal(null);
    await loadAll();
    await reloadBatchPayments(batchId);
  }

  async function handleUnassign(paymentId: number, batchId: number) {
    if (!await appConfirm("Remove this payment from the batch? It will become unassigned.")) return;
    await unassignPaymentFromBatch(paymentId, batchId);
    await loadAll();
    await reloadBatchPayments(batchId);
  }

  async function handleDeleteUnassigned(paymentId: number) {
    if (!await appConfirm("Delete this payment? This cannot be undone.")) return;
    await deletePayment(paymentId, null);
    const u = await listUnassignedPayments();
    setUnassigned(u);
  }

  async function handlePost(batchId: number) {
    if (!await appConfirm("Post this deposit batch? It will be locked.")) return;
    await postDepositBatch(batchId);
    await loadAll();
  }

  async function handleOpenMatching(batch: BatchRow) {
    setMatching({ batchId: batch.id, candidates: [], loading: true });
    try {
      const candidates = await listCandidateBankTxns(batch.bank_account_id, batch.total_amount, batch.deposit_date);
      setMatching({ batchId: batch.id, candidates, loading: false });
    } catch {
      setMatching({ batchId: batch.id, candidates: [], loading: false });
    }
  }

  async function handleLink(batchId: number, txnId: number) {
    await linkDepositToTxn(batchId, txnId);
    setMatching(null);
    await loadAll();
  }

  async function handleUnlink(batchId: number) {
    await unlinkDepositTxn(batchId);
    await loadAll();
  }

  const sorted = [...batches].sort((a, b) => {
    let cmp = 0;
    if (sortCol === "date")      cmp = a.deposit_date.localeCompare(b.deposit_date);
    else if (sortCol === "account")   cmp = a.account_name.localeCompare(b.account_name);
    else if (sortCol === "payments")  cmp = a.check_count - b.check_count;
    else if (sortCol === "total")     cmp = a.total_amount - b.total_amount;
    else if (sortCol === "status")    cmp = a.status.localeCompare(b.status);
    return sortDir === "asc" ? cmp : -cmp;
  });

  return (
    <PageLayout
      title="Deposits"
      subtitle="Owner payment batches deposited to the bank."
      helpId="deposits"
      actions={
        <div className="flex gap-2">
          <button
            onClick={() => setModal({ mode: "recordPayment" })}
            className="px-4 py-2 text-sm rounded-lg border"
            style={{ borderColor: "#2a6b5e", color: "#2a6b5e" }}
          >
            Record Payment
          </button>
          <button
            onClick={() => setModal({ mode: "newBatch" })}
            className="px-4 py-2 text-sm text-white rounded-lg"
            style={{ backgroundColor: "#2f6046" }}
          >
            + New Deposit
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        {loading && <p className="text-sm text-gray-400">Loading…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}

        {!loading && !error && (
          <>
            {/* ── Unassigned Payments ── */}
            <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
              <button
                onClick={() => setUnassignedOpen((o) => !o)}
                className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                <span className="flex items-center gap-2">
                  Unassigned Payments
                  {unassigned.length > 0 && (
                    <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-orange-100 text-orange-700">
                      {unassigned.length}
                    </span>
                  )}
                </span>
                <span className="text-gray-400 text-xs">{unassignedOpen ? "▲" : "▼"}</span>
              </button>
              {unassignedOpen && (
                <div className="border-t border-gray-200">
                  {unassigned.length === 0 ? (
                    <p className="px-4 py-4 text-sm text-gray-400">No unassigned payments.</p>
                  ) : (
                    <table className="w-full text-xs">
                      <thead className="bg-gray-50 border-b border-gray-200">
                        <tr>
                          <th className="px-4 py-2 text-left font-medium text-gray-600">Date</th>
                          <th className="px-4 py-2 text-left font-medium text-gray-600">Lot</th>
                          <th className="px-4 py-2 text-left font-medium text-gray-600">Owner</th>
                          <th className="px-4 py-2 text-left font-medium text-gray-600">Type</th>
                          <th className="px-4 py-2 text-left font-medium text-gray-600">Method</th>
                          <th className="px-4 py-2 text-left font-medium text-gray-600">Check #</th>
                          <th className="px-4 py-2 text-right font-medium text-gray-600">Amount</th>
                          <th className="px-4 py-2" />
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {unassigned.map((p) => (
                          <tr key={p.id} className="hover:bg-gray-50">
                            <td className="px-4 py-1.5 font-mono text-gray-600">{p.payment_date}</td>
                            <td className="px-4 py-1.5 font-medium text-gray-800">Lot {p.lot_number}</td>
                            <td className="px-4 py-1.5 text-gray-500">{p.owner_name ?? "—"}</td>
                            <td className="px-4 py-1.5 text-gray-500">
                              {PAYMENT_TYPE_LABELS[p.payment_type as PaymentTypeValue] ?? p.payment_type}
                            </td>
                            <td className="px-4 py-1.5 text-gray-500">{p.payment_method}</td>
                            <td className="px-4 py-1.5 text-gray-500">{p.check_number ?? "—"}</td>
                            <td className="px-4 py-1.5 text-right font-mono font-semibold text-gray-800">{fmt(p.amount)}</td>
                            <td className="px-4 py-1.5 text-right">
                              <button
                                onClick={() => void handleDeleteUnassigned(p.id)}
                                className="text-red-400 hover:text-red-600 text-xs"
                                title="Delete"
                              >
                                Delete
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                      <tfoot className="bg-gray-50 border-t border-gray-200">
                        <tr>
                          <td colSpan={6} className="px-4 py-2 text-xs text-gray-500">{unassigned.length} payment{unassigned.length !== 1 ? "s" : ""}</td>
                          <td className="px-4 py-2 text-right font-mono font-semibold text-gray-800 text-xs">
                            {fmt(unassigned.reduce((s, p) => s + p.amount, 0))}
                          </td>
                          <td />
                        </tr>
                      </tfoot>
                    </table>
                  )}
                </div>
              )}
            </div>

            {/* ── Deposit Batches ── */}
            <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
              {batches.length === 0 ? (
                <p className="px-6 py-10 text-center text-gray-400 text-sm">
                  No deposit batches yet. Click "+ New Deposit" to create one.
                </p>
              ) : (
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b border-gray-200">
                    <tr>
                      <th className="w-6 px-4 py-2.5" />
                      <SortTh col="date"     active={sortCol} dir={sortDir} onClick={toggleSort}>Date</SortTh>
                      <SortTh col="account"  active={sortCol} dir={sortDir} onClick={toggleSort}>Account</SortTh>
                      <SortTh col="payments" active={sortCol} dir={sortDir} onClick={toggleSort}>Payments</SortTh>
                      <SortTh col="status"   active={sortCol} dir={sortDir} onClick={toggleSort}>Status</SortTh>
                      <th className="px-4 py-2.5 text-xs font-medium text-gray-600 text-left">OFX Match</th>
                      <SortTh col="total"    active={sortCol} dir={sortDir} onClick={toggleSort} right>Total</SortTh>
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.map((batch) => {
                      const isOpen = batch.id === selectedId;
                      const batchPayments = payments.get(batch.id) ?? [];
                      const isLoadingDetail = loadingIds.has(batch.id);
                      return (
                        <>
                          <tr
                            key={batch.id}
                            onClick={() => void toggleBatch(batch.id)}
                            className={`cursor-pointer transition-colors border-t border-gray-100 first:border-t-0 ${isOpen ? "bg-blue-50" : "hover:bg-gray-50"}`}
                          >
                            <td className="px-4 py-2.5 w-6 text-gray-400 text-xs select-none">{isOpen ? "▼" : "▶"}</td>
                            <td className={`px-4 py-2.5 font-medium ${isOpen ? "text-blue-900" : "text-gray-900"}`}>{batch.deposit_date}</td>
                            <td className="px-4 py-2.5 text-gray-600 text-xs">{batch.account_name}</td>
                            <td className="px-4 py-2.5 text-gray-500 text-xs">{batch.check_count}</td>
                            <td className="px-4 py-2.5">
                              <span className={`px-2 py-0.5 rounded text-xs font-medium ${batch.status === "POSTED" ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"}`}>
                                {batch.status}
                              </span>
                            </td>
                            <td className="px-4 py-2.5">
                              {batch.bank_transaction_id
                                ? <span className="px-2 py-0.5 rounded text-xs font-medium bg-teal-100 text-teal-700">Matched ✓</span>
                                : <span className="px-2 py-0.5 rounded text-xs font-medium bg-orange-100 text-orange-700">Unmatched</span>
                              }
                            </td>
                            <td className="px-4 py-2.5 text-right font-mono font-semibold text-gray-900">{fmt(batch.total_amount)}</td>
                          </tr>

                          {isOpen && (
                            <tr key={`${batch.id}-detail`} className="bg-blue-50">
                              <td colSpan={7} className="px-0 py-0">
                                <div className="border-t border-blue-200">
                                  {/* Detail toolbar */}
                                  <div className="px-4 py-2 bg-blue-100 flex items-center justify-between flex-wrap gap-2">
                                    <span className="text-xs text-blue-700 font-medium">{batch.notes || "Payments"}</span>
                                    <div className="flex items-center gap-2 flex-wrap">
                                      {batch.bank_transaction_id ? (
                                        <div className="flex items-center gap-1">
                                          <span className="text-xs text-teal-700 font-medium">OFX matched (txn #{batch.bank_transaction_id})</span>
                                          <button onClick={(e) => { e.stopPropagation(); void handleUnlink(batch.id); }}
                                            className="px-2 py-0.5 text-xs border border-orange-400 text-orange-600 rounded hover:bg-orange-50">
                                            Unlink
                                          </button>
                                        </div>
                                      ) : (
                                        <button
                                          onClick={(e) => { e.stopPropagation(); if (matching?.batchId === batch.id) setMatching(null); else void handleOpenMatching(batch); }}
                                          className="px-2 py-0.5 text-xs border rounded"
                                          style={{ borderColor: "#2a6b5e", color: "#2a6b5e" }}
                                        >
                                          {matching?.batchId === batch.id ? "Hide OFX" : "Match OFX"}
                                        </button>
                                      )}
                                      <button
                                        onClick={(e) => { e.stopPropagation(); setModal({ mode: "editBatch", batch }); }}
                                        className="px-2 py-0.5 text-xs border border-gray-400 text-gray-600 rounded hover:bg-gray-100"
                                      >
                                        Edit
                                      </button>
                                      {batch.status === "OPEN" && (
                                        <>
                                          <button
                                            onClick={(e) => { e.stopPropagation(); setModal({ mode: "assignToBatch", batchId: batch.id }); }}
                                            className="px-2 py-0.5 text-xs border rounded"
                                            style={{ borderColor: "#2a6b5e", color: "#2a6b5e" }}
                                          >
                                            Assign Payments
                                          </button>
                                          <button
                                            onClick={(e) => { e.stopPropagation(); setModal({ mode: "addPayment", batchId: batch.id }); }}
                                            className="px-2 py-0.5 text-xs text-white rounded"
                                            style={{ backgroundColor: "#2a6b5e" }}
                                          >
                                            + New Payment
                                          </button>
                                          <button
                                            onClick={(e) => { e.stopPropagation(); void handlePost(batch.id); }}
                                            className="px-2 py-0.5 text-xs bg-green-600 text-white rounded hover:bg-green-700"
                                          >
                                            Post Batch
                                          </button>
                                        </>
                                      )}
                                    </div>
                                  </div>

                                  {/* OFX candidate picker */}
                                  {matching?.batchId === batch.id && (
                                    <div className="border-t border-teal-200 bg-teal-50 px-4 py-3">
                                      <p className="text-xs font-semibold text-teal-800 mb-2">
                                        OFX candidates — same account, within ±5% amount and ±14 days of {batch.deposit_date}
                                      </p>
                                      {matching.loading ? (
                                        <p className="text-xs text-teal-600">Searching…</p>
                                      ) : matching.candidates.length === 0 ? (
                                        <p className="text-xs text-orange-700">No matching bank transactions found.</p>
                                      ) : (
                                        <table className="w-full text-xs">
                                          <thead>
                                            <tr className="text-teal-700">
                                              <th className="text-left py-1 pr-3 font-medium">Date</th>
                                              <th className="text-left py-1 pr-3 font-medium">Description</th>
                                              <th className="text-right py-1 pr-3 font-medium">Amount</th>
                                              <th className="text-right py-1 pr-3 font-medium">Days off</th>
                                              <th className="py-1" />
                                            </tr>
                                          </thead>
                                          <tbody>
                                            {matching.candidates.map((c) => (
                                              <tr key={c.id} className="border-t border-teal-100 hover:bg-teal-100">
                                                <td className="py-1 pr-3 text-gray-700">{c.transaction_date}</td>
                                                <td className="py-1 pr-3 text-gray-700 truncate">{c.description}</td>
                                                <td className="py-1 pr-3 text-right font-mono text-gray-800">{fmt(c.amount)}</td>
                                                <td className="py-1 pr-3 text-right text-gray-500">{Math.round(c.days_diff)}</td>
                                                <td className="py-1 text-right">
                                                  <button
                                                    onClick={(e) => { e.stopPropagation(); void handleLink(batch.id, c.id); }}
                                                    className="px-2 py-0.5 rounded text-white text-xs"
                                                    style={{ backgroundColor: "#2f6046" }}
                                                  >
                                                    Link
                                                  </button>
                                                </td>
                                              </tr>
                                            ))}
                                          </tbody>
                                        </table>
                                      )}
                                    </div>
                                  )}

                                  {/* Payment rows */}
                                  {isLoadingDetail ? (
                                    <p className="px-6 py-3 text-xs text-gray-400">Loading…</p>
                                  ) : (
                                    <table className="w-full text-xs">
                                      <thead className="bg-blue-50">
                                        <tr>
                                          <th className="pl-8 pr-4 py-1.5 text-left text-gray-500 font-medium">Date</th>
                                          <th className="px-4 py-1.5 text-left text-gray-500 font-medium">Lot</th>
                                          <th className="px-4 py-1.5 text-left text-gray-500 font-medium">Owner</th>
                                          <th className="px-4 py-1.5 text-left text-gray-500 font-medium">Type</th>
                                          <th className="px-4 py-1.5 text-left text-gray-500 font-medium">Method</th>
                                          <th className="px-4 py-1.5 text-left text-gray-500 font-medium">Check #</th>
                                          <th className="px-4 py-1.5 text-right text-gray-500 font-medium pr-8">Amount</th>
                                        </tr>
                                      </thead>
                                      <tbody className="divide-y divide-blue-100">
                                        {batchPayments.length === 0 && (
                                          <tr>
                                            <td colSpan={7} className="pl-8 py-3 text-gray-400 italic">No payments in this batch.</td>
                                          </tr>
                                        )}
                                        {batchPayments.map((p) => (
                                          <tr key={p.id} className="hover:bg-blue-100">
                                            <td className="pl-8 pr-4 py-1.5 text-gray-500">{p.payment_date}</td>
                                            <td className="px-4 py-1.5 font-medium text-gray-800">Lot {p.lot_number}</td>
                                            <td className="px-4 py-1.5 text-gray-500">{p.owner_name ?? "—"}</td>
                                            <td className="px-4 py-1.5 text-gray-500">
                                              {PAYMENT_TYPE_LABELS[p.payment_type as PaymentTypeValue] ?? p.payment_type}
                                            </td>
                                            <td className="px-4 py-1.5 text-gray-500">{p.payment_method}</td>
                                            <td className="px-4 py-1.5 text-gray-500">{p.check_number ?? "—"}</td>
                                            <td className="px-4 py-1.5 text-right font-mono text-gray-800 pr-6">
                                              {fmt(p.amount)}
                                              {batch.status === "OPEN" && (
                                                <button
                                                  onClick={(e) => { e.stopPropagation(); void handleUnassign(p.id, batch.id); }}
                                                  className="ml-2 text-orange-400 hover:text-orange-600 text-xs"
                                                  title="Remove from batch"
                                                >
                                                  ✕
                                                </button>
                                              )}
                                            </td>
                                          </tr>
                                        ))}
                                      </tbody>
                                      {batchPayments.length > 0 && (
                                        <tfoot className="bg-blue-50 border-t border-blue-200">
                                          <tr>
                                            <td colSpan={6} className="pl-8 py-1.5 text-gray-500">
                                              {batchPayments.length} payment{batchPayments.length !== 1 ? "s" : ""}
                                            </td>
                                            <td className="px-4 py-1.5 text-right font-mono font-semibold text-gray-800 pr-8">
                                              {fmt(batchPayments.reduce((s, p) => s + p.amount, 0))}
                                            </td>
                                          </tr>
                                        </tfoot>
                                      )}
                                    </table>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )}
                        </>
                      );
                    })}
                  </tbody>
                  <tfoot className="bg-gray-50 border-t border-gray-200">
                    <tr>
                      <td colSpan={6} className="px-4 py-2 text-xs text-gray-500">{batches.length} batches</td>
                      <td className="px-4 py-2 text-right font-mono font-semibold text-gray-800 text-sm">
                        {fmt(batches.reduce((s, b) => s + b.total_amount, 0))}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              )}
            </div>
          </>
        )}

        {/* ── Modals ── */}
        {modal?.mode === "newBatch" && (
          <Modal title="New Deposit Batch" onClose={() => setModal(null)}>
            <BatchForm accounts={accounts} onSave={handleCreateBatch} onCancel={() => setModal(null)} submitLabel="Create Deposit" />
          </Modal>
        )}

        {modal?.mode === "editBatch" && (
          <Modal title="Edit Deposit Batch" onClose={() => setModal(null)}>
            <BatchForm
              accounts={accounts}
              initial={{ date: modal.batch.deposit_date, accountId: modal.batch.bank_account_id, notes: modal.batch.notes ?? "" }}
              onSave={(date, accountId, notes) => handleEditBatch(modal.batch.id, date, accountId, notes)}
              onCancel={() => setModal(null)}
              submitLabel="Save Changes"
            />
          </Modal>
        )}

        {modal?.mode === "recordPayment" && (
          <Modal title="Record Payment" onClose={() => setModal(null)}>
            <PaymentForm lots={lots} onSave={handleRecordPayment} onCancel={() => setModal(null)} />
          </Modal>
        )}

        {modal?.mode === "addPayment" && (
          <Modal title="Add Payment to Batch" onClose={() => setModal(null)}>
            <PaymentForm
              lots={lots}
              onSave={(v) => handleAddPayment(modal.batchId, v)}
              onCancel={() => setModal(null)}
            />
          </Modal>
        )}

        {modal?.mode === "assignToBatch" && (
          <Modal title="Assign Unassigned Payments to Batch" onClose={() => setModal(null)}>
            <AssignPaymentsPicker
              unassigned={unassigned}
              onAssign={(ids) => handleAssignToBatch(modal.batchId, ids)}
              onCancel={() => setModal(null)}
            />
          </Modal>
        )}
      </div>
    </PageLayout>
  );
}
