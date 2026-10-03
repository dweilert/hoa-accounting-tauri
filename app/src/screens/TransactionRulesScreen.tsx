import { useEffect, useState, useCallback, useMemo } from "react";
import { Modal } from "../components/Modal";
import { PageLayout } from "../components/PageLayout";
import {
  listTransactionRules,
  insertTransactionRule,
  updateTransactionRule,
  toggleRuleActive,
  deleteTransactionRule,
  testRuleAgainstDescription,
  checkRuleConflicts,
  type TransactionRule,
  type TransactionRuleFormValues,
  type RuleConflict,
} from "../repositories/transactionRuleRepo";
import { listCategories } from "../repositories/categoryRepo";
import { listVendors } from "../repositories/vendorRepo";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import type { Category } from "../types/category";
import type { Vendor } from "../types/vendor";
import type { BankAccount } from "../types/bankAccount";
import { appAlert, appConfirm } from "../components/AppDialogs";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

const ACTION_TYPES = [
  { value: "CATEGORIZE", label: "Categorize as Income" },
  { value: "LINK_EXPENSE", label: "Link to Vendor Expense" },
  { value: "IGNORE", label: "Auto-Ignore (bank fee, etc.)" },
];

const CONFIDENCE_MODES = [
  { value: "REVIEW_FIRST", label: "Review First" },
  { value: "AUTO_POST", label: "Auto-Post" },
];

const BLANK_FORM: TransactionRuleFormValues = {
  rule_name: "",
  description_contains: "",
  amount_min: "",
  amount_max: "",
  transaction_type: "",
  action_type: "CATEGORIZE",
  category_id: null,
  vendor_id: null,
  bank_account_id: null,
  confidence_mode: "REVIEW_FIRST",
};

