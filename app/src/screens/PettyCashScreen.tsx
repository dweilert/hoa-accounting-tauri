import { useEffect, useState, useCallback } from "react";
import { PageLayout } from "../components/PageLayout";
import { Modal } from "../components/Modal";
import {
  listPettyCashAccounts,
  getPettyCashBalance,
  listPettyCashTxns,
  insertPettyCashTxn,
  deletePettyCashTxn,
  listReplenishments,
  insertReplenishment,
  type PettyCashTxn,
  type Replenishment,
} from "../repositories/pettyCashRepo";
import { listBankAccounts, setPettyCashFlag } from "../repositories/bankAccountRepo";
import { insertBankAccount } from "../repositories/bankAccountRepo";
import { listCategories } from "../repositories/categoryRepo";
import type { BankAccount } from "../types/bankAccount";
import type { Category } from "../types/category";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

type ModalType = "newFund" | "spend" | "replenish" | "designate" | null;

// ── Setup prompt ─────────────────────────────────────────────────────────────

function SetupPrompt({ onNew, onDesignate }: { onNew: () => void; onDesignate: () => void }) {
  return (
    <div className="border-2 border-dashed border-gray-300 rounded-xl p-10 text-center space-y-4">
      <p className="text-gray-500 text-sm">No petty cash fund set up yet.</p>
      <div className="flex justify-center gap-3">
        <button
          onClick={onNew}
          className="px-4 py-2 rounded text-sm text-white"
          style={{ backgroundColor: "#2f6046" }}
        >
          + Create New Fund
        </button>
        <button
          onClick={onDesignate}
          className="px-4 py-2 rounded text-sm border border-gray-300 text-gray-700 hover:bg-gray-50"
        >
          Use Existing Account
        </button>
      </div>
    </div>
  );
}

// ── Main screen ───────────────────────────────────────────────────────────────

