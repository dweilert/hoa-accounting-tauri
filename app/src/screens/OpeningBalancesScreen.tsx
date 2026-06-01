import { useEffect, useState, useCallback } from "react";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import { listLots } from "../repositories/lotRepo";
import { listOpeningBalances, upsertOpeningBalance } from "../repositories/openingBalanceRepo";
import type { BankAccount } from "../types/bankAccount";
import type { Lot } from "../types/lot";
import type { OpeningBalance } from "../types/openingBalance";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

type Tab = "bank" | "lots";

// ── Bank Accounts tab ─────────────────────────────────────────────────────────

type BankRow = {
  account: BankAccount;
  balance: OpeningBalance | null;
  editing: boolean;
  draft: { as_of_date: string; amount: string; notes: string };
  saving: boolean;
};

function BankBalancesTab() {
  const [rows, setRows] = useState<BankRow[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    const [accounts, balances] = await Promise.all([
      listBankAccounts(true),
      listOpeningBalances("BANK_ACCOUNT"),
    ]);
    const byId = new Map(balances.map((b) => [b.entity_id, b]));
    setRows(
      accounts.map((a) => ({
        account: a,
        balance: byId.get(a.id) ?? null,
        editing: false,
        draft: {
          as_of_date: byId.get(a.id)?.as_of_date ?? "",
          amount: String(byId.get(a.id)?.amount ?? "0"),
          notes: byId.get(a.id)?.notes ?? "",
        },
        saving: false,
      }))
    );
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  function startEdit(id: number) {
    setRows((prev) =>
      prev.map((r) => (r.account.id === id ? { ...r, editing: true } : r))
    );
  }

  function cancelEdit(id: number) {
    setRows((prev) =>
      prev.map((r) => {
        if (r.account.id !== id) return r;
        return {
          ...r,
          editing: false,
          draft: {
            as_of_date: r.balance?.as_of_date ?? "",
            amount: String(r.balance?.amount ?? "0"),
            notes: r.balance?.notes ?? "",
          },
        };
      })
    );
  }

  function setDraft(id: number, key: string, value: string) {
    setRows((prev) =>
      prev.map((r) =>
        r.account.id === id ? { ...r, draft: { ...r.draft, [key]: value } } : r
      )
    );
  }

  async function save(id: number) {
    const row = rows.find((r) => r.account.id === id);
    if (!row) return;
    setRows((prev) =>
      prev.map((r) => (r.account.id === id ? { ...r, saving: true } : r))
    );
    try {
      await upsertOpeningBalance("BANK_ACCOUNT", id, {
        as_of_date: row.draft.as_of_date,
        amount: parseFloat(row.draft.amount) || 0,
        notes: row.draft.notes || undefined,
      });
      await load();
    } catch (e) {
      alert(String(e));
      setRows((prev) =>
        prev.map((r) => (r.account.id === id ? { ...r, saving: false } : r))
      );
    }
  }

  if (loading) return <p className="text-sm text-gray-400 py-4">Loading…</p>;
  if (rows.length === 0)
    return (
      <p className="text-sm text-gray-500 py-4">
        No active bank accounts. Add accounts first in Bank → Accounts.
      </p>
    );

  return (
    <div className="border rounded-lg overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 border-b">
          <tr>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Account</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Fund</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">As-of Date</th>
            <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Opening Balance</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Notes</th>
            <th className="px-4 py-2" />
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {rows.map((row) => (
            <tr key={row.account.id}>
              <td className="px-4 py-3 font-medium text-gray-900">{row.account.account_name}</td>
              <td className="px-4 py-3 text-gray-500 text-xs">{row.account.fund_code}</td>

              {row.editing ? (
                <>
                  <td className="px-4 py-2">
                    <input
                      type="date"
                      value={row.draft.as_of_date}
                      onChange={(e) => setDraft(row.account.id, "as_of_date", e.target.value)}
                      className="border border-gray-300 rounded px-2 py-1 text-sm w-36 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </td>
                  <td className="px-4 py-2 text-right">
                    <input
                      type="number"
                      step="0.01"
                      value={row.draft.amount}
                      onChange={(e) => setDraft(row.account.id, "amount", e.target.value)}
                      className="border border-gray-300 rounded px-2 py-1 text-sm w-28 text-right focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </td>
                  <td className="px-4 py-2">
                    <input
                      type="text"
                      value={row.draft.notes}
                      onChange={(e) => setDraft(row.account.id, "notes", e.target.value)}
                      placeholder="Optional"
                      className="border border-gray-300 rounded px-2 py-1 text-sm w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </td>
                  <td className="px-4 py-2 text-right whitespace-nowrap space-x-2">
                    <button
                      onClick={() => void save(row.account.id)}
                      disabled={row.saving}
                      className="text-xs text-white bg-blue-600 hover:bg-blue-700 rounded px-3 py-1 disabled:opacity-50"
                    >
                      {row.saving ? "Saving…" : "Save"}
                    </button>
                    <button
                      onClick={() => cancelEdit(row.account.id)}
                      className="text-xs text-gray-500 hover:text-gray-800"
                    >
                      Cancel
                    </button>
                  </td>
                </>
              ) : (
                <>
                  <td className="px-4 py-3 text-gray-600">{row.balance?.as_of_date ?? "—"}</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-700">
                    {row.balance ? fmt(row.balance.amount) : "—"}
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{row.balance?.notes ?? ""}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => startEdit(row.account.id)}
                      className="text-xs text-blue-600 hover:underline"
                    >
                      {row.balance ? "Edit" : "Set"}
                    </button>
                  </td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Lot Balances tab ──────────────────────────────────────────────────────────

type LotRow = {
  lot: Lot;
  duesBalance: OpeningBalance | null;
  editingDues: boolean;
  draftDues: { as_of_date: string; amount: string };
  savingDues: boolean;
};

function LotBalancesTab() {
  const [rows, setRows] = useState<LotRow[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    const [lots, duesBalances] = await Promise.all([
      listLots(true),
      listOpeningBalances("LOT_DUES"),
    ]);
    const duesById = new Map(duesBalances.map((b) => [b.entity_id, b]));
    setRows(
      lots.map((lot) => ({
        lot,
        duesBalance: duesById.get(lot.id) ?? null,
        editingDues: false,
        draftDues: {
          as_of_date: duesById.get(lot.id)?.as_of_date ?? "",
          amount: String(duesById.get(lot.id)?.amount ?? "0"),
        },
        savingDues: false,
      }))
    );
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  function startEdit(lotId: number) {
    setRows((prev) => prev.map((r) => (r.lot.id === lotId ? { ...r, editingDues: true } : r)));
  }

  function cancelEdit(lotId: number) {
    setRows((prev) =>
      prev.map((r) => {
        if (r.lot.id !== lotId) return r;
        return {
          ...r,
          editingDues: false,
          draftDues: {
            as_of_date: r.duesBalance?.as_of_date ?? "",
            amount: String(r.duesBalance?.amount ?? "0"),
          },
        };
      })
    );
  }

  function setDraft(lotId: number, key: string, value: string) {
    setRows((prev) =>
      prev.map((r) =>
        r.lot.id === lotId ? { ...r, draftDues: { ...r.draftDues, [key]: value } } : r
      )
    );
  }

  async function save(lotId: number) {
    const row = rows.find((r) => r.lot.id === lotId);
    if (!row) return;
    setRows((prev) => prev.map((r) => (r.lot.id === lotId ? { ...r, savingDues: true } : r)));
    try {
      await upsertOpeningBalance("LOT_DUES", lotId, {
        as_of_date: row.draftDues.as_of_date,
        amount: parseFloat(row.draftDues.amount) || 0,
      });
      await load();
    } catch (e) {
      alert(String(e));
      setRows((prev) => prev.map((r) => (r.lot.id === lotId ? { ...r, savingDues: false } : r)));
    }
  }

  if (loading) return <p className="text-sm text-gray-400 py-4">Loading…</p>;
  if (rows.length === 0)
    return <p className="text-sm text-gray-500 py-4">No active lots. Add lots first.</p>;

  return (
    <div className="border rounded-lg overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 border-b">
          <tr>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Lot #</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Address</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-gray-600 w-36">As-of Date</th>
            <th className="px-4 py-2 text-right text-xs font-medium text-gray-600 w-32">Dues Balance Owed</th>
            <th className="px-4 py-2" />
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 bg-white">
          {rows.map((row) => (
            <tr key={row.lot.id}>
              <td className="px-4 py-3 font-medium text-gray-900">{row.lot.lot_number}</td>
              <td className="px-4 py-3 text-gray-600 text-xs">
                {row.lot.street_address_1 ?? "—"}
              </td>

              {row.editingDues ? (
                <>
                  <td className="px-4 py-2">
                    <input
                      type="date"
                      value={row.draftDues.as_of_date}
                      onChange={(e) => setDraft(row.lot.id, "as_of_date", e.target.value)}
                      className="border border-gray-300 rounded px-2 py-1 text-sm w-36 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </td>
                  <td className="px-4 py-2 text-right">
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      value={row.draftDues.amount}
                      onChange={(e) => setDraft(row.lot.id, "amount", e.target.value)}
                      className="border border-gray-300 rounded px-2 py-1 text-sm w-28 text-right focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </td>
                  <td className="px-4 py-2 text-right whitespace-nowrap space-x-2">
                    <button
                      onClick={() => void save(row.lot.id)}
                      disabled={row.savingDues}
                      className="text-xs text-white bg-blue-600 hover:bg-blue-700 rounded px-3 py-1 disabled:opacity-50"
                    >
                      {row.savingDues ? "Saving…" : "Save"}
                    </button>
                    <button
                      onClick={() => cancelEdit(row.lot.id)}
                      className="text-xs text-gray-500 hover:text-gray-800"
                    >
                      Cancel
                    </button>
                  </td>
                </>
              ) : (
                <>
                  <td className="px-4 py-3 text-gray-600">{row.duesBalance?.as_of_date ?? "—"}</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-700">
                    {row.duesBalance ? fmt(row.duesBalance.amount) : "—"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => startEdit(row.lot.id)}
                      className="text-xs text-blue-600 hover:underline"
                    >
                      {row.duesBalance ? "Edit" : "Set"}
                    </button>
                  </td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

export function OpeningBalancesScreen() {
  const [tab, setTab] = useState<Tab>("bank");

  return (
    <div className="p-8 max-w-5xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Opening Balances</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Set starting balances for bank accounts and lot owner dues at the beginning of the fiscal year.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 border-b">
        {(["bank", "lots"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === t
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {t === "bank" ? "Bank Accounts" : "Lot Dues Balances"}
          </button>
        ))}
      </div>

      {tab === "bank" ? <BankBalancesTab /> : <LotBalancesTab />}
    </div>
  );
}
