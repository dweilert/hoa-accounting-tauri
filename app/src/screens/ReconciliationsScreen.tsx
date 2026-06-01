import { useEffect, useState, useCallback } from "react";
import { PageLayout } from "../components/PageLayout";
import {
  listReconciliations,
  getReconciliation,
  createReconciliation,
  finalizeReconciliation,
  reopenReconciliation,
  deleteReconciliation,
  listBankTransactions,
  getClearedTransactionIds,
  toggleClear,
  getLastReconBalance,
} from "../repositories/reconciliationRepo";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import type { BankReconciliation, BankTransaction } from "../types/reconciliation";
import type { BankAccount } from "../types/bankAccount";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

type ReconRow = BankReconciliation & { account_name: string };

// ── New Reconciliation Form ───────────────────────────────────────────────────

function NewReconForm({ accounts, onSave, onCancel }: {
  accounts: BankAccount[];
  onSave: (accountId: number, date: string, endingBalance: number, notes: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [accountId, setAccountId] = useState(accounts[0]?.id ?? 0);
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [endingBalance, setEndingBalance] = useState("0");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try { await onSave(accountId, date, parseFloat(endingBalance) || 0, notes); }
    finally { setSaving(false); }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 p-4 border rounded-lg bg-gray-50">
      <h3 className="font-semibold text-gray-800">New Reconciliation</h3>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Bank Account</label>
          <select
            value={accountId}
            onChange={(e) => setAccountId(Number(e.target.value))}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Statement Ending Date</label>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Statement Ending Balance</label>
          <input
            type="number"
            step="0.01"
            value={endingBalance}
            onChange={(e) => setEndingBalance(e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
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
      </div>
      <div className="flex gap-3 pt-1">
        <button
          type="submit"
          disabled={saving}
          className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Creating…" : "Start Reconciliation"}
        </button>
        <button type="button" onClick={onCancel} className="px-4 py-1.5 text-sm text-gray-600 hover:text-gray-900">
          Cancel
        </button>
      </div>
    </form>
  );
}

// ── Reconciliation Workspace ──────────────────────────────────────────────────

function ReconWorkspace({ recon, onBack, onFinalized }: {
  recon: BankReconciliation;
  onBack: () => void;
  onFinalized: () => void;
}) {
  const [transactions, setTransactions] = useState<BankTransaction[]>([]);
  const [clearedIds, setClearedIds] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(true);
  const [finalizing, setFinalizing] = useState(false);

  const load = useCallback(async () => {
    const [txns, cleared] = await Promise.all([
      listBankTransactions(recon.bank_account_id, { excludeIgnored: true }),
      getClearedTransactionIds(recon.id),
    ]);
    setTransactions(txns);
    setClearedIds(cleared);
    setLoading(false);
  }, [recon.bank_account_id, recon.id]);

  useEffect(() => { void load(); }, [load]);

  async function handleToggle(txnId: number) {
    if (recon.status === "FINALIZED") return;
    const nowCleared = !clearedIds.has(txnId);
    await toggleClear(recon.id, txnId, nowCleared);
    setClearedIds((prev) => {
      const next = new Set(prev);
      if (nowCleared) next.add(txnId); else next.delete(txnId);
      return next;
    });
  }

  async function handleFinalize() {
    if (!confirm("Finalize this reconciliation? It will be locked.")) return;
    setFinalizing(true);
    try {
      await finalizeReconciliation(recon.id, clearedBalance);
      onFinalized();
    } finally {
      setFinalizing(false); }
  }

  async function handleReopen() {
    if (!confirm("Reopen this reconciliation for editing?")) return;
    await reopenReconciliation(recon.id);
    onFinalized();
  }

  const clearedSum = transactions
    .filter((t) => clearedIds.has(t.id))
    .reduce((s, t) => s + t.amount, 0);
  const clearedBalance = recon.beginning_balance + clearedSum;
  const difference = recon.statement_ending_balance - clearedBalance;
  const isBalanced = Math.abs(difference) < 0.005;

  if (loading) return <p className="text-sm text-gray-400 py-4">Loading transactions…</p>;

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <button onClick={onBack} className="text-sm text-blue-600 hover:underline">← Reconciliations</button>
        <span className="text-gray-400">/</span>
        <span className="font-semibold text-gray-900">{recon.statement_ending_date}</span>
        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
          recon.status === "FINALIZED" ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"
        }`}>
          {recon.status}
        </span>
      </div>

      {/* Balance summary */}
      <div className="grid grid-cols-4 gap-3 mb-4">
        {[
          { label: "Beginning Balance", value: recon.beginning_balance },
          { label: "Cleared Total", value: clearedSum },
          { label: "Book Balance", value: clearedBalance },
          { label: "Statement Balance", value: recon.statement_ending_balance },
        ].map(({ label, value }) => (
          <div key={label} className="p-3 bg-white border rounded-lg">
            <div className="text-xs text-gray-500">{label}</div>
            <div className="font-mono font-semibold text-gray-900 mt-0.5">{fmt(value)}</div>
          </div>
        ))}
      </div>

      <div className={`mb-4 px-4 py-2 rounded-lg text-sm font-medium ${
        isBalanced ? "bg-green-100 text-green-800" : "bg-red-100 text-red-700"
      }`}>
        {isBalanced
          ? "✓ Balanced — book balance matches statement."
          : `Difference: ${fmt(difference)} — clear items until this reaches $0.00.`}
      </div>

      {/* Actions */}
      {recon.status === "OPEN" && (
        <div className="flex gap-2 mb-4">
          <button
            onClick={() => void handleFinalize()}
            disabled={!isBalanced || finalizing}
            className="px-4 py-1.5 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50"
          >
            {finalizing ? "Finalizing…" : "Finalize"}
          </button>
        </div>
      )}
      {recon.status === "FINALIZED" && (
        <div className="flex gap-2 mb-4">
          <button
            onClick={() => void handleReopen()}
            className="px-4 py-1.5 border text-sm text-gray-600 rounded hover:bg-gray-50"
          >
            Reopen
          </button>
        </div>
      )}

      {/* Transactions table */}
      <div className="border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-4 py-2 w-10" />
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Date</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Description</th>
              <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {transactions.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-gray-400 text-sm">
                  No bank transactions for this account. Import a bank statement first.
                </td>
              </tr>
            )}
            {transactions.map((t) => {
              const cleared = clearedIds.has(t.id);
              return (
                <tr
                  key={t.id}
                  onClick={() => void handleToggle(t.id)}
                  className={`cursor-pointer transition-colors ${cleared ? "bg-green-50 hover:bg-green-100" : "hover:bg-gray-50"}`}
                >
                  <td className="px-4 py-2 text-center">
                    <input
                      type="checkbox"
                      checked={cleared}
                      readOnly
                      className="rounded"
                    />
                  </td>
                  <td className="px-4 py-2 text-gray-600">{t.transaction_date}</td>
                  <td className="px-4 py-2 text-gray-700">
                    {t.description ?? "—"}
                    {t.memo && <span className="ml-2 text-xs text-gray-400">{t.memo}</span>}
                  </td>
                  <td className={`px-4 py-2 text-right font-mono ${t.amount < 0 ? "text-red-600" : "text-green-700"}`}>
                    {fmt(t.amount)}
                  </td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs ${
                      t.validation_status === "VALIDATED" ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"
                    }`}>
                      {t.validation_status}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-gray-400">
        Click a row to toggle cleared status. {clearedIds.size} of {transactions.length} items cleared.
      </p>
    </div>
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

export function ReconciliationsScreen() {
  const [recons, setRecons] = useState<ReconRow[]>([]);
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [selected, setSelected] = useState<BankReconciliation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);

  const load = useCallback(async () => {
    try {
      const [r, a] = await Promise.all([listReconciliations(), listBankAccounts(true)]);
      setRecons(r);
      setAccounts(a);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function handleCreate(accountId: number, date: string, endingBalance: number, notes: string) {
    const beginning = await getLastReconBalance(accountId);
    await createReconciliation(accountId, date, endingBalance, beginning, notes);
    setShowNew(false);
    await load();
  }

  async function handleDelete(r: ReconRow) {
    if (r.status !== "OPEN") { alert("Only OPEN reconciliations can be deleted."); return; }
    if (!confirm("Delete this reconciliation?")) return;
    await deleteReconciliation(r.id);
    await load();
  }

  async function openRecon(r: ReconRow) {
    const full = await getReconciliation(r.id);
    setSelected(full);
  }

  if (selected) {
    return (
      <PageLayout title="Reconciliations" subtitle="Match book balance to bank statement." helpId="reconciliations">
        <div className="max-w-5xl">
          <ReconWorkspace
            recon={selected}
            onBack={() => setSelected(null)}
            onFinalized={() => { setSelected(null); void load(); }}
          />
        </div>
      </PageLayout>
    );
  }

  return (
    <PageLayout
      title="Reconciliations"
      subtitle="Match book balance to bank statement."
      helpId="reconciliations"
      actions={
        !showNew ? (
          <button
            onClick={() => setShowNew(true)}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
          >
            + New Reconciliation
          </button>
        ) : undefined
      }
    >
      <div className="max-w-4xl">

      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {showNew && (
        <div className="mb-6">
          <NewReconForm
            accounts={accounts}
            onSave={handleCreate}
            onCancel={() => setShowNew(false)}
          />
        </div>
      )}

      {!loading && !error && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Account</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Statement Date</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Beginning</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Statement Ending</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Book Balance</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Status</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {recons.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-gray-400 text-sm">
                    No reconciliations yet. Click "New Reconciliation" to get started.
                  </td>
                </tr>
              )}
              {recons.map((r) => (
                <tr key={r.id}>
                  <td className="px-4 py-3 font-medium text-gray-900">{r.account_name}</td>
                  <td className="px-4 py-3 text-gray-600">{r.statement_ending_date}</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-600">{fmt(r.beginning_balance)}</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-700">{fmt(r.statement_ending_balance)}</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-700">
                    {r.book_balance != null ? fmt(r.book_balance) : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      r.status === "FINALIZED" ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"
                    }`}>
                      {r.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right whitespace-nowrap space-x-2">
                    <button
                      onClick={() => void openRecon(r)}
                      className="text-xs text-blue-600 hover:underline"
                    >
                      {r.status === "OPEN" ? "Work" : "View"}
                    </button>
                    {r.status === "OPEN" && (
                      <button
                        onClick={() => void handleDelete(r)}
                        className="text-xs text-red-500 hover:underline"
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      </div>
    </PageLayout>
  );
}
