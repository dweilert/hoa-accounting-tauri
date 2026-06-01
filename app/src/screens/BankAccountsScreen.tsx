import { useEffect, useState, useCallback } from "react";
import { Modal } from "../components/Modal";
import {
  listBankAccounts,
  insertBankAccount,
  updateBankAccount,
  deleteBankAccount,
  hasTransactions,
} from "../repositories/bankAccountRepo";
import {
  BankAccountFormSchema,
  type BankAccount,
  type BankAccountFormValues,
  type AccountTypeValue,
  type FundCodeValue,
} from "../types/bankAccount";

// ── Helpers ───────────────────────────────────────────────────────────────────

const ACCOUNT_TYPE_LABELS: Record<AccountTypeValue, string> = {
  CHECKING: "Checking",
  SAVINGS: "Savings",
  MONEY_MARKET: "Money Market",
  OTHER: "Other",
};

const FUND_COLORS: Record<FundCodeValue, string> = {
  OPERATING: "bg-gray-100 text-gray-600",
  RESERVE: "bg-yellow-100 text-yellow-700",
  SPECIAL: "bg-purple-100 text-purple-700",
};

function fmt(amount: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(amount);
}

// ── Form ─────────────────────────────────────────────────────────────────────

type FormProps = {
  initial?: BankAccount;
  onSave: (v: BankAccountFormValues) => Promise<void>;
  onCancel: () => void;
};