export function PettyCashScreen() {
  const [funds, setFunds] = useState<BankAccount[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [balance, setBalance] = useState(0);
  const [txns, setTxns] = useState<PettyCashTxn[]>([]);
  const [replenishments, setReplenishments] = useState<Replenishment[]>([]);
  const [allAccounts, setAllAccounts] = useState<BankAccount[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState<ModalType>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const selectedFund = funds.find((f) => f.id === selectedId) ?? null;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [f, a, c] = await Promise.all([
        listPettyCashAccounts(),
        listBankAccounts(true),
        listCategories(),
      ]);
      setFunds(f);
      setAllAccounts(a);
      setCategories(c);
      if (f.length > 0 && !selectedId) setSelectedId(f[0]!.id);
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  const loadFundData = useCallback(async (id: number) => {
    const [b, t, r] = await Promise.all([
      getPettyCashBalance(id),
      listPettyCashTxns(id),
      listReplenishments(id),
    ]);
    setBalance(b);
    setTxns(t);
    setReplenishments(r);
  }, []);

  useEffect(() => { void load(); }, []);
  useEffect(() => { if (selectedId) void loadFundData(selectedId); }, [selectedId]);

  function openModal(m: ModalType) { setErr(null); setModal(m); }

  // ── Create new fund ──────────────────────────────────────────────────────

  async function handleNewFund(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const account_name = fd.get("account_name") as string;
    const opening_balance = Number(fd.get("opening_balance") ?? 0);
    const opening_balance_date = (fd.get("opening_balance_date") as string) || null;
    setSaving(true); setErr(null);
    try {
      const id = await insertBankAccount({
        account_name,
        institution_name: "Cash on Hand",
        account_type: "OTHER",
        fund_code: "OPERATING",
        active_flag: 1,
        opening_balance,
        opening_balance_date: opening_balance_date ?? undefined,
      });
      await setPettyCashFlag(id, true);
      setModal(null);
      await load();
      setSelectedId(id);
    } catch (e) { setErr(String(e)); } finally { setSaving(false); }
  }

  // ── Designate existing account ───────────────────────────────────────────

  async function handleDesignate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const id = Number(fd.get("bank_account_id"));
    setSaving(true); setErr(null);
    try {
      await setPettyCashFlag(id, true);
      setModal(null);
      await load();
      setSelectedId(id);
    } catch (e) { setErr(String(e)); } finally { setSaving(false); }
  }

  // ── Record expenditure ───────────────────────────────────────────────────

  async function handleSpend(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!selectedId) return;
    const fd = new FormData(e.currentTarget);
    const txn_date   = fd.get("txn_date") as string;
    const amount     = Number(fd.get("amount"));
    const desc       = fd.get("description") as string;
    const cat_id     = fd.get("category_id") ? Number(fd.get("category_id")) : null;
    const receipt    = (fd.get("receipt_ref") as string) || null;
    if (!txn_date || !amount || !desc) { setErr("Date, amount, and description required."); return; }
    setSaving(true); setErr(null);
    try {
      await insertPettyCashTxn(selectedId, txn_date, amount, desc, cat_id, receipt);
      setModal(null);
      await loadFundData(selectedId);
    } catch (e) { setErr(String(e)); } finally { setSaving(false); }
  }

  // ── Replenish ────────────────────────────────────────────────────────────

  async function handleReplenish(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!selectedId) return;
    const fd = new FormData(e.currentTarget);
    const from_id = Number(fd.get("from_account_id"));
    const amount  = Number(fd.get("amount"));
    const date    = fd.get("transfer_date") as string;
    const desc    = (fd.get("description") as string) || null;
    if (!from_id || !amount || !date) { setErr("All fields required."); return; }
    setSaving(true); setErr(null);
    try {
      await insertReplenishment(from_id, selectedId, date, amount, desc);
      setModal(null);
      await loadFundData(selectedId);
    } catch (e) { setErr(String(e)); } finally { setSaving(false); }
  }

  async function handleDeleteTxn(id: number) {
    if (!selectedId) return;
    await deletePettyCashTxn(id);
    await loadFundData(selectedId);
  }

  const expenseCategories = categories.filter((c) => c.category_type === "EXPENSE");
  const nonPettyCash = allAccounts.filter((a) => !a.is_petty_cash);

  // ── Combined timeline ────────────────────────────────────────────────────

  type TimelineRow =
    | { kind: "spend"; data: PettyCashTxn }
    | { kind: "replenish"; data: Replenishment };

  const timeline: TimelineRow[] = [
    ...txns.map((t): TimelineRow => ({ kind: "spend", data: t })),
    ...replenishments.map((r): TimelineRow => ({ kind: "replenish", data: r })),
  ].sort((a, b) => {
    const da = a.kind === "spend" ? a.data.txn_date : a.data.transfer_date;
    const db2 = b.kind === "spend" ? b.data.txn_date : b.data.transfer_date;
    return db2 < da ? -1 : db2 > da ? 1 : 0;
  });

  return (
    <PageLayout
      title="Petty Cash"
      actions={
        selectedFund && (
          <div className="flex gap-2">
            <button
              onClick={() => openModal("replenish")}
              className="px-3 py-1.5 text-xs border border-gray-300 rounded text-gray-700 hover:bg-gray-50"
            >
              + Replenish
            </button>
            <button
              onClick={() => openModal("spend")}
              className="px-3 py-1.5 text-xs rounded text-white"
              style={{ backgroundColor: "#2f6046" }}
            >
              + Record Expenditure
            </button>
          </div>
        )
      }
    >
      {loading ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : funds.length === 0 ? (
        <SetupPrompt
          onNew={() => openModal("newFund")}
          onDesignate={() => openModal("designate")}
        />
      ) : (
        <div className="space-y-5">
          {/* Fund selector (if multiple) */}
          {funds.length > 1 && (
            <div className="flex gap-2">
              {funds.map((f) => (
                <button
                  key={f.id}
                  onClick={() => setSelectedId(f.id)}
                  className={`px-3 py-1.5 rounded text-sm border ${
                    f.id === selectedId
                      ? "border-green-700 text-green-800 bg-green-50 font-medium"
                      : "border-gray-300 text-gray-600 hover:bg-gray-50"
                  }`}
                >
                  {f.account_name}
                </button>
              ))}
            </div>
          )}

          {/* Balance card */}
          <div
            className="rounded-xl p-5 flex items-center justify-between"
            style={{ backgroundColor: balance < 0 ? "#fef2f2" : "#f0fdf4", border: `1px solid ${balance < 0 ? "#fca5a5" : "#86efac"}` }}
          >
            <div>
              <p className="text-xs font-medium uppercase tracking-wide" style={{ color: balance < 0 ? "#b91c1c" : "#166534" }}>
                {selectedFund?.account_name ?? "Petty Cash"} Balance
              </p>
              <p className="text-3xl font-bold mt-1" style={{ color: balance < 0 ? "#b91c1c" : "#15803d" }}>
                {fmt(balance)}
              </p>
            </div>
            <div className="text-right text-xs text-gray-500 space-y-1">
              <p>{replenishments.length} replenishment{replenishments.length !== 1 ? "s" : ""}</p>
              <p>{txns.length} expenditure{txns.length !== 1 ? "s" : ""}</p>
            </div>
          </div>

          {/* Timeline */}
          {timeline.length === 0 ? (
            <p className="text-sm text-gray-400 italic">No transactions yet. Use the buttons above to replenish or record an expenditure.</p>
          ) : (
            <div className="border rounded-lg overflow-auto max-h-[calc(100vh-200px)] ">
              <table className="w-full text-sm">
                <thead className="sticky top-0 z-10 bg-gray-50 border-b">
                  <tr>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-600">Date</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-600">Type</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-600">Description</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-600">Category</th>
                    <th className="px-3 py-2 text-left text-xs font-medium text-gray-600">Receipt</th>
                    <th className="px-3 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
                    <th className="px-3 py-2 w-8" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {timeline.map((row) => {
                    if (row.kind === "replenish") {
                      const r = row.data;
                      return (
                        <tr key={`r-${r.id}`} className="hover:bg-gray-50">
                          <td className="px-3 py-1.5 text-xs font-mono text-gray-600">{r.transfer_date}</td>
                          <td className="px-3 py-1.5">
                            <span className="px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700">Replenishment</span>
                          </td>
                          <td className="px-3 py-1.5 text-xs text-gray-600">{r.description ?? `From ${r.from_account_name}`}</td>
                          <td className="px-3 py-1.5 text-xs text-gray-400">—</td>
                          <td className="px-3 py-1.5 text-xs text-gray-400">—</td>
                          <td className="px-3 py-1.5 text-right text-xs font-mono font-semibold text-green-700">+{fmt(r.amount)}</td>
                          <td className="px-3 py-1.5" />
                        </tr>
                      );
                    } else {
                      const t = row.data;
                      return (
                        <tr key={`t-${t.id}`} className="hover:bg-gray-50">
                          <td className="px-3 py-1.5 text-xs font-mono text-gray-600">{t.txn_date}</td>
                          <td className="px-3 py-1.5">
                            <span className="px-2 py-0.5 rounded text-xs font-medium bg-orange-100 text-orange-700">Expenditure</span>
                          </td>
                          <td className="px-3 py-1.5 text-xs text-gray-800">{t.description}</td>
                          <td className="px-3 py-1.5 text-xs text-gray-500">{t.category_name ?? "—"}</td>
                          <td className="px-3 py-1.5 text-xs text-gray-500">{t.receipt_ref ?? "—"}</td>
                          <td className="px-3 py-1.5 text-right text-xs font-mono text-red-700">−{fmt(t.amount)}</td>
                          <td className="px-3 py-1.5 text-right">
                            <button
                              onClick={() => handleDeleteTxn(t.id)}
                              className="text-xs text-red-400 hover:text-red-600"
                              title="Delete"
                            >✕</button>
                          </td>
                        </tr>
                      );
                    }
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Modals ── */}

      {modal === "newFund" && (
        <Modal title="Create Petty Cash Fund" onClose={() => setModal(null)}>
          <form onSubmit={handleNewFund} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Fund Name</label>
              <input name="account_name" defaultValue="Petty Cash" required
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Opening Balance</label>
                <input name="opening_balance" type="number" step="0.01" defaultValue="0"
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">As Of Date</label>
                <input name="opening_balance_date" type="date"
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
              </div>
            </div>
            {err && <p className="text-xs text-red-600">{err}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setModal(null)}
                className="px-3 py-1.5 text-xs border border-gray-300 rounded text-gray-600 hover:bg-gray-50">Cancel</button>
              <button type="submit" disabled={saving}
                className="px-3 py-1.5 text-xs rounded text-white disabled:opacity-50"
                style={{ backgroundColor: "#2f6046" }}>{saving ? "Saving…" : "Create Fund"}</button>
            </div>
          </form>
        </Modal>
      )}

      {modal === "designate" && (
        <Modal title="Use Existing Account as Petty Cash Fund" onClose={() => setModal(null)}>
          <form onSubmit={handleDesignate} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Bank Account</label>
              <select name="bank_account_id" required
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
                <option value="">Select account…</option>
                {nonPettyCash.map((a) => (
                  <option key={a.id} value={a.id}>{a.account_name}</option>
                ))}
              </select>
            </div>
            {err && <p className="text-xs text-red-600">{err}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setModal(null)}
                className="px-3 py-1.5 text-xs border border-gray-300 rounded text-gray-600 hover:bg-gray-50">Cancel</button>
              <button type="submit" disabled={saving}
                className="px-3 py-1.5 text-xs rounded text-white disabled:opacity-50"
                style={{ backgroundColor: "#2f6046" }}>{saving ? "Saving…" : "Designate"}</button>
            </div>
          </form>
        </Modal>
      )}

      {modal === "spend" && (
        <Modal title="Record Expenditure" onClose={() => setModal(null)}>
          <form onSubmit={handleSpend} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Date</label>
                <input name="txn_date" type="date" required defaultValue={new Date().toISOString().slice(0, 10)}
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Amount</label>
                <input name="amount" type="number" step="0.01" min="0.01" required placeholder="0.00"
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Description</label>
              <input name="description" required placeholder="What was purchased?"
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Category <span className="text-gray-400">(optional)</span></label>
                <select name="category_id"
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
                  <option value="">— None —</option>
                  {expenseCategories.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Receipt # <span className="text-gray-400">(optional)</span></label>
                <input name="receipt_ref" placeholder="e.g. #0042"
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
              </div>
            </div>
            {err && <p className="text-xs text-red-600">{err}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setModal(null)}
                className="px-3 py-1.5 text-xs border border-gray-300 rounded text-gray-600 hover:bg-gray-50">Cancel</button>
              <button type="submit" disabled={saving}
                className="px-3 py-1.5 text-xs rounded text-white disabled:opacity-50"
                style={{ backgroundColor: "#2f6046" }}>{saving ? "Saving…" : "Record"}</button>
            </div>
          </form>
        </Modal>
      )}

      {modal === "replenish" && (
        <Modal title="Replenish Petty Cash" onClose={() => setModal(null)}>
          <form onSubmit={handleReplenish} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Transfer From</label>
              <select name="from_account_id" required
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
                <option value="">Select account…</option>
                {nonPettyCash.map((a) => (
                  <option key={a.id} value={a.id}>{a.account_name}</option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Date</label>
                <input name="transfer_date" type="date" required defaultValue={new Date().toISOString().slice(0, 10)}
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Amount</label>
                <input name="amount" type="number" step="0.01" min="0.01" required placeholder="0.00"
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Description <span className="text-gray-400">(optional)</span></label>
              <input name="description" placeholder="e.g. Petty cash replenishment"
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400" />
            </div>
            {err && <p className="text-xs text-red-600">{err}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setModal(null)}
                className="px-3 py-1.5 text-xs border border-gray-300 rounded text-gray-600 hover:bg-gray-50">Cancel</button>
              <button type="submit" disabled={saving}
                className="px-3 py-1.5 text-xs rounded text-white disabled:opacity-50"
                style={{ backgroundColor: "#2f6046" }}>{saving ? "Saving…" : "Record Transfer"}</button>
            </div>
          </form>
        </Modal>
      )}
    </PageLayout>
  );
}
