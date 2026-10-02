import { useEffect, useState, useCallback } from "react";
import { Modal } from "../components/Modal";
import { PageLayout } from "../components/PageLayout";
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
import type { LotWithOwner } from "../types/lot";
import type { OwnerWithLots } from "../types/owner";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

type BatchRow = {
  id: number;
  deposit_date: string;
  account_name: string;
  total_amount: number;
  check_count: number;
  notes: string | null;
  status: string;
};

type SortCol = "date" | "account" | "payments" | "total" | "status";

// ── Add Payment Form ──────────────────────────────────────────────────────────

function PaymentForm({ lots, owners, onSave, onCancel }: {
  lots: LotWithOwner[];
  owners: OwnerWithLots[];
  onSave: (v: PaymentFormValues) => Promise<void>;
  onCancel: () => void;
}) {
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
          <input type="date" value={values.payment_date}
            onChange={(e) => set("payment_date", e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Amount <span className="text-red-500">*</span></label>
          <input type="number" step="0.01" min="0.01" value={values.amount}
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
        <label className="block text-xs font-medium text-gray-700 mb-1">Owner (optional)</label>
        <select value={values.owner_id ?? ""}
          onChange={(e) => set("owner_id", e.target.value ? Number(e.target.value) : undefined)}
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
          <option value="">— Auto from lot —</option>
          {owners.map((o) => <option key={o.id} value={o.id}>{o.display_name}</option>)}
        </select>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Memo</label>
        <input type="text" value={values.memo ?? ""}
          onChange={(e) => set("memo", e.target.value || undefined)}
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
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
        <button type="submit" disabled={saving} className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
          {saving ? "Creating…" : "Create Deposit"}
        </button>
      </div>
    </form>
  );
}

// ── Sort header helper ────────────────────────────────────────────────────────

function SortTh({ col, active, dir, onClick, children, right }: {
  col: SortCol; active: SortCol; dir: "asc" | "desc";
  onClick: (c: SortCol) => void; children: React.ReactNode; right?: boolean;
}) {
  const isActive = active === col;
  return (
    <th
      onClick={() => onClick(col)}
      className={`px-4 py-2.5 text-xs font-medium text-gray-600 cursor-pointer select-none hover:text-blue-600 ${right ? "text-right" : "text-left"}`}
    >
      {children}{isActive ? (dir === "asc" ? " ↑" : " ↓") : ""}
    </th>
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

type ModalState = { mode: "newBatch" } | { mode: "addPayment"; batchId: number } | null;

export function DepositsScreen() {
  const [batches, setBatches] = useState<BatchRow[]>([]);
  const [payments, setPayments] = useState<Map<number, PaymentRow[]>>(new Map());
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [lots, setLots] = useState<LotWithOwner[]>([]);
  const [owners, setOwners] = useState<OwnerWithLots[]>([]);
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalState>(null);
  const [sortCol, setSortCol] = useState<SortCol>("date");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  function toggleSort(col: SortCol) {
    if (sortCol === col) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortCol(col); setSortDir("asc"); }
  }

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

  const [loadingIds, setLoadingIds] = useState<Set<number>>(new Set());

  async function toggleBatch(batchId: number) {
    if (selectedId === batchId) { setSelectedId(null); return; }
    setSelectedId(batchId);
    if (!payments.has(batchId)) {
      setLoadingIds((s) => new Set(s).add(batchId));
      try {
        const rows = await listPaymentsForBatch(batchId);
        setPayments((prev) => new Map(prev).set(batchId, rows));
      } finally {
        setLoadingIds((s) => { const n = new Set(s); n.delete(batchId); return n; });
      }
    }
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
    const rows = await listPaymentsForBatch(batchId);
    setPayments((prev) => new Map(prev).set(batchId, rows));
  }

  async function handleDeletePayment(paymentId: number, batchId: number) {
    if (!confirm("Remove this payment?")) return;
    await deletePayment(paymentId, batchId);
    await loadBatches();
    const rows = await listPaymentsForBatch(batchId);
    setPayments((prev) => new Map(prev).set(batchId, rows));
  }

  async function handlePost(batchId: number) {
    if (!confirm("Post this deposit batch? It will be locked.")) return;
    await postDepositBatch(batchId);
    await loadBatches();
  }

  const sorted = [...batches].sort((a, b) => {
    let cmp = 0;
    if (sortCol === "date")     cmp = a.deposit_date.localeCompare(b.deposit_date);
    else if (sortCol === "account")  cmp = a.account_name.localeCompare(b.account_name);
    else if (sortCol === "payments") cmp = a.check_count - b.check_count;
    else if (sortCol === "total")    cmp = a.total_amount - b.total_amount;
    else if (sortCol === "status")   cmp = a.status.localeCompare(b.status);
    return sortDir === "asc" ? cmp : -cmp;
  });


  return (
    <PageLayout
      title="Deposits"
      subtitle="Owner payment batches deposited to the bank."
      helpId="deposits"
      actions={
        <button
          onClick={() => setModal({ mode: "newBatch" })}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
        >
          + New Deposit
        </button>
      }
    >
      <div className="max-w-5xl space-y-4">

        {loading && <p className="text-sm text-gray-400">Loading…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}

        {!loading && !error && (
          <>
            {/* ── Sortable batch table ── */}
            <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
              {batches.length === 0 ? (
                <p className="px-6 py-10 text-center text-gray-400 text-sm">
                  No deposit batches yet. Click "New Deposit" to record owner payments.
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
                            <td className="px-4 py-2.5 w-6 text-gray-400 text-xs select-none">
                              {isOpen ? "▼" : "▶"}
                            </td>
                            <td className={`px-4 py-2.5 font-medium ${isOpen ? "text-blue-900" : "text-gray-900"}`}>
                              {batch.deposit_date}
                            </td>
                            <td className="px-4 py-2.5 text-gray-600 text-xs">{batch.account_name}</td>
                            <td className="px-4 py-2.5 text-gray-500 text-xs">{batch.check_count}</td>
                            <td className="px-4 py-2.5">
                              <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                                batch.status === "POSTED" ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"
                              }`}>
                                {batch.status}
                              </span>
                            </td>
                            <td className="px-4 py-2.5 text-right font-mono font-semibold text-gray-900">
                              {fmt(batch.total_amount)}
                            </td>
                          </tr>
                          {isOpen && (
                            <tr key={`${batch.id}-detail`} className="bg-blue-50">
                              <td colSpan={6} className="px-0 py-0">
                                {/* ── inline detail panel ── */}
                                <div className="border-t border-blue-200">
                                  <div className="px-4 py-2 bg-blue-100 flex items-center justify-between">
                                    <span className="text-xs text-blue-700 font-medium">
                                      {batch.notes ? batch.notes : "Payments"}
                                    </span>
                                    <div className="flex items-center gap-2">
                                      {batch.status === "OPEN" && (
                                        <>
                                          <button
                                            onClick={(e) => { e.stopPropagation(); setModal({ mode: "addPayment", batchId: batch.id }); }}
                                            className="px-2 py-0.5 text-xs bg-blue-600 text-white rounded hover:bg-blue-700"
                                          >
                                            + Payment
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
                                  {isLoadingDetail ? (
                                    <p className="px-6 py-3 text-xs text-gray-400">Loading…</p>
                                  ) : (
                                    <table className="w-full text-xs">
                                      <thead className="bg-blue-50">
                                        <tr>
                                          <th className="pl-8 pr-4 py-1.5 text-left text-gray-500 font-medium">Date</th>
                                          <th className="px-4 py-1.5 text-left text-gray-500 font-medium">Lot</th>
                                          <th className="px-4 py-1.5 text-left text-gray-500 font-medium">Owner</th>
                                          <th className="px-4 py-1.5 text-left text-gray-500 font-medium">Method</th>
                                          <th className="px-4 py-1.5 text-left text-gray-500 font-medium">Check #</th>
                                          <th className="px-4 py-1.5 text-right text-gray-500 font-medium pr-8">Amount</th>
                                        </tr>
                                      </thead>
                                      <tbody className="divide-y divide-blue-100">
                                        {batchPayments.length === 0 && (
                                          <tr>
                                            <td colSpan={6} className="pl-8 py-3 text-gray-400 italic">No payments in this batch.</td>
                                          </tr>
                                        )}
                                        {batchPayments.map((p) => (
                                          <tr key={p.id} className="hover:bg-blue-100">
                                            <td className="pl-8 pr-4 py-1.5 text-gray-500">{p.payment_date}</td>
                                            <td className="px-4 py-1.5 font-medium text-gray-800">Lot {p.lot_number}</td>
                                            <td className="px-4 py-1.5 text-gray-500">{p.owner_name ?? "—"}</td>
                                            <td className="px-4 py-1.5 text-gray-500">{p.payment_method}</td>
                                            <td className="px-4 py-1.5 text-gray-500">{p.check_number ?? "—"}</td>
                                            <td className="px-4 py-1.5 text-right font-mono text-gray-800 pr-6">
                                              {fmt(p.amount)}
                                              {batch.status === "OPEN" && (
                                                <button
                                                  onClick={(e) => { e.stopPropagation(); void handleDeletePayment(p.id, batch.id); }}
                                                  className="ml-2 text-red-400 hover:text-red-600"
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
                                            <td colSpan={5} className="pl-8 py-1.5 text-gray-500">
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
                      <td colSpan={5} className="px-4 py-2 text-xs text-gray-500">{batches.length} batches</td>
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

        {modal?.mode === "newBatch" && (
          <Modal title="New Deposit Batch" onClose={() => setModal(null)}>
            <NewBatchForm accounts={accounts} onCreate={handleCreateBatch} onCancel={() => setModal(null)} />
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
    </PageLayout>
  );
}
