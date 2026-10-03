import { useEffect, useState } from "react";
import { getDb } from "../lib/db";
import { PageLayout } from "../components/PageLayout";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import type { BankAccount } from "../types/bankAccount";
import { appAlert, appConfirm } from "../components/AppDialogs";

// ── Types ─────────────────────────────────────────────────────────────────────

type AccountTransfer = {
  id: number;
  transfer_date: string;
  from_account: string;
  to_account: string;
  amount: number;
  description: string | null;
  notes: string | null;
  from_txn_id: number | null;
  to_txn_id: number | null;
};

const fmt = (n: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

// ── Repo helpers ──────────────────────────────────────────────────────────────

async function loadTransfers(): Promise<AccountTransfer[]> {
  const db = await getDb();
  return db.select<AccountTransfer[]>(`
    SELECT t.id, t.transfer_date,
           fa.account_name AS from_account,
           ta.account_name AS to_account,
           t.amount, t.description, t.notes,
           t.from_txn_id, t.to_txn_id
    FROM account_transfers t
    JOIN bank_accounts fa ON fa.id = t.from_account_id
    JOIN bank_accounts ta ON ta.id = t.to_account_id
    ORDER BY t.transfer_date DESC, t.id DESC
  `);
}

async function insertTransfer(
  transfer_date: string,
  from_account_id: number,
  to_account_id: number,
  amount: number,
  description: string,
  notes: string,
  from_txn_id: number | null,
  to_txn_id: number | null
): Promise<void> {
  const db = await getDb();
  const result = await db.execute(
    `INSERT INTO account_transfers
       (transfer_date, from_account_id, to_account_id, amount, description, notes, from_txn_id, to_txn_id)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    [
      transfer_date,
      from_account_id,
      to_account_id,
      amount,
      description || null,
      notes || null,
      from_txn_id,
      to_txn_id,
    ]
  );
  const transferId = result.lastInsertId;
  // Validate linked OFX txns
  for (const txnId of [from_txn_id, to_txn_id]) {
    if (!txnId) continue;
    await db.execute(
      `INSERT OR IGNORE INTO bank_transaction_links (bank_transaction_id, source_type, source_id)
       VALUES (?, 'ACCOUNT_TRANSFER', ?)`,
      [txnId, transferId]
    );
    await db.execute(
      "UPDATE bank_transactions SET validation_status = 'VALIDATED' WHERE id = ?",
      [txnId]
    );
  }
}

async function deleteTransfer(id: number): Promise<void> {
  const db = await getDb();
  // Un-validate linked OFX txns before deleting
  const rows = await db.select<{ from_txn_id: number | null; to_txn_id: number | null }[]>(
    "SELECT from_txn_id, to_txn_id FROM account_transfers WHERE id = ?",
    [id]
  );
  const row = rows[0];
  if (row) {
    for (const txnId of [row.from_txn_id, row.to_txn_id]) {
      if (!txnId) continue;
      await db.execute("DELETE FROM bank_transaction_links WHERE bank_transaction_id = ? AND source_type = 'ACCOUNT_TRANSFER'", [txnId]);
      await db.execute("UPDATE bank_transactions SET validation_status = 'UNVALIDATED' WHERE id = ?", [txnId]);
    }
  }
  await db.execute("DELETE FROM account_transfers WHERE id = ?", [id]);
}

// ── Unvalidated OFX txns for linking ─────────────────────────────────────────

type PendingTxn = { id: number; transaction_date: string; amount: number; description: string; bank_account_id: number; account_name: string };

async function loadUnvalidatedTxns(): Promise<PendingTxn[]> {
  const db = await getDb();
  return db.select<PendingTxn[]>(`
    SELECT bt.id, bt.transaction_date, bt.amount,
           COALESCE(bt.description,'') AS description,
           bt.bank_account_id, ba.account_name
    FROM bank_transactions bt
    JOIN bank_accounts ba ON ba.id = bt.bank_account_id
    WHERE bt.validation_status = 'UNVALIDATED'
    ORDER BY bt.transaction_date DESC
  `);
}

// ── New Transfer Form ─────────────────────────────────────────────────────────

function NewTransferForm({
  accounts,
  pendingTxns,
  onSaved,
}: {
  accounts: BankAccount[];
  pendingTxns: PendingTxn[];
  onSaved: () => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate] = useState(today);
  const [fromId, setFromId] = useState<number>(accounts[0]?.id ?? 0);
  const [toId, setToId] = useState<number>(accounts[1]?.id ?? 0);
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [notes, setNotes] = useState("");
  const [fromTxnId, setFromTxnId] = useState<number | null>(null);
  const [toTxnId, setToTxnId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const amt = parseFloat(amount);
    if (!date || isNaN(amt) || amt <= 0) { setError("Date and positive amount required."); return; }
    if (fromId === toId) { setError("From and To accounts must differ."); return; }
    setSaving(true);
    setError(null);
    try {
      await insertTransfer(date, fromId, toId, amt, description, notes, fromTxnId, toTxnId);
      setAmount(""); setDescription(""); setNotes(""); setFromTxnId(null); setToTxnId(null);
      onSaved();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  const negativeTxns = pendingTxns.filter((t) => t.amount < 0);
  const positiveTxns = pendingTxns.filter((t) => t.amount > 0);

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="bg-white border rounded-lg p-5 space-y-4">
      <h2 className="font-semibold text-gray-800 text-sm">New Account Transfer</h2>
      {error && <p className="text-xs text-red-600">{error}</p>}

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Date</label>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Amount</label>
          <input type="number" step="0.01" min="0.01" value={amount}
            onChange={(e) => setAmount(e.target.value)} placeholder="0.00" required
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">From Account</label>
          <select value={fromId} onChange={(e) => setFromId(Number(e.target.value))}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">To Account</label>
          <select value={toId} onChange={(e) => setToId(Number(e.target.value))}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Description</label>
          <input type="text" value={description} onChange={(e) => setDescription(e.target.value)}
            placeholder="Monthly reserve contribution"
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Notes</label>
          <input type="text" value={notes} onChange={(e) => setNotes(e.target.value)}
            placeholder="Optional"
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
      </div>

      {/* OFX Linking */}
      <div className="border-t pt-4 space-y-3">
        <p className="text-xs font-medium text-gray-600">Link OFX Transactions (optional — marks them Validated)</p>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Withdrawal (negative)</label>
            <select value={fromTxnId ?? ""} onChange={(e) => setFromTxnId(e.target.value ? Number(e.target.value) : null)}
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="">— None —</option>
              {negativeTxns.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.transaction_date} | {t.account_name} | {fmt(t.amount)} | {t.description.slice(0, 35)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Deposit (positive)</label>
            <select value={toTxnId ?? ""} onChange={(e) => setToTxnId(e.target.value ? Number(e.target.value) : null)}
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="">— None —</option>
              {positiveTxns.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.transaction_date} | {t.account_name} | {fmt(t.amount)} | {t.description.slice(0, 35)}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <button type="submit" disabled={saving}
        className="px-5 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50">
        {saving ? "Posting…" : "Post Transfer"}
      </button>
    </form>
  );
}

// ── Transfer List ─────────────────────────────────────────────────────────────

function TransferRow({ transfer, onDelete }: { transfer: AccountTransfer; onDelete: () => void }) {
  async function handleDelete() {
    const ok = await appConfirm(`Delete transfer of ${fmt(transfer.amount)} on ${transfer.transfer_date}? This will un-validate any linked OFX transactions.`, "Delete Transfer");
    if (!ok) return;
    try {
      await deleteTransfer(transfer.id);
      onDelete();
    } catch (e) {
      await appAlert(String(e), "Error");
    }
  }

  return (
    <tr className="border-t hover:bg-gray-50">
      <td className="py-2 pr-4 text-sm text-gray-700 whitespace-nowrap">{transfer.transfer_date}</td>
      <td className="py-2 pr-4 text-sm text-gray-700">{transfer.from_account}</td>
      <td className="py-2 pr-4 text-sm text-gray-500">→</td>
      <td className="py-2 pr-4 text-sm text-gray-700">{transfer.to_account}</td>
      <td className="py-2 pr-4 text-sm font-mono font-medium text-right text-gray-900">{fmt(transfer.amount)}</td>
      <td className="py-2 pr-4 text-sm text-gray-500">{transfer.description ?? "—"}</td>
      <td className="py-2 pr-4 text-center">
        <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${transfer.from_txn_id ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-400"}`}>
          {transfer.from_txn_id ? `OFX #${transfer.from_txn_id}` : "—"}
        </span>
      </td>
      <td className="py-2 pr-4 text-center">
        <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${transfer.to_txn_id ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-400"}`}>
          {transfer.to_txn_id ? `OFX #${transfer.to_txn_id}` : "—"}
        </span>
      </td>
      <td className="py-2 text-right">
        <button onClick={() => void handleDelete()} className="text-xs text-red-500 hover:text-red-700">Delete</button>
      </td>
    </tr>
  );
}

// ── Main Screen ───────────────────────────────────────────────────────────────

export function BankTransfersScreen() {
  const [transfers, setTransfers] = useState<AccountTransfer[]>([]);
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [pendingTxns, setPendingTxns] = useState<PendingTxn[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const [t, a, p] = await Promise.all([loadTransfers(), listBankAccounts(), loadUnvalidatedTxns()]);
      setTransfers(t);
      setAccounts(a);
      setPendingTxns(p);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void refresh(); }, []);

  const total = transfers.reduce((s, t) => s + t.amount, 0);

  if (loading) return <div className="p-8 text-gray-500 text-sm">Loading…</div>;
  if (error) return <div className="p-8 text-red-600 text-sm">Error: {error}</div>;

  return (
    <PageLayout
      title="Account Transfers"
      subtitle="Record and track transfers between checking and reserve accounts."
    >
      <div className="space-y-6">
        <NewTransferForm accounts={accounts} pendingTxns={pendingTxns} onSaved={() => void refresh()} />

        <div className="bg-white border rounded-lg overflow-hidden">
          <div className="px-5 py-3 border-b flex items-center justify-between">
            <h2 className="font-semibold text-gray-800 text-sm">Transfer History</h2>
            <span className="text-xs text-gray-500">{transfers.length} transfers · Total moved: {fmt(total)}</span>
          </div>
          {transfers.length === 0 ? (
            <p className="px-5 py-6 text-sm text-gray-400">No transfers recorded yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="text-xs font-medium text-gray-500 uppercase tracking-wide bg-gray-50">
                    <th className="px-5 py-2 text-left">Date</th>
                    <th className="px-0 py-2 text-left">From</th>
                    <th className="px-0 py-2"></th>
                    <th className="px-0 py-2 text-left">To</th>
                    <th className="px-0 py-2 text-right">Amount</th>
                    <th className="px-0 py-2 text-left">Description</th>
                    <th className="px-0 py-2 text-center">Withdrawal OFX</th>
                    <th className="px-0 py-2 text-center">Deposit OFX</th>
                    <th className="px-0 py-2"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {transfers.map((t) => (
                    <TransferRow key={t.id} transfer={t} onDelete={() => void refresh()} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </PageLayout>
  );
}
