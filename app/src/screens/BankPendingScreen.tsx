import { useEffect, useState, useCallback } from "react";
import { PageLayout } from "../components/PageLayout";
import { listAllBankTransactions, updateTransactionStatus } from "../repositories/reconciliationRepo";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import { listCategories } from "../repositories/categoryRepo";
import {
  applyRulesToPending,
  revertValidated,
  listTransactionRules,
  testRuleAgainstDescription,
  type TransactionRule,
} from "../repositories/transactionRuleRepo";
import { listCandidateDepositBatches, linkDepositToTxn, autoMatchDeposits } from "../repositories/depositRepo";
import type { CandidateDepositBatch } from "../repositories/depositRepo";
import { getDb } from "../lib/db";
import { Modal } from "../components/Modal";
import type { BankTransaction } from "../types/reconciliation";
import type { BankAccount } from "../types/bankAccount";
import type { Category } from "../types/category";
import { appAlert, appConfirm } from "../components/AppDialogs";

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

// ── Per-row rule analysis ─────────────────────────────────────────────────────

type RuleAnalysis = ReturnType<typeof testRuleAgainstDescription> & {
  noConditions: boolean;
  descPasses: boolean;
  amtPasses: boolean;
};

type TxnAnalysis = {
  rules: RuleAnalysis[];
  deposits: CandidateDepositBatch[] | null; // null = not a positive txn
  loading: boolean;
};

