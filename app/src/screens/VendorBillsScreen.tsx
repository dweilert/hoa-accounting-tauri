import { useEffect, useState, useCallback } from "react";
import { Modal } from "../components/Modal";
import {
  listVendorBills, insertVendorBill, updateVendorBill, voidBill,
  billHasPayments, listPaymentsForBill, insertBillPayment, deleteBillPayment,
} from "../repositories/vendorBillRepo";
import { listVendors } from "../repositories/vendorRepo";
import { listCategories } from "../repositories/categoryRepo";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import {
  VendorBillFormSchema, BillPaymentFormSchema,
  type VendorBill, type BillPayment,
  type VendorBillFormValues, type BillPaymentFormValues, type BillStatusValue,
} from "../types/vendorBill";
import type { Vendor } from "../types/vendor";
import type { Category } from "../types/category";
import type { BankAccount } from "../types/bankAccount";

// ── Helpers ───────────────────────────────────────────────────────────────────

const STATUS_COLORS: Record<BillStatusValue, string> = {
  OPEN:    "bg-blue-100 text-blue-700",
  PARTIAL: "bg-yellow-100 text-yellow-700",
  PAID:    "bg-green-100 text-green-700",
  VOID:    "bg-gray-100 text-gray-400",
};

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

// ── Bill Form ─────────────────────────────────────────────────────────────────

type BillFormProps = {
  initial?: VendorBill;
  vendors: Vendor[];
  categories: Category[];
  hasPayments?: boolean;
  onSave: (v: VendorBillFormValues) => Promise<void>;
  onCancel: () => void;
};