function BankAccountForm({ initial, onSave, onCancel }: FormProps) {
  const isEdit = !!initial;
  const [values, setValues] = useState<BankAccountFormValues>({
    account_name: initial?.account_name ?? "",
    institution_name: initial?.institution_name ?? "",
    account_last4: initial?.account_last4 ?? "",
    account_type: initial?.account_type ?? "CHECKING",
    fund_code: initial?.fund_code ?? "OPERATING",
    active_flag: initial?.active_flag ?? 1,
    opening_balance: initial?.opening_balance ?? 0,
    opening_balance_date: initial?.opening_balance_date ?? "",
  });
  const [errors, setErrors] = useState<Partial<Record<string, string>>>({});
  const [saving, setSaving] = useState(false);

  const set = <K extends keyof BankAccountFormValues>(k: K, v: BankAccountFormValues[K]) =>
    setValues((p) => ({ ...p, [k]: v }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const result = BankAccountFormSchema.safeParse(values);
    if (!result.success) {
      const errs: typeof errors = {};
      for (const issue of result.error.issues) errs[String(issue.path[0])] = issue.message;
      setErrors(errs);
      return;
    }
    setSaving(true);
    try { await onSave(result.data); } finally { setSaving(false); }
  }

  const inp = (
    label: string,
    field: keyof BankAccountFormValues,
    opts?: { placeholder?: string; type?: string; required?: boolean }
  ) => (
    <div>
      <label className="block text-xs font-medium text-gray-700 mb-1">
        {label}{opts?.required && <span className="text-red-500 ml-0.5">*</span>}
      </label>
      <input
        type={opts?.type ?? "text"}
        value={String(values[field] ?? "")}
        onChange={(e) => set(field, e.target.value as BankAccountFormValues[typeof field])}
        placeholder={opts?.placeholder}
        className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      {errors[field] && <p className="mt-1 text-xs text-red-600">{errors[field]}</p>}
    </div>
  );

  const sel = <K extends keyof BankAccountFormValues>(
    label: string,
    field: K,
    options: [string, string][],
    required?: boolean
  ) => (
    <div>
      <label className="block text-xs font-medium text-gray-700 mb-1">
        {label}{required && <span className="text-red-500 ml-0.5">*</span>}
      </label>
      <select
        value={String(values[field] ?? "")}
        onChange={(e) => set(field, e.target.value as BankAccountFormValues[K])}
        className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      >
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
      {errors[field] && <p className="mt-1 text-xs text-red-600">{errors[field]}</p>}
    </div>
  );

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {inp("Account Name", "account_name", { required: true, placeholder: "e.g. HOA Operating Checking" })}
      {inp("Institution", "institution_name", { required: true, placeholder: "e.g. First National Bank" })}

      <div className="grid grid-cols-2 gap-4">
        {sel("Account Type", "account_type", [
          ["CHECKING", "Checking"],
          ["SAVINGS", "Savings"],
          ["MONEY_MARKET", "Money Market"],
          ["OTHER", "Other"],
        ], true)}
        {sel("Fund", "fund_code", [
          ["OPERATING", "Operating"],
          ["RESERVE", "Reserve"],
          ["SPECIAL", "Special"],
        ], true)}
      </div>

      {inp("Last 4 Digits", "account_last4", { placeholder: "1234" })}

      <div className="grid grid-cols-2 gap-4">
        {inp("Opening Balance", "opening_balance", { type: "number", placeholder: "0.00" })}
        {inp("Opening Balance Date", "opening_balance_date", { type: "date" })}
      </div>

      {isEdit && (
        <div className="flex gap-4">
          {([1, 0] as const).map((v) => (
            <label key={v} className="flex items-center gap-2 text-sm cursor-pointer">
              <input
                type="radio"
                name="active_flag"
                value={v}
                checked={values.active_flag === v}
                onChange={() => set("active_flag", v)}
              />
              {v === 1 ? "Active" : "Inactive"}
            </label>
          ))}
        </div>
      )}

      <div className="flex justify-end gap-3 pt-2 border-t">
        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : isEdit ? "Save Changes" : "Add Account"}
        </button>
      </div>
    </form>
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

type ModalState = { mode: "add" } | { mode: "edit"; account: BankAccount } | null;

export function BankAccountsScreen() {
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalState>(null);
  const [showInactive, setShowInactive] = useState(false);

  const load = useCallback(async () => {
    try { setAccounts(await listBankAccounts()); }
    catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function handleSave(values: BankAccountFormValues) {
    if (modal?.mode === "edit") {
      await updateBankAccount(modal.account.id, values);
    } else {
      await insertBankAccount(values);
    }
    setModal(null);
    await load();
  }

  async function handleDelete(acct: BankAccount) {
    if (await hasTransactions(acct.id)) {
      alert("This account has transactions. Deactivate it instead of deleting.");
      return;
    }
    if (!confirm(`Delete "${acct.account_name}"? This cannot be undone.`)) return;
    try { await deleteBankAccount(acct.id); await load(); }
    catch (e) { alert(String(e)); }
  }

  const visible = showInactive ? accounts : accounts.filter((a) => a.active_flag);
  const inactiveCount = accounts.filter((a) => !a.active_flag).length;

  return (
    <div className="p-8 max-w-4xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Bank Accounts</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {accounts.filter((a) => a.active_flag).length} active
            {inactiveCount > 0 && ` · ${inactiveCount} inactive`}
          </p>
        </div>
        <div className="flex items-center gap-4">
          {inactiveCount > 0 && (
            <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
              <input
                type="checkbox"
                checked={showInactive}
                onChange={(e) => setShowInactive(e.target.checked)}
                className="rounded"
              />
              Show inactive
            </label>
          )}
          <button
            onClick={() => setModal({ mode: "add" })}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
          >
            + Add Account
          </button>
        </div>
      </div>

      {loading && <p className="text-gray-400 text-sm">Loading…</p>}
      {error && <p className="text-red-600 text-sm">{error}</p>}

      {!loading && !error && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Account Name</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Institution</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Type</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Fund</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Opening Balance</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Status</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {visible.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-center text-gray-400 text-sm">
                    No bank accounts yet. Click "Add Account" to get started.
                  </td>
                </tr>
              )}
              {visible.map((acct) => (
                <tr key={acct.id} className={acct.active_flag ? "" : "opacity-50"}>
                  <td className="px-4 py-3">
                    <span className="font-medium text-gray-900">{acct.account_name}</span>
                    {acct.account_last4 && (
                      <span className="ml-2 text-xs text-gray-400">••••{acct.account_last4}</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-600">{acct.institution_name}</td>
                  <td className="px-4 py-3 text-gray-600 text-xs">
                    {ACCOUNT_TYPE_LABELS[acct.account_type]}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${FUND_COLORS[acct.fund_code]}`}>
                      {acct.fund_code}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-sm text-gray-700">
                    {fmt(acct.opening_balance)}
                    {acct.opening_balance_date && (
                      <span className="block text-xs text-gray-400 font-sans">{acct.opening_balance_date}</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      acct.active_flag ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"
                    }`}>
                      {acct.active_flag ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right space-x-2 whitespace-nowrap">
                    <button
                      onClick={() => setModal({ mode: "edit", account: acct })}
                      className="text-xs text-blue-600 hover:underline"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => handleDelete(acct)}
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
      )}

      {modal && (
        <Modal
          title={modal.mode === "add" ? "Add Bank Account" : `Edit — ${modal.mode === "edit" ? modal.account.account_name : ""}`}
          onClose={() => setModal(null)}
        >
          {modal.mode === "edit" ? (
            <BankAccountForm initial={modal.account} onSave={handleSave} onCancel={() => setModal(null)} />
          ) : (
            <BankAccountForm onSave={handleSave} onCancel={() => setModal(null)} />
          )}
        </Modal>
      )}
    </div>
  );
}
