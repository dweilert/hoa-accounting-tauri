import { useEffect, useState, useCallback } from "react";
import { listAllBankTransactions, updateTransactionStatus } from "../repositories/reconciliationRepo";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import { listCategories } from "../repositories/categoryRepo";
import { getDb } from "../lib/db";
import { Modal } from "../components/Modal";
import type { BankTransaction } from "../types/reconciliation";
import type { BankAccount } from "../types/bankAccount";
import type { Category } from "../types/category";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

type TxnRow = BankTransaction & { account_name: string };

// ── Classify Modal ────────────────────────────────────────────────────────────

type ClassifySplit = { category_id: number | null; amount: string; description: string };

function ClassifyModal({
  txn,
  categories,
  onDone,
  onClose,
}: {
  txn: TxnRow;
  categories: Category[];
  onDone: () => void;
  onClose: () => void;
}) {
  const isIncome = txn.amount > 0;
  const [lines, setLines] = useState<ClassifySplit[]>([
    { category_id: null, amount: String(Math.abs(txn.amount)), description: txn.description ?? "" },
  ]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const totalLines = lines.reduce((s, l) => s + (Number(l.amount) || 0), 0);
  const remaining = Math.abs(txn.amount) - totalLines;

  function addLine() {
    setLines((prev) => [...prev, { category_id: null, amount: remaining > 0 ? String(remaining.toFixed(2)) : "0", description: "" }]);
  }

  function removeLine(i: number) {
    setLines((prev) => prev.filter((_, idx) => idx !== i));
  }

  function setLine<K extends keyof ClassifySplit>(i: number, k: K, v: ClassifySplit[K]) {
    setLines((prev) => prev.map((l, idx) => idx === i ? { ...l, [k]: v } : l));
  }

  async function handleSave() {
    for (const l of lines) {
      if (!l.category_id) { setError("Select a category for every line."); return; }
      if (!Number(l.amount) || Number(l.amount) <= 0) { setError("Each line needs a positive amount."); return; }
    }
    if (Math.abs(remaining) > 0.01) { setError(`Lines total ${fmt(totalLines)} but transaction is ${fmt(Math.abs(txn.amount))} — adjust amounts.`); return; }

    setSaving(true);
    setError(null);
    try {
      const db = await getDb();
      // Find the bank_account_id from the transaction
      const bankAccountId = txn.bank_account_id;

      for (const l of lines) {
        const amount = isIncome ? Number(l.amount) : -Number(l.amount);
        await db.execute(
          `INSERT INTO income_batches (income_date, bank_account_id, category_id, amount, description)
           VALUES (?, ?, ?, ?, ?)`,
          [txn.transaction_date, bankAccountId, l.category_id, amount, l.description || txn.description || null]
        );
        const result = await db.select<{ id: number }[]>(
          "SELECT id FROM income_batches ORDER BY id DESC LIMIT 1"
        );
        if (result[0]) {
          await db.execute(
            `INSERT OR IGNORE INTO bank_transaction_links
               (bank_transaction_id, source_type, source_id)
             VALUES (?, 'INCOME_BATCH', ?)`,
            [txn.id, result[0].id]
          );
        }
      }
      await updateTransactionStatus(txn.id, "VALIDATED");
      onDone();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  const incomeCategories = categories.filter((c) => c.category_type === (isIncome ? "INCOME" : "EXPENSE"));

  return (
    <div className="space-y-4">
      <div className="p-3 bg-gray-50 rounded-lg text-sm">
        <div className="flex justify-between">
          <span className="text-gray-600">{txn.transaction_date} · {txn.account_name}</span>
          <span className={`font-mono font-semibold ${txn.amount >= 0 ? "text-green-700" : "text-red-600"}`}>
            {fmt(txn.amount)}
          </span>
        </div>
        {txn.description && <p className="text-xs text-gray-500 mt-1">{txn.description}</p>}
      </div>

      {error && <p className="text-sm text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}

      <div className="space-y-3">
        {lines.map((l, i) => (
          <div key={i} className="border border-gray-200 rounded-lg p-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-gray-500">Line {i + 1}</span>
              {lines.length > 1 && (
                <button onClick={() => removeLine(i)} className="text-xs text-red-500 hover:underline">Remove</button>
              )}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Category</label>
                <select
                  value={l.category_id ?? ""}
                  onChange={(e) => setLine(i, "category_id", e.target.value ? Number(e.target.value) : null)}
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">— Select —</option>
                  {incomeCategories.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Amount</label>
                <input
                  type="number"
                  step="0.01"
                  min="0.01"
                  value={l.amount}
                  onChange={(e) => setLine(i, "amount", e.target.value)}
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Description / Memo</label>
              <input
                type="text"
                value={l.description}
                onChange={(e) => setLine(i, "description", e.target.value)}
                placeholder={txn.description ?? ""}
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>
        ))}
      </div>

      {Math.abs(remaining) > 0.01 && (
        <p className="text-xs text-orange-600">
          {remaining > 0 ? `${fmt(remaining)} unallocated` : `${fmt(Math.abs(remaining))} over-allocated`}
        </p>
      )}

      <div className="flex items-center justify-between pt-2 border-t">
        <button
          onClick={addLine}
          className="text-xs text-blue-600 hover:underline"
        >
          + Add split line
        </button>
        <div className="flex gap-3">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">
            Cancel
          </button>
          <button
            onClick={() => void handleSave()}
            disabled={saving}
            className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Classify & Validate"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Manual Transaction Entry ──────────────────────────────────────────────────

function ManualEntryModal({
  bankAccounts,
  onDone,
  onClose,
}: {
  bankAccounts: BankAccount[];
  onDone: () => void;
  onClose: () => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const [date, setDate] = useState(today);
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [bankAccountId, setBankAccountId] = useState(bankAccounts[0]?.id ?? 0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    if (!date) { setError("Date is required."); return; }
    if (!amount || Number(amount) === 0) { setError("Amount is required (use negative for expense)."); return; }
    if (!bankAccountId) { setError("Select a bank account."); return; }
    setSaving(true);
    setError(null);
    try {
      const db = await getDb();
      await db.execute(
        `INSERT INTO bank_transactions
           (bank_account_id, transaction_date, amount, description, validation_status)
         VALUES (?, ?, ?, ?, 'UNVALIDATED')`,
        [bankAccountId, date, Number(amount), description || null]
      );
      onDone();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">Manually add a bank transaction not present in your imported statement.</p>
      {error && <p className="text-sm text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}

      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Bank Account</label>
        <select
          value={bankAccountId}
          onChange={(e) => setBankAccountId(Number(e.target.value))}
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {bankAccounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
        </select>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Date</label>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Amount (negative = expense)</label>
          <input
            type="number"
            step="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="e.g. 250.00 or -75.00"
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Description</label>
        <input
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="e.g. Manual adjustment"
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      <div className="flex justify-end gap-3 pt-2 border-t">
        <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">Cancel</button>
        <button
          onClick={() => void handleSave()}
          disabled={saving}
          className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Add Transaction"}
        </button>
      </div>
    </div>
  );
}

// ── Main Screen ───────────────────────────────────────────────────────────────

type ModalState =
  | { mode: "classify"; txn: TxnRow }
  | { mode: "manual" }
  | null;

export function BankPendingScreen() {
  const [transactions, setTransactions] = useState<TxnRow[]>([]);
  const [bankAccounts, setBankAccounts] = useState<BankAccount[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"UNVALIDATED" | "VALIDATED" | "all">("UNVALIDATED");
  const [accountFilter, setAccountFilter] = useState<number | "all">("all");
  const [modal, setModal] = useState<ModalState>(null);
  const [bulkWorking, setBulkWorking] = useState(false);

  const load = useCallback(async () => {
    try {
      const [rows, accounts, cats] = await Promise.all([
        listAllBankTransactions({ limit: 500 }),
        listBankAccounts(),
        listCategories(),
      ]);
      setTransactions(rows as TxnRow[]);
      setBankAccounts(accounts);
      setCategories(cats);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function handleStatus(id: number, status: string) {
    await updateTransactionStatus(id, status);
    await load();
  }

  async function acceptAll() {
    const unvalidated = visible.filter((t) => t.validation_status === "UNVALIDATED");
    if (unvalidated.length === 0) return;
    if (!confirm(`Mark ${unvalidated.length} transactions as Validated?`)) return;
    setBulkWorking(true);
    try {
      const db = await getDb();
      for (const t of unvalidated) {
        await db.execute(
          "UPDATE bank_transactions SET validation_status = 'VALIDATED' WHERE id = ?",
          [t.id]
        );
      }
      await load();
    } finally {
      setBulkWorking(false);
    }
  }

  const visible = transactions
    .filter((t) => filter === "all" || t.validation_status === filter)
    .filter((t) => accountFilter === "all" || t.bank_account_id === accountFilter);

  const unvalidatedCount = visible.filter((t) => t.validation_status === "UNVALIDATED").length;

  return (
    <div className="p-8 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Pending Transactions</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Imported bank transactions awaiting validation or classification.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {unvalidatedCount > 0 && (
            <button
              onClick={() => void acceptAll()}
              disabled={bulkWorking}
              className="px-3 py-1.5 bg-green-600 text-white text-sm rounded-lg hover:bg-green-700 disabled:opacity-50"
            >
              {bulkWorking ? "Working…" : `Validate All (${unvalidatedCount})`}
            </button>
          )}
          <button
            onClick={() => setModal({ mode: "manual" })}
            className="px-3 py-1.5 bg-gray-700 text-white text-sm rounded-lg hover:bg-gray-800"
          >
            + Manual Entry
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-3 mb-4">
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value as typeof filter)}
          className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="UNVALIDATED">Unvalidated</option>
          <option value="VALIDATED">Validated</option>
          <option value="all">All</option>
        </select>
        <select
          value={accountFilter}
          onChange={(e) => setAccountFilter(e.target.value === "all" ? "all" : Number(e.target.value))}
          className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="all">All Accounts</option>
          {bankAccounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
        </select>
        <span className="self-center text-sm text-gray-400">{visible.length} shown</span>
      </div>

      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {!loading && !error && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Date</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Account</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Description</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Status</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {visible.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-gray-400 text-sm">
                    {filter === "UNVALIDATED"
                      ? "No unvalidated transactions. Import a bank statement first."
                      : "No transactions found."}
                  </td>
                </tr>
              )}
              {visible.map((t) => (
                <tr key={t.id}>
                  <td className="px-4 py-2 text-gray-600">{t.transaction_date}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{t.account_name}</td>
                  <td className="px-4 py-2 text-gray-700">
                    {t.description ?? "—"}
                    {t.memo && <span className="ml-2 text-xs text-gray-400">{t.memo}</span>}
                  </td>
                  <td className={`px-4 py-2 text-right font-mono ${t.amount < 0 ? "text-red-600" : "text-green-700"}`}>
                    {fmt(t.amount)}
                  </td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      t.validation_status === "VALIDATED"
                        ? "bg-green-100 text-green-700"
                        : "bg-yellow-100 text-yellow-700"
                    }`}>
                      {t.validation_status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right whitespace-nowrap space-x-2">
                    {t.validation_status === "UNVALIDATED" && (
                      <button
                        onClick={() => setModal({ mode: "classify", txn: t })}
                        className="text-xs text-blue-600 hover:underline"
                      >
                        Classify
                      </button>
                    )}
                    {t.validation_status === "UNVALIDATED" && (
                      <button
                        onClick={() => void handleStatus(t.id, "VALIDATED")}
                        className="text-xs text-green-600 hover:underline"
                      >
                        Validate
                      </button>
                    )}
                    {t.validation_status === "VALIDATED" && (
                      <button
                        onClick={() => void handleStatus(t.id, "UNVALIDATED")}
                        className="text-xs text-gray-500 hover:underline"
                      >
                        Unvalidate
                      </button>
                    )}
                    <button
                      onClick={() => void handleStatus(t.id, "IGNORED")}
                      className="text-xs text-red-500 hover:underline"
                    >
                      Ignore
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modal?.mode === "classify" && (
        <Modal
          title="Classify Transaction"
          onClose={() => setModal(null)}
        >
          <ClassifyModal
            txn={modal.txn}
            categories={categories}
            onDone={() => { setModal(null); void load(); }}
            onClose={() => setModal(null)}
          />
        </Modal>
      )}

      {modal?.mode === "manual" && (
        <Modal
          title="Add Manual Transaction"
          onClose={() => setModal(null)}
        >
          <ManualEntryModal
            bankAccounts={bankAccounts}
            onDone={() => { setModal(null); void load(); }}
            onClose={() => setModal(null)}
          />
        </Modal>
      )}
    </div>
  );
}