function BillForm({ initial, vendors, categories, hasPayments, onSave, onCancel }: BillFormProps) {
  const isEdit = !!initial;
  const [values, setValues] = useState<VendorBillFormValues>({
    vendor_id: initial?.vendor_id ?? 0,
    invoice_number: initial?.invoice_number ?? "",
    invoice_date: initial?.invoice_date ?? today(),
    due_date: initial?.due_date ?? "",
    amount: initial?.amount ?? 0,
    fund_code: initial?.fund_code ?? "OPERATING",
    category_id: initial?.category_id ?? null,
    description: initial?.description ?? "",
  });
  const [errors, setErrors] = useState<Partial<Record<string, string>>>({});
  const [saving, setSaving] = useState(false);

  const set = <K extends keyof VendorBillFormValues>(k: K, v: VendorBillFormValues[K]) =>
    setValues((p) => ({ ...p, [k]: v }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const result = VendorBillFormSchema.safeParse(values);
    if (!result.success) {
      const errs: typeof errors = {};
      for (const issue of result.error.issues) errs[String(issue.path[0])] = issue.message;
      setErrors(errs);
      return;
    }
    setSaving(true);
    try { await onSave(result.data); } finally { setSaving(false); }
  }

  const expenseCategories = categories.filter((c) => c.category_type === "EXPENSE");

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Vendor <span className="text-red-500">*</span></label>
        <select
          value={values.vendor_id}
          onChange={(e) => set("vendor_id", Number(e.target.value))}
          disabled={isEdit}
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
        >
          <option value={0}>— Select vendor —</option>
          {vendors.map((v) => <option key={v.id} value={v.id}>{v.vendor_name}</option>)}
        </select>
        {errors.vendor_id && <p className="mt-1 text-xs text-red-600">{errors.vendor_id}</p>}
      </div>

      <div className="grid grid-cols-2 gap-4">
        {[
          ["Invoice #", "invoice_number", "text", "INV-001"],
          ["Invoice Date", "invoice_date", "date", ""],
        ].map(([label, field, type, placeholder]) => (
          <div key={field}>
            <label className="block text-xs font-medium text-gray-700 mb-1">{label} <span className="text-red-500">*</span></label>
            <input
              type={type}
              value={String(values[field as keyof VendorBillFormValues] ?? "")}
              onChange={(e) => set(field as keyof VendorBillFormValues, e.target.value as never)}
              placeholder={placeholder}
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            {field && errors[field] && <p className="mt-1 text-xs text-red-600">{errors[field]}</p>}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Due Date</label>
          <input type="date" value={values.due_date ?? ""} onChange={(e) => set("due_date", e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Amount <span className="text-red-500">*</span></label>
          <input type="number" step="0.01" value={values.amount}
            onChange={(e) => set("amount", Number(e.target.value))}
            disabled={hasPayments}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
          />
          {hasPayments && <p className="mt-1 text-xs text-gray-400">Locked — payment recorded</p>}
          {errors.amount && <p className="mt-1 text-xs text-red-600">{errors.amount}</p>}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Fund</label>
          <select value={values.fund_code} onChange={(e) => set("fund_code", e.target.value as VendorBillFormValues["fund_code"])}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="OPERATING">Operating</option>
            <option value="RESERVE">Reserve</option>
            <option value="SPECIAL">Special</option>
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Category</label>
          <select value={values.category_id ?? ""} onChange={(e) => set("category_id", e.target.value ? Number(e.target.value) : null)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">— None —</option>
            {expenseCategories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Description</label>
        <input type="text" value={values.description ?? ""} onChange={(e) => set("description", e.target.value)}
          placeholder="Optional memo"
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
      </div>

      <div className="flex justify-end gap-3 pt-2 border-t">
        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">Cancel</button>
        <button type="submit" disabled={saving}
          className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
          {saving ? "Saving…" : isEdit ? "Save Changes" : "Add Bill"}
        </button>
      </div>
    </form>
  );
}

// ── Payment Form ──────────────────────────────────────────────────────────────

type PaymentFormProps = {
  bill: VendorBill;
  bankAccounts: BankAccount[];
  payments: BillPayment[];
  onSave: (v: BillPaymentFormValues) => Promise<void>;
  onDeletePayment: (id: number) => Promise<void>;
  onClose: () => void;
};

function PaymentPanel({ bill, bankAccounts, payments, onSave, onDeletePayment, onClose }: PaymentFormProps) {
  const remaining = bill.amount - (bill.amount_paid ?? 0);
  const [values, setValues] = useState<BillPaymentFormValues>({
    payment_date: today(),
    amount: remaining > 0 ? remaining : bill.amount,
    bank_account_id: 0,
    check_number: "",
    notes: "",
  });
  const [errors, setErrors] = useState<Partial<Record<string, string>>>({});
  const [saving, setSaving] = useState(false);

  const set = <K extends keyof BillPaymentFormValues>(k: K, v: BillPaymentFormValues[K]) =>
    setValues((p) => ({ ...p, [k]: v }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const result = BillPaymentFormSchema.safeParse(values);
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
    <div className="space-y-4">
      {/* Bill summary */}
      <div className="bg-gray-50 rounded p-3 text-sm">
        <div className="flex justify-between">
          <span className="text-gray-600">Bill amount</span>
          <span className="font-mono">{fmt(bill.amount)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-600">Paid to date</span>
          <span className="font-mono">{fmt(bill.amount_paid ?? 0)}</span>
        </div>
        <div className="flex justify-between font-medium border-t mt-1 pt-1">
          <span>Remaining</span>
          <span className="font-mono">{fmt(remaining)}</span>
        </div>
      </div>

      {/* Existing payments */}
      {payments.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Payments Recorded</p>
          <div className="border rounded divide-y text-sm">
            {payments.map((p) => (
              <div key={p.id} className="flex items-center justify-between px-3 py-2">
                <div>
                  <span className="font-mono text-gray-900">{fmt(p.amount)}</span>
                  <span className="ml-2 text-gray-500 text-xs">{p.payment_date}</span>
                  {p.check_number && <span className="ml-2 text-gray-400 text-xs">#{p.check_number}</span>}
                  <span className="ml-2 text-gray-400 text-xs">{p.bank_account_name}</span>
                </div>
                <button onClick={() => onDeletePayment(p.id)} className="text-xs text-red-500 hover:underline">Remove</button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* New payment form */}
      {bill.status !== "PAID" && bill.status !== "VOID" && (
        <form onSubmit={handleSubmit} className="space-y-3">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Record Payment</p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Date <span className="text-red-500">*</span></label>
              <input type="date" value={values.payment_date} onChange={(e) => set("payment_date", e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              {errors.payment_date && <p className="mt-1 text-xs text-red-600">{errors.payment_date}</p>}
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Amount <span className="text-red-500">*</span></label>
              <input type="number" step="0.01" value={values.amount} onChange={(e) => set("amount", Number(e.target.value))}
                className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              {errors.amount && <p className="mt-1 text-xs text-red-600">{errors.amount}</p>}
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Bank Account <span className="text-red-500">*</span></label>
            <select value={values.bank_account_id} onChange={(e) => set("bank_account_id", Number(e.target.value))}
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value={0}>— Select account —</option>
              {bankAccounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
            </select>
            {errors.bank_account_id && <p className="mt-1 text-xs text-red-600">{errors.bank_account_id}</p>}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Check #</label>
              <input type="text" value={values.check_number ?? ""} onChange={(e) => set("check_number", e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Notes</label>
              <input type="text" value={values.notes ?? ""} onChange={(e) => set("notes", e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>
          <div className="flex justify-end gap-3 pt-2 border-t">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">Close</button>
            <button type="submit" disabled={saving}
              className="px-4 py-2 text-sm bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50">
              {saving ? "Saving…" : "Record Payment"}
            </button>
          </div>
        </form>
      )}
      {(bill.status === "PAID" || bill.status === "VOID") && (
        <div className="flex justify-end pt-2 border-t">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">Close</button>
        </div>
      )}
    </div>
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

type ModalState =
  | { mode: "add" }
  | { mode: "edit"; bill: VendorBill; hasPayments: boolean }
  | { mode: "payment"; bill: VendorBill; payments: BillPayment[] }
  | null;

const STATUS_FILTERS: [string, string][] = [
  ["ALL", "All"],
  ["OPEN", "Open"],
  ["PARTIAL", "Partial"],
  ["PAID", "Paid"],
  ["VOID", "Void"],
];

export function VendorBillsScreen() {
  const [bills, setBills] = useState<VendorBill[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [bankAccounts, setBankAccounts] = useState<BankAccount[]>([]);
  const [statusFilter, setStatusFilter] = useState("OPEN");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalState>(null);

  const loadBills = useCallback(async () => {
    try { setBills(await listVendorBills(statusFilter)); }
    catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [statusFilter]);

  useEffect(() => {
    void loadBills();
  }, [loadBills]);

  useEffect(() => {
    Promise.all([
      listVendors(true),
      listCategories(),
      listBankAccounts(true),
    ]).then(([v, c, b]) => {
      setVendors(v);
      setCategories(c);
      setBankAccounts(b);
    }).catch(console.error);
  }, []);

  async function handleSaveBill(values: VendorBillFormValues) {
    if (modal?.mode === "edit") {
      await updateVendorBill(modal.bill.id, values);
    } else {
      await insertVendorBill(values);
    }
    setModal(null);
    await loadBills();
  }

  async function handleOpenPayment(bill: VendorBill) {
    const payments = await listPaymentsForBill(bill.id);
    setModal({ mode: "payment", bill, payments });
  }

  async function handleSavePayment(values: BillPaymentFormValues) {
    if (modal?.mode !== "payment") return;
    await insertBillPayment(modal.bill.id, values);
    const [updatedBill, payments] = await Promise.all([
      listVendorBills().then((bills) => bills.find((b) => b.id === modal.bill.id)),
      listPaymentsForBill(modal.bill.id),
    ]);
    if (updatedBill) setModal({ mode: "payment", bill: updatedBill, payments });
    await loadBills();
  }

  async function handleDeletePayment(paymentId: number) {
    if (modal?.mode !== "payment") return;
    if (!confirm("Remove this payment? The bill will return to Open/Partial status.")) return;
    await deleteBillPayment(paymentId, modal.bill.id);
    const [updatedBill, payments] = await Promise.all([
      listVendorBills().then((bills) => bills.find((b) => b.id === modal.bill.id)),
      listPaymentsForBill(modal.bill.id),
    ]);
    if (updatedBill) setModal({ mode: "payment", bill: updatedBill, payments });
    await loadBills();
  }

  async function handleOpenEdit(bill: VendorBill) {
    const hasPaymentsFlag = await billHasPayments(bill.id);
    setModal({ mode: "edit", bill, hasPayments: hasPaymentsFlag });
  }

  async function handleVoid(bill: VendorBill) {
    if (!confirm(`Void bill "${bill.invoice_number}" from ${bill.vendor_name}?`)) return;
    await voidBill(bill.id);
    await loadBills();
  }

  return (
    <div className="p-8 max-w-6xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold text-gray-900">Vendor Bills</h1>
        <button
          onClick={() => setModal({ mode: "add" })}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
        >
          + Add Bill
        </button>
      </div>

      {/* Status filter tabs */}
      <div className="flex gap-1 mb-4 border-b">
        {STATUS_FILTERS.map(([val, label]) => (
          <button
            key={val}
            onClick={() => { setStatusFilter(val); setLoading(true); }}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              statusFilter === val
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {loading && <p className="text-gray-400 text-sm">Loading…</p>}
      {error && <p className="text-red-600 text-sm">{error}</p>}

      {!loading && !error && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Vendor</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Invoice #</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Date</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Due</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Category</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Paid</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Status</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {bills.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-4 py-6 text-center text-gray-400 text-sm">
                    No bills found. Click "Add Bill" to enter your first vendor bill.
                  </td>
                </tr>
              )}
              {bills.map((bill) => (
                <tr key={bill.id} className={bill.status === "VOID" ? "opacity-40" : ""}>
                  <td className="px-4 py-2 font-medium text-gray-900">{bill.vendor_name}</td>
                  <td className="px-4 py-2 text-gray-600 font-mono text-xs">{bill.invoice_number}</td>
                  <td className="px-4 py-2 text-gray-600 text-xs">{bill.invoice_date}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{bill.due_date ?? "—"}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{bill.category_code ?? "—"}</td>
                  <td className="px-4 py-2 text-right font-mono text-gray-900">{fmt(bill.amount)}</td>
                  <td className="px-4 py-2 text-right font-mono text-gray-500 text-xs">
                    {(bill.amount_paid ?? 0) > 0 ? fmt(bill.amount_paid ?? 0) : "—"}
                  </td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[bill.status]}`}>
                      {bill.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right space-x-2 whitespace-nowrap">
                    <button onClick={() => handleOpenEdit(bill)} className="text-xs text-blue-600 hover:underline">Edit</button>
                    {bill.status !== "VOID" && bill.status !== "PAID" && (
                      <button onClick={() => handleOpenPayment(bill)} className="text-xs text-green-600 hover:underline">Pay</button>
                    )}
                    {bill.status === "PARTIAL" && (
                      <button onClick={() => handleOpenPayment(bill)} className="text-xs text-gray-500 hover:underline">Payments</button>
                    )}
                    {bill.status === "OPEN" && (
                      <button onClick={() => handleVoid(bill)} className="text-xs text-red-500 hover:underline">Void</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Add/Edit Bill modal */}
      {modal?.mode === "add" && (
        <Modal title="Add Vendor Bill" onClose={() => setModal(null)}>
          <BillForm vendors={vendors} categories={categories} hasPayments={false}
            onSave={handleSaveBill} onCancel={() => setModal(null)} />
        </Modal>
      )}
      {modal?.mode === "edit" && (
        <Modal title={`Edit Bill — ${modal.bill.invoice_number}`} onClose={() => setModal(null)}>
          <BillForm initial={modal.bill} vendors={vendors} categories={categories}
            hasPayments={modal.hasPayments} onSave={handleSaveBill} onCancel={() => setModal(null)} />
        </Modal>
      )}

      {/* Payment modal */}
      {modal?.mode === "payment" && (
        <Modal
          title={`Payments — ${modal.bill.vendor_name} · ${modal.bill.invoice_number}`}
          onClose={() => setModal(null)}
        >
          <PaymentPanel
            bill={modal.bill}
            bankAccounts={bankAccounts}
            payments={modal.payments}
            onSave={handleSavePayment}
            onDeletePayment={handleDeletePayment}
            onClose={() => setModal(null)}
          />
        </Modal>
      )}
    </div>
  );
}