function RuleForm({
  initial,
  categories,
  vendors,
  bankAccounts,
  onSave,
  onCancel,
}: {
  initial?: TransactionRule | undefined;
  categories: Category[];
  vendors: Vendor[];
  bankAccounts: BankAccount[];
  onSave: (v: TransactionRuleFormValues) => Promise<void>;
  onCancel: () => void;
}) {
  const [values, setValues] = useState<TransactionRuleFormValues>(
    initial
      ? {
          rule_name: initial.rule_name,
          description_contains: initial.description_contains ?? "",
          amount_min: initial.amount_min !== null ? String(initial.amount_min) : "",
          amount_max: initial.amount_max !== null ? String(initial.amount_max) : "",
          transaction_type: initial.transaction_type ?? "",
          action_type: initial.action_type,
          category_id: initial.category_id,
          vendor_id: initial.vendor_id,
          bank_account_id: initial.bank_account_id ?? null,
          confidence_mode: initial.confidence_mode,
        }
      : BLANK_FORM
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflicts, setConflicts] = useState<RuleConflict[]>([]);

  const set = <K extends keyof TransactionRuleFormValues>(k: K, v: TransactionRuleFormValues[K]) =>
    setValues((p) => ({ ...p, [k]: v }));

  async function runConflictCheck(desc: string) {
    if (!desc.trim()) { setConflicts([]); return; }
    const found = await checkRuleConflicts(desc, initial?.id);
    setConflicts(found);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!values.rule_name.trim()) { setError("Rule name is required."); return; }
    const hasCondition =
      values.description_contains.trim() !== "" ||
      values.amount_min !== "" ||
      values.amount_max !== "";
    if (!hasCondition) {
      setError("At least one match condition is required (description, min amount, or max amount). A rule with no conditions matches every transaction and blocks all rules with higher IDs.");
      return;
    }
    // Re-check conflicts at save time; block on duplicates
    const liveConflicts = await checkRuleConflicts(values.description_contains, initial?.id);
    setConflicts(liveConflicts);
    if (liveConflicts.some((c) => c.kind === "duplicate")) {
      setError("Duplicate rule: another active rule already matches the same description. Edit or disable that rule first.");
      return;
    }
    setSaving(true);
    setError(null);
    try { await onSave(values); } catch (e) { setError(String(e)); setSaving(false); }
  }

  const incomeCategories = categories.filter((c) => c.category_type === "INCOME");

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && <p className="text-sm text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}

      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Rule Name <span className="text-red-500">*</span></label>
        <input
          type="text"
          value={values.rule_name}
          onChange={(e) => set("rule_name", e.target.value)}
          autoFocus
          placeholder="e.g. HOA Dues Payment"
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      <fieldset className="border border-gray-200 rounded-lg p-4">
        <legend className="text-xs font-semibold text-gray-500 px-1">Match Conditions (all must be true)</legend>
        <div className="space-y-3 mt-2">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Bank Account</label>
            <select
              value={values.bank_account_id ?? ""}
              onChange={(e) => set("bank_account_id", e.target.value ? Number(e.target.value) : null)}
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">— Any account —</option>
              {bankAccounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
            </select>
            <p className="mt-1 text-xs text-gray-400">Restrict rule to transactions from a specific account. Leave blank to match all accounts.</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Description Contains</label>
            <input
              type="text"
              value={values.description_contains}
              onChange={(e) => set("description_contains", e.target.value)}
              onBlur={(e) => void runConflictCheck(e.target.value)}
              placeholder="e.g. DUES, LANDSCAPING (case-insensitive)"
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <p className="mt-1 text-xs text-gray-400">
              If set, a matching description is sufficient to match this rule — amount filters are ignored.
            </p>
            {conflicts.length > 0 && (
              <div className="mt-2 space-y-1">
                {conflicts.map((c, i) => (
                  <div
                    key={i}
                    className={`rounded px-3 py-2 text-xs ${
                      c.kind === "duplicate"
                        ? "bg-red-50 border border-red-300 text-red-800"
                        : "bg-amber-50 border border-amber-300 text-amber-800"
                    }`}
                  >
                    <span className="font-semibold mr-1">
                      {c.kind === "duplicate" ? "⛔ Duplicate:" : "⚠ Conflict:"}
                    </span>
                    {c.message}
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Min Amount</label>
              <input
                type="number"
                step="0.01"
                value={values.amount_min}
                onChange={(e) => set("amount_min", e.target.value)}
                placeholder="No minimum"
                className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Max Amount</label>
              <input
                type="number"
                step="0.01"
                value={values.amount_max}
                onChange={(e) => set("amount_max", e.target.value)}
                placeholder="No maximum"
                className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>
        </div>
      </fieldset>

      <fieldset className="border border-gray-200 rounded-lg p-4">
        <legend className="text-xs font-semibold text-gray-500 px-1">Action</legend>
        <div className="space-y-3 mt-2">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Action Type</label>
            <select
              value={values.action_type}
              onChange={(e) => set("action_type", e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {ACTION_TYPES.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
            </select>
          </div>
          {values.action_type === "CATEGORIZE" && (
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Category</label>
              <select
                value={values.category_id ?? ""}
                onChange={(e) => set("category_id", e.target.value ? Number(e.target.value) : null)}
                className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">— Select category —</option>
                {incomeCategories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
          )}
          {values.action_type === "LINK_EXPENSE" && (
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Vendor</label>
              <select
                value={values.vendor_id ?? ""}
                onChange={(e) => set("vendor_id", e.target.value ? Number(e.target.value) : null)}
                className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">— Select vendor —</option>
                {vendors.map((v) => <option key={v.id} value={v.id}>{v.vendor_name}</option>)}
              </select>
            </div>
          )}
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Confidence</label>
            <select
              value={values.confidence_mode}
              onChange={(e) => set("confidence_mode", e.target.value as "REVIEW_FIRST" | "AUTO_POST")}
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {CONFIDENCE_MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
            <p className="mt-1 text-xs text-gray-400">
              {values.confidence_mode === "AUTO_POST"
                ? "Matching transactions will be classified automatically on import."
                : "Matching transactions will be flagged for review."}
            </p>
          </div>
        </div>
      </fieldset>

      <div className="flex justify-end gap-3 pt-2 border-t">
        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : initial ? "Save Changes" : "Create Rule"}
        </button>
      </div>
    </form>
  );
}

function RuleTester({ rules }: { rules: TransactionRule[] }) {
  const [testDesc, setTestDesc] = useState("");
  const [testAmt, setTestAmt] = useState("");
  const [results, setResults] = useState<ReturnType<typeof testRuleAgainstDescription>[]>([]);

  function runTest() {
    const amt = Number(testAmt) || 0;
    const r = rules
      .filter((rule) => rule.active_flag === 1)
      .map((rule) => testRuleAgainstDescription(rule, testDesc, amt));
    setResults(r);
  }

  return (
    <div className="bg-gray-50 border border-gray-200 rounded-xl p-5 mt-6">
      <h2 className="text-sm font-semibold text-gray-700 mb-3">Rule Tester</h2>
      <div className="flex gap-3 items-end">
        <div className="flex-1">
          <label className="block text-xs font-medium text-gray-600 mb-1">Transaction Description</label>
          <input
            type="text"
            value={testDesc}
            onChange={(e) => setTestDesc(e.target.value)}
            placeholder="e.g. DUES PAYMENT LOT 7"
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div className="w-32">
          <label className="block text-xs font-medium text-gray-600 mb-1">Amount</label>
          <input
            type="number"
            step="0.01"
            value={testAmt}
            onChange={(e) => setTestAmt(e.target.value)}
            placeholder="0.00"
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <button
          onClick={runTest}
          className="px-4 py-1.5 bg-gray-700 text-white text-sm rounded hover:bg-gray-800"
        >
          Test
        </button>
      </div>
      {results.length > 0 && (
        <div className="mt-3 space-y-1">
          {results.map((r) => (
            <div
              key={r.ruleId}
              className={`flex items-start gap-2 px-3 py-2 rounded text-xs ${
                r.matches ? "bg-green-50 text-green-800 border border-green-200" : "bg-gray-100 text-gray-500"
              }`}
            >
              <span className="font-bold shrink-0">{r.matches ? "✓ MATCH" : "✗"}</span>
              <span className="font-medium shrink-0">{r.ruleName}:</span>
              <span>{r.reason}</span>
            </div>
          ))}
          {results.every((r) => !r.matches) && (
            <p className="text-xs text-gray-500 mt-1">No active rules matched this transaction.</p>
          )}
        </div>
      )}
    </div>
  );
}

type RuleSortCol = "name" | "action" | "mode" | "hits";

function SortTh({ col, active, dir, onClick, children, right }: {
  col: RuleSortCol; active: RuleSortCol; dir: "asc" | "desc";
  onClick: (c: RuleSortCol) => void; children: React.ReactNode; right?: boolean;
}) {
  return (
    <th
      className={`px-4 py-2 text-xs font-medium text-gray-600 cursor-pointer select-none hover:text-gray-900 ${right ? "text-right" : "text-left"}`}
      onClick={() => onClick(col)}
    >
      {children}{active === col ? (dir === "asc" ? " ↑" : " ↓") : ""}
    </th>
  );
}

type ModalState = { mode: "add" } | { mode: "edit"; rule: TransactionRule } | null;

export function TransactionRulesScreen() {
  const [rules, setRules] = useState<TransactionRule[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [bankAccounts, setBankAccounts] = useState<BankAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalState>(null);
  const [sortCol, setSortCol] = useState<RuleSortCol>("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  function toggleSort(col: RuleSortCol) {
    if (col === sortCol) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortCol(col); setSortDir("asc"); }
  }

  const sorted = useMemo(() => {
    const cmp = (a: TransactionRule, b: TransactionRule): number => {
      let v = 0;
      if (sortCol === "name") v = a.rule_name.localeCompare(b.rule_name);
      else if (sortCol === "action") v = a.action_type.localeCompare(b.action_type);
      else if (sortCol === "mode") v = a.confidence_mode.localeCompare(b.confidence_mode);
      else if (sortCol === "hits") v = (a.match_count ?? 0) - (b.match_count ?? 0);
      return sortDir === "asc" ? v : -v;
    };
    return [...rules].sort(cmp);
  }, [rules, sortCol, sortDir]);

  const load = useCallback(async () => {
    try {
      const [r, c, v, a] = await Promise.all([
        listTransactionRules(),
        listCategories(),
        listVendors(),
        listBankAccounts(),
      ]);
      setRules(r);
      setCategories(c);
      setVendors(v);
      setBankAccounts(a);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function handleSave(values: TransactionRuleFormValues) {
    if (modal?.mode === "edit") {
      await updateTransactionRule(modal.rule.id, values);
    } else {
      await insertTransactionRule(values);
    }
    setModal(null);
    await load();
  }

  async function handleToggle(rule: TransactionRule) {
    await toggleRuleActive(rule.id, rule.active_flag === 0);
    await load();
  }

  async function handleDelete(rule: TransactionRule) {
    if (!await appConfirm(`Delete rule "${rule.rule_name}"?`)) return;
    try { await deleteTransactionRule(rule.id); await load(); }
    catch (e) { await appAlert(String(e)); }
  }

  return (
    <PageLayout
      title="Transaction Rules"
      subtitle="Auto-categorization rules for imported bank transactions."
      helpId="transactionRules"
      actions={
        <button
          onClick={() => setModal({ mode: "add" })}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
        >
          + New Rule
        </button>
      }
    >
      <div>
        {loading && <p className="text-sm text-gray-400">Loading…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}

        {!loading && !error && (
          <>
            {rules.some(r => r.active_flag === 1 && !r.description_contains && r.amount_min === null && r.amount_max === null) && (
              <div className="mb-4 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
                <strong>Warning:</strong> One or more active rules have no match conditions and will catch every transaction, blocking all rules that follow them (higher IDs).{" "}
                Rules affected:{" "}
                {rules
                  .filter(r => r.active_flag === 1 && !r.description_contains && r.amount_min === null && r.amount_max === null)
                  .map(r => <strong key={r.id}>{r.rule_name}</strong>)
                  .reduce<React.ReactNode[]>((acc, el, i) => i === 0 ? [el] : [...acc, ", ", el], [])}
                . Edit them to add at least one condition.
              </div>
            )}
            <div className="border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <SortTh col="name" active={sortCol} dir={sortDir} onClick={toggleSort}>Rule</SortTh>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Account</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Match</th>
                  <SortTh col="action" active={sortCol} dir={sortDir} onClick={toggleSort}>Action</SortTh>
                  <SortTh col="mode" active={sortCol} dir={sortDir} onClick={toggleSort}>Mode</SortTh>
                  <SortTh col="hits" active={sortCol} dir={sortDir} onClick={toggleSort} right>Hits</SortTh>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {sorted.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-gray-400 text-sm">
                      No rules yet. Create one to auto-classify imported transactions.
                    </td>
                  </tr>
                )}
                {sorted.map((r) => (
                  <tr key={r.id} className={r.active_flag === 0 ? "opacity-40" : ""}>
                    <td className="px-4 py-3">
                      <span className="font-medium text-gray-900">{r.rule_name}</span>
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {r.bank_account_name ? (
                        <span className="px-2 py-0.5 rounded font-medium bg-indigo-100 text-indigo-700">{r.bank_account_name}</span>
                      ) : (
                        <span className="text-gray-400">Any</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500">
                      {r.description_contains && <span>desc: <em>{r.description_contains}</em></span>}
                      {r.amount_min !== null && <span className="ml-1">≥{fmt(r.amount_min)}</span>}
                      {r.amount_max !== null && <span className="ml-1">≤{fmt(r.amount_max)}</span>}
                      {!r.description_contains && r.amount_min === null && r.amount_max === null && "—"}
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {r.action_type === "CATEGORIZE" && (
                        <span className="text-blue-700">{r.category_name ?? "— no category —"}</span>
                      )}
                      {r.action_type === "LINK_EXPENSE" && (
                        <span className="text-orange-700">{r.vendor_name ?? "— no vendor —"}</span>
                      )}
                      {r.action_type === "IGNORE" && (
                        <span className="text-gray-500">Auto-Ignore</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                        r.confidence_mode === "AUTO_POST"
                          ? "bg-green-100 text-green-700"
                          : "bg-yellow-100 text-yellow-700"
                      }`}>
                        {r.confidence_mode === "AUTO_POST" ? "Auto-Post" : "Review First"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-xs text-gray-400">{r.match_count}</td>
                    <td className="px-4 py-3 text-right whitespace-nowrap space-x-2">
                      <button
                        onClick={() => setModal({ mode: "edit", rule: r })}
                        className="text-xs text-blue-600 hover:underline"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => void handleToggle(r)}
                        className="text-xs text-gray-500 hover:underline"
                      >
                        {r.active_flag === 1 ? "Disable" : "Enable"}
                      </button>
                      <button
                        onClick={() => void handleDelete(r)}
                        className="text-xs text-red-500 hover:underline"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

            <RuleTester rules={rules} />
          </>
        )}

        {modal && (
          <Modal
            title={modal.mode === "add" ? "New Transaction Rule" : `Edit Rule: ${modal.mode === "edit" ? modal.rule.rule_name : ""}`}
            onClose={() => setModal(null)}
          >
            <RuleForm
              initial={modal.mode === "edit" ? modal.rule : undefined}
              categories={categories}
              vendors={vendors}
              bankAccounts={bankAccounts}
              onSave={handleSave}
              onCancel={() => setModal(null)}
            />
          </Modal>
        )}
      </div>
    </PageLayout>
  );
}
