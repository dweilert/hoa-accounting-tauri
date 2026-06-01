import { useEffect, useState, useCallback } from "react";
import { getDb } from "../lib/db";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import type { BankAccount } from "../types/bankAccount";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

type LedgerRow = {
  txn_date: string;
  source_type: string;
  description: string;
  amount: number;
  lot_number: string | null;
  running_balance?: number;
};

async function loadLedger(bankAccountId: number, limit: number): Promise<LedgerRow[]> {
  const db = await getDb();
  const sql = `
    SELECT p.payment_date        AS txn_date,
           'PAYMENT'             AS source_type,
           COALESCE('Payment — ' || o.display_name, 'Payment — Lot ' || l.lot_number) AS description,
           p.amount,
           l.lot_number
    FROM   payments p
    JOIN   lots l ON l.id = p.lot_id
    LEFT JOIN owners o ON o.id = p.owner_id
    LEFT JOIN deposit_batches d ON d.id = p.deposit_batch_id
    WHERE  d.bank_account_id = ?

    UNION ALL

    SELECT bp.payment_date,
           'BILL_PAYMENT',
           'Bill payment — ' || v.vendor_name,
           -bp.amount,
           NULL
    FROM   bill_payments bp
    JOIN   vendor_bills vb ON vb.id = bp.vendor_bill_id
    JOIN   vendors v       ON v.id = vb.vendor_id
    WHERE  bp.bank_account_id = ?

    UNION ALL

    SELECT ib.income_date,
           'INCOME',
           COALESCE(ib.description, c.name),
           ib.amount,
           l.lot_number
    FROM   income_batches ib
    JOIN   categories c ON c.id = ib.category_id
    LEFT JOIN lots l ON l.id = ib.lot_id
    WHERE  ib.bank_account_id = ?

    ORDER BY txn_date ASC
    LIMIT ?
  `;
  const rows = await db.select<LedgerRow[]>(sql, [bankAccountId, bankAccountId, bankAccountId, limit]);

  // Compute running balance
  let balance = 0;
  for (const r of rows) {
    balance += r.amount;
    r.running_balance = balance;
  }
  return rows.reverse();
}

export function LedgerByAccountScreen() {
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [selectedId, setSelectedId] = useState<number>(0);
  const [rows, setRows] = useState<LedgerRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(100);

  useEffect(() => {
    listBankAccounts()
      .then((a) => {
        setAccounts(a);
        if (a[0]) setSelectedId(a[0].id);
      })
      .catch((e) => { setError(String(e)); setLoading(false); });
  }, []);

  const load = useCallback(async () => {
    if (!selectedId) { setLoading(false); return; }
    try {
      setLoading(true);
      setRows(await loadLedger(selectedId, limit));
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [selectedId, limit]);

  useEffect(() => { if (selectedId) void load(); }, [load, selectedId]);

  const SOURCE_LABELS: Record<string, string> = {
    PAYMENT: "Payment",
    BILL_PAYMENT: "Bill Payment",
    INCOME: "Income",
  };

  return (
    <div className="p-8 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Ledger by Account</h1>
          <p className="text-sm text-gray-500 mt-0.5">Transaction history with running balance.</p>
        </div>
        <div className="flex gap-3">
          <select
            value={selectedId}
            onChange={(e) => setSelectedId(Number(e.target.value))}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
          </select>
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value={50}>Last 50</option>
            <option value={100}>Last 100</option>
            <option value={250}>Last 250</option>
          </select>
        </div>
      </div>

      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {accounts.length === 0 && !loading && (
        <p className="text-sm text-gray-500">No bank accounts yet. Add accounts in Bank → Accounts.</p>
      )}

      {!loading && !error && accounts.length > 0 && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Date</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Type</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Description</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Lot</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Balance</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {rows.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-gray-400 text-sm">
                    No transactions for this account.
                  </td>
                </tr>
              )}
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="px-4 py-2 text-gray-600">{r.txn_date}</td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      r.source_type === "PAYMENT" ? "bg-green-100 text-green-700"
                      : r.source_type === "BILL_PAYMENT" ? "bg-red-100 text-red-700"
                      : "bg-blue-100 text-blue-700"
                    }`}>
                      {SOURCE_LABELS[r.source_type] ?? r.source_type}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-gray-700">{r.description}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{r.lot_number ? `Lot ${r.lot_number}` : "—"}</td>
                  <td className={`px-4 py-2 text-right font-mono ${r.amount < 0 ? "text-red-600" : "text-green-700"}`}>
                    {fmt(r.amount)}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-gray-700">
                    {r.running_balance !== undefined ? fmt(r.running_balance) : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
