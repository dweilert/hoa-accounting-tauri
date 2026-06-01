import { useEffect, useState, useCallback } from "react";
import { listAllBankTransactions, updateTransactionStatus } from "../repositories/reconciliationRepo";
import type { BankTransaction } from "../types/reconciliation";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

type TxnRow = BankTransaction & { account_name: string };

export function BankPendingScreen() {
  const [transactions, setTransactions] = useState<TxnRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"UNVALIDATED" | "VALIDATED" | "all">("UNVALIDATED");

  const load = useCallback(async () => {
    try {
      const rows = await listAllBankTransactions({ limit: 300 });
      setTransactions(rows as TxnRow[]);
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

  const visible = filter === "all" ? transactions : transactions.filter((t) => t.validation_status === filter);

  return (
    <div className="p-8 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Pending Transactions</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Imported bank transactions awaiting validation.
          </p>
        </div>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value as typeof filter)}
          className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="UNVALIDATED">Unvalidated</option>
          <option value="VALIDATED">Validated</option>
          <option value="all">All</option>
        </select>
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
    </div>
  );
}