function analyzeRule(rule: TransactionRule, description: string, amount: number): RuleAnalysis {
  const base = testRuleAgainstDescription(rule, description, amount);
  const noConditions = !rule.description_contains && rule.amount_min === null && rule.amount_max === null;
  const descPasses = !rule.description_contains ||
    description.toLowerCase().includes(rule.description_contains.toLowerCase());
  const amtMinPasses = rule.amount_min === null || amount >= rule.amount_min;
  const amtMaxPasses = rule.amount_max === null || amount <= rule.amount_max;
  return { ...base, noConditions, descPasses, amtPasses: amtMinPasses && amtMaxPasses };
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
  const [filter, setFilter] = useState<"UNVALIDATED" | "VALIDATED" | "IGNORED" | "all" | "UNMATCHED_TRIAL">("UNVALIDATED");
  const [accountFilter, setAccountFilter] = useState<number | "all">("all");
  const [modal, setModal] = useState<ModalState>(null);
  const [bulkWorking, setBulkWorking] = useState(false);
  type TrialResult = { rule_name: string; auto: boolean; action_type: string };
  const [trialMap, setTrialMap] = useState<Map<number, TrialResult> | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [applying, setApplying] = useState(false);
  const [cachedRules, setCachedRules] = useState<TransactionRule[] | null>(null);
  const [expandedTxnId, setExpandedTxnId] = useState<number | null>(null);
  const [txnAnalysis, setTxnAnalysis] = useState<Map<number, TxnAnalysis>>(new Map());

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
    if (!await appConfirm(`Mark ${unvalidated.length} transactions as Validated?`)) return;
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

  async function handleDryRun() {
    setApplying(true);
    try {
      const acct = accountFilter === "all" ? undefined : accountFilter;
      const result = await applyRulesToPending(acct, true);
      const map = new Map<number, TrialResult>();
      for (const d of result.details) {
        map.set(d.txn_id, { rule_name: d.rule_name, auto: d.auto, action_type: d.action_type });
      }
      setTrialMap(map);
      setSelectedIds(new Set(result.details.filter(d => d.auto).map(d => d.txn_id)));
    } finally {
      setApplying(false);
    }
  }

  async function handleApplySelected() {
    if (!trialMap || selectedIds.size === 0) return;
    setApplying(true);
    try {
      const acct = accountFilter === "all" ? undefined : accountFilter;
      const result = await applyRulesToPending(acct, false, selectedIds);
      setTrialMap(null);
      setSelectedIds(new Set());
      await load();
      if (result.errors.length > 0) {
        await appAlert(`Applied ${result.matched} transactions.\n\nERRORS (${result.errors.length}):\n` +
          result.errors.slice(0, 5).map(e => `txn ${e.txn_id} / ${e.rule_name}: ${e.error}`).join("\n"));
      } else {
        await appAlert(`Applied: ${result.matched} classified, ${result.reviewed} flagged for review.`);
      }
    } catch (err) {
      console.error("Apply rules failed:", err);
      await appAlert(`Apply rules failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setApplying(false);
    }
  }

  async function handleRevertValidated() {
    const acct = accountFilter === "all" ? undefined : accountFilter;
    const processed = transactions.filter(
      (t) => (t.validation_status === "VALIDATED" || t.validation_status === "IGNORED") &&
             (accountFilter === "all" || t.bank_account_id === accountFilter)
    ).length;
    if (processed === 0) { await appAlert("No VALIDATED or IGNORED transactions to revert."); return; }
    if (!await appConfirm(`Revert ${processed} VALIDATED/IGNORED transaction(s) back to UNVALIDATED?`)) return;
    setBulkWorking(true);
    try {
      await revertValidated(acct);
      await load();
    } finally {
      setBulkWorking(false);
    }
  }

  async function handleAutoMatchDeposits() {
    setBulkWorking(true);
    try {
      const acct = accountFilter === "all" ? undefined : accountFilter;
      const preview = await autoMatchDeposits(acct, true);
      if (preview.matched === 0) {
        await appAlert(`No unambiguous deposit matches found.\n${preview.total} positive UNVALIDATED transactions scanned.\n${preview.skipped} had multiple qualifying candidates (ambiguous).`);
        return;
      }
      const lines = preview.details.map(
        (d) => `  • $${d.amount.toFixed(2)} on ${d.txn_date} → batch ${d.batch_date} (${d.reason})`
      ).join("\n");
      if (!await appConfirm(`Auto-match ${preview.matched} deposit(s)?\n\n${lines}\n\nClick OK to link and mark VALIDATED.`)) return;
      const result = await autoMatchDeposits(acct, false);
      await load();
      await appAlert(`Linked ${result.matched} deposit batch(es) to OFX transactions and marked VALIDATED.`);
    } catch (err) {
      await appAlert(`Auto-match failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBulkWorking(false);
    }
  }

  async function handleTestRow(txn: TxnRow) {
    if (expandedTxnId === txn.id) { setExpandedTxnId(null); return; }
    setExpandedTxnId(txn.id);
    setTxnAnalysis((prev) => new Map(prev).set(txn.id, { rules: [], deposits: null, loading: true }));

    let rules = cachedRules;
    if (!rules) {
      rules = await listTransactionRules();
      setCachedRules(rules);
    }

    const ruleResults = rules
      .filter((r) => r.active_flag === 1)
      .map((r) => analyzeRule(r, txn.description ?? "", txn.amount));

    // Sort: full match → description-only near-miss → amount-only near-miss → no-conditions warning → no match
    ruleResults.sort((a, b) => {
      const score = (r: RuleAnalysis) =>
        r.matches ? 4 : r.noConditions ? 3 : r.descPasses && !r.amtPasses ? 2 : r.amtPasses && !r.descPasses ? 1 : 0;
      return score(b) - score(a);
    });

    let deposits: CandidateDepositBatch[] | null = null;
    if (txn.amount > 0) {
      // Use wide date tolerance (730 days) so all amount-matching deposits show in detail
      deposits = await listCandidateDepositBatches(txn.bank_account_id, txn.amount, txn.transaction_date, 730);
    }

    setTxnAnalysis((prev) => new Map(prev).set(txn.id, { rules: ruleResults, deposits, loading: false }));
  }

  const visible = transactions
    .filter((t) => {
      if (filter === "UNMATCHED_TRIAL") return trialMap !== null && !trialMap.has(t.id) && t.validation_status === "UNVALIDATED";
      return filter === "all" || t.validation_status === filter;
    })
    .filter((t) => accountFilter === "all" || t.bank_account_id === accountFilter);

  const unvalidatedCount = visible.filter((t) => t.validation_status === "UNVALIDATED").length;

  return (
    <PageLayout
      title="Bank Pending"
      subtitle="Classify imported bank transactions."
      helpId="bankPending"
      actions={
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => void handleDryRun()}
            disabled={applying || bulkWorking}
            className="px-3 py-1.5 text-white text-sm rounded-lg disabled:opacity-50"
            style={{ backgroundColor: "#2f6046" }}
          >
            {applying ? "Running…" : "Apply Rules (Trial)"}
          </button>
          {trialMap && selectedIds.size > 0 && (
            <button
              onClick={() => void handleApplySelected()}
              disabled={applying}
              className="px-3 py-1.5 bg-green-600 text-white text-sm rounded-lg hover:bg-green-700 disabled:opacity-50"
            >
              {applying ? "Applying…" : `Apply Selected (${selectedIds.size})`}
            </button>
          )}
          {trialMap && (
            <button
              onClick={() => { setTrialMap(null); setSelectedIds(new Set()); setFilter("UNVALIDATED"); }}
              className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 text-gray-600 hover:bg-gray-50"
            >
              Clear Trial
            </button>
          )}
          <button
            onClick={() => void handleAutoMatchDeposits()}
            disabled={applying || bulkWorking}
            className="px-3 py-1.5 text-white text-sm rounded-lg disabled:opacity-50"
            style={{ backgroundColor: "#0f766e" }}
          >
            {bulkWorking ? "Matching…" : "Auto-Match Deposits"}
          </button>
          {unvalidatedCount > 0 && (
            <button
              onClick={() => void acceptAll()}
              disabled={bulkWorking || applying}
              className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {bulkWorking ? "Working…" : `Validate All (${unvalidatedCount})`}
            </button>
          )}
          <button
            onClick={() => void handleRevertValidated()}
            disabled={bulkWorking || applying}
            className="px-3 py-1.5 text-sm rounded-lg border disabled:opacity-50"
            style={{ borderColor: "#c9c1ad", color: "#5f5d54" }}
          >
            Revert Validated
          </button>
          <button
            onClick={() => setModal({ mode: "manual" })}
            className="px-3 py-1.5 bg-gray-700 text-white text-sm rounded-lg hover:bg-gray-800"
          >
            + Manual Entry
          </button>
        </div>
      }
    >
      <div>

      {/* Filters */}
      <div className="flex gap-3 mb-4">
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value as typeof filter)}
          className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="UNVALIDATED">Unvalidated</option>
          <option value="VALIDATED">Validated</option>
          <option value="IGNORED">Ignored</option>
          <option value="all">All</option>
          {trialMap && <option value="UNMATCHED_TRIAL">Unmatched (trial)</option>}
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
                <th className="px-2 py-2 w-8" />
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Date</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Account</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Description</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Status</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {visible.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-gray-400 text-sm">
                    {filter === "UNVALIDATED"
                      ? "No unvalidated transactions. Import a bank statement first."
                      : "No transactions found."}
                  </td>
                </tr>
              )}
              {visible.map((t) => {
                const isExpanded = expandedTxnId === t.id;
                const analysis = txnAnalysis.get(t.id);
                const trial = trialMap?.get(t.id);
                return (
                  <>
                    <tr key={t.id} className={isExpanded ? "bg-indigo-50" : trial?.auto ? "bg-green-50" : trial ? "bg-amber-50" : undefined}>
                      <td className="px-2 py-2">
                        {trial && (
                          <input
                            type="checkbox"
                            checked={selectedIds.has(t.id)}
                            onChange={(e) => {
                              const next = new Set(selectedIds);
                              e.target.checked ? next.add(t.id) : next.delete(t.id);
                              setSelectedIds(next);
                            }}
                          />
                        )}
                      </td>
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
                        {trial ? (
                          <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                            trial.auto && trial.action_type === "IGNORE" ? "bg-gray-200 text-gray-700"
                            : trial.auto && trial.action_type === "CATEGORIZE" ? "bg-green-100 text-green-800"
                            : trial.auto && trial.action_type === "LINK_EXPENSE" ? "bg-purple-100 text-purple-800"
                            : trial.auto && trial.action_type === "DEPOSIT_MATCH" ? "bg-teal-100 text-teal-800"
                            : "bg-amber-100 text-amber-800"
                          }`}>
                            {trial.rule_name} / {trial.auto ? trial.action_type.replace(/_/g, " ") : "REVIEW FIRST"}
                          </span>
                        ) : (
                          <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                            t.validation_status === "VALIDATED"
                              ? "bg-green-100 text-green-700"
                              : t.validation_status === "IGNORED"
                              ? "bg-gray-200 text-gray-600"
                              : "bg-yellow-100 text-yellow-700"
                          }`}>
                            {t.validation_status}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-2 text-right whitespace-nowrap space-x-2">
                        <button
                          onClick={() => void handleTestRow(t)}
                          className="text-xs font-medium hover:underline"
                          style={{ color: isExpanded ? "#2a6b5e" : "#6366f1" }}
                          title="Test rules and find matching deposits"
                        >
                          {isExpanded ? "▲ Close" : "▼ Test"}
                        </button>
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
                        {(t.validation_status === "VALIDATED" || t.validation_status === "IGNORED") && (
                          <button
                            onClick={() => void handleStatus(t.id, "UNVALIDATED")}
                            className="text-xs text-gray-500 hover:underline"
                          >
                            Unvalidate
                          </button>
                        )}
                        {t.validation_status !== "IGNORED" && (
                          <button
                            onClick={() => void handleStatus(t.id, "IGNORED")}
                            className="text-xs text-red-500 hover:underline"
                          >
                            Ignore
                          </button>
                        )}
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr key={`${t.id}-analysis`}>
                        <td colSpan={7} className="px-0 py-0 bg-indigo-50 border-b border-indigo-200">
                          {/* OFX raw data — available immediately, no query needed */}
                          <div className="px-5 py-3 border-b border-indigo-200 bg-indigo-100">
                            <p className="text-xs font-semibold text-indigo-800 mb-2">OFX / Bank Record</p>
                            <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
                              <div className="flex gap-2">
                                <dt className="text-indigo-600 font-medium shrink-0">FITID</dt>
                                <dd className="font-mono text-gray-700 truncate">{t.fitid ?? "—"}</dd>
                              </div>
                              <div className="flex gap-2">
                                <dt className="text-indigo-600 font-medium shrink-0">OFX Type</dt>
                                <dd className="text-gray-700">{t.transaction_type ?? "—"}</dd>
                              </div>
                              <div className="flex gap-2">
                                <dt className="text-indigo-600 font-medium shrink-0">Description</dt>
                                <dd className="text-gray-700 break-all">{t.description ?? "—"}</dd>
                              </div>
                              <div className="flex gap-2">
                                <dt className="text-indigo-600 font-medium shrink-0">Memo</dt>
                                <dd className="font-mono text-gray-600 truncate">{t.memo ?? "—"}</dd>
                              </div>
                              <div className="flex gap-2">
                                <dt className="text-indigo-600 font-medium shrink-0">Import batch</dt>
                                <dd className="text-gray-600">{t.import_batch_id ?? "—"}</dd>
                              </div>
                              <div className="flex gap-2">
                                <dt className="text-indigo-600 font-medium shrink-0">Imported</dt>
                                <dd className="text-gray-600">{t.created_at?.slice(0, 10) ?? "—"}</dd>
                              </div>
                            </dl>
                          </div>

                          {analysis?.loading ? (
                            <p className="px-6 py-3 text-xs text-indigo-500">Analyzing rules…</p>
                          ) : analysis ? (
                            <div className="px-5 py-3 space-y-4">

                              {/* ── Rule matches ── */}
                              <div>
                                <p className="text-xs font-semibold text-indigo-800 mb-2">
                                  Rule Analysis — "{t.description}" / {fmt(t.amount)}
                                </p>
                                {analysis.rules.length === 0 ? (
                                  <p className="text-xs text-gray-500">No active rules.</p>
                                ) : (
                                  <div className="space-y-1">
                                    {analysis.rules.map((r) => {
                                      let bg = "bg-gray-100 text-gray-500";
                                      let badge = "✗ NO MATCH";
                                      if (r.matches) { bg = "bg-green-50 border border-green-200 text-green-800"; badge = "✓ MATCH"; }
                                      else if (r.noConditions) { bg = "bg-red-50 border border-red-200 text-red-800"; badge = "⚠ CATCH-ALL"; }
                                      else if (r.descPasses && !r.amtPasses) { bg = "bg-amber-50 border border-amber-200 text-amber-800"; badge = "≈ DESC MATCH"; }
                                      else if (r.amtPasses && !r.descPasses) { bg = "bg-blue-50 border border-blue-200 text-blue-700"; badge = "≈ AMT MATCH"; }
                                      return (
                                        <div key={r.ruleId} className={`flex items-start gap-2 px-3 py-1.5 rounded text-xs ${bg}`}>
                                          <span className="font-bold shrink-0 w-24">{badge}</span>
                                          <span className="font-medium shrink-0 w-40 truncate">{r.ruleName}</span>
                                          <span className="text-xs opacity-75">{r.reason}</span>
                                        </div>
                                      );
                                    })}
                                  </div>
                                )}
                              </div>

                              {/* ── Deposit batch candidates (positive amounts only) ── */}
                              {analysis.deposits !== null && (
                                <div>
                                  {/* Extract check number from "Name - NNNN — Teller Deposit" pattern */}
                                  {(() => {
                                    const m = (t.description ?? "").match(/^\w+\s*-\s*(\d+)\s*[—-]/);
                                    return m ? (
                                      <p className="text-xs text-teal-700 mb-1 font-medium">
                                        Check # <strong>{m[1]}</strong> parsed from OFX description — use this when recording the matching payment.
                                      </p>
                                    ) : null;
                                  })()}
                                  <p className="text-xs font-semibold text-indigo-800 mb-2">
                                    Posted Deposit Batches — same account, ±5% amount, any date.
                                    {" "}<span className="font-normal text-indigo-600">Likely Match = unique amount <em>or</em> within 2 days. All unlinked deposits with matching amount shown.</span>
                                  </p>
                                  {analysis.deposits.length === 0 ? (
                                    <p className="text-xs text-orange-700">
                                      No matching deposit batches found. The deposit may not have been recorded yet, or the date/amount differs beyond tolerance.
                                    </p>
                                  ) : (
                                    <table className="w-full text-xs">
                                      <thead>
                                        <tr className="text-indigo-700">
                                          <th className="text-left py-1 pr-3 font-medium">Deposit Date</th>
                                          <th className="text-right py-1 pr-3 font-medium">Amount</th>
                                          <th className="text-right py-1 pr-3 font-medium">Payments</th>
                                          <th className="text-left py-1 pr-3 font-medium">Status</th>
                                          <th className="text-right py-1 pr-3 font-medium">Days off</th>
                                          <th className="text-left py-1 pr-3 font-medium">Match</th>
                                          <th className="text-left py-1 font-medium">OFX Link</th>
                                        </tr>
                                      </thead>
                                      <tbody>
                                        {analysis.deposits.map((d) => {
                                          const likelyMatch = d.same_amount_count === 1 || d.days_diff <= 2;
                                          return (
                                          <tr key={d.id} className={`border-t border-indigo-100 hover:bg-indigo-100 ${likelyMatch ? "bg-teal-50" : ""}`}>
                                            <td className="py-1 pr-3 text-gray-700">{d.deposit_date}</td>
                                            <td className={`py-1 pr-3 text-right font-mono font-medium ${Math.abs(d.amount_diff) < 0.01 ? "text-green-700" : "text-gray-800"}`}>
                                              {fmt(d.total_amount)}
                                            </td>
                                            <td className="py-1 pr-3 text-right text-gray-500">{d.check_count}</td>
                                            <td className="py-1 pr-3">
                                              <span className={`px-1.5 py-0.5 rounded font-medium ${d.status === "POSTED" ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"}`}>
                                                {d.status}
                                              </span>
                                            </td>
                                            <td className="py-1 pr-3 text-right text-gray-500">{Math.round(d.days_diff)}</td>
                                            <td className="py-1 pr-3">
                                              {likelyMatch ? (
                                                <span className="px-1.5 py-0.5 rounded text-xs font-medium bg-teal-100 text-teal-800">
                                                  {d.same_amount_count === 1 && d.days_diff <= 2 ? "Unique + Close" : d.same_amount_count === 1 ? "Unique amt" : "≤ 2 days"}
                                                </span>
                                              ) : (
                                                <span className="text-gray-400 text-xs">—</span>
                                              )}
                                            </td>
                                            <td className="py-1">
                                              {d.bank_transaction_id === t.id
                                                ? <span className="text-teal-700 font-medium text-xs">linked ✓</span>
                                                : d.bank_transaction_id
                                                  ? <span className="text-orange-600 text-xs">txn #{d.bank_transaction_id}</span>
                                                  : (
                                                    <button
                                                      className="px-2 py-0.5 text-xs rounded font-medium bg-teal-600 text-white hover:bg-teal-700"
                                                      onClick={async () => {
                                                        await linkDepositToTxn(d.id, t.id);
                                                        await updateTransactionStatus(t.id, "VALIDATED");
                                                        await load();
                                                        // Refresh analysis to show new link state
                                                        setTxnAnalysis((prev) => {
                                                          const next = new Map(prev);
                                                          next.delete(t.id);
                                                          return next;
                                                        });
                                                        setExpandedTxnId(null);
                                                      }}
                                                    >
                                                      Link →
                                                    </button>
                                                  )}
                                            </td>
                                          </tr>
                                          );
                                        })}
                                      </tbody>
                                    </table>
                                  )}
                                </div>
                              )}
                            </div>
                          ) : null}
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
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
    </PageLayout>
  );
}
